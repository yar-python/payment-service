from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import PaymentStatus
from app.domain.payment import NewPayment
from app.domain.protocols import PaymentRepository
from app.infrastructure.db.models import Payment


class SqlPaymentRepository(PaymentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, payment_id: UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_for_update(self, payment_id: UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id, with_for_update=True)

    async def get_by_idempotency_key(self, idempotency_key: str) -> Payment | None:
        result = await self._session.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        return result.scalar_one_or_none()

    async def create(self, payment: NewPayment) -> Payment:
        row = Payment(
            id=uuid4(),
            amount=payment.amount,
            currency=payment.currency.value,
            description=payment.description,
            metadata_=payment.metadata,
            status=PaymentStatus.pending,
            idempotency_key=payment.idempotency_key,
            webhook_url=payment.webhook_url,
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        return row

    async def commit(self) -> None:
        await self._session.commit()
