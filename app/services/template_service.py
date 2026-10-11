from typing import Any

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.models.template import Template
from app.repositories.template_repo import TemplateRepository
from app.schemas.template import TemplateCreate, TemplateUpdate

environment = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def render_text(source: str, variables: dict[str, Any]) -> str:
    try:
        return environment.from_string(source).render(**variables)
    except TemplateError as exc:
        raise AppError(f"template rendering failed: {exc}") from exc


class TemplateService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = TemplateRepository(session)

    async def create(self, data: TemplateCreate) -> Template:
        self.validate_syntax(data.body, data.subject)
        template = Template(
            name=data.name, channel=data.channel.value, subject=data.subject, body=data.body
        )
        try:
            await self.repo.add(template)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(f"template {data.name} already exists") from exc
        return template

    async def get(self, name: str) -> Template:
        template = await self.repo.get_by_name(name)
        if not template:
            raise NotFoundError(f"template {name} not found")
        return template

    async def list(self) -> list[Template]:
        return await self.repo.list()

    async def update(self, name: str, data: TemplateUpdate) -> Template:
        self.validate_syntax(data.body, data.subject)
        template = await self.get(name)
        template.subject = data.subject
        template.body = data.body
        await self.session.commit()
        return template

    async def delete(self, name: str) -> None:
        template = await self.get(name)
        await self.repo.delete(template)
        await self.session.commit()

    def validate_syntax(self, body: str, subject: str | None) -> None:
        try:
            environment.parse(body)
            if subject:
                environment.parse(subject)
        except TemplateError as exc:
            raise AppError(f"invalid template syntax: {exc}") from exc

    async def render(
        self, name: str, channel: str, variables: dict[str, Any]
    ) -> tuple[str | None, str]:
        template = await self.get(name)
        if template.channel != channel:
            raise AppError(f"template {name} is for channel {template.channel}")
        subject = render_text(template.subject, variables) if template.subject else None
        return subject, render_text(template.body, variables)
