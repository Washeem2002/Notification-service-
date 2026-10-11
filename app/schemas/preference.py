from pydantic import BaseModel, ConfigDict, Field

from app.models.base import Category, Channel


class PreferenceItem(BaseModel):
    channel: Channel
    category: Category
    enabled: bool


class PreferenceUpdate(BaseModel):
    preferences: list[PreferenceItem] = Field(min_length=1)


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: str
    category: str
    enabled: bool


class PreferenceList(BaseModel):
    user_id: str
    preferences: list[PreferenceOut]
