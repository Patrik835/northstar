import logging

import httpx

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.encryption import CredentialCipher
from app.integrations.ai.openai_provider import OpenAINewsBriefingAgent
from app.integrations.connectors.registry import ConnectorRegistry
from app.integrations.email import SMTPEmailSender
from app.integrations.market_data import (
    AlphaVantageProvider,
    EcbFxRateProvider,
    FxRateError,
)
from app.integrations.news.finnhub import FinnhubNewsProvider
from app.models.enums import SyncTrigger
from app.repositories.connections import ConnectionRepository
from app.services.connection_sync import ConnectionSyncService
from app.services.content import MarketContentService, NotificationDigestService
from app.services.historical_market_data import HistoricalMarketDataService
from app.services.news_briefing import PortfolioNewsBriefingService

logger = logging.getLogger(__name__)


async def sync_live_connections() -> None:
    """Synchronize providers whose data is intended for intraday refresh."""
    registry = ConnectorRegistry()
    async with SessionFactory() as db:
        connections = await ConnectionRepository(db).syncable_live(
            registry.brokers_for_schedule("intraday")
        )
        service = ConnectionSyncService(db, CredentialCipher())
        for connection in connections:
            await service.sync(connection, trigger=SyncTrigger.SCHEDULED)
    logger.info("Scheduled live-connection sync completed for %d connections", len(connections))


async def sync_daily_connections() -> None:
    """Synchronize reporting APIs whose source data refreshes once per day."""
    registry = ConnectorRegistry()
    async with SessionFactory() as db:
        connections = await ConnectionRepository(db).syncable_live(
            registry.brokers_for_schedule("daily")
        )
        service = ConnectionSyncService(db, CredentialCipher())
        for connection in connections:
            await service.sync(connection, trigger=SyncTrigger.SCHEDULED)
    logger.info("Scheduled daily-connection sync completed for %d connections", len(connections))


async def sync_monthly_etoro_snapshots() -> None:
    """Ensure an eToro valuation is captured near each month end."""
    async with SessionFactory() as db:
        connections = await ConnectionRepository(db).syncable_etoro()
        service = ConnectionSyncService(db, CredentialCipher())
        for connection in connections:
            await service.sync(connection, trigger=SyncTrigger.SCHEDULED)
    logger.info("Scheduled eToro month-end sync completed for %d connections", len(connections))


async def sync_portfolio_news() -> None:
    """Fetch and deduplicate Finnhub news for tickers held by active users."""
    settings = get_settings()
    if not settings.news_enabled or not settings.finnhub_api_key:
        return
    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1", timeout=15) as client:
        async with SessionFactory() as db:
            news, events = await MarketContentService(
                db, FinnhubNewsProvider(settings.finnhub_api_key, client=client)
            ).sync()
            generated = failed = 0
            if settings.ai_enabled and settings.openai_api_key:
                generated, failed = await PortfolioNewsBriefingService(
                    db,
                    settings,
                    OpenAINewsBriefingAgent(settings.openai_api_key, settings.openai_model),
                ).generate_all()
    logger.info("Finnhub content stored: %d news items and %d calendar events", news, events)
    if settings.ai_enabled and settings.openai_api_key:
        logger.info("Portfolio news briefs processed: %d successful, %d failed", generated, failed)


async def deliver_notification_digests() -> None:
    settings = get_settings()
    async with SessionFactory() as db:
        sent, failed = await NotificationDigestService(
            db, settings, SMTPEmailSender(settings)
        ).deliver_due()
    logger.info("Notification digests delivered: %d sent, %d failed", sent, failed)


async def refresh_ecb_rates() -> None:
    """Fetch and persist the newest ECB working-day reference rates."""

    async with SessionFactory() as db:
        try:
            rate_date = await EcbFxRateProvider(db).refresh(force=True)
            await db.commit()
        except FxRateError:
            await db.rollback()
            logger.warning("Scheduled ECB exchange-rate refresh failed")
            return
    logger.info("Scheduled ECB exchange rates stored for %s", rate_date)


async def refresh_historical_prices() -> None:
    settings = get_settings()
    if not settings.alpha_vantage_key:
        return
    async with SessionFactory() as db:
        service = HistoricalMarketDataService(db, AlphaVantageProvider(settings.alpha_vantage_key))
        instruments, points = await service.refresh()
    logger.info(
        "Alpha Vantage weekly history refreshed for %d instruments (%d new points)",
        instruments,
        points,
    )
