"""PostgreSQL locks for invariants that span transactions or multiple rows."""

from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_users_table(db: AsyncSession) -> None:
    """Serialize user-set invariants (last admin, first account) until commit."""
    # SQLite test adapters serialize writes themselves; PostgreSQL needs an explicit lock.
    session = db if isinstance(db, AsyncSession) else db.session
    if session.get_bind().dialect.name == "postgresql":
        await db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))


lock_admin_deletion = lock_users_table


@asynccontextmanager
async def connection_sync_lock(db: AsyncSession, connection_id: UUID):
    if not isinstance(db, AsyncSession) or db.get_bind().dialect.name != "postgresql":
        yield True
        return
    # Dedicated connection: sync commits must not release ownership. Closing or a
    # worker crash releases the session lock; no durable RUNNING flag is used as a lock.
    key = int.from_bytes(sha256(connection_id.bytes).digest()[:8], "big", signed=True)
    async with db.bind.connect() as owner:
        acquired = await owner.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            try:
                await owner.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            except BaseException:
                await owner.invalidate()
                raise
