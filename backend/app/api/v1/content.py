import logging
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query, status

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.integrations.ai.openai_provider import AIProviderError, OpenAINewsBriefingAgent
from app.integrations.email import EmailDeliveryError, SMTPEmailSender
from app.integrations.news.finnhub import FinnhubNewsProvider
from app.schemas.content import (
    ContentSummary,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
)
from app.services.content import (
    ContentQueryService,
    MarketContentService,
    NotificationDigestService,
)
from app.services.news_briefing import PortfolioNewsBriefingService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=ContentSummary)
async def content_summary(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    news_limit: int = Query(default=8, ge=1, le=30),
    event_limit: int = Query(default=8, ge=1, le=30),
    alert_limit: int = Query(default=8, ge=1, le=30),
) -> ContentSummary:
    return await ContentQueryService(db, settings).summary(
        user.id,
        news_limit=news_limit,
        event_limit=event_limit,
        alert_limit=alert_limit,
    )


@router.post("/refresh", response_model=ContentSummary)
async def refresh_content(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> ContentSummary:
    if not settings.news_enabled or not settings.finnhub_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Market updates are not enabled")
    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1", timeout=15) as client:
        await MarketContentService(
            db, FinnhubNewsProvider(settings.finnhub_api_key, client=client)
        ).sync(user.id)
    if settings.ai_enabled and settings.openai_api_key:
        try:
            await PortfolioNewsBriefingService(
                db,
                settings,
                OpenAINewsBriefingAgent(settings.openai_api_key, settings.openai_model),
            ).generate(user.id)
        except AIProviderError:
            await db.rollback()
            logger.warning("Portfolio news brief generation failed during manual refresh")
    return await ContentQueryService(db, settings).summary(
        user.id, news_limit=20, event_limit=20, alert_limit=20
    )


@router.post("/news/{news_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_news_read(
    news_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
):
    if not await ContentQueryService(db, settings).mark_news_read(user.id, news_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "News item not found")


@router.post("/alerts/{alert_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_alert_read(
    alert_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: AppSettings
):
    if not await ContentQueryService(db, settings).mark_alert_read(user.id, alert_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")


@router.get("/preferences", response_model=NotificationPreferenceRead)
async def notification_preferences(
    user: CurrentUser, db: DbSession, settings: AppSettings
) -> NotificationPreferenceRead:
    return await ContentQueryService(db, settings).preferences(user)


@router.put("/preferences", response_model=NotificationPreferenceRead)
async def update_notification_preferences(
    payload: NotificationPreferenceUpdate,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> NotificationPreferenceRead:
    try:
        return await ContentQueryService(db, settings).update_preferences(user, payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/digest/send", status_code=status.HTTP_204_NO_CONTENT)
async def send_digest_now(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
):
    try:
        await NotificationDigestService(db, settings, SMTPEmailSender(settings)).send_now(user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except EmailDeliveryError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The digest email could not be delivered"
        ) from exc
