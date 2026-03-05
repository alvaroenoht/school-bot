"""
FastAPI webhook endpoint — receives all incoming WhatsApp messages from waha.

DM routing (evaluated in order, first match wins):
  1. Admin JID (resolved phone == ADMIN_PHONE)      → admin commands
  2. Active ConversationSession for this JID         → route by flow
  3. Active RegistrationSession for this JID         → continue registration
  4. Registered active parent  (by whatsapp_jid)     → "pay/pagar" → payment flow, else Q&A
  5. Known contact             (by jid)              → "pay/pagar" → payment flow
  6. Message is a valid invite code                  → start registration
  7. Unknown sender in a linked group                → start known-contact flow
  8. Everything else                                 → silently ignored

Group routing:
  - vincular <id>    → link group to classroom (registered parent only)
  - @mention of bot  → Q&A scoped to the classroom linked to THIS group
  - anything else    → silently ignored

Image handling:
  - Images are routed to ConversationSession if the active step expects media.
"""
import logging

from fastapi import APIRouter, Request

from app.bot import admin_commands, qa_handler, registration, intent_agent
from app.bot import known_contact, fundraiser_admin, payment_flow
from app.config import get_settings
from app.db.database import SessionLocal
from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
router = APIRouter()


def _is_group(chat_id: str) -> bool:
    return "@g.us" in chat_id


def _is_mentioned(payload: dict, bot_phone: str) -> bool:
    # 1. Standard mentionedIds field
    mentions = payload.get("mentionedIds") or []
    if any(bot_phone in str(m) for m in mentions):
        return True

    # 2. WAHA _data.mentionedJidList (webjs engine)
    jid_list = payload.get("_data", {}).get("mentionedJidList") or []
    if any(bot_phone in str(j) for j in jid_list):
        return True

    # 3. Fallback: body contains @<lid_number> — resolve to phone
    import re
    body = payload.get("body") or ""
    at_ids = re.findall(r"@(\d{10,})", body)
    if at_ids:
        wa = WahaClient()
        for lid_num in at_ids:
            phone = wa.resolve_phone(f"{lid_num}@lid")
            if phone == bot_phone:
                return True

    return False


def _strip_mention(text: str, bot_phone: str) -> str:
    import re
    # Remove @<digits> mentions (handles both @phone and @lid formats)
    return re.sub(r"@\d{10,}", "", text).strip()


