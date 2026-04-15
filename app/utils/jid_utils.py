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


def safe_phone(raw_jid: str, wa: WahaClient | None) -> str | None:
    if "@c.us" in raw_jid:
        p = raw_jid.split("@", 1)[0].lstrip("+")
        return p if _looks_like_phone(p) else None
    if "@lid" in raw_jid:
        if wa is None:
            return None
        p = wa.resolve_phone(raw_jid)
        return p if _looks_like_phone(p) else None
    return None


def canonicalize_jid(raw_jid: str, wa: WahaClient | None) -> str:
    """Return {phone}@c.us when the phone can be resolved safely, else raw_jid.

    Used at insert time so new Parent rows land on a stable identity; existing
    bot callers still reach them via find_parent_by_jid's exact-match step.
    """
    phone = safe_phone(raw_jid, wa)
    return f"{phone}@c.us" if phone else raw_jid


def find_parent_by_jid(
    db: Session,
    raw_jid: str,
    wa: WahaClient | None = None,
    *,
    require_active: bool = True,
) -> models.Parent | None:
    """Resolve a Parent across WAHA @c.us ↔ @lid drift.

    Gathers every candidate that could plausibly be the same parent (exact
    raw_jid, phone-equivalent @c.us when input is @lid, and the KnownContact
    phone bridge) and prefers the one with the most state: credentials first,
    then largest student_ids. This makes already-split databases converge on
    the keeper row instead of whichever format arrived first.
    """
    q = db.query(models.Parent)
    if require_active:
        q = q.filter(models.Parent.is_active == True)

    candidates: list[models.Parent] = []

    def _add(p: models.Parent | None) -> None:
        if p is not None and all(p.id != c.id for c in candidates):
            candidates.append(p)

    _add(q.filter(models.Parent.whatsapp_jid == raw_jid).first())

    phone = safe_phone(raw_jid, wa)
    if phone:
        # @lid-input → @c.us stored: alt is direct.
        # @c.us-input → @lid stored: the lid is opaque WAHA state not derivable
        # from the phone, so we bridge through KnownContact.phone instead.
        if "@lid" in raw_jid:
            _add(q.filter(models.Parent.whatsapp_jid == f"{phone}@c.us").first())

        kc_match: models.Parent | None = None
        kc = (
            db.query(models.KnownContact)
            .filter(models.KnownContact.phone == phone)
            .filter(models.KnownContact.jid != raw_jid)
            .first()
        )
        if kc:
            kc_match = q.filter(models.Parent.whatsapp_jid == kc.jid).first()
            if kc_match:
                _add(kc_match)

        # Last-resort reverse lookup for @c.us → stored @lid when the KC
        # bridge is absent. The lid is opaque WAHA state, so we enumerate
        # @lid parents and resolve_phone each. Bounded by @lid-parent count
        # (small) and skipped entirely for @lid inputs (already covered by
        # the direct @c.us swap above).
        if "@c.us" in raw_jid and not kc_match and wa is not None:
            lid_parents = q.filter(models.Parent.whatsapp_jid.like("%@lid")).all()
            for p in lid_parents:
                if safe_phone(p.whatsapp_jid, wa) == phone:
                    _add(p)
                    break

    if not candidates:
        return None

    def _score(p: models.Parent) -> tuple[int, int]:
        has_creds = 1 if p.encrypted_username else 0
        n_students = len(p.student_ids or [])
        return (has_creds, n_students)

    candidates.sort(key=_score, reverse=True)
    return candidates[0]
