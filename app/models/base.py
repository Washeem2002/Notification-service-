import enum
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Channel(enum.StrEnum):
    email = "email"
    sms = "sms"
    push = "push"


class Category(enum.StrEnum):
    otp = "otp"
    transactional = "transactional"
    marketing = "marketing"


class Status(enum.StrEnum):
    queued = "queued"
    processing = "processing"
    retrying = "retrying"
    sent = "sent"
    dead = "dead"
    skipped = "skipped"
    cancelled = "cancelled"


PRIORITY = {Category.otp: 0, Category.transactional: 1, Category.marketing: 2}
