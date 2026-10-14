from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from app.api.deps import get_payment_service
from app.config import settings
from app.domain.enums import PaymentStatus
from app.main import app


def test_compose_contains_required_services() -> None:
    text = Path("docker-compose.yml").read_text()
    for name in ("postgres:", "rabbitmq:", "api:", "consumer:"):
        assert name in text


async def test_duplicate_create_returns_existing_payment(api_client: httpx.AsyncClient) -> None:
    payment_id = uuid4()

    class Service:
        async def create(self, _payment: object) -> SimpleNamespace:
            return SimpleNamespace(
                payment=SimpleNamespace(
                    id=payment_id,
                    status=PaymentStatus.pending,
                    created_at=datetime.now(UTC),
                ),
                created=False,
            )

    app.dependency_overrides[get_payment_service] = lambda: Service()
    response = await api_client.post(
        "/api/v1/payments",
        headers={
            "X-API-Key": settings.api_key,
            "Idempotency-Key": "same-key",
        },
        json={
            "amount": "10.00",
            "currency": "RUB",
            "webhook_url": "https://example.com/hook",
        },
    )
    assert response.status_code == 200
    assert response.json()["payment_id"] == str(payment_id)
