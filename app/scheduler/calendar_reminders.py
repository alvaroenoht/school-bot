"""
Daily job: fetch all CalendarSubscription rows, check for due reminders,
and send WhatsApp messages to the linked groups.
"""
import logging
from datetime import date

import pytz

from app.config import get_settings
from app.db.database import SessionLocal
from app.db import models
from app.api.ical_client import get_due_reminders
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)


async def send_calendar_reminders() -> None:
    settings = get_settings()
    tz = pytz.timezone(settings.timezone)
    today = date.today()  # scheduler runs in configured TZ via APScheduler

    db = SessionLocal()
    wa = WahaClient()

    try:
        subscriptions = db.query(models.CalendarSubscription).all()
        logger.info("⏰ Calendar reminders: checking %d subscription(s)", len(subscriptions))

        for sub in subscriptions:
            try:
                events = get_due_reminders(sub.ical_url, today)
                for event in events:
                    msg = _format_message(event)
                    wa.send_text(sub.whatsapp_group_id, msg)
                    logger.info(
                        "CALENDAR reminder sent group=%s summary=%r days_before=%d",
                        sub.whatsapp_group_id,
                        event["summary"],
                        event["days_before"],
                    )
            except Exception as e:
                logger.error(
                    "CALENDAR reminder failed sub_id=%d label=%r: %s",
                    sub.id, sub.label, e,
                )
    finally:
        db.close()


def _format_message(event: dict) -> str:
    event_date = event["event_date"]
    days_before = event["days_before"]
    summary = event["summary"]
    description = event.get("description")
    is_birthday = event["is_birthday"]

    date_str = event_date.strftime("%d/%m")

    if is_birthday:
        # Extract the name after "Cumpleaños de "
        name = summary
        for prefix in ("Cumpleaños de ", "cumpleaños de "):
            if prefix in summary:
                name = summary.split(prefix, 1)[1].strip()
                break
        first_name = name.split()[0]

        return (
            f"🎉🎂 *¡Hoy es el cumpleaños de {name}!* 🎂🎉\n\n"
            f"En esta fecha tan especial, nos unimos para felicitar con mucho cariño "
            f"al cumpleañero, deseándole abundantes bendiciones, salud, alegría y un "
            f"año colmado de hermosos momentos.\n"
            f"¡Feliz cumpleaños! 🎉🎂"
        )

    # Regular event
    if days_before == 0:
        timing = "hoy"
    elif days_before == 1:
        timing = "mañana"
    else:
        timing = f"en {days_before} días"

    body = (
        f"📅 *Recordatorio — {timing} {date_str}:*\n\n"
        f"• 📌 *{summary}*"
    )
    if description:
        body += f"\n  _{description}_"

    return body
