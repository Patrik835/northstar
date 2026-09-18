import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.email.base import EmailDeliveryError, EmailSender
from app.integrations.news.base import NewsProvider, NewsProviderError
from app.models.broker import BrokerConnection
from app.models.content import (
    Alert,
    CalendarEvent,
    NewsItem,
    NewsReadState,
    NotificationPreference,
    PortfolioNewsBrief,
    calendar_event_users,
    news_item_users,
)
from app.models.enums import AssetType, ConnectionStatus
from app.models.instrument import Instrument
from app.models.portfolio import Position
from app.models.user import User
from app.repositories.portfolio import PortfolioRepository
from app.schemas.content import (
    AlertRead,
    CalendarEventRead,
    ContentSummary,
    NewsRead,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    PortfolioNewsBriefRead,
)
from app.services.freshness import connection_freshness
from app.services.portfolio import PortfolioService

logger = logging.getLogger(__name__)


class MarketContentService:
    def __init__(self, db: AsyncSession, provider: NewsProvider) -> None:
        self.db = db
        self.provider = provider

    async def sync(self, user_id: uuid.UUID | None = None) -> tuple[int, int]:
        ownership = await self._ticker_owners(user_id)
        news_added = 0
        events_added = 0
        since = datetime.now(timezone.utc) - timedelta(days=3)
        start = date.today()
        end = start + timedelta(days=35)
        for ticker, user_ids in sorted(ownership.items())[:50]:
            try:
                news = await self.provider.company_news(ticker, since)
            except NewsProviderError as exc:
                logger.warning("Company news unavailable for %s: %s", ticker, exc)
                news = []
            try:
                events = await self.provider.calendar_events(ticker, start, end)
            except NewsProviderError as exc:
                logger.warning("Calendar unavailable for %s: %s", ticker, exc)
                events = []
            for item in news:
                stored = await self.db.scalar(
                    select(NewsItem).where(NewsItem.external_id == item.external_id)
                )
                if stored is None:
                    stored = NewsItem(
                        external_id=item.external_id,
                        ticker=item.ticker,
                        headline=item.headline,
                        summary=item.summary,
                        source=item.source,
                        image_url=item.image_url,
                        published_at=item.published_at,
                        url=item.url,
                    )
                    self.db.add(stored)
                    await self.db.flush()
                    news_added += 1
                await self._link(news_item_users, "news_item_id", stored.id, user_ids)
            for item in events:
                stored_event = await self.db.scalar(
                    select(CalendarEvent).where(CalendarEvent.external_id == item.external_id)
                )
                if stored_event is None:
                    stored_event = CalendarEvent(
                        external_id=item.external_id,
                        ticker=item.ticker,
                        event_type=item.event_type,
                        event_date=item.event_date,
                        title=item.title,
                        details=item.details,
                        source_url=item.source_url,
                    )
                    self.db.add(stored_event)
                    await self.db.flush()
                    events_added += 1
                await self._link(
                    calendar_event_users,
                    "calendar_event_id",
                    stored_event.id,
                    user_ids,
                )
        await self.db.commit()
        return news_added, events_added

    async def _ticker_owners(self, user_id: uuid.UUID | None = None) -> dict[str, set[uuid.UUID]]:
        statement = (
            select(
                BrokerConnection.user_id,
                Position.ticker,
                Position.asset_type,
                Instrument.canonical_symbol,
                Instrument.asset_type,
            )
            .join(Position, Position.broker_connection_id == BrokerConnection.id)
            .outerjoin(Instrument, Instrument.id == Position.canonical_instrument_id)
            .where(BrokerConnection.status != ConnectionStatus.DISABLED)
        )
        if user_id is not None:
            statement = statement.where(BrokerConnection.user_id == user_id)
        rows = await self.db.execute(statement)
        result: dict[str, set[uuid.UUID]] = defaultdict(set)
        for user_id, position_ticker, position_type, canonical_symbol, canonical_type in rows:
            asset_type = canonical_type or position_type
            ticker = str(canonical_symbol or position_ticker).strip().upper()
            if asset_type not in {AssetType.STOCK, AssetType.ETF}:
                continue
            if not ticker or ticker.startswith("ISIN:") or len(ticker) > 20:
                continue
            result[ticker].add(user_id)
        return result

    async def _link(
        self,
        table,
        id_column: str,
        item_id: uuid.UUID,
        user_ids: set[uuid.UUID],
    ) -> None:
        existing = set(
            await self.db.scalars(
                select(table.c.user_id).where(getattr(table.c, id_column) == item_id)
            )
        )
        for user_id in user_ids - existing:
            await self.db.execute(insert(table).values(**{id_column: item_id, "user_id": user_id}))


