"""
Summary and reminder senders — called by APScheduler jobs.
"""
import logging
import os
from datetime import datetime, timedelta

import pytz
from sqlalchemy import text

from app.db.database import SessionLocal
from app.db import models
from app.utils.pdf_generator import create_weekly_pdf
from app.utils.summary_formatter import generate_weekly_data, generate_weekly_summary
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
                # Text summary
                raw_conn = db.connection()
                message = generate_weekly_summary(raw_conn, student_id, start, end)
                if message:
                    wa.send_chunked(classroom.whatsapp_group_id, message)
                else:
                    logger.warning(f"No assignments for student {student_id} in week {start}–{end}")
                    continue

                # PDF
                pdf_data = generate_weekly_data(raw_conn, student_id, start, end)
                pdf_path = f"/tmp/student_{student_id}_week_{start}.pdf"
                try:
                    create_weekly_pdf(pdf_data, pdf_path, week_dates)
                    wa.send_document(
                        classroom.whatsapp_group_id,
                        pdf_path,
                        caption=f"📄 Actividades del {week_dates[0].day} al {week_dates[-1].day}",
                    )
                finally:
                    if os.path.exists(pdf_path):
                        os.remove(pdf_path)

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
