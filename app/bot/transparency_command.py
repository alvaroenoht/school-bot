"""
Parent-facing `reporte <CODE>` command.

Generates a transparency PDF for a group-fund fundraiser and sends it
to the requester via WhatsApp. Only works when:
  1. Fundraiser has mode="fund".
  2. fund.transparency_enabled is True.
  3. Sender belongs to at least one of the fundraiser's audience classrooms
     (known via KnownContactGroup + KnownContact.phone/jid bridge).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy.orm import Session

from app.db import models
from app.utils.transparency_report import build_transparency_pdf
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()


def _resolve_fund(code: str, db: Session) -> Optional[models.Fundraiser]:
    code = (code or "").strip().strip("*_~`").strip().upper()
    if not code:
        return None
    return (
        db.query(models.Fundraiser)
        .filter(models.Fundraiser.code.ilike(code))
        .first()
    )


def _sender_classroom_ids(raw_jid: str, from_phone: Optional[str], db: Session) -> set[int]:
    kcg_jids: set[str] = set()
    contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
    if not contact and from_phone:
        contact = db.query(models.KnownContact).filter_by(phone=from_phone).first()
    if contact:
        kcg_jids.add(contact.jid)

    # Also look up parent record (may be stored under @lid or @c.us)
    parent = db.query(models.Parent).filter_by(whatsapp_jid=raw_jid).first()
    if not parent and from_phone:
        parent = db.query(models.Parent).filter_by(whatsapp_jid=f"{from_phone}@c.us").first()

    classroom_ids: set[int] = set()
    if kcg_jids:
        rows = (
            db.query(models.KnownContactGroup)
            .filter(
                models.KnownContactGroup.contact_jid.in_(kcg_jids),
                models.KnownContactGroup.active == True,
            )
            .all()
        )
        for row in rows:
            if row.classroom_id:
                classroom_ids.add(row.classroom_id)

    if parent:
        students = db.query(models.Student).filter_by(parent_id=parent.id).all()
        for s in students:
            if s.classroom_id:
                classroom_ids.add(s.classroom_id)

    return classroom_ids


def is_reporte_command(text: str) -> bool:
    t = (text or "").strip().lstrip("/").lower()
    return t == "reporte" or t.startswith("reporte ")


async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    from_phone: Optional[str],
    db: Session,
) -> None:
    """Respond to a `reporte <CODE>` DM.
    Sends a prompt for a missing code, a polite refusal on gate failure,
    or the PDF itself on success.
    """
    args = text.strip().lstrip("/").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        wa.send_text(
            chat_id,
            "📊 *Reporte de transparencia*\n\n"
            "Usa: `reporte <CÓDIGO>`\n"
            "Ejemplo: `reporte FONDO2026`\n\n"
            "Solo funciona para fondos con transparencia publicada.",
        )
        return

    fund = _resolve_fund(args[1], db)
    if not fund or fund.mode != "fund":
        wa.send_text(chat_id, "❌ No encontré ese fondo. Verifica el código.")
        return
    if not fund.transparency_enabled:
        wa.send_text(
            chat_id,
            "🔒 Este fondo no tiene transparencia publicada todavía.\n"
            "El delegado debe activarla en el panel.",
        )
        return

    audience = set(fund.audience_classroom_ids or [])
    sender_classrooms = _sender_classroom_ids(raw_jid, from_phone, db)
    if audience and not (audience & sender_classrooms):
        wa.send_text(
            chat_id,
            "❌ Este reporte es solo para los salones vinculados al fondo.",
        )
        return

    wa.send_text(chat_id, "📊 Generando reporte de transparencia…")

    try:
        pdf_path = build_transparency_pdf(fund, db)
    except Exception:
        logger.exception("Failed to build transparency PDF for fundraiser %s", fund.id)
        wa.send_text(chat_id, "⚠️ No pude generar el reporte. Intenta más tarde.")
        return

    try:
        caption = f"📊 *{fund.name}* — Reporte de transparencia"
        wa.send_document(chat_id, pdf_path, caption=caption)
    except Exception:
        logger.exception("Failed to send transparency PDF to %s", chat_id)
        wa.send_text(chat_id, "⚠️ No pude enviar el PDF. Intenta de nuevo.")
    finally:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass
