import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import httpx
from faststream import AckPolicy, Context, FastStream
from faststream.rabbit import RabbitMessage, RabbitQueue
from sqlalchemy.exc import SQLAlchemyError

from app.application.process_payment import ProcessPaymentService, webhook_payload
from app.config import settings
from app.domain.enums import ClaimDecision
from app.domain.exceptions import PaymentNotFoundError, WebhookError
from app.domain.protocols import (
    PaymentGateway,
    PaymentProcessor,
    PaymentRepository,
    WebhookNotifier,
)
from app.infrastructure.db.repositories import SqlPaymentRepository
from app.infrastructure.db.session import async_session_factory
from app.infrastructure.gateway import EmulatedPaymentGateway
from app.infrastructure.messaging.broker import (
    create_broker,
    declare_topology,
    payments_dlq,
    payments_queue,
    payments_retry_5s,
    payments_retry_10s,
)
from app.infrastructure.messaging.schemas import PaymentCreatedEvent
from app.infrastructure.webhook import HttpWebhookNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

broker = create_broker()
app = FastStream(broker)

_PERMANENT = (WebhookError, PaymentNotFoundError)
_RETRYABLE = (SQLAlchemyError, OSError, TimeoutError)
_MAX_PROCESSING_ATTEMPTS = 3
_RETRY_ATTEMPT_HEADER = "x-retry-attempt"


@asynccontextmanager
async def sql_uow() -> AsyncIterator[PaymentRepository]:
    async with async_session_factory() as session:
        yield SqlPaymentRepository(session)


@app.on_startup
async def setup_context() -> None:
    client = httpx.AsyncClient(timeout=settings.webhook_timeout_seconds)
    app.context.set_global("http_client", client)
    app.context.set_global("gateway", EmulatedPaymentGateway())
    app.context.set_global("notifier", HttpWebhookNotifier(client=client))
    app.context.set_global("payment_service", ProcessPaymentService())


@app.on_shutdown
async def close_http_client() -> None:
    client: httpx.AsyncClient = app.context.get("http_client")
    await client.aclose()


async def handle_payment(
    payment_id: UUID,
    *,
    service: PaymentProcessor,
    gateway: PaymentGateway,
    notifier: WebhookNotifier,
) -> None:
    async with sql_uow() as payments_repo:
        decision = await service.claim(payments_repo, payment_id)
    if decision == ClaimDecision.done:
        return
    status = await gateway.charge(payment_id)
    async with sql_uow() as payments_repo:
        payment = await service.finalize(
            payments_repo,
            payment_id,
            status=status,
        )
    await notifier.notify(payment.webhook_url, webhook_payload(payment))


async def _publish_dlq(
    body: PaymentCreatedEvent,
    *,
    error: str,
    delivery: Any,
) -> None:
    await broker.publish(
        {**body.model_dump(mode="json"), "error": error},
        queue=payments_dlq,
        persist=True,
        mandatory=True,
        timeout=settings.rabbitmq_publish_timeout_seconds,
        message_id=f"dlq-{body.payment_id}",
    )
    await delivery.ack()


def _retry_attempt(delivery: RabbitMessage) -> int:
    value = delivery.headers.get(_RETRY_ATTEMPT_HEADER, 0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _retry_queue(attempt: int) -> RabbitQueue:
    return payments_retry_5s if attempt == 1 else payments_retry_10s


async def _schedule_retry(
    body: PaymentCreatedEvent,
    *,
    delivery: RabbitMessage,
    attempt: int,
) -> None:
    await broker.publish(
        body.model_dump(mode="json"),
        queue=_retry_queue(attempt),
        persist=True,
        mandatory=True,
        timeout=settings.rabbitmq_publish_timeout_seconds,
        headers={_RETRY_ATTEMPT_HEADER: attempt},
        message_id=f"retry-{body.payment_id}-{attempt}",
    )
    await delivery.ack()


@broker.subscriber(payments_queue, ack_policy=AckPolicy.MANUAL)
async def process_payment(
    body: PaymentCreatedEvent,
    delivery: RabbitMessage,
    gateway: Annotated[PaymentGateway, Context()],
    notifier: Annotated[WebhookNotifier, Context()],
    service: Annotated[PaymentProcessor, Context("payment_service")],
) -> None:
    try:
        await handle_payment(
            body.payment_id,
            service=service,
            gateway=gateway,
            notifier=notifier,
        )
    except _PERMANENT as exc:
        logger.exception("Permanent failure on %s", settings.payments_queue)
        await _publish_dlq(body, error=str(exc), delivery=delivery)
    except _RETRYABLE as exc:
        logger.exception("Retryable failure on %s", settings.payments_queue)
        attempt = _retry_attempt(delivery)
        if attempt + 1 >= _MAX_PROCESSING_ATTEMPTS:
            await _publish_dlq(body, error=str(exc), delivery=delivery)
        else:
            await _schedule_retry(body, delivery=delivery, attempt=attempt + 1)
    else:
        await delivery.ack()


async def main() -> None:
    await broker.connect()
    await declare_topology(broker)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
