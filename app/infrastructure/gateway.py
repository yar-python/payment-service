import asyncio
import logging
import random
from uuid import UUID

from app.domain.enums import PaymentStatus
from app.domain.protocols import PaymentGateway

logger = logging.getLogger(__name__)


class EmulatedPaymentGateway(PaymentGateway):
    async def charge(self, payment_id: UUID) -> PaymentStatus:
        delay = random.uniform(2.0, 5.0)
        logger.info("Charging payment %s at the gateway (%.2fs)", payment_id, delay)
        await asyncio.sleep(delay)
        outcome = PaymentStatus.succeeded if random.random() < 0.9 else PaymentStatus.failed
        logger.info("Gateway charged payment %s as %s", payment_id, outcome)
        return outcome
