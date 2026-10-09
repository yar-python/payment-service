class DomainError(Exception):
    pass


class PaymentNotFoundError(DomainError):
    pass


class IdempotencyConflictError(DomainError):
    pass


class PaymentNotCreatedError(DomainError):
    pass


class WebhookError(DomainError):
    pass
