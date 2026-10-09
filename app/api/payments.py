from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from app.api.deps import get_payment_repository, get_payment_service, verify_api_key
from app.api.schemas import ErrorResponse, PaymentCreate, PaymentCreatedResponse, PaymentResponse
from app.application.payment_service import PaymentService
from app.domain.exceptions import IdempotencyConflictError, PaymentNotCreatedError
from app.domain.payment import NewPayment
from app.domain.protocols import PaymentRepository

router = APIRouter(
    prefix="/api/v1/payments",
    tags=["payments"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Invalid or missing API key",
        }
    },
)


@router.post(
    path="",
    response_model=PaymentCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
    responses={
        status.HTTP_200_OK: {
            "model": PaymentCreatedResponse,
            "description": "Idempotency-Key was already used with the same payload",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Idempotency-Key was already used with a different payload",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Payment was not created and can be retried with the same key",
        },
    },
)
async def create_payment(
    body: PaymentCreate,
    response: Response,
    service: Annotated[PaymentService, Depends(get_payment_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> PaymentCreatedResponse:
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key header must not be empty",
        )
    try:
        result = await service.create(
            NewPayment(
                **body.model_dump(exclude={"webhook_url"}),
                webhook_url=str(body.webhook_url),
                idempotency_key=idempotency_key,
            )
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different payload",
        ) from exc
    except PaymentNotCreatedError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment was not created. Retry the request with the same Idempotency-Key.",
        ) from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return PaymentCreatedResponse(
        payment_id=result.payment.id,
        status=result.payment.status,
        created_at=result.payment.created_at,
    )


@router.get(
    path="/{payment_id}",
    response_model=PaymentResponse,
    dependencies=[Depends(verify_api_key)],
    responses={
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "Payment not found",
        },
    },
)
async def get_payment(
    payment_id: UUID,
    payments: Annotated[PaymentRepository, Depends(get_payment_repository)],
) -> PaymentResponse:
    payment = await payments.get_by_id(payment_id)
    if payment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return PaymentResponse.model_validate(payment)
