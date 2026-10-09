from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from app.domain.enums import OutboxStatus, PaymentStatus
from app.domain.payment import NewPayment, PaymentCreatedMessage


class PaymentRecord(Protocol):
    id: UUID
    amount: Decimal
    currency: str
    description: str
    metadata_: dict[str, Any]
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None


class OutboxRecord(Protocol):
    id: int
    payment_id: UUID
    event_type: str
    status: OutboxStatus
    published_at: datetime | None
    claimed_at: datetime | None


class PaymentRepository(Protocol):
    async def get_by_id(self, payment_id: UUID) -> PaymentRecord | None: ...
    async def get_for_update(self, payment_id: UUID) -> PaymentRecord | None: ...
    async def get_by_idempotency_key(self, idempotency_key: str) -> PaymentRecord | None: ...
    async def create(self, payment: NewPayment) -> PaymentRecord: ...
    async def commit(self) -> None: ...


class OutboxRepository(Protocol):
    async def add_event(self, *, payment_id: UUID, event_type: str) -> None: ...


class OutboxClaimRepository(Protocol):
    async def claim_next(self, *, expired_before: datetime) -> OutboxRecord | None: ...
    async def mark_published(self, event_id: int, published_at: datetime) -> None: ...
    async def release_claim(self, event_id: int) -> None: ...


class PaymentGateway(Protocol):
    async def charge(self, payment_id: UUID) -> PaymentStatus: ...


class EventPublisher(Protocol):
    async def publish(self, event: OutboxRecord, message: PaymentCreatedMessage) -> None: ...
