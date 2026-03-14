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

    # ── Form reminders + auto-close (runs daily at 09:00) ─────────────────────
    scheduler.add_job(
        _form_jobs,
        CronTrigger(hour=9, minute=0, timezone=tz),
        id="form_daily",
        name="Form reminders and auto-close",
        replace_existing=True,
    )

    # ── Known-contact group membership sync (every 4 hours) ───────────────────
    scheduler.add_job(
        _sync_known_contact_groups_job,
        CronTrigger(hour="7,11,15,19", minute=0, timezone=tz),
        id="sync_known_contact_groups",
        name="Sync KnownContact group membership",
        replace_existing=True,
    )

    # ── Hourly DB backup → S3 ──────────────────────────────────────────────────
    scheduler.add_job(
        _db_backup_job,
        CronTrigger(minute=0, timezone=tz),  # top of every hour
        id="db_backup",
        name="Hourly PostgreSQL backup to S3",
        replace_existing=True,
    )

    return scheduler


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run_in_new_loop(coro_factory):
    """Run an async coroutine in a fresh event loop (for thread-pool execution)."""
    import asyncio
    asyncio.run(coro_factory())


# ── Job wrappers ───────────────────────────────────────────────────────────────

async def _sync_job():
    """Run the blocking sync in a thread pool so the event loop stays free."""
    import asyncio
    logger.info("⏰ Scheduled sync starting...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_in_new_loop, _do_sync)


async def _do_sync():
    from app.scheduler.sync import run_sync
    await run_sync()


async def _weekly_summary_job():
    import asyncio
    logger.info("⏰ Weekly summary: syncing assignments first...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _run_in_new_loop, _do_weekly_summary)


async def _do_weekly_summary():
    from app.scheduler.sync import run_sync
    from app.scheduler.summary import send_weekly_summaries
    await run_sync()
    logger.info("⏰ Sync done, sending weekly summaries...")
    await send_weekly_summaries()


async def _form_jobs():
    """Send reminders to non-respondents and auto-close forms past closes_at."""
    from datetime import datetime
    from app.db.database import SessionLocal
    from app.db import models
    from app.whatsapp.client import WahaClient

    db = SessionLocal()
    wa = WahaClient()
    now = datetime.utcnow()

    try:
        open_forms = db.query(models.Form).filter_by(status="open").all()
        logger.info("⏰ Form jobs: %d open form(s)", len(open_forms))

        for form in open_forms:
            # Auto-close if past closes_at
            if form.closes_at and now >= form.closes_at:
                form.status = "closed"
                db.commit()
                logger.info("FORM auto-closed form_id=%d", form.id)
                # Clean up pending sessions
                sessions = db.query(models.ConversationSession).filter_by(flow="form_respond").all()
                for s in sessions:
                    if (s.data or {}).get("form_id") == form.id:
                        db.delete(s)
                db.commit()
                continue

            # Send reminders if enabled
            if not form.send_group_reminders or not form.reminder_interval_days:
                continue

            # Only remind every reminder_interval_days
            opens_at = form.opens_at or form.created_at
            days_open = (now - opens_at).days if opens_at else 0
            if days_open > 0 and days_open % form.reminder_interval_days != 0:
                continue

            # Find audience classrooms
            audience_rows = db.query(models.FormAudience).filter_by(form_id=form.id).all()
            classroom_ids = [a.classroom_id for a in audience_rows]

            submitted_jids = {
                s.respondent_jid
                for s in db.query(models.FormSubmission)
                .filter_by(form_id=form.id, status="submitted")
                .all()
            }

            # Count non-respondents per classroom (via student membership)
            for cid in classroom_ids:
                cls = db.query(models.Classroom).get(cid)
                if not cls:
                    continue

                student_parent_ids = {
                    s.parent_id
                    for s in db.query(models.Student).filter_by(classroom_id=cid).all()
                    if s.parent_id
                }
                parents_in_cls = db.query(models.Parent).filter(
                    models.Parent.id.in_(student_parent_ids),
                    models.Parent.is_active == True,
                ).all()

                pending_count = sum(
                    1 for p in parents_in_cls if p.whatsapp_jid not in submitted_jids
                )

                if pending_count > 0 and cls.whatsapp_group_id and form.send_group_reminders:
                    try:
                        wa.send_text(
                            cls.whatsapp_group_id,
                            f"⏰ *Recordatorio:* {pending_count} padre(s) aún no han respondido "
                            f"el formulario *{form.title}*.\n"
                            "Revisa tus mensajes directos para completarlo.",
                        )
                        logger.info(
                            "FORM reminder sent form_id=%d classroom_id=%d pending=%d",
                            form.id, cid, pending_count,
                        )
                    except Exception as e:
                        logger.warning("FORM reminder failed cls=%d: %s", cid, e)

    except Exception as e:
        logger.exception("FORM jobs error: %s", e)
    finally:
        db.close()


async def _db_backup_job():
    """Dump PostgreSQL DB and upload to S3 under backups/YYYY-MM-DD/schoolbot_YYYYMMDD_HHmm.dump.
    S3 lifecycle rules can be used to auto-expire old backups (recommended: 30 days).
    """
    import asyncio
    import os
    import subprocess
    import tempfile
    from datetime import datetime
    from urllib.parse import urlparse

    from app.config import get_settings
    from app.utils.s3_upload import upload_file_to_s3

    settings = get_settings()
    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")
    ts_str = now.strftime("%Y%m%d_%H%M")
    s3_key = f"backups/{date_str}/schoolbot_{ts_str}.dump"

    logger.info("⏰ DB backup starting → s3://%s/%s", settings.s3_bucket, s3_key)

    db_url = urlparse(settings.database_url)
    env = {**os.environ, "PGPASSWORD": db_url.password or ""}

    with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [
                    "pg_dump",
                    "--format=custom",
                    f"--host={db_url.hostname}",
                    f"--port={db_url.port or 5432}",
                    f"--username={db_url.username}",
                    f"--dbname={db_url.path.lstrip('/')}",
                    f"--file={tmp_path}",
                ],
                env=env,
                capture_output=True,
                text=True,
            ),
        )
        if result.returncode != 0:
            logger.error("DB backup pg_dump failed: %s", result.stderr)
            return

        await loop.run_in_executor(None, lambda: upload_file_to_s3(tmp_path, s3_key))
        logger.info("✅ DB backup uploaded: %s", s3_key)
    except Exception:
        logger.exception("DB backup failed")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def _sync_known_contact_groups_job():
    """Sync KnownContact group membership from live WAHA data every 4 hours."""
    from datetime import datetime
    from app.db.database import SessionLocal
    from app.db import models
    from app.whatsapp.client import WahaClient

    db = SessionLocal()
    wa = WahaClient()
    now = datetime.utcnow()
    logger.info("⏰ Syncing KnownContact group memberships...")

    try:
        # Migrate legacy KnownContacts with source_group_id but no KnownContactGroup row
        for contact in db.query(models.KnownContact).filter(
            models.KnownContact.source_group_id.isnot(None)
        ).all():
            classroom = db.query(models.Classroom).filter_by(
                whatsapp_group_id=contact.source_group_id, is_active=True
            ).first()
            if not classroom:
                continue
            exists = db.query(models.KnownContactGroup).filter_by(
                contact_jid=contact.jid, classroom_id=classroom.id
            ).first()
            if not exists:
                db.add(models.KnownContactGroup(
                    contact_jid=contact.jid,
                    classroom_id=classroom.id,
                    active=True,
                    synced_at=now,
                ))
        db.commit()

        # For each linked classroom sync live membership
        classrooms = db.query(models.Classroom).filter(
            models.Classroom.whatsapp_group_id.isnot(None),
            models.Classroom.is_active == True,
        ).all()

        for classroom in classrooms:
            try:
                participants = wa.get_group_participants(classroom.whatsapp_group_id)
                # Build a set of resolvable identifiers for fast lookup
                participant_ids: set[str] = set()
                for p in participants:
                    participant_ids.add(p)
                    phone = wa.resolve_phone(p)
                    participant_ids.add(f"{phone}@c.us")

                for kcg in db.query(models.KnownContactGroup).filter_by(classroom_id=classroom.id).all():
                    contact = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
                    if not contact:
                        continue
                    phone = wa.resolve_phone(contact.jid)
                    is_member = contact.jid in participant_ids or f"{phone}@c.us" in participant_ids
                    kcg.active = is_member
                    kcg.synced_at = now

                db.commit()
                logger.info("KCG sync classroom_id=%d participants=%d", classroom.id, len(participants))
            except Exception as e:
                logger.warning("KCG sync failed classroom_id=%d: %s", classroom.id, e)

    except Exception as e:
        logger.exception("KCG sync error: %s", e)
    finally:
        db.close()
