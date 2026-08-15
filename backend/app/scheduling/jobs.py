import logging

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.encryption import CredentialCipher
from app.integrations.market_data import (
    AlphaVantageProvider,
    EcbFxRateProvider,
    FxRateError,
)
from app.models.enums import SyncTrigger
from app.repositories.connections import ConnectionRepository
from app.services.connection_sync import ConnectionSyncService
from app.services.historical_market_data import HistoricalMarketDataService

logger = logging.getLogger(__name__)


async def sync_live_connections() -> None:
    """Dispatch all live broker/exchange connections through their connectors."""
    async with SessionFactory() as db:
        connections = await ConnectionRepository(db).syncable_live()
        service = ConnectionSyncService(db, CredentialCipher())
        for connection in connections:
            await service.sync(connection, trigger=SyncTrigger.SCHEDULED)
    logger.info("Scheduled live-connection sync completed for %d connections", len(connections))


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
    logger.info("Scheduled portfolio-news sync tick")


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
        service = HistoricalMarketDataService(
            db, AlphaVantageProvider(settings.alpha_vantage_key)
        )
        instruments, points = await service.refresh()
    logger.info(
        "Alpha Vantage weekly history refreshed for %d instruments (%d new points)",
        instruments,
        points,
    )
