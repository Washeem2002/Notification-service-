from fastapi import APIRouter, Depends, Response, status

from app.api.deps import get_template_service, require_api_key
from app.schemas.template import TemplateCreate, TemplateOut, TemplateUpdate
from app.services.template_service import TemplateService

router = APIRouter(
    prefix="/api/v1/templates", tags=["templates"], dependencies=[Depends(require_api_key)]
)


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreate, service: TemplateService = Depends(get_template_service)
) -> TemplateOut:
    return TemplateOut.model_validate(await service.create(body))


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    service: TemplateService = Depends(get_template_service),
) -> list[TemplateOut]:
    return [TemplateOut.model_validate(item) for item in await service.list()]


@router.get("/{name}", response_model=TemplateOut)
async def get_template(
    name: str, service: TemplateService = Depends(get_template_service)
) -> TemplateOut:
    return TemplateOut.model_validate(await service.get(name))


@router.put("/{name}", response_model=TemplateOut)
async def update_template(
    name: str, body: TemplateUpdate, service: TemplateService = Depends(get_template_service)
) -> TemplateOut:
    return TemplateOut.model_validate(await service.update(name, body))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    name: str, service: TemplateService = Depends(get_template_service)
) -> Response:
    await service.delete(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
