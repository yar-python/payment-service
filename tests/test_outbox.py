import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from aiormq.exceptions import AMQPError
from pamqp.commands import Basic as PamqpBasic

from app.application.publish_outbox import PublishOutboxService
from app.config import settings
from app.domain.enums import OutboxStatus
from app.domain.payment import PaymentCreatedMessage
from app.infrastructure.messaging.broker import (
    RabbitEventPublisher,
    payments_queue,
    payments_retry_5s,
    payments_retry_10s,
)


def _event(event_type: str = "payment.created", event_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=event_id,
        payment_id=uuid4(),
        status=OutboxStatus.pending,
        event_type=event_type,
        created_at=datetime.now(UTC),
        published_at=None,
        claimed_at=None,
    )


class Outbox:
    def __init__(self, events: list[SimpleNamespace]) -> None:
        self.events = events

    async def claim_next(self, *, expired_before: datetime):
        for event in self.events:
            pending = event.status == OutboxStatus.pending
            expired = (
                event.status == OutboxStatus.claimed
                and event.claimed_at is not None
                and event.claimed_at < expired_before
            )
            if not pending and not expired:
                continue
            event.status = OutboxStatus.claimed
            event.claimed_at = datetime.now(UTC)
            return event
        return None

    async def mark_published(self, event_id, published_at) -> None:
        for row in self.events:
            if row.id == event_id and row.status != OutboxStatus.published:
                row.status = OutboxStatus.published
                row.published_at = published_at

    async def release_claim(self, event_id) -> None:
        for row in self.events:
            if row.id == event_id and row.status != OutboxStatus.published:
                row.status = OutboxStatus.pending
                row.claimed_at = None


class Publisher:
    def __init__(self, fail: bool = False, *, wait_for: int = 0) -> None:
        self.fail = fail
        self.wait_for = wait_for
        self.body = None
        self.entered = 0
        self.release = asyncio.Event()

    async def publish(self, event, body) -> None:
        self.body = body
        self.entered += 1
        if self.fail:
            raise AMQPError(event.event_type)
        if not self.wait_for:
            return
        if self.entered == self.wait_for:
            self.release.set()
        await asyncio.wait_for(self.release.wait(), timeout=1)


def _service(outbox: Outbox, publisher: Publisher) -> PublishOutboxService:
    return PublishOutboxService(
        outbox,
        publisher,
        claim_timeout=timedelta(seconds=30),
    )


async def test_publish_failure_releases_the_claim() -> None:
    event = _event()
    published = await _service(Outbox([event]), Publisher(fail=True)).execute()
    assert published == 0
    assert event.status == OutboxStatus.pending
    assert event.published_at is None
    assert event.claimed_at is None


async def test_claimed_events_are_published_concurrently() -> None:
    events = [_event(event_id=event_id) for event_id in range(3)]
    publisher = Publisher(wait_for=len(events))
    published = await _service(Outbox(events), publisher).execute()
    assert published == 3
    assert publisher.entered == 3
    assert all(event.published_at is not None for event in events)


class Broker:
    def __init__(self) -> None:
        self.kwargs: dict | None = None
        self.queue = None

    async def publish(self, _body, queue, **kwargs):
        self.kwargs = kwargs
        self.queue = queue
        return PamqpBasic.Ack()


async def test_payment_created_is_published_to_payments_new() -> None:
    event = _event("payment.created")
    broker = Broker()
    await RabbitEventPublisher(broker).publish(  # type: ignore[arg-type]
        event,
        PaymentCreatedMessage(payment_id=event.payment_id),
    )
    assert broker.queue is payments_queue
    assert broker.kwargs is not None
    assert broker.kwargs["persist"] is True
    assert broker.kwargs["message_id"] == str(event.id)
    assert broker.kwargs["timeout"] == settings.rabbitmq_publish_timeout_seconds


def test_retry_queues_apply_exponential_backoff_and_return_to_payments_new() -> None:
    assert payments_retry_5s.arguments["x-message-ttl"] == 5_000
    assert payments_retry_10s.arguments["x-message-ttl"] == 10_000
    for queue in (payments_retry_5s, payments_retry_10s):
        assert queue.arguments["x-dead-letter-exchange"] == ""
        assert queue.arguments["x-dead-letter-routing-key"] == settings.payments_queue
