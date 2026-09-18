from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.database import Base
from app.integrations.news.base import ProviderCalendarEvent, ProviderNewsItem
from app.models.broker import BrokerConnection
from app.models.content import CalendarEvent, NewsItem, calendar_event_users, news_item_users
from app.models.enums import AssetType, Broker, ConnectionStatus
from app.models.instrument import Instrument
from app.models.portfolio import Position
from app.models.user import User
from app.services.content import MarketContentService


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: Any) -> None:
        self.session.add(item)

    async def flush(self) -> None:
        self.session.flush()

    async def commit(self) -> None:
        self.session.commit()

    async def refresh(self, item: Any) -> None:
        self.session.refresh(item)

    async def execute(self, statement: Any):
        return self.session.execute(statement)

    async def scalar(self, statement: Any):
        return self.session.scalar(statement)

    async def scalars(self, statement: Any):
        return self.session.scalars(statement)


class FixedProvider:
    async def company_news(self, ticker: str, since: datetime):
        return [
            ProviderNewsItem(
                external_id="finnhub:news:one",
                ticker=ticker,
                headline="Held company update",
                summary=None,
                source="News",
                image_url=None,
                published_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
                url="https://example.com/one",
            )
        ]

    async def calendar_events(self, ticker: str, start: date, end: date):
        return [
            ProviderCalendarEvent(
                external_id="finnhub:event:one",
                ticker=ticker,
                event_type="earnings",
                event_date=date(2026, 8, 20),
                title=f"{ticker} earnings",
                details={},
            )
        ]


@pytest.mark.asyncio
async def test_market_content_deduplicates_and_links_every_owner() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            instrument = Instrument(
                identity_key="ISIN:US0378331005",
                canonical_symbol="AAPL",
                name="Apple",
                asset_type=AssetType.STOCK,
                isin="US0378331005",
            )
            db.add(instrument)
            await db.flush()
            owner_ids = []
            for number in range(2):
                user = User(username=f"news-owner-{number}", password_hash="unused")
                db.add(user)
                await db.flush()
                owner_ids.append(user.id)
                connection = BrokerConnection(
                    user_id=user.id,
                    broker=Broker.TRADING212 if number == 0 else Broker.ETORO,
                    encrypted_credentials=b"unused",
                    credential_hint="unused",
                    status=ConnectionStatus.ACTIVE,
                )
                db.add(connection)
                await db.flush()
                db.add(
                    Position(
                        broker_connection_id=connection.id,
                        instrument_id=f"provider-{number}",
                        canonical_instrument_id=instrument.id,
                        ticker="AAPL",
                        name="Apple",
                        asset_type=AssetType.STOCK,
                        quantity=Decimal(1),
                        current_value=Decimal(100),
                        currency="EUR",
                        current_value_eur=Decimal(100),
                    )
                )
            await db.commit()
            service = MarketContentService(db, FixedProvider())  # type: ignore[arg-type]

            first = await service.sync(owner_ids[0])
            assert await db.scalar(select(func.count()).select_from(news_item_users)) == 1
            second = await service.sync()

            assert first == (1, 1)
            assert second == (0, 0)
            assert await db.scalar(select(func.count()).select_from(NewsItem)) == 1
            assert await db.scalar(select(func.count()).select_from(CalendarEvent)) == 1
            assert await db.scalar(select(func.count()).select_from(news_item_users)) == 2
            assert await db.scalar(select(func.count()).select_from(calendar_event_users)) == 2
    finally:
        engine.dispose()
