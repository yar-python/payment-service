from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import OutboxStatus
from app.domain.protocols import OutboxClaimRepository, OutboxRepository
from app.infrastructure.db.models import OutboxEvent
from app.infrastructure.db.session import async_session_factory


class SqlOutboxRepository(OutboxRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, *, payment_id: UUID, event_type: str) -> None:
        self._session.add(
            OutboxEvent(
                payment_id=payment_id,
                event_type=event_type,
                status=OutboxStatus.pending,
            )
        )


class SqlOutboxClaimRepository(OutboxClaimRepository):
    async def claim_next(self, *, expired_before: datetime) -> OutboxEvent | None:
        async with async_session_factory() as session:
            result = await session.execute(
                select(OutboxEvent)
                .where(
                    or_(
                        OutboxEvent.status == OutboxStatus.pending,
                        and_(
                            OutboxEvent.status == OutboxStatus.claimed,
                            OutboxEvent.claimed_at < expired_before,
                        ),
                    ),
                )
                .order_by(OutboxEvent.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            event = result.scalar_one_or_none()
            if event is None:
                return None
            event.status = OutboxStatus.claimed
            event.claimed_at = datetime.now(UTC)
            await session.commit()
            return event

    async def mark_published(self, event_id: int, published_at: datetime) -> None:
        await self._update_unpublished(
            event_id,
            status=OutboxStatus.published,
            published_at=published_at,
        )

    async def release_claim(self, event_id: int) -> None:
        await self._update_unpublished(
            event_id,
            status=OutboxStatus.pending,
            claimed_at=None,
        )

    async def _update_unpublished(self, event_id: int, **values: datetime | str | None) -> None:
        async with async_session_factory() as session:
            await session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == event_id,
                    OutboxEvent.status != OutboxStatus.published,
                )
                .values(**values)
            )
            await session.commit()
