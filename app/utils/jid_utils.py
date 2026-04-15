"""
Shared matcher for Parent rows keyed by WhatsApp JID.

WAHA delivers the same sender as {phone}@c.us or {lidnum}@lid depending on
session/contact state. Parent.whatsapp_jid is stored raw at registration, so
a drift between formats leaves the parent unrecognised unless every lookup
tries both equivalents.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.whatsapp.client import WahaClient


def _looks_like_phone(s: str | None) -> bool:
    return bool(s) and s.isdigit() and 8 <= len(s) <= 15


def _safe_phone(raw_jid: str, wa: WahaClient | None) -> str | None:
    if "@c.us" in raw_jid:
        p = raw_jid.split("@", 1)[0].lstrip("+")
        return p if _looks_like_phone(p) else None
    if "@lid" in raw_jid:
        if wa is None:
            return None
        p = wa.resolve_phone(raw_jid)
        return p if _looks_like_phone(p) else None
    return None


def find_parent_by_jid(
    db: Session,
    raw_jid: str,
    wa: WahaClient | None = None,
    *,
    require_active: bool = True,
) -> models.Parent | None:
    q = db.query(models.Parent)
    if require_active:
        q = q.filter(models.Parent.is_active == True)

    hit = q.filter(models.Parent.whatsapp_jid == raw_jid).first()
    if hit:
        return hit

    phone = _safe_phone(raw_jid, wa)
    if not phone:
        return None

    # @lid-input → @c.us stored: alt is direct (we have the phone).
    # @c.us-input → @lid stored: the lid is an opaque WAHA identifier, not
    # derivable from the phone. Bridge via KnownContact.phone → kc.jid.
    if "@lid" in raw_jid:
        alt_hit = q.filter(models.Parent.whatsapp_jid == f"{phone}@c.us").first()
        if alt_hit:
            return alt_hit

    kc = (
        db.query(models.KnownContact)
        .filter(models.KnownContact.phone == phone)
        .filter(models.KnownContact.jid != raw_jid)
        .first()
    )
    if kc:
        return q.filter(models.Parent.whatsapp_jid == kc.jid).first()
    return None
