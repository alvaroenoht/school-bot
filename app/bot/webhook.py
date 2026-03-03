"""
FastAPI webhook endpoint — receives all incoming WhatsApp messages from waha.

DM routing:
  1. Admin JID (resolved phone == ADMIN_PHONE) → admin commands
  2. Active registration session for this JID   → continue registration
  3. Registered active parent (by whatsapp_jid) → Q&A
  4. Message is a valid invite code             → start registration
  5. Everything else                            → silently ignored

Group routing:
  - vincular <id>    → link group to classroom (registered parent only, no @mention needed)
  - @mention of bot  → Q&A scoped to the classroom linked to THIS group
  - anything else    → silently ignored
  - unlinked group   → silently ignored

The bot is fully silent to anyone it doesn't know.
The ONLY way an unknown person can trigger a response is by sending a valid invite code.
"""
import logging

from fastapi import APIRouter, Request

from app.bot import admin_commands, qa_handler, registration
from app.config import get_settings
from app.db.database import SessionLocal
from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_group(chat_id: str) -> bool:
    return "@g.us" in chat_id


def _is_mentioned(payload: dict, bot_phone: str) -> bool:
    mentions = payload.get("mentionedIds") or []
    return any(bot_phone in str(m) for m in mentions)


def _strip_mention(text: str, bot_phone: str) -> str:
    return text.replace(f"@{bot_phone}", "").strip()


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    body = await request.json()
    settings = get_settings()

    logger.info(f"WEBHOOK BODY: {body}")

    if body.get("event") != "message":
        logger.info(f"IGNORED EVENT: {body.get('event')}")
        return {"status": "ignored"}

    payload = body.get("payload", {})
    chat_id: str = payload.get("from", "")
    raw_text: str = (payload.get("body") or "").strip()
    message_id: str = payload.get("id", "")

    # raw_jid = sender's WhatsApp JID (participant in groups, "from" in DMs)
    raw_jid: str = payload.get("participant") if _is_group(chat_id) else chat_id
    if not raw_jid:
        return {"status": "ignored"}

    wa = WahaClient()
    from_phone = wa.resolve_phone(raw_jid)
    logger.info(f"Resolved sender: {raw_jid} → {from_phone}")

    db = SessionLocal()
    try:
        # ══════════════════════════════════════════════════════════════════════
        # GROUP MESSAGES
        # ══════════════════════════════════════════════════════════════════════
        if _is_group(chat_id):

            # vincular <id> — no @mention needed, but sender must be a registered parent
            if raw_text.lower().startswith("vincular "):
                _handle_vincular(raw_jid, chat_id, raw_text, db, wa)
                return {"status": "ok"}

            # All other group messages require @mention
            if not _is_mentioned(payload, settings.waha_bot_phone):
                return {"status": "ignored"}

            clean_text = _strip_mention(raw_text, settings.waha_bot_phone).strip()
            if not clean_text:
                return {"status": "ok"}

            # Q&A scoped to the classroom linked to THIS group — any member can ask
            classroom = (
                db.query(models.Classroom)
                .filter_by(whatsapp_group_id=chat_id, is_active=True)
                .first()
            )
            if not classroom:
                # Group not linked — silently ignore (don't reveal the bot is here)
                return {"status": "ignored"}

            parent = db.query(models.Parent).filter_by(
                classroom_id=classroom.id, is_active=True
            ).first()
            if parent:
                await qa_handler.handle(raw_jid, chat_id, clean_text, db, parent)
            return {"status": "ok"}

        # ══════════════════════════════════════════════════════════════════════
        # DIRECT MESSAGES
        # ══════════════════════════════════════════════════════════════════════

        if not raw_text:
            return {"status": "ok"}

        # 1. Admin — matched by resolved phone
        if from_phone == settings.admin_phone:
            handled = await admin_commands.handle(from_phone, chat_id, raw_text, db)
            if handled:
                return {"status": "ok"}

        # 2. Active registration session for this JID — keep going
        reg_session = (
            db.query(models.RegistrationSession).filter_by(chat_jid=raw_jid).first()
        )
        if reg_session:
            await registration.handle(raw_jid, chat_id, raw_text, db, reg_session, message_id=message_id)
            return {"status": "ok"}

        # 3. Registered active parent — Q&A
        parent = db.query(models.Parent).filter_by(
            whatsapp_jid=raw_jid, is_active=True
        ).first()
        if parent and parent.classroom_id:
            await qa_handler.handle(raw_jid, chat_id, raw_text, db, parent)
            return {"status": "ok"}

        # 4. Unknown sender — only respond if they sent a valid invite code
        code = raw_text.strip().upper()
        invite = db.query(models.InviteCode).filter_by(code=code, status="active").first()
        if invite:
            await registration.handle(raw_jid, chat_id, raw_text, db, None, invite=invite, message_id=message_id)
            return {"status": "ok"}

        # 5. Unknown sender, no valid code → silently ignore
        logger.debug(f"Ignoring DM from unknown JID {raw_jid} (no valid code)")
        return {"status": "ignored"}

    except Exception as e:
        logger.exception(f"Unhandled error processing message from {raw_jid}: {e}")
        return {"status": "error"}
    finally:
        db.close()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _handle_vincular(raw_jid: str, chat_id: str, text: str, db, wa: WahaClient):
    """Link a WhatsApp group to a classroom. Sender must be a registered parent."""
    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        wa.send_text(chat_id, "Uso: `vincular <id_del_salón>`, ej: `vincular 3`")
        return

    classroom_id = int(parts[1])
    parent = db.query(models.Parent).filter_by(
        whatsapp_jid=raw_jid, is_active=True
    ).first()

    if not parent:
        # Sender is not a registered parent — silently ignore
        return

    if parent.classroom_id != classroom_id:
        wa.send_text(chat_id, f"❌ El salón `{classroom_id}` no corresponde a tu registro.")
        return

    classroom = db.query(models.Classroom).get(classroom_id)
    classroom.whatsapp_group_id = chat_id
    db.commit()

    wa.send_text(
        chat_id,
        f"✅ Grupo vinculado al salón *{classroom.name}*.\n\n"
        "Cualquier miembro puede mencionarme con *@Asistente Seduca* "
        "para consultar actividades. 📚",
    )
