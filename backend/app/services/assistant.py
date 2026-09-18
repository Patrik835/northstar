import hashlib
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.ai.openai_provider import OpenAIInvestmentAssistant
from app.models.content import (
    AIRecommendation,
    ChatMessage,
    Conversation,
    PortfolioContextSnapshot,
)
from app.models.enums import ChatRole
from app.models.user import UserProfile
from app.repositories.analytics import AnalyticsRepository
from app.repositories.portfolio import PortfolioRepository
from app.schemas.assistant import (
    CalculationReference,
    ChatMessageRead,
    ConversationRead,
    PortfolioContextRead,
    PortfolioReviewRead,
)
from app.services.analytics import AnalyticsService
from app.services.portfolio import PortfolioService

CONTEXT_VERSION = "portfolio-context-v3"
INJECTION_PATTERNS = (
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|system|developer)\s+instructions?\b", re.I),
    re.compile(r"\b(reveal|show|print|repeat)\s+(the\s+)?(system|developer)\s+prompt\b", re.I),
    re.compile(r"\bact\s+as\s+if\s+(the\s+)?portfolio[_ ]data\s+were\s+instructions\b", re.I),
    re.compile(r"<\/?(system|developer|portfolio_data)>", re.I),
)


class AssistantInputError(ValueError):
    pass


class AssistantLimitError(RuntimeError):
    pass


