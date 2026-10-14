from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from tenacity import wait_none

from app.domain.exceptions import WebhookError
from app.infrastructure.webhook import HttpWebhookNotifier


@pytest_asyncio.fixture
async def webhook_factory() -> AsyncIterator[object]:
    clients: list[httpx.AsyncClient] = []

    def open_notifier(status_code: int) -> tuple[HttpWebhookNotifier, list[httpx.Request]]:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(status_code)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(client)
        return HttpWebhookNotifier(client=client), calls

    original_wait = HttpWebhookNotifier.notify.retry.wait  # type: ignore[attr-defined]
    HttpWebhookNotifier.notify.retry.wait = wait_none()  # type: ignore[attr-defined]
    yield open_notifier
    HttpWebhookNotifier.notify.retry.wait = original_wait  # type: ignore[attr-defined]
    for client in clients:
        await client.aclose()


async def _notify(notifier: HttpWebhookNotifier, event_id: str = "event-1") -> None:
    await notifier.notify(
        "https://example.com/hook",
        {
            "event_id": event_id,
            "payment_id": "payment-1",
            "status": "succeeded",
            "amount": "10.00",
            "currency": "RUB",
        },
    )


async def test_send_error_is_retried(webhook_factory) -> None:
    notifier, calls = webhook_factory(404)
    with pytest.raises(WebhookError):
        await _notify(notifier)
    assert len(calls) == 3


async def test_success_sends_idempotency_key_and_decimal_amount(webhook_factory) -> None:
    notifier, calls = webhook_factory(204)
    await _notify(notifier, event_id="event-42")
    assert calls[0].headers["Idempotency-Key"] == "event-42"
    assert b'"amount":"10.00"' in calls[0].content or b'"amount": "10.00"' in calls[0].content
