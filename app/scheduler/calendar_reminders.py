"""
Daily job: materialize birthdays from Student.birth_date, then broadcast
day-of and day-before reminders for events to audience WA groups.

Idempotent via notified_day_before / notified_day_of flags on Event.
"""
import logging
from datetime import date, datetime, timedelta, time

from sqlalchemy import extract

from app.db.database import SessionLocal
from app.db import models
from app.bot.notifications import _get_group_ids
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)


async def send_calendar_reminders() -> None:
    today = date.today()
    tomorrow = today + timedelta(days=1)

    db = SessionLocal()
    wa = WahaClient()
    try:
        _materialize_birthdays_for(today, db)

        # Day-of reminders
        day_of_events = (
            db.query(models.Event)
            .filter(
                models.Event.notified_day_of == False,  # noqa: E712
                models.Event.date >= datetime.combine(today, time.min),
                models.Event.date <  datetime.combine(tomorrow, time.min),
            )
            .all()
        )
        for ev in day_of_events:
            _broadcast(ev, when="day_of", db=db, wa=wa)
            ev.notified_day_of = True

        # Day-before reminders (skip birthdays — day-of only per decision)
        after_tomorrow = tomorrow + timedelta(days=1)
        day_before_events = (
            db.query(models.Event)
            .filter(
                models.Event.notified_day_before == False,  # noqa: E712
                models.Event.type != "birthday",
                models.Event.date >= datetime.combine(tomorrow, time.min),
                models.Event.date <  datetime.combine(after_tomorrow, time.min),
            )
            .all()
        )
        for ev in day_before_events:
            _broadcast(ev, when="day_before", db=db, wa=wa)
            ev.notified_day_before = True

        db.commit()
        logger.info(
            "⏰ Calendar reminders: day_of=%d, day_before=%d",
            len(day_of_events), len(day_before_events),
        )
    finally:
        db.close()


def _materialize_birthdays_for(day: date, db) -> None:
    """Create Birthday Events for students whose birth_date matches day (month+day)."""
    students = (
        db.query(models.Student)
        .filter(
            models.Student.birth_date.isnot(None),
            extract("month", models.Student.birth_date) == day.month,
            extract("day",   models.Student.birth_date) == day.day,
        )
        .all()
    )
    for s in students:
        # Skip if a birthday event for this student on this date already exists
        existing = (
            db.query(models.Event)
            .filter(
                models.Event.type == "birthday",
                models.Event.student_id == s.id,
                models.Event.date >= datetime.combine(day, time.min),
                models.Event.date <  datetime.combine(day + timedelta(days=1), time.min),
            )
            .first()
        )
        if existing:
            continue

        ev = models.Event(
            title=f"Cumpleaños de {s.name}",
            description=None,
            date=datetime.combine(day, time(8, 0)),
            location=None,
            is_global=False,
            type="birthday",
            student_id=s.id,
        )
        db.add(ev)
        db.flush()
        if s.classroom_id:
            db.add(models.EventAudience(event_id=ev.id, classroom_id=s.classroom_id))
    db.flush()


def _broadcast(event: models.Event, *, when: str, db, wa: WahaClient) -> None:
    """Send event message to audience WA groups."""
    if event.is_global:
        classroom_ids = [c.id for c in db.query(models.Classroom).all()]
    else:
        classroom_ids = [a.classroom_id for a in event.audience]
    group_ids = _get_group_ids(classroom_ids, db)
    if not group_ids:
        logger.info("CALENDAR event=%d no audience groups", event.id)
        return

    msg = _format_message(event, when)
    for gid in group_ids:
        try:
            wa.send_text(gid, msg)
            logger.info("CALENDAR sent event=%d type=%s when=%s group=%s", event.id, event.type, when, gid)
        except Exception as e:
            logger.warning("CALENDAR send failed event=%d group=%s: %s", event.id, gid, e)


def _format_message(event: models.Event, when: str) -> str:
    date_str = event.date.strftime("%d/%m")

    if event.type == "birthday":
        name = event.student.name if event.student else event.title.replace("Cumpleaños de ", "")
        return (
            f"🎉🎂 *¡Hoy es el cumpleaños de {name}!* 🎂🎉\n\n"
            f"En esta fecha tan especial, nos unimos para felicitar con mucho cariño "
            f"al cumpleañero, deseándole abundantes bendiciones, salud, alegría y un "
            f"año colmado de hermosos momentos.\n"
            f"¡Feliz cumpleaños! 🎉🎂"
        )

    timing = "hoy" if when == "day_of" else "mañana"
    icon = {"holiday": "🎉", "exam": "📝", "general": "📅"}.get(event.type, "📅")
    label = {"holiday": "Día feriado", "exam": "Examen", "general": "Recordatorio"}.get(event.type, "Recordatorio")

    body = f"{icon} *{label} — {timing} {date_str}:*\n\n• 📌 *{event.title}*"
    if event.location:
        body += f"\n  📍 {event.location}"
    if event.description:
        body += f"\n  _{event.description}_"
    return body
