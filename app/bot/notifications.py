"""
Audience notifications — sent to WhatsApp groups when fundraisers/forms are created.
"""
import logging
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()


def _get_group_ids(classroom_ids: list[int], db: Session) -> list[str]:
    """Return WhatsApp group IDs for the given classroom IDs."""
    group_ids = []
    for cid in classroom_ids:
        cls = db.query(models.Classroom).get(cid)
        if cls and cls.whatsapp_group_id:
            group_ids.append(cls.whatsapp_group_id)
    return group_ids


def notify_fundraiser_created(fundraiser: models.Fundraiser, db: Session):
    """Send notification to audience WA groups when a fundraiser is created."""
    group_ids = _get_group_ids(fundraiser.audience_classroom_ids or [], db)
    if not group_ids:
        return

    bot_phone = get_settings().waha_bot_phone
    wa_link = f"https://wa.me/{bot_phone}?text={quote(fundraiser.code)}"

    if fundraiser.type == "fixed" and fundraiser.fixed_amount:
        amount_line = f"\n💳 Monto: *${fundraiser.fixed_amount}*"
    else:
        amount_line = "\n🛒 Catálogo de productos"

    msg = (
        f"📢 *Nueva actividad: {fundraiser.friendly_name or fundraiser.name}*"
        f"{amount_line}\n\n"
        f"📲 Para pagar, escríbeme: *{fundraiser.code}*\n"
        f"O toca el enlace: {wa_link}"
    )

    for gid in group_ids:
        try:
            wa.send_text(gid, msg)
        except Exception as e:
            logger.warning("notify_fundraiser group=%s error: %s", gid, e)


def notify_form_created(form: models.Form, db: Session):
    """Send notification to audience WA groups when a form is opened."""
    audience_rows = db.query(models.FormAudience).filter_by(form_id=form.id).all()
    classroom_ids = [a.classroom_id for a in audience_rows]
    group_ids = _get_group_ids(classroom_ids, db)
    if not group_ids:
        return

    bot_phone = get_settings().waha_bot_phone
    wa_link = f"https://wa.me/{bot_phone}?text={quote(form.form_code)}"

    desc = f"\n_{form.description}_\n" if form.description else "\n"

    msg = (
        f"📢 *Nuevo formulario: {form.title}*"
        f"{desc}"
        f"📲 Para responder, escríbeme: *{form.form_code}*\n"
        f"O toca el enlace: {wa_link}"
    )

    for gid in group_ids:
        try:
            wa.send_text(gid, msg)
        except Exception as e:
            logger.warning("notify_form group=%s error: %s", gid, e)
