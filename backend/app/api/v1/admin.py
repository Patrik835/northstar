from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import AdminUser, DbSession
from app.core.security import hash_password
from app.models.user import User
from app.repositories.users import UserRepository
from app.schemas.user import AdminUserCreate, UserRead

router = APIRouter()


@router.get("/users", response_model=list[UserRead])
async def list_users(admin: AdminUser, db: DbSession) -> list[UserRead]:
    users = list(await db.scalars(select(User).order_by(User.created_at)))
    return [UserRead.model_validate(user) for user in users]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminUserCreate, admin: AdminUser, db: DbSession
) -> UserRead:
    user = User(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.initial_password),
        is_admin=payload.is_admin,
        email_verified_at=datetime.now(timezone.utc) if payload.email else None,
    )
    try:
        await UserRepository(db).create(user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already exists") from exc
    return UserRead.model_validate(user)
