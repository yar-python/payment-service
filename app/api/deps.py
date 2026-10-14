from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.payment_service import PaymentService
from app.config import settings
from app.infrastructure.db.repositories import SqlOutboxRepository, SqlPaymentRepository
from app.infrastructure.db.session import get_session


api_key_header = APIKeyHeader(
    name="X-API-Key",
    scheme_name="API key",
    auto_error=True,
)


def verify_api_key(x_api_key: Annotated[str , Security(api_key_header)]) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )


def get_payment_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SqlPaymentRepository:
    return SqlPaymentRepository(session)


def get_payment_service(session: Annotated[AsyncSession, Depends(get_session)]) -> PaymentService:
    return PaymentService(
        session,
        SqlPaymentRepository(session),
        SqlOutboxRepository(session),
    )
