import asyncio
import logging
from datetime import timedelta

from sqlalchemy.exc import SQLAlchemyError

from app.application.publish_outbox import PublishOutboxService
from app.config import settings
from app.infrastructure.db.repositories import SqlOutboxClaimRepository
from app.infrastructure.messaging.broker import (
    RabbitEventPublisher,
    create_broker,
    declare_topology,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(self) -> None:
        self._broker = create_broker()
        self._publisher = RabbitEventPublisher(self._broker)
        self._outbox = SqlOutboxClaimRepository()

    async def publish_batch(self) -> None:
        try:
            count = await PublishOutboxService(
                self._outbox,
                self._publisher,
                claim_timeout=timedelta(seconds=settings.outbox_claim_timeout_seconds),
            ).execute(limit=settings.outbox_batch_limit)
        except SQLAlchemyError:
            logger.exception("Outbox worker iteration failed")
            return
        if count:
            logger.info("Published %s outbox event(s)", count)

    async def run(self) -> None:
        async with self._broker:
            await declare_topology(self._broker)
            logger.info(
                "Outbox worker started (interval=%ss, queue=%s)",
                settings.outbox_poll_interval_seconds,
                settings.payments_queue,
            )
            while True:
                await self.publish_batch()
                await asyncio.sleep(settings.outbox_poll_interval_seconds)


def main() -> None:
    asyncio.run(OutboxPublisher().run())


if __name__ == "__main__":
    main()
