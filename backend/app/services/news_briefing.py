import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.ai.openai_provider import NewsBriefSelection
from app.models.content import NewsItem, PortfolioNewsBrief, news_item_users
from app.repositories.portfolio import PortfolioRepository
from app.services.portfolio import PortfolioService

logger = logging.getLogger(__name__)

NEWS_BRIEF_VERSION = "portfolio-news-v1"


class NewsBriefingProvider(Protocol):
    @property
    def model(self) -> str: ...

    async def create_brief(
        self,
        portfolio_positions: list[dict],
        news_candidates: list[dict],
        *,
        safety_identifier: str,
    ) -> NewsBriefSelection: ...


class PortfolioNewsBriefingService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        provider: NewsBriefingProvider,
    ) -> None:
        self.db = db
        self.settings = settings
        self.provider = provider

    async def generate(self, user_id: uuid.UUID) -> PortfolioNewsBrief | None:
        now = datetime.now(timezone.utc)
        positions = await self._positions(user_id)
        candidates = await self._candidates(user_id, now)
        if not positions or not candidates:
            return None

        context_hash = _hash_payload({"version": NEWS_BRIEF_VERSION, "positions": positions})
        news_hash = _hash_payload(
            {
                "version": NEWS_BRIEF_VERSION,
                "news": [
                    (item["id"], item["ticker"], item["headline"], item["published_at"])
                    for item in candidates
                ],
            }
        )
        brief_date = now.date()
        cached = await self.db.scalar(
            select(PortfolioNewsBrief).where(
                PortfolioNewsBrief.user_id == user_id,
                PortfolioNewsBrief.brief_date == brief_date,
                PortfolioNewsBrief.context_hash == context_hash,
                PortfolioNewsBrief.news_hash == news_hash,
            )
        )
        if cached is not None:
            return cached

        result = await self.provider.create_brief(
            positions,
            candidates,
            safety_identifier=_safety_identifier(user_id, self.settings.app_secret_key),
        )
        selected_ids = self._validated_selection(result, candidates, positions)
        highlights = self._validated_highlights(result, candidates, selected_ids)
        brief = PortfolioNewsBrief(
            user_id=user_id,
            brief_date=brief_date,
            context_hash=context_hash,
            news_hash=news_hash,
            positions_count=len(positions),
            selected_news_ids=selected_ids,
            highlights=highlights,
            model_used=self.provider.model,
        )
        self.db.add(brief)
        await self.db.commit()
        await self.db.refresh(brief)
        return brief

    async def generate_all(self) -> tuple[int, int]:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        user_ids = list(
            await self.db.scalars(
                select(news_item_users.c.user_id)
                .join(NewsItem, NewsItem.id == news_item_users.c.news_item_id)
                .where(NewsItem.published_at >= since)
                .distinct()
            )
        )
        generated = 0
        failed = 0
        for user_id in user_ids:
            try:
                if await self.generate(user_id) is not None:
                    generated += 1
            except Exception:
                await self.db.rollback()
                failed += 1
                logger.warning("Portfolio news brief generation failed for one user")
        return generated, failed

    async def _positions(self, user_id: uuid.UUID) -> list[dict]:
        holdings = await PortfolioService(PortfolioRepository(self.db)).holdings(user_id)
        return [
            {
                "symbol": _clean_text(item.symbol, 32),
                "name": _clean_text(item.name, 120),
                "asset_type": item.asset_type.value,
                "portfolio_weight_percent": float(item.portfolio_percentage),
            }
            for item in holdings.holdings
        ]

    async def _candidates(self, user_id: uuid.UUID, now: datetime) -> list[dict]:
        limit = max(10, min(self.settings.news_brief_candidate_limit, 500))
        items = list(
            await self.db.scalars(
                select(NewsItem)
                .join(news_item_users, news_item_users.c.news_item_id == NewsItem.id)
                .where(
                    news_item_users.c.user_id == user_id,
                    NewsItem.published_at >= now - timedelta(hours=24),
                    NewsItem.published_at <= now,
                )
                .order_by(NewsItem.published_at.desc())
                .limit(limit * 3)
            )
        )
        result: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            dedupe_key = (item.ticker.casefold(), _normalized_headline(item.headline))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.append(
                {
                    "id": str(item.id),
                    "ticker": _clean_text(item.ticker.upper(), 32),
                    "headline": _clean_text(item.headline, 240),
                    "summary": _clean_text(item.summary or "", 400),
                    "source": _clean_text(item.source, 80),
                    "published_at": _aware(item.published_at).isoformat(),
                }
            )
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _validated_selection(
        result: NewsBriefSelection,
        candidates: list[dict],
        positions: list[dict],
    ) -> list[str]:
        allowed = {item["id"] for item in candidates}
        selected: list[str] = []
        for raw_id in result.selected_news_ids:
            news_id = str(raw_id)
            if news_id in allowed and news_id not in selected:
                selected.append(news_id)
            if len(selected) == 10:
                return selected

        weights = {item["symbol"].upper(): item["portfolio_weight_percent"] for item in positions}
        fallback = sorted(
            candidates,
            key=lambda item: (weights.get(item["ticker"].upper(), 0), item["published_at"]),
            reverse=True,
        )
        for item in fallback:
            if item["id"] not in selected:
                selected.append(item["id"])
            if len(selected) == min(10, len(candidates)):
                break
        return selected

    @staticmethod
    def _validated_highlights(
        result: NewsBriefSelection,
        candidates: list[dict],
        selected_ids: list[str],
    ) -> list[dict]:
        selected = set(selected_ids)
        ticker_by_id = {item["id"]: item["ticker"] for item in candidates}
        highlights: list[dict] = []
        for item in result.highlights[:3]:
            source_ids = list(
                dict.fromkeys(str(news_id) for news_id in item.news_ids if str(news_id) in selected)
            )[:4]
            title = _clean_text(item.title, 160)
            summary = _clean_text(item.summary, 500)
            if not source_ids or not title or not summary:
                continue
            supported_tickers = {ticker_by_id[news_id] for news_id in source_ids}
            tickers = [
                ticker
                for ticker in dict.fromkeys(
                    _clean_text(value.upper(), 32) for value in item.tickers
                )
                if ticker in supported_tickers
            ][:5]
            if not tickers:
                tickers = sorted(supported_tickers)[:5]
            highlights.append(
                {
                    "title": title,
                    "summary": summary,
                    "tickers": tickers,
                    "news_ids": source_ids,
                }
            )
        return highlights


def _clean_text(value: str, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _normalized_headline(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _safety_identifier(user_id: uuid.UUID, secret: str) -> str:
    return hashlib.sha256(f"{secret}:{user_id}".encode()).hexdigest()
