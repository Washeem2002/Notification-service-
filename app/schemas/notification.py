import re
import uuid
from datetime import datetime
from typing import Any, Self

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.base import Category, Channel, Status

PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")


class NotificationCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    channel: Channel
    category: Category = Category.transactional
    recipient: str = Field(min_length=1, max_length=320)
    template_name: str | None = Field(default=None, max_length=100)
    variables: dict[str, Any] = Field(default_factory=dict)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=10000)
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if not self.template_name and not self.body:
            raise ValueError("either template_name or body is required")
        if self.channel is Channel.email:
            try:
                self.recipient = validate_email(
                    self.recipient, check_deliverability=False
                ).normalized
            except EmailNotValidError as exc:
                raise ValueError(f"invalid email recipient: {exc}") from exc
        elif self.channel is Channel.sms and not PHONE_PATTERN.match(self.recipient):
            raise ValueError("sms recipient must be in E.164 format")
        return self


class BatchCreate(BaseModel):
    items: list[NotificationCreate] = Field(min_length=1)


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: str
    channel: str
    category: str
    priority: int
    recipient: str
    template_name: str | None
    subject: str | None
    body: str
    status: Status
    attempts: int
    max_attempts: int
    last_error: str | None
    provider_message_id: str | None
    scheduled_at: datetime | None
    next_attempt_at: datetime | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt: int
    outcome: str
    error: str | None
    created_at: datetime


class NotificationDetail(NotificationOut):
    history: list[AttemptOut] = []


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None


class BatchResult(BaseModel):
    items: list[NotificationOut]
