from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.infrastructure.messaging.consumer as consumer
from app.application.process_payment import ProcessPaymentService
from app.domain.enums import PaymentStatus
from app.infrastructure.messaging.consumer import handle_payment


def _payment() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        amount=Decimal("25.00"),
        currency="RUB",
        description="",
        metadata_={},
        status=PaymentStatus.pending,
        idempotency_key="key",
        webhook_url="https://example.com/hook",
        created_at=datetime.now(UTC),
        processed_at=None,
    )


class Payments:
    def __init__(self, payment: SimpleNamespace) -> None:
        self.payment = payment

    async def get_by_id(self, payment_id: UUID) -> SimpleNamespace | None:
        if self.payment.id == payment_id:
            return self.payment
        return None

    async def get_for_update(self, _payment_id: UUID) -> SimpleNamespace:
        return self.payment

    async def commit(self) -> None:
        return None


class Gateway:
    def __init__(self) -> None:
        self.charges = 0

    async def charge(self, _payment_id: UUID) -> PaymentStatus:
        self.charges += 1
        return PaymentStatus.succeeded


class Notifier:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def notify(self, webhook_url: str, payload: dict[str, Any]) -> None:
        if self.fail:
            raise TimeoutError("webhook down")
        self.calls.append((webhook_url, payload))


def _patch_uow(monkeypatch: pytest.MonkeyPatch, payments: Payments) -> None:
    @asynccontextmanager
    async def fake_uow() -> AsyncIterator[Payments]:
        yield payments

    monkeypatch.setattr(consumer, "sql_uow", fake_uow)


async def test_consumer_sends_webhook_after_status_is_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    payments = Payments(payment)
    gateway = Gateway()
    notifier = Notifier()
    _patch_uow(monkeypatch, payments)
    service = ProcessPaymentService()

    await handle_payment(
        payment.id,
        service=service,
        gateway=gateway,
        notifier=notifier,
    )

    assert payment.status == PaymentStatus.succeeded
    assert payment.processed_at is not None
    assert gateway.charges == 1
    assert notifier.calls[0][0] == "https://example.com/hook"
    assert notifier.calls[0][1]["amount"] == "25.00"
    assert notifier.calls[0][1]["status"] == PaymentStatus.succeeded

    await handle_payment(
        payment.id,
        service=service,
        gateway=gateway,
        notifier=notifier,
    )
    assert gateway.charges == 1
    assert len(notifier.calls) == 1


async def test_webhook_failure_keeps_processed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment = _payment()
    payments = Payments(payment)
    gateway = Gateway()
    _patch_uow(monkeypatch, payments)

    with pytest.raises(TimeoutError):
        await handle_payment(
            payment.id,
            service=ProcessPaymentService(),
            gateway=gateway,
            notifier=Notifier(fail=True),
        )

    assert gateway.charges == 1
    assert payment.status == PaymentStatus.succeeded
    assert payment.processed_at is not None
