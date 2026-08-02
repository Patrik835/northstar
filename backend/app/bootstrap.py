import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.user import User


async def bootstrap_admin() -> None:
    settings = get_settings()
    if not settings.initial_admin_password:
        raise SystemExit("INITIAL_ADMIN_PASSWORD is required for the first bootstrap")
    async with SessionFactory() as db:
        existing = await db.scalar(
            select(User).where(User.username == settings.initial_admin_username)
        )
        if existing:
            print(f"Admin '{settings.initial_admin_username}' already exists")
            return
        db.add(
            User(
                username=settings.initial_admin_username,
                password_hash=hash_password(settings.initial_admin_password),
                is_admin=True,
            )
        )
        await db.commit()
        print(f"Created admin '{settings.initial_admin_username}'")


if __name__ == "__main__":
    asyncio.run(bootstrap_admin())
