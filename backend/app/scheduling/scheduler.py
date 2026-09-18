from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import Settings
from app.scheduling.jobs import (
    deliver_notification_digests,
    refresh_ecb_rates,
    refresh_historical_prices,
    sync_daily_connections,
    sync_live_connections,
    sync_monthly_etoro_snapshots,
    sync_portfolio_news,
)
from app.services.operations import monitored_job


def build_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        monitored_job("live-portfolio-sync", sync_live_connections),
        IntervalTrigger(minutes=settings.portfolio_sync_minutes),
        id="live-portfolio-sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        monitored_job("etoro-month-end", sync_monthly_etoro_snapshots),
        CronTrigger(day="28-31", hour=23, minute=30),
        id="etoro-month-end",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        monitored_job("daily-portfolio-sync", sync_daily_connections),
        CronTrigger(hour=5, minute=30),
        id="daily-portfolio-sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        monitored_job("daily-ecb-fx-rates", refresh_ecb_rates),
        CronTrigger(hour=16, minute=30),
        id="daily-ecb-fx-rates",
        max_instances=1,
        coalesce=True,
    )
    if settings.alpha_vantage_key:
        scheduler.add_job(
            monitored_job("initial-historical-price-backfill", refresh_historical_prices),
            DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=10)),
            id="initial-historical-price-backfill",
            max_instances=1,
        )
        scheduler.add_job(
            monitored_job("daily-historical-price-backfill", refresh_historical_prices),
            CronTrigger(hour=2, minute=15),
            id="daily-historical-price-backfill",
            max_instances=1,
            coalesce=True,
        )
    if settings.news_enabled:
        scheduler.add_job(
            monitored_job("initial-portfolio-news", sync_portfolio_news),
            DateTrigger(run_date=datetime.now(timezone.utc) + timedelta(seconds=5)),
            id="initial-portfolio-news",
            max_instances=1,
        )
        scheduler.add_job(
            monitored_job("portfolio-news", sync_portfolio_news),
            CronTrigger(hour=settings.news_sync_hour_utc),
            id="portfolio-news",
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        monitored_job("notification-digests", deliver_notification_digests),
        CronTrigger(hour=settings.notification_digest_hour_utc),
        id="notification-digests",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