class AlertService:
    GENERATED_TYPES = {"stale_connection", "sync_failure", "allocation_drift", "event"}

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def refresh(self, user_id: uuid.UUID) -> None:
        active: dict[str, dict] = {}
        connections = list(
            await self.db.scalars(
                select(BrokerConnection).where(BrokerConnection.user_id == user_id)
            )
        )
        now = datetime.now(timezone.utc)
        for connection in connections:
            freshness = connection_freshness(
                connection.broker, connection.last_successful_sync_at, now=now
            )
            if freshness.status == "stale":
                key = f"stale:{connection.id}:{connection.last_successful_sync_at}"
                active[key] = {
                    "alert_type": "stale_connection",
                    "severity": "warning",
                    "title": f"{connection.broker.value.replace('_', ' ').title()} is stale",
                    "message": "This source has not refreshed on schedule.",
                    "source_url": "/connections",
                    "event_at": freshness.stale_after,
                }
            if connection.status == ConnectionStatus.ERROR:
                key = f"sync:{connection.id}:{connection.last_sync_attempt_at}"
                active[key] = {
                    "alert_type": "sync_failure",
                    "severity": "error",
                    "title": f"{connection.broker.value.replace('_', ' ').title()} needs attention",
                    "message": connection.last_error or "The latest synchronization failed.",
                    "source_url": "/connections",
                    "event_at": connection.last_sync_attempt_at,
                }

        holdings = await PortfolioService(PortfolioRepository(self.db)).holdings(user_id)
        for holding in holdings.holdings:
            target = holding.target_allocation_percentage
            if target is None:
                continue
            drift = holding.portfolio_percentage - target
            if abs(drift) < Decimal(self.settings.allocation_drift_alert_points):
                continue
            key = f"drift:{holding.key}"[:180]
            direction = "above" if drift > 0 else "below"
            active[key] = {
                "alert_type": "allocation_drift",
                "severity": "info",
                "title": f"{holding.symbol} is {direction} target",
                "message": (
                    f"Current {holding.portfolio_percentage}% · target {target}% "
                    f"({abs(drift).quantize(Decimal('0.1'))} points {direction})."
                ),
                "source_url": "/analytics",
                "event_at": None,
            }

        upcoming = await self.db.execute(
            select(CalendarEvent)
            .join(
                calendar_event_users,
                calendar_event_users.c.calendar_event_id == CalendarEvent.id,
            )
            .where(
                calendar_event_users.c.user_id == user_id,
                CalendarEvent.event_date >= date.today(),
                CalendarEvent.event_date <= date.today() + timedelta(days=7),
            )
        )
        for event in upcoming.scalars():
            key = f"event:{event.id}"
            active[key] = {
                "alert_type": "event",
                "severity": "info",
                "title": event.title,
                "message": f"Scheduled for {event.event_date.strftime('%d %b')}.",
                "source_url": "/updates",
                "event_at": datetime.combine(event.event_date, time.min, tzinfo=timezone.utc),
            }

        existing = list(
            await self.db.scalars(
                select(Alert).where(
                    Alert.user_id == user_id,
                    Alert.alert_type.in_(self.GENERATED_TYPES),
                )
            )
        )
        by_key = {item.dedupe_key: item for item in existing}
        for key, values in active.items():
            if key not in by_key:
                self.db.add(Alert(user_id=user_id, dedupe_key=key, **values))
        resolved = [item.id for item in existing if item.dedupe_key not in active]
        if resolved:
            await self.db.execute(delete(Alert).where(Alert.id.in_(resolved)))
        await self.db.commit()


