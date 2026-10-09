import logging
from dataclasses import dataclass

import asyncpg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import IdempotencyConflictError, PaymentNotCreatedError
from app.domain.payment import NewPayment
from app.domain.protocols import OutboxRepository, PaymentRecord, PaymentRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CreatePaymentResult:
    payment: PaymentRecord
    created: bool


class PaymentService:
    def __init__(
        self,
        session: AsyncSession,
        payments: PaymentRepository,
        outbox: OutboxRepository,
    ) -> None:
        self._session = session
        self._payments = payments
        self._outbox = outbox

    async def create(self, payment: NewPayment) -> CreatePaymentResult:
        existing = await self._payments.get_by_idempotency_key(payment.idempotency_key)
        if existing is not None:
            if not payment.matches(existing):
                raise IdempotencyConflictError
            return CreatePaymentResult(existing, created=False)

        added = await self._payments.create(payment)
        await self._outbox.add_event(payment_id=added.id, event_type="payment.created")
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if not isinstance(exc.orig, asyncpg.UniqueViolationError):
                raise
            return await self._process_unique_violation(payment, exc.orig)
        return CreatePaymentResult(added, created=True)

    async def _process_unique_violation(
        self,
        payment: NewPayment,
        conflict: asyncpg.UniqueViolationError,
    ) -> CreatePaymentResult:
        stored = await self._payments.get_by_idempotency_key(payment.idempotency_key)
        if stored is None:
            logger.error(
                "Payment was not created after unique violation on %s",
                conflict.constraint_name or "unknown",
            )
            raise PaymentNotCreatedError
        if not payment.matches(stored):
            raise IdempotencyConflictError
        return CreatePaymentResult(stored, created=False)
