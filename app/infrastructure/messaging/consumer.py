import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

import httpx
from faststream import AckPolicy, Context, FastStream
from faststream.rabbit import RabbitMessage
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
_RETRYABLE = (SQLAlchemyError,)


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
    except _RETRYABLE:
        logger.exception("Retryable failure on %s", settings.payments_queue)
        await delivery.reject(requeue=True)
    else:
        await delivery.ack()


async def main() -> None:
    await broker.connect()
    await declare_topology(broker)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
