from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.preference import UserPreference


class PreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(self, user_id: str) -> list[UserPreference]:
        result = await self.session.execute(
            select(UserPreference)
            .where(UserPreference.user_id == user_id)
            .order_by(UserPreference.channel, UserPreference.category)
        )
        return list(result.scalars())

    async def get(self, user_id: str, channel: str, category: str) -> UserPreference | None:
        return await self.session.get(UserPreference, (user_id, channel, category))

    async def upsert(
        self, user_id: str, channel: str, category: str, enabled: bool
    ) -> UserPreference:
        existing = await self.get(user_id, channel, category)
        if existing:
            existing.enabled = enabled
            await self.session.flush()
            return existing
        created = UserPreference(
            user_id=user_id, channel=channel, category=category, enabled=enabled
        )
        self.session.add(created)
        await self.session.flush()
        return created
