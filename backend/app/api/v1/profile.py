from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.models.user import UserProfile
from app.repositories.users import UserRepository
from app.schemas.user import ProfileRead, ProfileUpdate

router = APIRouter()


@router.get("", response_model=ProfileRead)
async def get_profile(user: CurrentUser, db: DbSession) -> ProfileRead:
    profile = await UserRepository(db).profile(user.id)
    if not profile:
        return ProfileRead(goals=None, risk_tolerance=None, time_horizon_years=None)
    return ProfileRead.model_validate(profile, from_attributes=True)


@router.put("", response_model=ProfileRead)
async def update_profile(
    payload: ProfileUpdate, user: CurrentUser, db: DbSession
) -> ProfileRead:
    profile = await UserRepository(db).profile(user.id)
    if not profile:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return ProfileRead.model_validate(profile, from_attributes=True)

