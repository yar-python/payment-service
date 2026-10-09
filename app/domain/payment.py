from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.domain.enums import Currency

if TYPE_CHECKING:
    from app.domain.protocols import PaymentRecord


@dataclass(frozen=True, slots=True)
class PaymentCreatedMessage:
    payment_id: UUID


@dataclass(frozen=True, slots=True)
class NewPayment:
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    webhook_url: str
    idempotency_key: str

    def matches(self, other: "PaymentRecord") -> bool:
        stored = (
            other.amount,
            other.currency,
            other.description,
            other.metadata_,
            other.webhook_url,
        )
        incoming = (
            self.amount,
            self.currency.value,
            self.description,
            self.metadata,
            self.webhook_url,
        )
        return stored == incoming
