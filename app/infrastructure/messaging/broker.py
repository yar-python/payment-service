from faststream.rabbit import Channel, RabbitBroker, RabbitQueue

from app.config import settings
from app.domain.payment import PaymentCreatedMessage
from app.domain.protocols import EventPublisher, OutboxRecord


def _queue(name: str) -> RabbitQueue:
    return RabbitQueue(name, durable=True)


def _retry_queue(name: str, *, delay_ms: int) -> RabbitQueue:
    return RabbitQueue(
        name,
        durable=True,
        arguments={
            "x-message-ttl": delay_ms,
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": settings.payments_queue,
        },
    )


payments_queue = _queue(settings.payments_queue)
payments_dlq = _queue(settings.payments_dlq)
payments_retry_5s = _retry_queue("payments.retry.5s", delay_ms=5_000)
payments_retry_10s = _retry_queue("payments.retry.10s", delay_ms=10_000)


def default_channel() -> Channel:
    return Channel(
        prefetch_count=settings.consumer_prefetch,
        publisher_confirms=True,
        on_return_raises=True,
    )


def create_broker() -> RabbitBroker:
    return RabbitBroker(
        settings.rabbitmq_url,
        timeout=settings.rabbitmq_connect_timeout_seconds,
        default_channel=default_channel(),
    )


async def declare_topology(broker: RabbitBroker) -> None:
    await broker.declare_queue(payments_queue)
    await broker.declare_queue(payments_dlq)
    await broker.declare_queue(payments_retry_5s)
    await broker.declare_queue(payments_retry_10s)


class RabbitEventPublisher(EventPublisher):
    def __init__(self, broker: RabbitBroker) -> None:
        self._broker = broker

    async def publish(self, event: OutboxRecord, message: PaymentCreatedMessage) -> None:
        await self._broker.publish(
            {"payment_id": str(message.payment_id)},
            queue=payments_queue,
            persist=True,
            mandatory=True,
            timeout=settings.rabbitmq_publish_timeout_seconds,
            message_id=str(event.id),
        )
