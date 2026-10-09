from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.payment_service import PaymentService
from app.config import settings
from app.infrastructure.db.repositories import SqlOutboxRepository, SqlPaymentRepository
from app.infrastructure.db.session import get_session


def verify_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key"
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
