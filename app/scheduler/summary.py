"""
Summary and reminder senders — called by APScheduler jobs.
"""
import logging
import os
import tempfile
from datetime import datetime, timedelta

import pytz

from app.db.database import SessionLocal
from app.db import models
from app.utils.summary_formatter import generate_weekly_summary, generate_weekly_data
from app.utils.pdf_generator import create_weekly_pdf
from app.utils.s3_upload import upload_file_to_s3, generate_presigned_url
from app.utils.helpers import shorten_url
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()
PANAMA_TZ = pytz.timezone("America/Panama")


def _next_monday(ref):
    days = (7 - ref.weekday()) % 7
    return ref + timedelta(days=days if days else 7)


async def send_weekly_summaries():
    """Send weekly text summary + PDF to every active classroom group."""
    db = SessionLocal()
    try:
        today = datetime.now(PANAMA_TZ).date()
        start = _next_monday(today)
        end = start + timedelta(days=4)
        week_dates = [start + timedelta(days=i) for i in range(5)]

        classrooms = db.query(models.Classroom).filter_by(is_active=True).all()

        for classroom in classrooms:
            if not classroom.whatsapp_group_id:
                logger.warning(f"Classroom {classroom.id} has no WhatsApp group — skipping.")
                continue

            # Find students linked to this classroom
            student = db.query(models.Student).filter_by(classroom_id=classroom.id).first()
            if not student or not student.parent_id:
                continue

            parent = db.query(models.Parent).get(student.parent_id)
            if not parent:
                continue

            for student_id in [student.id]:
                raw_conn = db.connection().connection.dbapi_connection

                # Text summary
                message = generate_weekly_summary(raw_conn, student_id, start, end)
                if message:
                    wa.send_text(classroom.whatsapp_group_id, message)
                else:
                    logger.warning(f"No assignments for student {student_id} in week {start}–{end}")
                    continue

                # PDF generation + S3 upload
                try:
                    bot_status = db.query(models.BotStatus).first()
                    last_sync_str = None
                    if bot_status and bot_status.last_sync_at:
                        tz_obj = pytz.timezone("America/Panama")
                        local_dt = bot_status.last_sync_at.replace(tzinfo=pytz.utc).astimezone(tz_obj)
                        last_sync_str = local_dt.strftime("%d/%m/%Y %H:%M")

                    data_by_day = generate_weekly_data(raw_conn, student_id, start, end)
                    has_data = any(
                        data_by_day.get(day, {}).get("sumativas") or data_by_day.get(day, {}).get("materials")
                        for day in data_by_day
                    )
                    if not has_data:
                        continue

                    class_label = classroom.name if classroom.name else f"salon_{classroom.id}"

                    with tempfile.TemporaryDirectory() as tmpdir:
                        filename = f"resumen_{class_label}_{start.strftime('%d%m')}.pdf"
                        pdf_path = os.path.join(tmpdir, filename)
                        create_weekly_pdf(data_by_day, pdf_path, week_dates, last_sync_at=last_sync_str)

                        s3_key = f"resumenes/{start.strftime('%Y-%m-%d')}/{filename}"
                        upload_file_to_s3(pdf_path, s3_key)
                        presigned = generate_presigned_url(s3_key)
                        short_url = shorten_url(presigned)
                        wa.send_text(
                            classroom.whatsapp_group_id,
                            f"📄 *PDF de {class_label}:*\n{short_url}",
                        )
                except Exception as e:
                    logger.error(f"PDF generation/upload failed for student {student_id}: {e}")

    finally:
        db.close()


async def send_daily_reminders():
    """Send a morning digest of today's assignments to each active group."""
    db = SessionLocal()
    try:
        today = datetime.now(PANAMA_TZ).date()
        classrooms = db.query(models.Classroom).filter_by(is_active=True).all()

        for classroom in classrooms:
            if not classroom.whatsapp_group_id:
                continue

            # Find students linked to this classroom
            student = db.query(models.Student).filter_by(classroom_id=classroom.id).first()
            if not student or not student.parent_id:
                continue

            parent = db.query(models.Parent).get(student.parent_id)
            if not parent:
                continue

            for student_id in [student.id]:
                assignments = (
                    db.query(models.Assignment)
                    .filter(
                        models.Assignment.student_id == student_id,
                        models.Assignment.date == today.isoformat(),
                    )
                    .all()
                )

                if not assignments:
                    continue

                lines = [f"☀️ *Buenos días! Actividades para hoy {today.strftime('%d/%m')}:*\n"]
                for a in assignments:
                    subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
                    icon = subject.icon if subject else "📘"
                    name = subject.name if subject else f"Materia {a.subject_id}"
                    lines.append(f"{icon} *{name}*: {a.title}")
                    if a.summary:
                        lines.append(f"   _{a.summary}_")
                    if a.materials:
                        lines.append(f"   🎒 {a.materials}")
                    lines.append("")

                wa.send_text(classroom.whatsapp_group_id, "\n".join(lines))

    finally:
        db.close()
