from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+asyncpg://notif:notif@localhost:5432/notif"
    redis_url: str = "redis://localhost:6379/0"
    api_keys: list[str] = ["dev-key"]
    log_level: str = "INFO"
    max_attempts: int = 5
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 300.0
    lease_seconds: int = 60
    reaper_interval_seconds: int = 15
    stale_queued_seconds: int = 30
    worker_concurrency: int = 10
    provider_failure_rate: float = 0.0
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"
    channel_rate_email: int = 50
    channel_rate_sms: int = 20
    channel_rate_push: int = 100
    create_rate_limit: int = 300
    batch_max_size: int = 100

    @field_validator("api_keys", mode="before")
    @classmethod
    def split_keys(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def channel_rate(self, channel: str) -> int:
        return {
            "email": self.channel_rate_email,
            "sms": self.channel_rate_sms,
            "push": self.channel_rate_push,
        }[channel]


@lru_cache
def get_settings() -> Settings:
    return Settings()
