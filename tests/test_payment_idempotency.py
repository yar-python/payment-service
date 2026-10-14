from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.exc import IntegrityError

from app.application.payment_service import PaymentService
from app.domain.enums import Currency, PaymentStatus
from app.domain.exceptions import IdempotencyConflictError, PaymentNotCreatedError
from app.domain.payment import NewPayment


def _payment(**overrides: object) -> SimpleNamespace:
    data: dict[str, object] = {
        "id": uuid4(),
        "amount": Decimal("10.10"),
        "currency": "RUB",
        "description": "order",
        "metadata_": {"order_id": "1"},
        "status": PaymentStatus.pending,
        "idempotency_key": "key-1",
        "webhook_url": "https://example.com/hook",
        "created_at": datetime.now(UTC),
        "processed_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _new_payment(**overrides: object) -> NewPayment:
    data: dict[str, object] = {
        "amount": Decimal("10.10"),
        "currency": Currency.RUB,
        "description": "order",
        "metadata": {"order_id": "1"},
        "webhook_url": "https://example.com/hook",
        "idempotency_key": "key-1",
    }
    data.update(overrides)
    return NewPayment(**data)  # type: ignore[arg-type]


def _unique_error(constraint: str = "ix_payments_idempotency_key") -> IntegrityError:
    orig = asyncpg.UniqueViolationError.new({"M": "duplicate key", "C": "23505", "n": constraint})
    return IntegrityError("INSERT", {}, orig)


class PaymentRepo:
    def __init__(
        self,
        existing: SimpleNamespace | None = None,
        *,
        visible_on_reread: bool = False,
    ) -> None:
        self.existing = existing
        self.visible_on_reread = visible_on_reread
        self.lookups = 0
        self.created: list[SimpleNamespace] = []

    async def get_by_idempotency_key(self, idempotency_key: str):
        self.lookups += 1
        if self.visible_on_reread and self.lookups == 1:
            return None
        if self.existing is not None and self.existing.idempotency_key == idempotency_key:
            return self.existing
        return None

    async def create(self, payment: NewPayment):
        created = _payment(
            id=uuid4(),
            amount=payment.amount,
            currency=payment.currency.value,
            description=payment.description,
            metadata_=payment.metadata,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
        )
        self.created.append(created)
        return created


class OutboxRepo:
    def __init__(self) -> None:
        self.created: list[object] = []

    async def add_event(self, *, payment_id, event_type) -> None:
        self.created.append((payment_id, event_type))


class Session:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.error is not None:
            raise self.error

    async def rollback(self) -> None:
        self.rollbacks += 1


def _service(
    payments: PaymentRepo,
    outbox: OutboxRepo | None = None,
    session: Session | None = None,
) -> PaymentService:
    return PaymentService(
        session or Session(),  # type: ignore[arg-type]
        payments,
        outbox or OutboxRepo(),
    )


async def test_same_key_and_same_payload_returns_existing_payment() -> None:
    existing = _payment()
    payments = PaymentRepo(existing)
    outbox = OutboxRepo()
    result = await _service(payments, outbox).create(_new_payment())

    assert result.created is False
    assert result.payment.id == existing.id
    assert payments.created == []
    assert outbox.created == []


async def test_same_key_and_different_payload_is_a_conflict() -> None:
    payments = PaymentRepo(_payment())
    with pytest.raises(IdempotencyConflictError):
        await _service(payments).create(_new_payment(amount=Decimal("11.00")))
    assert payments.created == []


async def test_new_payment_is_stored_with_outbox_event() -> None:
    payments = PaymentRepo()
    outbox = OutboxRepo()
    session = Session()
    result = await _service(payments, outbox, session).create(_new_payment())

    assert result.created is True
    assert result.payment.id == payments.created[0].id
    assert outbox.created == [(result.payment.id, "payment.created")]
    assert session.commits == 1
    assert session.rollbacks == 0


async def test_concurrent_insert_returns_stored_payment_with_same_body() -> None:
    existing = _payment()
    payments = PaymentRepo(existing, visible_on_reread=True)
    session = Session(error=_unique_error())
    result = await _service(payments, session=session).create(_new_payment())

    assert result.created is False
    assert result.payment.id == existing.id
    assert session.rollbacks == 1


async def test_concurrent_insert_with_different_body_is_a_conflict() -> None:
    payments = PaymentRepo(_payment(amount=Decimal("11.00")), visible_on_reread=True)
    session = Session(error=_unique_error())
    with pytest.raises(IdempotencyConflictError):
        await _service(payments, session=session).create(_new_payment())
    assert session.rollbacks == 1


async def test_unique_violation_without_stored_payment_is_not_created() -> None:
    payments = PaymentRepo()
    session = Session(error=_unique_error(constraint="payments_pkey"))
    with pytest.raises(PaymentNotCreatedError):
        await _service(payments, session=session).create(_new_payment())
    assert session.rollbacks == 1
