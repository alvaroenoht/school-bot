"""Shared helpers for SEDUCA kiosk dashboard tokens.

Used by both the admin API (app/api/admin/dashboard.py) and the parent-facing
WhatsApp `dashboard` command (app/bot/webhook.py), so token shape and the
dashboard URL path stay in one place.

Tokens are hex (secrets.token_hex) rather than URL-safe base64 so they carry no
`_`/`-` characters that WhatsApp markdown could mangle when the link is DM'd.
"""
import secrets
from datetime import datetime, timedelta

from app.db import models

TOKEN_TTL_DAYS = 365   # long-lived kiosk token


def new_token() -> str:
    return secrets.token_hex(32)


def build_dashboard_path(token: str) -> str:
    return f"/api/admin/dashboard?token={token}"


def get_or_create_token(
    db,
    *,
    student_ids: list,
    created_by_jid: str,
    label: str | None = None,
    ttl_days: int = TOKEN_TTL_DAYS,
) -> models.DashboardToken:
    """Return this creator's existing active token for the same scope, or mint one.

    Idempotent per (created_by_jid, student_ids) so a parent who asks repeatedly
    keeps the same link (their iPad stays paired) instead of accumulating tokens.
    """
    now = datetime.utcnow()
    scope = student_ids or []

    existing = (
        db.query(models.DashboardToken)
        .filter(models.DashboardToken.created_by_jid == created_by_jid,
                models.DashboardToken.is_active == True)  # noqa: E712
        .order_by(models.DashboardToken.created_at.desc())
        .all()
    )
    for t in existing:
        if t.expires_at and t.expires_at < now:
            continue
        if (t.student_ids or []) == scope:
            return t

    tok = models.DashboardToken(
        token=new_token(),
        label=label,
        student_ids=scope,
        created_by_jid=created_by_jid,
        expires_at=None if ttl_days == 0 else now + timedelta(days=ttl_days),
    )
    db.add(tok)
    db.commit()
    db.refresh(tok)
    return tok
