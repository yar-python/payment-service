from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domain.enums import TERMINAL_STATUSES, ClaimDecision, PaymentStatus
from app.domain.exceptions import PaymentNotFoundError
from app.domain.protocols import PaymentProcessor, PaymentRecord, PaymentRepository


def webhook_payload(payment: PaymentRecord) -> dict[str, Any]:
    assert payment.processed_at is not None
    return {
        "event_id": str(payment.id),
        "payment_id": str(payment.id),
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "created_at": payment.created_at.isoformat(),
        "processed_at": payment.processed_at.isoformat(),
    }


class ProcessPaymentService(PaymentProcessor):
    async def claim(self, payments: PaymentRepository, payment_id: UUID) -> ClaimDecision:
        payment = await payments.get_for_update(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if payment.status in TERMINAL_STATUSES:
            return ClaimDecision.done
        return ClaimDecision.charge

    async def finalize(
        self,
        payments: PaymentRepository,
        payment_id: UUID,
        *,
        status: PaymentStatus,
    ) -> PaymentRecord:
        payment = await payments.get_for_update(payment_id)
        if payment is None:
            raise PaymentNotFoundError(str(payment_id))
        if payment.status not in TERMINAL_STATUSES:
            payment.status = status
        if payment.processed_at is None:
            payment.processed_at = datetime.now(UTC)
        await payments.commit()
        return payment
