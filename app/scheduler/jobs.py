"""
APScheduler job definitions.
Replaces AppDaemon's run_daily / run_at scheduling.
"""
import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    scheduler = AsyncIOScheduler(timezone=tz)

    sync_h, sync_m = settings.sync_time.split(":")
    summary_h, summary_m = settings.summary_time.split(":")

    # ── Daily assignment sync ──────────────────────────────────────────────────
    scheduler.add_job(
        _sync_job,
        CronTrigger(hour=int(sync_h), minute=int(sync_m), timezone=tz),
        id="daily_sync",
        name="Daily assignment sync",
        replace_existing=True,
    )

    # ── Weekly summary (sync first, then send) ────────────────────────────────
    scheduler.add_job(
        _weekly_summary_job,
        CronTrigger(
            day_of_week=settings.summary_day[:3],
            hour=int(summary_h),
            minute=int(summary_m),
            timezone=tz,
        ),
        id="weekly_summary",
        name="Weekly summary",
        replace_existing=True,
    )

    return scheduler


# ── Job wrappers ───────────────────────────────────────────────────────────────

async def _sync_job():
    from app.scheduler.sync import run_sync
    logger.info("⏰ Scheduled sync starting...")
    await run_sync()


async def _weekly_summary_job():
    from app.scheduler.sync import run_sync
    from app.scheduler.summary import send_weekly_summaries
    logger.info("⏰ Weekly summary: syncing assignments first...")
    await run_sync()
    logger.info("⏰ Sync done, sending weekly summaries...")
    await send_weekly_summaries()
