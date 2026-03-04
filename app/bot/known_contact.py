"""
Known Contact identification flow.

Triggered when an unknown sender DMs the bot and is verified as a member
of at least one linked WhatsApp group.  Captures name + child name, then
saves a lightweight KnownContact record.

If the sender's first message was a "pay" command, it is stored in
session.data["pending_command"] and resumed after identification.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

_WELCOME = (
    "\U0001f44b \u00a1Hola! Te detect\u00e9 como miembro de un grupo escolar.\n\n"
    "Para continuar necesito algunos datos.\n"
    "\u00bfCu\u00e1l es tu *nombre completo*?"
)


async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    session: models.ConversationSession | None,
    source_group_id: str | None = None,
    pending_command: str | None = None,
):
    """Drive the known-contact identification state machine."""

    # ── Start new session ─────────────────────────────────────────────────
    if session is None:
        session = models.ConversationSession(
            chat_jid=raw_jid,
            flow="known_contact",
            step="awaiting_name",
            data={
                "source_group_id": source_group_id,
                "pending_command": pending_command,
            },
        )
        db.add(session)
        db.commit()
        wa.send_text(chat_id, _WELCOME)
        return

    data: dict = session.data or {}

    # ── awaiting_name ─────────────────────────────────────────────────────
    if session.step == "awaiting_name":
        data["name"] = text.strip()
        _advance(session, "awaiting_child_name", data, db)
        wa.send_text(
            chat_id,
            f"Gracias, *{data['name']}*.\n\n"
            "\u00bfCu\u00e1l es el nombre de tu *hijo/a*?",
        )

    # ── awaiting_child_name ───────────────────────────────────────────────
    elif session.step == "awaiting_child_name":
        data["child_name"] = text.strip()

        # Save KnownContact
        contact = models.KnownContact(
            jid=raw_jid,
            name=data["name"],
            child_name=data["child_name"],
            source_group_id=data.get("source_group_id"),
        )
        db.add(contact)

        pending = data.get("pending_command")
        db.delete(session)
        db.commit()

        wa.send_text(
            chat_id,
            f"\u2705 \u00a1Listo, *{data['name']}*! Quedaste registrado/a.\n\n"
            "Ahora puedes usar el comando `pagar <nombre>` "
            "para pagar actividades escolares.",
        )

        # Resume pending command if any (e.g. "pay Kermesse")
        if pending:
            from app.bot import payment_flow
            await payment_flow.start_from_command(
                raw_jid, chat_id, pending, db, contact,
            )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()
