from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.template import Template


class TemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Template | None:
        result = await self.session.execute(select(Template).where(Template.name == name))
        return result.scalar_one_or_none()

    async def list(self, limit: int = 100) -> list[Template]:
        result = await self.session.execute(select(Template).order_by(Template.name).limit(limit))
        return list(result.scalars())

    async def add(self, template: Template) -> Template:
        self.session.add(template)
        await self.session.flush()
        return template

    async def delete(self, template: Template) -> None:
        await self.session.delete(template)
        await self.session.flush()