class PortfolioContextService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build(self, user_id: uuid.UUID) -> PortfolioContextSnapshot:
        portfolio_repository = PortfolioRepository(self.db)
        holdings = await PortfolioService(portfolio_repository).holdings(user_id)
        analytics = await AnalyticsService(portfolio_repository, AnalyticsRepository(self.db)).get(
            user_id, "1y"
        )
        profile = await self.db.get(UserProfile, user_id)
        payload: dict[str, Any] = {
            "schema_version": CONTEXT_VERSION,
            "currency": "EUR",
            "portfolio": {
                "total_value_eur": str(holdings.total_value_eur),
                "open_pnl_eur": (
                    str(holdings.reported_pnl_eur)
                    if holdings.reported_pnl_eur is not None
                    else None
                ),
                "instrument_count": holdings.instrument_count,
                "as_of": holdings.as_of.isoformat() if holdings.as_of else None,
                "stale": any(item.is_stale for item in holdings.holdings),
                "estimated_values": any(item.has_estimated_value for item in holdings.holdings),
            },
            "holdings": [
                {
                    "symbol": _safe_text(item.symbol, 32),
                    "name": _safe_text(item.name, 120),
                    "asset_type": item.asset_type.value,
                    "value_eur": str(item.total_value_eur),
                    "portfolio_percentage": str(item.portfolio_percentage),
                    "open_pnl_eur": (
                        str(item.performance.open_pnl_eur)
                        if item.performance.open_pnl_eur is not None
                        else None
                    ),
                    "open_pnl_percentage": (
                        str(item.performance.open_pnl_percentage)
                        if item.performance.open_pnl_percentage is not None
                        else None
                    ),
                    "open_pnl_source": item.performance.open_pnl_source,
                    "target_percentage": (
                        str(item.target_allocation_percentage)
                        if item.target_allocation_percentage is not None
                        else None
                    ),
                    "source_count": item.source_count,
                    "is_stale": item.is_stale,
                    "is_estimated": item.has_estimated_value,
                }
                for item in sorted(
                    holdings.holdings, key=lambda value: value.total_value_eur, reverse=True
                )[:30]
            ],
            "allocations": {
                item.dimension: {
                    "items": [
                        {
                            "label": _safe_text(value.label, 80),
                            "percentage": str(value.percentage),
                        }
                        for value in item.items[:10]
                    ],
                    "coverage_percentage": str(item.coverage_percentage),
                    "status": item.status,
                }
                for item in analytics.allocations
            },
            "performance_leaders": {
                "best": [_performer_context(item) for item in analytics.performance.best],
                "worst": [_performer_context(item) for item in analytics.performance.worst],
                "largest_contributors": [
                    _performer_context(item) for item in analytics.performance.contributors
                ],
                "coverage_percentage": str(analytics.performance.coverage_percentage),
                "basis": analytics.performance.message,
            },
            "benchmark": {
                "period": "1y",
                "symbol": _safe_text(analytics.benchmark.selected_symbol, 32),
                "name": _safe_text(analytics.benchmark.selected_name, 120),
                "portfolio_return_percentage": (
                    str(analytics.benchmark.portfolio_return_percentage)
                    if analytics.benchmark.portfolio_return_percentage is not None
                    else None
                ),
                "benchmark_return_percentage": (
                    str(analytics.benchmark.benchmark_return_percentage)
                    if analytics.benchmark.benchmark_return_percentage is not None
                    else None
                ),
                "relative_return_percentage": (
                    str(analytics.benchmark.relative_return_percentage)
                    if analytics.benchmark.relative_return_percentage is not None
                    else None
                ),
                "status": analytics.benchmark.status,
                "message": analytics.benchmark.message,
            },
            "risk": analytics.risk.model_dump(mode="json"),
            "targets": {
                "target_total_percentage": str(analytics.targets.target_total_percentage),
                "unallocated_percentage": str(analytics.targets.unallocated_percentage),
                "items": [
                    {
                        "symbol": _safe_text(item.symbol, 32),
                        "name": _safe_text(item.name, 120),
                        "current_percentage": str(item.current_percentage),
                        "target_percentage": (
                            str(item.target_percentage)
                            if item.target_percentage is not None
                            else None
                        ),
                        "drift_percentage_points": (
                            str(item.drift_percentage_points)
                            if item.drift_percentage_points is not None
                            else None
                        ),
                    }
                    for item in analytics.targets.items[:30]
                ],
            },
            "profile": {
                "risk_tolerance": profile.risk_tolerance if profile else None,
                "time_horizon_years": profile.time_horizon_years if profile else None,
                "goals": _safe_text(profile.goals, 500) if profile and profile.goals else None,
            },
            "calculation_references": calculation_references(),
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        context_hash = hashlib.sha256(serialized.encode()).hexdigest()
        existing = await self.db.scalar(
            select(PortfolioContextSnapshot).where(
                PortfolioContextSnapshot.user_id == user_id,
                PortfolioContextSnapshot.context_hash == context_hash,
            )
        )
        if existing is not None:
            return existing
        snapshot = PortfolioContextSnapshot(
            user_id=user_id,
            version=CONTEXT_VERSION,
            context_hash=context_hash,
            payload=payload,
        )
        self.db.add(snapshot)
        await self.db.commit()
        await self.db.refresh(snapshot)
        return snapshot

    async def read(self, user_id: uuid.UUID) -> PortfolioContextRead:
        snapshot = await self.build(user_id)
        return PortfolioContextRead(
            version=snapshot.version,
            context_hash=snapshot.context_hash,
            calculated_at=snapshot.calculated_at,
            calculation_references=[
                CalculationReference.model_validate(item)
                for item in snapshot.payload["calculation_references"]
            ],
        )


class AssistantService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        provider: OpenAIInvestmentAssistant,
    ) -> None:
        self.db = db
        self.settings = settings
        self.provider = provider
        self.contexts = PortfolioContextService(db)

    async def review(self, user_id: uuid.UUID, *, force: bool = False) -> PortfolioReviewRead:
        context = await self.contexts.build(user_id)
        newest = await self.db.scalar(
            select(AIRecommendation)
            .where(
                AIRecommendation.user_id == user_id,
                AIRecommendation.context_hash == context.context_hash,
            )
            .order_by(AIRecommendation.generated_at.desc())
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.settings.ai_review_cache_hours)
        if newest and _utc(newest.generated_at) >= cutoff and not force:
            return _review_read(newest, cached=True)
        review_count = await self.db.scalar(
            select(func.count())
            .select_from(AIRecommendation)
            .where(
                AIRecommendation.user_id == user_id,
                AIRecommendation.generated_at
                >= datetime.combine(
                    datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
                ),
            )
        )
        if int(review_count or 0) >= self.settings.ai_daily_review_limit:
            raise AssistantLimitError("Daily portfolio review limit reached")
        content = await self.provider.recommendation(
            context.payload,
            safety_identifier=_safety_identifier(user_id, self.settings.app_secret_key),
        )
        recommendation = AIRecommendation(
            user_id=user_id,
            content=content,
            model_used=self.provider.model,
            context_version=context.version,
            context_hash=context.context_hash,
            calculation_references=context.payload["calculation_references"],
        )
        self.db.add(recommendation)
        await self.db.commit()
        await self.db.refresh(recommendation)
        return _review_read(recommendation, cached=False)

    async def latest_review(self, user_id: uuid.UUID) -> PortfolioReviewRead | None:
        item = await self.db.scalar(
            select(AIRecommendation)
            .where(
                AIRecommendation.user_id == user_id,
                AIRecommendation.context_version == CONTEXT_VERSION,
            )
            .order_by(AIRecommendation.generated_at.desc())
        )
        return _review_read(item, cached=True) if item else None

    async def conversations(self, user_id: uuid.UUID) -> list[ConversationRead]:
        items = list(
            await self.db.scalars(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
            )
        )
        return [await self._conversation_read(item) for item in items]

    async def create_conversation(self, user_id: uuid.UUID) -> ConversationRead:
        item = Conversation(user_id=user_id)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return await self._conversation_read(item)

    async def delete_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        await self.db.commit()
        return bool(result.rowcount)

    async def prepare_chat(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message: str
    ) -> tuple[PortfolioContextSnapshot, list[dict[str, str]], str]:
        clean = validate_assistant_input(message, self.settings.ai_max_input_characters)
        conversation = await self._owned_conversation(user_id, conversation_id)
        if conversation is None:
            raise LookupError("Conversation not found")
        await self._enforce_limit(user_id)
        if await self.provider.moderate(clean):
            raise AssistantInputError("This message cannot be processed safely")
        existing = list(
            await self.db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.conversation_id == conversation_id,
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(16)
            )
        )[::-1]
        history = [
            {"role": item.role.value, "content": item.content}
            for item in existing
            if item.role in {ChatRole.USER, ChatRole.ASSISTANT}
        ]
        self.db.add(
            ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role=ChatRole.USER,
                content=clean,
            )
        )
        if not existing:
            conversation.title = _safe_text(clean, 72)
        conversation.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return await self.contexts.build(user_id), history, clean

    async def stream_reply(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        context: PortfolioContextSnapshot,
        history: list[dict[str, str]],
        message: str,
    ) -> AsyncIterator[str]:
        chunks: list[str] = []
        async for chunk in self.provider.stream_chat(
            context.payload,
            history,
            message,
            safety_identifier=_safety_identifier(user_id, self.settings.app_secret_key),
        ):
            chunks.append(chunk)
            yield chunk
        content = "".join(chunks).strip()
        disclaimer = self.provider.disclaimer
        if content and disclaimer.casefold() not in content.casefold():
            suffix = f"\n\n{disclaimer}"
            content += suffix
            yield suffix
        if content:
            self.db.add(
                ChatMessage(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    role=ChatRole.ASSISTANT,
                    content=content,
                )
            )
            conversation = await self._owned_conversation(user_id, conversation_id)
            if conversation:
                conversation.updated_at = datetime.now(timezone.utc)
            await self.db.commit()

    async def _owned_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> Conversation | None:
        return await self.db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )

    async def _conversation_read(self, item: Conversation) -> ConversationRead:
        messages = list(
            await self.db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.user_id == item.user_id,
                    ChatMessage.conversation_id == item.id,
                )
                .order_by(ChatMessage.created_at)
            )
        )
        return ConversationRead(
            id=item.id,
            title=item.title,
            created_at=item.created_at,
            updated_at=item.updated_at,
            messages=[
                ChatMessageRead.model_validate(value, from_attributes=True) for value in messages
            ],
        )

    async def _enforce_limit(self, user_id: uuid.UUID) -> None:
        start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
        count = await self.db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(
                ChatMessage.user_id == user_id,
                ChatMessage.role == ChatRole.USER,
                ChatMessage.created_at >= start,
            )
        )
        if int(count or 0) >= self.settings.ai_daily_message_limit:
            raise AssistantLimitError("Daily assistant message limit reached")