class ContentQueryService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def summary(
        self, user_id: uuid.UUID, *, news_limit: int = 8, event_limit: int = 8, alert_limit: int = 8
    ) -> ContentSummary:
        await AlertService(self.db, self.settings).refresh(user_id)
        brief = await self.db.scalar(
            select(PortfolioNewsBrief)
            .where(
                PortfolioNewsBrief.user_id == user_id,
                PortfolioNewsBrief.brief_date == datetime.now(timezone.utc).date(),
            )
            .order_by(PortfolioNewsBrief.generated_at.desc())
            .limit(1)
        )
        selected_ids: list[uuid.UUID] = []
        if brief is not None:
            for value in brief.selected_news_ids:
                try:
                    selected_ids.append(uuid.UUID(str(value)))
                except (TypeError, ValueError):
                    continue
        news_statement = (
            select(NewsItem, NewsReadState.read_at)
            .join(news_item_users, news_item_users.c.news_item_id == NewsItem.id)
            .outerjoin(
                NewsReadState,
                (NewsReadState.news_item_id == NewsItem.id) & (NewsReadState.user_id == user_id),
            )
            .where(news_item_users.c.user_id == user_id)
        )
        if selected_ids:
            news_rows = list(
                await self.db.execute(news_statement.where(NewsItem.id.in_(selected_ids)))
            )
            order = {news_id: index for index, news_id in enumerate(selected_ids)}
            news_rows.sort(key=lambda row: order.get(row[0].id, len(order)))
        else:
            news_rows = list(
                await self.db.execute(
                    news_statement.where(
                        NewsItem.published_at >= datetime.now(timezone.utc) - timedelta(hours=24)
                    )
                    .order_by(NewsItem.published_at.desc())
                    .limit(news_limit)
                )
            )
        unread_news = sum(1 for _, read_at in news_rows if read_at is None)
        news = [
            NewsRead(
                id=item.id,
                ticker=item.ticker,
                headline=item.headline,
                summary=item.summary,
                source=item.source,
                image_url=item.image_url,
                published_at=item.published_at,
                url=item.url,
                is_read=read_at is not None,
            )
            for item, read_at in news_rows[:news_limit]
        ]
        events = list(
            await self.db.scalars(
                select(CalendarEvent)
                .join(
                    calendar_event_users,
                    calendar_event_users.c.calendar_event_id == CalendarEvent.id,
                )
                .where(
                    calendar_event_users.c.user_id == user_id,
                    CalendarEvent.event_date >= date.today(),
                )
                .order_by(CalendarEvent.event_date)
                .limit(event_limit)
            )
        )
        alerts = list(
            await self.db.scalars(
                select(Alert)
                .where(Alert.user_id == user_id)
                .order_by(Alert.read_at.is_not(None), Alert.created_at.desc())
                .limit(alert_limit)
            )
        )
        unread_alerts = await self.db.scalar(
            select(func.count())
            .select_from(Alert)
            .where(Alert.user_id == user_id, Alert.read_at.is_(None))
        )
        return ContentSummary(
            news=news,
            events=[
                CalendarEventRead(
                    id=item.id,
                    ticker=item.ticker,
                    event_type=item.event_type,
                    event_date=item.event_date,
                    title=item.title,
                    details=item.details,
                    source_url=item.source_url,
                )
                for item in events
            ],
            alerts=[AlertRead.model_validate(item, from_attributes=True) for item in alerts],
            unread_news=unread_news,
            unread_alerts=int(unread_alerts or 0),
            brief=(
                PortfolioNewsBriefRead.model_validate(brief, from_attributes=True)
                if brief is not None
                else None
            ),
        )

    async def mark_news_read(self, user_id: uuid.UUID, news_id: uuid.UUID) -> bool:
        linked = await self.db.scalar(
            select(news_item_users.c.news_item_id).where(
                news_item_users.c.news_item_id == news_id,
                news_item_users.c.user_id == user_id,
            )
        )
        if linked is None:
            return False
        existing = await self.db.get(NewsReadState, (news_id, user_id))
        if existing is None:
            self.db.add(NewsReadState(news_item_id=news_id, user_id=user_id))
            await self.db.commit()
        return True

    async def mark_alert_read(self, user_id: uuid.UUID, alert_id: uuid.UUID) -> bool:
        alert = await self.db.scalar(
            select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
        )
        if alert is None:
            return False
        alert.read_at = datetime.now(timezone.utc)
        await self.db.commit()
        return True

    async def preferences(self, user: User) -> NotificationPreferenceRead:
        item = await self.db.get(NotificationPreference, user.id)
        return NotificationPreferenceRead(
            email_digest_enabled=item.email_digest_enabled if item else False,
            digest_frequency=item.digest_frequency if item else "weekly",
            email_available=bool(user.email and user.email_verified_at),
            email=user.email,
            email_verified=user.email_verified_at is not None,
            last_digest_at=item.last_digest_at if item else None,
        )

    async def update_preferences(
        self, user: User, payload: NotificationPreferenceUpdate
    ) -> NotificationPreferenceRead:
        if payload.email_digest_enabled and not (user.email and user.email_verified_at):
            raise ValueError("A verified email address is required for digests")
        item = await self.db.get(NotificationPreference, user.id)
        if item is None:
            item = NotificationPreference(user_id=user.id)
            self.db.add(item)
        item.email_digest_enabled = payload.email_digest_enabled
        item.digest_frequency = payload.digest_frequency
        await self.db.commit()
        return await self.preferences(user)


