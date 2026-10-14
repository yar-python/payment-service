import logging
from typing import Any

import httpx
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.domain.exceptions import WebhookError
from app.domain.protocols import WebhookNotifier

logger = logging.getLogger(__name__)


def _as_webhook_error(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception()  # type: ignore[union-attr]
    if isinstance(exc, httpx.HTTPStatusError):
        raise WebhookError(f"HTTP {exc.response.status_code}") from exc
    raise WebhookError(str(exc)) from exc


class HttpWebhookNotifier(WebhookNotifier):
    def __init__(self, *, client: httpx.AsyncClient) -> None:
        self._client = client

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(settings.webhook_max_attempts),
        wait=wait_exponential(
            multiplier=settings.webhook_retry_delay_seconds,
            exp_base=2,
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry_error_callback=_as_webhook_error,
    )
    async def notify(self, webhook_url: str, payload: dict[str, Any]) -> None:
        response = await self._client.post(
            webhook_url,
            json=payload,
            headers={"Idempotency-Key": str(payload["event_id"])},
        )
        response.raise_for_status()
        logger.info(
            "Webhook for payment %s delivered to %s",
            payload["payment_id"],
            webhook_url,
        )