def validate_assistant_input(message: str, maximum: int) -> str:
    clean = " ".join(message.strip().split())
    if not clean:
        raise AssistantInputError("Message cannot be empty")
    if len(clean) > maximum:
        raise AssistantInputError(f"Message must be {maximum} characters or fewer")
    if any(pattern.search(clean) for pattern in INJECTION_PATTERNS):
        raise AssistantInputError("This message appears to contain instruction-manipulation text")
    return clean


def calculation_references() -> list[dict[str, str]]:
    return [
        {"id": "portfolio.total_value", "label": "Current portfolio value", "source": "/holdings"},
        {"id": "portfolio.open_pnl", "label": "Current open P/L", "source": "/holdings"},
        {"id": "allocation.current", "label": "Current allocations", "source": "/analytics"},
        {"id": "risk.current", "label": "Risk and concentration metrics", "source": "/analytics"},
        {"id": "targets.drift", "label": "Target allocation drift", "source": "/analytics"},
    ]


def _safe_text(value: object, maximum: int) -> str:
    return re.sub(r"[<>\x00-\x1f]", "", " ".join(str(value or "").split()))[:maximum]


def _performer_context(item: Any) -> dict[str, str]:
    return {
        "symbol": _safe_text(item.symbol, 32),
        "name": _safe_text(item.name, 120),
        "current_value_eur": str(item.current_value_eur),
        "open_pnl_eur": str(item.open_pnl_eur),
        "open_pnl_percentage": str(item.open_pnl_percentage),
        "contribution_percentage_points": str(item.contribution_percentage_points),
        "source": item.source,
    }


def _safety_identifier(user_id: uuid.UUID, secret: str) -> str:
    return hashlib.sha256(f"{user_id}:{secret}".encode()).hexdigest()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _review_read(item: AIRecommendation, *, cached: bool) -> PortfolioReviewRead:
    return PortfolioReviewRead(
        id=item.id,
        content=item.content,
        model_used=item.model_used,
        context_version=item.context_version,
        context_hash=item.context_hash,
        calculation_references=item.calculation_references or [],
        generated_at=item.generated_at,
        cached=cached,
    )