class NotificationDigestService:
    def __init__(self, db: AsyncSession, settings: Settings, sender: EmailSender) -> None:
        self.db = db
        self.settings = settings
        self.sender = sender

    async def deliver_due(self) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        rows = await self.db.execute(
            select(NotificationPreference, User)
            .join(User, User.id == NotificationPreference.user_id)
            .where(
                NotificationPreference.email_digest_enabled.is_(True),
                User.email.is_not(None),
                User.email_verified_at.is_not(None),
                User.is_active.is_(True),
            )
        )
        sent = 0
        failed = 0
        for preference, user in rows:
            minimum_age = timedelta(days=1 if preference.digest_frequency == "daily" else 7)
            last_digest_at = preference.last_digest_at
            if last_digest_at and not last_digest_at.tzinfo:
                last_digest_at = last_digest_at.replace(tzinfo=timezone.utc)
            if last_digest_at and now - last_digest_at < minimum_age:
                continue
            content = await ContentQueryService(self.db, self.settings).summary(
                user.id, news_limit=5, event_limit=5, alert_limit=5
            )
            alerts = [item.title for item in content.alerts if item.read_at is None]
            news = [f"{item.ticker}: {item.headline}" for item in content.news if not item.is_read]
            events = [
                f"{item.event_date.strftime('%d %b')} · {item.title}" for item in content.events
            ]
            if not alerts and not news and not events:
                preference.last_digest_at = now
                continue
            try:
                await self.sender.send_notification_digest(
                    recipient=user.email,
                    username=user.username,
                    alerts=alerts,
                    news=news,
                    events=events,
                    updates_url=f"{self.settings.public_web_url.rstrip('/')}/updates",
                )
            except (EmailDeliveryError, NotImplementedError):
                failed += 1
                continue
            preference.last_digest_at = now
            sent += 1
        await self.db.commit()
        return sent, failed

    async def send_now(self, user_id: uuid.UUID) -> None:
        row = (
            await self.db.execute(
                select(NotificationPreference, User)
                .join(User, User.id == NotificationPreference.user_id)
                .where(
                    NotificationPreference.user_id == user_id,
                    NotificationPreference.email_digest_enabled.is_(True),
                    User.email.is_not(None),
                    User.email_verified_at.is_not(None),
                    User.is_active.is_(True),
                )
            )
        ).first()
        if row is None:
            raise ValueError("Enable the digest after verifying your email address")
        preference, user = row
        content = await ContentQueryService(self.db, self.settings).summary(
            user.id, news_limit=5, event_limit=5, alert_limit=5
        )
        await self.sender.send_notification_digest(
            recipient=user.email,
            username=user.username,
            alerts=[item.title for item in content.alerts if item.read_at is None],
            news=[f"{item.ticker}: {item.headline}" for item in content.news if not item.is_read],
            events=[
                f"{item.event_date.strftime('%d %b')} · {item.title}" for item in content.events
            ],
            updates_url=f"{self.settings.public_web_url.rstrip('/')}/updates",
        )
        preference.last_digest_at = datetime.now(timezone.utc)
        await self.db.commit()