def _is_pay_command(text: str) -> bool:
    t = text.lstrip("/").lower()
    return t.startswith(("pay ", "pagar "))


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    body = await request.json()
    settings = get_settings()

    logger.info(
        "WEBHOOK event=%s from=%s to=%s type=%s hasMedia=%s bodyLen=%s",
        body.get("event"),
        body.get("payload", {}).get("participant") or body.get("payload", {}).get("from"),
        body.get("payload", {}).get("to"),
        body.get("payload", {}).get("type"),
        body.get("payload", {}).get("hasMedia"),
        len(body.get("payload", {}).get("body") or ""),
    )

    if body.get("event") != "message":
        logger.info(f"IGNORED EVENT: {body.get('event')}")
        return {"status": "ignored"}

    payload = body.get("payload", {})

    # Ignore messages sent by the bot itself (prevents echo loops)
    if payload.get("fromMe", False):
        return {"status": "ignored"}
    chat_id: str = payload.get("from", "")
    raw_text: str = (payload.get("body") or "").strip()
    message_id: str = payload.get("id", "")
    has_media: bool = payload.get("hasMedia", False)
    media_type: str = payload.get("type") or payload.get("_data", {}).get("type") or ""
    if has_media:
        logger.info("MEDIA_DEBUG type=%s media=%s", media_type, payload.get("media"))

    # raw_jid = sender's WhatsApp JID (participant in groups, "from" in DMs)
    raw_jid: str = payload.get("participant") if _is_group(chat_id) else chat_id
    if not raw_jid:
        return {"status": "ignored"}

    wa = WahaClient()
    from_phone = wa.resolve_phone(raw_jid)
    logger.info("ROUTE from=%s phone=%s group=%s", raw_jid, from_phone, _is_group(chat_id))

    db = SessionLocal()
    try:
        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
        # GROUP MESSAGES
        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
        if _is_group(chat_id):

            # vincular <id> \u2014 no @mention needed, sender must be registered parent
            if raw_text.lstrip("/").lower().startswith("vincular "):
                _handle_vincular(raw_jid, chat_id, raw_text.lstrip("/"), db, wa)
                return {"status": "ok"}

            # All other group messages require @mention
            logger.info(
                "GROUP_DEBUG bot_phone=%s mentionedIds=%s body=%s",
                settings.waha_bot_phone,
                payload.get("mentionedIds"),
                raw_text[:80],
            )
            if not _is_mentioned(payload, settings.waha_bot_phone):
                return {"status": "ignored"}

            clean_text = _strip_mention(raw_text, settings.waha_bot_phone).strip()
            if not clean_text:
                return {"status": "ok"}

            # Q&A scoped to the classroom linked to THIS group
            classroom = (
                db.query(models.Classroom)
                .filter_by(whatsapp_group_id=chat_id, is_active=True)
                .first()
            )
            if not classroom:
                return {"status": "ignored"}

            # Find parent via student linked to this classroom
            student = db.query(models.Student).filter_by(
                classroom_id=classroom.id
            ).first()
            parent = (
                db.query(models.Parent).get(student.parent_id)
                if student else None
            )
            if parent:
                await intent_agent.handle(raw_jid, chat_id, clean_text, db, parent)
            return {"status": "ok"}

        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
        # DIRECT MESSAGES
        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

        # Accept text OR image messages for DM routing
        if not raw_text and not has_media:
            return {"status": "ok"}

        # 1. Admin \u2014 matched by resolved phone
        if from_phone == settings.admin_phone:
            # Check for active fundraiser creation conversation
            conv = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
            if conv and conv.flow == "fundraiser_create":
                await fundraiser_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv)
                return {"status": "ok"}
            handled = await admin_commands.handle(from_phone, chat_id, raw_text, db)  # / stripped inside handle()
            if handled:
                return {"status": "ok"}

        # 2. Active ConversationSession \u2014 route by flow
        conv_session = (
            db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
        )
        if conv_session:
            if conv_session.flow == "known_contact":
                await known_contact.handle(raw_jid, chat_id, raw_text, db, conv_session)
            elif conv_session.flow == "fundraiser_create":
                await fundraiser_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv_session)
            elif conv_session.flow == "payment":
                await payment_flow.handle(
                    raw_jid, chat_id, raw_text, db, conv_session, payload=payload,
                )
            return {"status": "ok"}

        # 3. Active RegistrationSession \u2014 keep going
        reg_session = (
            db.query(models.RegistrationSession).filter_by(chat_jid=raw_jid).first()
        )
        if reg_session:
            await registration.handle(
                raw_jid, chat_id, raw_text, db, reg_session, message_id=message_id,
            )
            return {"status": "ok"}

        # 4. Registered active parent \u2014 "pay/pagar" or Q&A
        parent = db.query(models.Parent).filter_by(
            whatsapp_jid=raw_jid, is_active=True
        ).first()
        if parent:
            if _is_pay_command(raw_text):
                await payment_flow.start_from_command(raw_jid, chat_id, raw_text, db, parent)
            else:
                await intent_agent.handle(
                    raw_jid, chat_id, raw_text, db, parent,
                    is_admin=(from_phone == settings.admin_phone),
                    has_media=has_media, media_type=media_type,
                    message_id=message_id, payload=payload,
                )
            return {"status": "ok"}

        # 5. Known contact \u2014 "pay/pagar" or brief help
        contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
        if contact:
            if _is_pay_command(raw_text):
                await payment_flow.start_from_command(raw_jid, chat_id, raw_text, db, contact)
            else:
                await intent_agent.handle(
                    raw_jid, chat_id, raw_text, db, contact,
                    has_media=has_media, media_type=media_type,
                    message_id=message_id, payload=payload,
                )
            return {"status": "ok"}

        # 6. Unknown sender \u2014 valid invite code?
        if raw_text:
            code = raw_text.strip().upper()
            invite = db.query(models.InviteCode).filter_by(code=code, status="active").first()
            if invite:
                await registration.handle(
                    raw_jid, chat_id, raw_text, db, None, invite=invite, message_id=message_id,
                )
                return {"status": "ok"}

        # 7. Unknown sender \u2014 check group membership
        group_id = _check_group_membership(raw_jid, db, wa)
        if group_id:
            pending = raw_text if _is_pay_command(raw_text) else None
            await known_contact.handle(
                raw_jid, chat_id, raw_text, db, None,
                source_group_id=group_id, pending_command=pending,
            )
            return {"status": "ok"}

        # 8. Unknown sender, not in any group \u2192 silently ignore
        logger.debug(f"Ignoring DM from unknown JID {raw_jid}")
        return {"status": "ignored"}

    except Exception as e:
        logger.exception(f"Unhandled error processing message from {raw_jid}: {e}")
        return {"status": "error"}
    finally:
        db.close()


# \u2500\u2500 Helpers \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

def _handle_vincular(raw_jid: str, chat_id: str, text: str, db, wa: WahaClient):
    """Link a WhatsApp group to a classroom. Sender must be a registered parent."""
    parts = text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        wa.send_text(chat_id, "Uso: `vincular <id_del_sal\u00f3n>`, ej: `vincular 3`")
        return

    classroom_id = int(parts[1])
    parent = db.query(models.Parent).filter_by(
        whatsapp_jid=raw_jid, is_active=True
    ).first()

    if not parent:
        return

    # Check classroom belongs to one of the parent's students
    student = db.query(models.Student).filter_by(
        classroom_id=classroom_id, parent_id=parent.id
    ).first()
    if not student:
        wa.send_text(chat_id, f"\u274c El sal\u00f3n `{classroom_id}` no corresponde a tu registro.")
        return

    classroom = db.query(models.Classroom).get(classroom_id)
    classroom.whatsapp_group_id = chat_id
    db.commit()

    wa.send_text(
        chat_id,
        f"\u2705 Grupo vinculado al sal\u00f3n *{classroom.name}*.\n\n"
        "Cualquier miembro puede mencionarme con *@Asistente Seduca* "
        "para consultar actividades. \U0001f4da",
    )


def _check_group_membership(raw_jid: str, db, wa: WahaClient) -> str | None:
    """Check if JID is a participant in any linked WhatsApp group. Returns group_id or None."""
    classrooms = db.query(models.Classroom).filter(
        models.Classroom.whatsapp_group_id.isnot(None),
        models.Classroom.is_active == True,
    ).all()

    for classroom in classrooms:
        try:
            participants = wa.get_group_participants(classroom.whatsapp_group_id)
            if raw_jid in participants:
                return classroom.whatsapp_group_id
        except Exception as e:
            logger.warning(f"Could not check participants for group {classroom.whatsapp_group_id}: {e}")
    return None
