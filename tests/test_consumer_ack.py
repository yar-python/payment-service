from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.infrastructure.messaging.consumer as consumer
from app.domain.exceptions import PaymentNotFoundError, WebhookError
from app.infrastructure.messaging.consumer import process_payment
from app.infrastructure.messaging.schemas import PaymentCreatedEvent


class FakeMsg:
    def __init__(self, headers: dict[str, object] | None = None) -> None:
        self.acked = False
        self.rejected: bool | None = None
        self.headers = headers or {}

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = requeue


class Dlq:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        body: PaymentCreatedEvent,
        *,
        error: str,
        delivery: FakeMsg,
    ) -> None:
        self.calls.append({**body.model_dump(mode="json"), "error": error})
        await delivery.ack()


def _message() -> PaymentCreatedEvent:
    return PaymentCreatedEvent(payment_id=uuid4())


async def test_success_acks_once(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = FakeMsg()
    dlq = Dlq()

    async def handle(_payment_id: UUID, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(consumer, "handle_payment", handle)
    monkeypatch.setattr(consumer, "_publish_dlq", dlq)

    body = _message()
    await process_payment(
        body,
        delivery,  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
    )

    assert delivery.acked is True
    assert delivery.rejected is None
    assert dlq.calls == []


async def test_retryable_failure_is_scheduled_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = FakeMsg()
    dlq = Dlq()
    published: list[dict[str, Any]] = []

    async def handle(_payment_id: UUID, **_kwargs: Any) -> None:
        raise SQLAlchemyError("db down")

    async def publish(_body: object, **kwargs: Any) -> None:
        published.append(kwargs)

    monkeypatch.setattr(consumer, "handle_payment", handle)
    monkeypatch.setattr(consumer, "_publish_dlq", dlq)
    monkeypatch.setattr(consumer.broker, "publish", publish)

    body = _message()
    await process_payment(
        body,
        delivery,  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
    )

    assert delivery.acked is True
    assert delivery.rejected is None
    assert dlq.calls == []
    assert published == [
        {
            "queue": consumer.payments_retry_5s,
            "persist": True,
            "mandatory": True,
            "timeout": consumer.settings.rabbitmq_publish_timeout_seconds,
            "headers": {"x-retry-attempt": 1},
            "message_id": f"retry-{body.payment_id}-1",
        }
    ]


async def test_retryable_failure_after_third_attempt_is_dead_lettered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = FakeMsg(headers={"x-retry-attempt": 2})
    dlq = Dlq()

    async def handle(_payment_id: UUID, **_kwargs: Any) -> None:
        raise SQLAlchemyError("db down")

    monkeypatch.setattr(consumer, "handle_payment", handle)
    monkeypatch.setattr(consumer, "_publish_dlq", dlq)

    body = _message()
    await process_payment(
        body,
        delivery,  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
    )

    assert delivery.acked is True
    assert dlq.calls == [{**body.model_dump(mode="json"), "error": "db down"}]


async def test_permanent_failure_is_dead_lettered(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = FakeMsg()
    dlq = Dlq()
    body = _message()

    async def handle(_payment_id: UUID, **_kwargs: Any) -> None:
        raise WebhookError("HTTP 500")

    monkeypatch.setattr(consumer, "handle_payment", handle)
    monkeypatch.setattr(consumer, "_publish_dlq", dlq)

    await process_payment(
        body,
        delivery,  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
    )

    assert dlq.calls == [{**body.model_dump(mode="json"), "error": "HTTP 500"}]
    assert delivery.acked is True


async def test_missing_payment_is_dead_lettered(monkeypatch: pytest.MonkeyPatch) -> None:
    delivery = FakeMsg()
    dlq = Dlq()
    body = _message()

    async def handle(_payment_id: UUID, **_kwargs: Any) -> None:
        raise PaymentNotFoundError(str(body.payment_id))

    monkeypatch.setattr(consumer, "handle_payment", handle)
    monkeypatch.setattr(consumer, "_publish_dlq", dlq)

    await process_payment(
        body,
        delivery,  # type: ignore[arg-type]
        gateway=object(),  # type: ignore[arg-type]
        notifier=object(),  # type: ignore[arg-type]
        service=object(),  # type: ignore[arg-type]
    )

    assert dlq.calls == [{**body.model_dump(mode="json"), "error": str(body.payment_id)}]
    assert delivery.acked is True
