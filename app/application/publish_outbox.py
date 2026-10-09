import asyncio
import logging
from datetime import UTC, datetime, timedelta

from aiormq.exceptions import AMQPError
from sqlalchemy.exc import SQLAlchemyError

from app.domain.payment import PaymentCreatedMessage
from app.domain.protocols import EventPublisher, OutboxClaimRepository, OutboxRecord

logger = logging.getLogger(__name__)

_PUBLISH_ERRORS = (AMQPError, TimeoutError)


class PublishOutboxService:
    def __init__(
        self,
        outbox: OutboxClaimRepository,
        publisher: EventPublisher,
        claim_timeout: timedelta,
    ) -> None:
        self._outbox = outbox
        self._publisher = publisher
        self._claim_timeout = claim_timeout

    async def execute(self, limit: int = 100) -> int:
        tasks: list[asyncio.Task[bool]] = []
        for _ in range(limit):
            event = await self._outbox.claim_next(
                expired_before=datetime.now(UTC) - self._claim_timeout,
            )
            if event is None:
                break
            tasks.append(asyncio.create_task(self._publish_one(event)))
        if not tasks:
            return 0
        results = await asyncio.gather(*tasks)
        return sum(results)

    async def _publish_one(self, event: OutboxRecord) -> bool:
        try:
            await self._publisher.publish(
                event,
                PaymentCreatedMessage(payment_id=event.payment_id),
            )
        except _PUBLISH_ERRORS:
            logger.exception("Outbox event %s was not published", event.id)
            await self._release_claim(event.id)
            return False
        await self._outbox.mark_published(event.id, datetime.now(UTC))
        return True

    async def _release_claim(self, event_id: int) -> None:
        try:
            await self._outbox.release_claim(event_id)
        except SQLAlchemyError:
            logger.exception("Outbox event %s claim was not released", event_id)
