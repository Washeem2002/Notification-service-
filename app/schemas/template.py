import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import Channel


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.]+$")
    channel: Channel
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


class TemplateUpdate(BaseModel):
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    channel: str
    subject: str | None
    body: str
    created_at: datetime
    updated_at: datetime
