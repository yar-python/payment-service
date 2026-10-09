import enum


class Currency(enum.StrEnum):
    RUB = "RUB"
    USD = "USD"
    EUR = "EUR"


class PaymentStatus(enum.StrEnum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


TERMINAL_STATUSES = frozenset({PaymentStatus.succeeded, PaymentStatus.failed})


class ClaimDecision(enum.StrEnum):
    done = "done"
    charge = "charge"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    claimed = "claimed"
    published = "published"
