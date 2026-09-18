from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base
from app.integrations.ai.openai_provider import NewsBriefHighlight, NewsBriefSelection
from app.models.broker import BrokerConnection
from app.models.content import NewsItem, PortfolioNewsBrief, news_item_users
from app.models.enums import AssetType, Broker, ConnectionStatus
from app.models.portfolio import Position
from app.models.user import User
from app.services.news_briefing import PortfolioNewsBriefingService


class AsyncSessionAdapter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, item: Any) -> None:
        self.session.add(item)

    async def commit(self) -> None:
        self.session.commit()

    async def rollback(self) -> None:
        self.session.rollback()

    async def refresh(self, item: Any) -> None:
        self.session.refresh(item)

    async def execute(self, statement: Any):
        return self.session.execute(statement)

    async def scalar(self, statement: Any):
        return self.session.scalar(statement)

    async def scalars(self, statement: Any):
        return self.session.scalars(statement)


class RecordingProvider:
    model = "test-news-model"

    def __init__(self) -> None:
        self.calls: list[tuple[list[dict], list[dict], str]] = []

    async def create_brief(
        self,
        positions: list[dict],
        candidates: list[dict],
        *,
        safety_identifier: str,
    ) -> NewsBriefSelection:
        self.calls.append((positions, candidates, safety_identifier))
        return NewsBriefSelection(
            selected_news_ids=["invented-id", candidates[0]["id"]],
            highlights=[
                NewsBriefHighlight(
                    title="Material held-company update",
                    summary="A concise evidence-based summary.",
                    tickers=[candidates[0]["ticker"]],
                    news_ids=[candidates[0]["id"], "invented-id"],
                )
            ],
        )


@pytest.mark.asyncio
async def test_brief_uses_minimal_all_holdings_context_validates_and_caches() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory() as sync_db:
            db = AsyncSessionAdapter(sync_db)
            user = User(username="brief-owner", password_hash="unused")
            stranger = User(username="brief-stranger", password_hash="unused")
            db.add(user)
            db.add(stranger)
            await db.commit()
            connection = BrokerConnection(
                user_id=user.id,
                broker=Broker.TRADING212,
                encrypted_credentials=b"secret-that-must-not-leave",
                credential_hint="hint",
                status=ConnectionStatus.ACTIVE,
            )
            db.add(connection)
            await db.commit()
            for number, asset_type in enumerate((AssetType.STOCK, AssetType.CRYPTO)):
                db.add(
                    Position(
                        broker_connection_id=connection.id,
                        instrument_id=f"instrument-{number}",
                        ticker="AAPL" if number == 0 else "BTC",
                        name="Apple" if number == 0 else "Bitcoin",
                        asset_type=asset_type,
                        quantity=Decimal("3.25"),
                        current_value=Decimal(100 - number * 20),
                        currency="EUR",
                        current_value_eur=Decimal(100 - number * 20),
                    )
                )
            now = datetime.now(timezone.utc)
            for number in range(12):
                item = NewsItem(
                    external_id=f"news-{number}",
                    ticker="AAPL",
                    headline=f"Apple update {number}",
                    summary="News summary",
                    source="Source",
                    published_at=now - timedelta(minutes=number),
                    url=f"https://example.com/{number}",
                )
                db.add(item)
                await db.commit()
                await db.execute(
                    insert(news_item_users).values(news_item_id=item.id, user_id=user.id)
                )
            stranger_news = NewsItem(
                external_id="stranger-news",
                ticker="MSFT",
                headline="Must remain tenant scoped",
                source="Source",
                published_at=now,
                url="https://example.com/stranger",
            )
            db.add(stranger_news)
            await db.commit()
            await db.execute(
                insert(news_item_users).values(news_item_id=stranger_news.id, user_id=stranger.id)
            )
            await db.commit()

            provider = RecordingProvider()
            service = PortfolioNewsBriefingService(
                db,  # type: ignore[arg-type]
                get_settings(),
                provider,
            )
            first = await service.generate(user.id)
            second = await service.generate(user.id)

            assert first is not None and second is not None
            assert first.id == second.id
            assert len(provider.calls) == 1
            positions, candidates, safety_identifier = provider.calls[0]
            assert {item["symbol"] for item in positions} == {"AAPL", "BTC"}
            assert all(
                set(item) == {"symbol", "name", "asset_type", "portfolio_weight_percent"}
                for item in positions
            )
            assert all(item["ticker"] == "AAPL" for item in candidates)
            assert "secret-that-must-not-leave" not in str((positions, candidates))
            assert len(safety_identifier) == 64
            assert len(first.selected_news_ids) == 10
            assert "invented-id" not in first.selected_news_ids
            assert first.highlights[0]["news_ids"] == [candidates[0]["id"]]
            assert await db.scalar(select(func.count()).select_from(PortfolioNewsBrief)) == 1
    finally:
        engine.dispose()
