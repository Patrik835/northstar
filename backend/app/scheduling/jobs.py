import logging

from app.core.database import SessionFactory
from app.core.encryption import CredentialCipher
from app.repositories.connections import ConnectionRepository
from app.services.connection_sync import ConnectionSyncService

logger = logging.getLogger(__name__)


async def sync_live_connections() -> None:
    """Dispatch due Trading212/Binance connections through their registered connectors."""
    async with SessionFactory() as db:
        connections = await ConnectionRepository(db).syncable_live()
        service = ConnectionSyncService(db, CredentialCipher())
        for connection in connections:
            await service.sync(connection)
    logger.info("Scheduled live-connection sync completed for %d connections", len(connections))


async def sync_monthly_etoro_snapshots() -> None:
    """Persist eToro month-end values; calendar handling belongs in this job."""
    logger.info("Scheduled eToro snapshot tick")


async def sync_portfolio_news() -> None:
    """Fetch and deduplicate Finnhub news for tickers held by active users."""
    logger.info("Scheduled portfolio-news sync tick")
