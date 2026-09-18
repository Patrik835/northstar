import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.user import AuthRateLimitEvent


class AuthRateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__("Too many requests")


class AuthRateLimiter:
    """Database-backed throttling without retaining raw IPs or account identifiers."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def check(
        self,
        action: str,
        request: Request,
        *,
        subject: str | None = None,
        ip_limit: int,
        subject_limit: int | None = None,
        window_minutes: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        minutes = window_minutes or self.settings.auth_rate_limit_window_minutes
        cutoff = now - timedelta(minutes=minutes)
        ip_digest = self._digest(self._client_ip(request))
        subject_digest = self._digest(subject.strip().casefold()) if subject else None

        filters = [
            AuthRateLimitEvent.action == action,
            AuthRateLimitEvent.created_at >= cutoff,
        ]
        ip_count = await self.db.scalar(
            select(func.count()).select_from(AuthRateLimitEvent).where(
                *filters, AuthRateLimitEvent.ip_digest == ip_digest
            )
        )
        subject_count = 0
        if subject_digest and subject_limit is not None:
            subject_count = await self.db.scalar(
                select(func.count()).select_from(AuthRateLimitEvent).where(
                    *filters, AuthRateLimitEvent.subject_digest == subject_digest
                )
            )
        ip_exceeded = int(ip_count or 0) >= ip_limit
        subject_exceeded = (
            subject_digest is not None
            and subject_limit is not None
            and int(subject_count or 0) >= subject_limit
        )
        if ip_exceeded or subject_exceeded:
            oldest_values = []
            if ip_exceeded:
                oldest_values.append(
                    await self.db.scalar(
                        select(func.min(AuthRateLimitEvent.created_at)).where(
                            *filters, AuthRateLimitEvent.ip_digest == ip_digest
                        )
                    )
                )
            if subject_exceeded:
                oldest_values.append(
                    await self.db.scalar(
                        select(func.min(AuthRateLimitEvent.created_at)).where(
                            *filters,
                            AuthRateLimitEvent.subject_digest == subject_digest,
                        )
                    )
                )
            retry_times = [
                (value if value.tzinfo else value.replace(tzinfo=timezone.utc))
                + timedelta(minutes=minutes)
                for value in oldest_values
                if value is not None
            ]
            retry_at = max(retry_times, default=now + timedelta(minutes=minutes))
            raise AuthRateLimitExceeded(int((retry_at - now).total_seconds()) + 1)

        self.db.add(
            AuthRateLimitEvent(
                action=action,
                ip_digest=ip_digest,
                subject_digest=subject_digest,
            )
        )
        await self.db.execute(
            delete(AuthRateLimitEvent).where(
                AuthRateLimitEvent.created_at < now - timedelta(hours=24)
            )
        )
        await self.db.commit()

    def _digest(self, value: str) -> str:
        return hmac.new(
            self.settings.app_secret_key.encode(), value.encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"
