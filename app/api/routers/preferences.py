from fastapi import APIRouter, Depends

from app.api.deps import get_preference_service, require_api_key
from app.schemas.preference import PreferenceList, PreferenceOut, PreferenceUpdate
from app.services.preference_service import PreferenceService

router = APIRouter(
    prefix="/api/v1/users", tags=["preferences"], dependencies=[Depends(require_api_key)]
)


@router.get("/{user_id}/preferences", response_model=PreferenceList)
async def get_preferences(
    user_id: str, service: PreferenceService = Depends(get_preference_service)
) -> PreferenceList:
    items = await service.list(user_id)
    return PreferenceList(
        user_id=user_id, preferences=[PreferenceOut.model_validate(item) for item in items]
    )


@router.put("/{user_id}/preferences", response_model=PreferenceList)
async def update_preferences(
    user_id: str,
    body: PreferenceUpdate,
    service: PreferenceService = Depends(get_preference_service),
) -> PreferenceList:
    items = await service.update(user_id, body)
    return PreferenceList(
        user_id=user_id, preferences=[PreferenceOut.model_validate(item) for item in items]
    )
