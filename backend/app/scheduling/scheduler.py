from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import Settings
from app.scheduling.jobs import (
    refresh_ecb_rates,
    refresh_historical_prices,
    sync_live_connections,
    sync_monthly_etoro_snapshots,
    sync_portfolio_news,
)


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        sync_live_connections,
        IntervalTrigger(minutes=settings.portfolio_sync_minutes),
        id="live-portfolio-sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_monthly_etoro_snapshots,
        CronTrigger(day="28-31", hour=23, minute=30),
        id="etoro-month-end",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        refresh_ecb_rates,
        CronTrigger(hour=16, minute=30),
        id="daily-ecb-fx-rates",
        max_instances=1,
        coalesce=True,
    )
    if settings.alpha_vantage_key:
        scheduler.add_job(
            refresh_historical_prices,
            DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=10)),
            id="initial-historical-price-backfill",
            max_instances=1,
        )
        scheduler.add_job(
            refresh_historical_prices,
            CronTrigger(hour=2, minute=15),
            id="daily-historical-price-backfill",
            max_instances=1,
            coalesce=True,
        )
    if settings.news_enabled:
        scheduler.add_job(
            sync_portfolio_news,
            CronTrigger(hour=settings.news_sync_hour_utc),
            id="portfolio-news",
            max_instances=1,
            coalesce=True,
        )
    return scheduler
