"""
Admin group commands for Google Calendar subscriptions.

Commands (sent from within the WhatsApp group):
  /subscribe_calendar <ical_url> [label]
  /unsubscribe_calendar <label_or_id>
  /list_calendars
"""
import logging

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)


async def handle_group(group_jid: str, body: str, db) -> bool:
    """
    Handle calendar commands from an admin inside a group.
    Returns True if the command was handled (even if it failed), False if unrecognised.
    """
    wa = WahaClient()
    cmd = body.strip().lstrip("/").lower()

    if cmd.startswith("subscribe_calendar"):
        _handle_subscribe(group_jid, body, db, wa)
        return True

    if cmd.startswith("unsubscribe_calendar"):
        _handle_unsubscribe(group_jid, body, db, wa)
        return True

    if cmd.strip() == "list_calendars":
        _handle_list(group_jid, db, wa)
        return True

    return False


def _handle_subscribe(group_jid: str, body: str, db, wa: WahaClient) -> None:
    parts = body.strip().split(None, 2)
    # parts[0] = /subscribe_calendar, parts[1] = url, parts[2] = label (optional)
    if len(parts) < 2:
        wa.send_text(group_jid, "Uso: `/subscribe_calendar <url_ical> [nombre]`")
        return

    ical_url = parts[1]
    label = parts[2].strip() if len(parts) > 2 else None

    if not ical_url.startswith("https://"):
        wa.send_text(group_jid, "❌ La URL debe comenzar con `https://`.")
        return

    existing = (
        db.query(models.CalendarSubscription)
        .filter_by(ical_url=ical_url, whatsapp_group_id=group_jid)
        .first()
    )
    if existing:
        wa.send_text(group_jid, "⚠️ Este calendario ya está vinculado a este grupo.")
        return

    sub = models.CalendarSubscription(
        ical_url=ical_url,
        whatsapp_group_id=group_jid,
        label=label,
    )
    db.add(sub)
    db.commit()

    logger.info("CALENDAR subscribed group=%s label=%r", group_jid, label)
    wa.send_text(
        group_jid,
        "✅ Calendario vinculado a este grupo. Recibirán recordatorios según las "
        "notificaciones configuradas en Google Calendar.",
    )


def _handle_unsubscribe(group_jid: str, body: str, db, wa: WahaClient) -> None:
    parts = body.strip().split(None, 1)
    if len(parts) < 2:
        wa.send_text(group_jid, "Uso: `/unsubscribe_calendar <nombre_o_id>`")
        return

    identifier = parts[1].strip()

    # Try by numeric ID first, then by label
    sub = None
    if identifier.isdigit():
        sub = (
            db.query(models.CalendarSubscription)
            .filter_by(id=int(identifier), whatsapp_group_id=group_jid)
            .first()
        )
    if not sub:
        sub = (
            db.query(models.CalendarSubscription)
            .filter_by(label=identifier, whatsapp_group_id=group_jid)
            .first()
        )

    if not sub:
        wa.send_text(group_jid, f"❌ No se encontró el calendario `{identifier}` en este grupo.")
        return

    label_str = sub.label or f"ID {sub.id}"
    db.delete(sub)
    db.commit()
    logger.info("CALENDAR unsubscribed group=%s label=%r", group_jid, label_str)
    wa.send_text(group_jid, f"✅ Calendario *{label_str}* desvinculado.")


def _handle_list(group_jid: str, db, wa: WahaClient) -> None:
    subs = (
        db.query(models.CalendarSubscription)
        .filter_by(whatsapp_group_id=group_jid)
        .order_by(models.CalendarSubscription.id)
        .all()
    )
    if not subs:
        wa.send_text(group_jid, "📅 No hay calendarios vinculados a este grupo.")
        return

    lines = ["📅 *Calendarios vinculados:*\n"]
    for s in subs:
        label_str = s.label or "_(sin nombre)_"
        lines.append(f"  {s.id}. *{label_str}*")
    wa.send_text(group_jid, "\n".join(lines))
