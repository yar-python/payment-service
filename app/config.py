from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    rabbitmq_user: str
    rabbitmq_password: str
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    api_key: str

    @property
    def database_url(self) -> str:
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def rabbitmq_url(self) -> str:
        user = quote(self.rabbitmq_user, safe="")
        password = quote(self.rabbitmq_password, safe="")
        return f"amqp://{user}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}/"

    payments_queue: str = "payments.new"
    payments_dlq: str = "payments.dlq"
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_limit: int = 100
    outbox_claim_timeout_seconds: float = 120.0
    consumer_prefetch: int = 10
    webhook_max_attempts: int = 3
    webhook_retry_delay_seconds: float = 5.0
    webhook_timeout_seconds: float = 10.0
    rabbitmq_connect_timeout_seconds: float = 10.0
    rabbitmq_publish_timeout_seconds: float = 10.0
    db_pool_size: int = 2
    db_max_overflow: int = 3
    db_pool_timeout_seconds: float = 30.0
    db_pool_recycle_seconds: int = 1800
    db_connect_timeout_seconds: float = 10.0
    db_command_timeout_seconds: float = 10.0


settings = Settings()
