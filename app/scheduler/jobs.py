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
    reminder_h, reminder_m = settings.reminder_time.split(":")

    # ── Daily assignment sync ──────────────────────────────────────────────────
    scheduler.add_job(
        _sync_job,
        CronTrigger(hour=int(sync_h), minute=int(sync_m), timezone=tz),
        id="daily_sync",
        name="Daily assignment sync",
        replace_existing=True,
    )

    # ── Weekly summary (Thursday) ──────────────────────────────────────────────
    scheduler.add_job(
        _weekly_summary_job,
        CronTrigger(
            day_of_week=settings.summary_day[:3],   # "thu"
            hour=int(summary_h),
            minute=int(summary_m),
            timezone=tz,
        ),
        id="weekly_summary",
        name="Weekly summary + PDF",
        replace_existing=True,
    )

    # ── Daily morning reminder (Mon–Fri) ───────────────────────────────────────
    scheduler.add_job(
        _daily_reminder_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour=int(reminder_h),
            minute=int(reminder_m),
            timezone=tz,
        ),
        id="daily_reminder",
        name="Morning reminder",
        replace_existing=True,
    )

    return scheduler


# ── Job wrappers ───────────────────────────────────────────────────────────────

async def _sync_job():
    from app.scheduler.sync import run_sync
    logger.info("⏰ Scheduled sync starting...")
    await run_sync()


async def _weekly_summary_job():
    from app.scheduler.summary import send_weekly_summaries
    logger.info("⏰ Sending weekly summaries...")
    await send_weekly_summaries()


async def _daily_reminder_job():
    from app.scheduler.summary import send_daily_reminders
    logger.info("⏰ Sending daily reminders...")
    await send_daily_reminders()
