from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.domain.enums import Currency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal = Field(
        ...,
        gt=0,
        max_digits=12,
        decimal_places=2,
        json_schema_extra={"example": "1500.00"},
    )
    currency: Currency
    description: str = ""
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra={"example": {"order_id": "1"}},
    )
    webhook_url: HttpUrl


class ErrorResponse(BaseModel):
    detail: str


class PaymentCreatedResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: Decimal = Field(json_schema_extra={"example": "1500.00"})
    currency: Currency
    description: str
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_",
        json_schema_extra={"example": {"order_id": "1"}},
    )
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None
