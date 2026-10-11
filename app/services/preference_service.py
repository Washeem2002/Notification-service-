from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Category
from app.models.preference import UserPreference
from app.repositories.preference_repo import PreferenceRepository
from app.schemas.preference import PreferenceUpdate


class PreferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PreferenceRepository(session)

    async def update(self, user_id: str, data: PreferenceUpdate) -> list[UserPreference]:
        for item in data.preferences:
            await self.repo.upsert(user_id, item.channel.value, item.category.value, item.enabled)
        await self.session.commit()
        return await self.repo.list_for_user(user_id)

    async def list(self, user_id: str) -> list[UserPreference]:
        return await self.repo.list_for_user(user_id)

    async def is_allowed(self, user_id: str, channel: str, category: str) -> bool:
        if category == Category.otp.value:
            return True
        preference = await self.repo.get(user_id, channel, category)
        return True if preference is None else preference.enabled
