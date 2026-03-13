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
from datetime import datetime, timedelta

from fastapi import APIRouter, Request

from app.bot import admin_commands, qa_handler, registration, intent_agent
from app.bot import known_contact, fundraiser_admin, payment_flow, form_admin, form_flow
from app.config import get_settings
from app.db.database import SessionLocal
from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
router = APIRouter()

# Per-group cooldown for /resumen — prevents duplicate sends when multiple admins invoke it
_resumen_last_sent: dict[str, datetime] = {}
_RESUMEN_COOLDOWN = timedelta(minutes=30)


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

            # All other group messages require @mention or quoting a bot message
            _data = payload.get("_data", {})
            quoted_fields = {k: v for k, v in _data.items() if "quot" in k.lower()}
            logger.info(
                "GROUP_DEBUG bot_phone=%s mentionedIds=%s quoted=%s body=%s",
                settings.waha_bot_phone,
                payload.get("mentionedIds"),
                {k: (str(v)[:60] if not isinstance(v, (bool, int, type(None))) else v)
                 for k, v in quoted_fields.items()} if quoted_fields else None,
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

            # /resumen in group — super admin or registered parent with a student in this classroom
            if clean_text.lstrip("/").lower().startswith("resumen"):
                is_super_admin = from_phone == settings.admin_phone
                authorized = is_super_admin
                if not authorized:
                    invoker = db.query(models.Parent).filter_by(
                        whatsapp_jid=raw_jid, is_active=True
                    ).first()
                    if invoker and invoker.student_ids:
                        authorized = db.query(models.Student).filter(
                            models.Student.id.in_(invoker.student_ids),
                            models.Student.classroom_id == classroom.id,
                        ).first() is not None
                if authorized:
                    last = _resumen_last_sent.get(chat_id)
                    if last and (datetime.utcnow() - last) < _RESUMEN_COOLDOWN:
                        wa.send_text(chat_id, "📋 El resumen ya fue enviado recientemente.")
                    else:
                        _resumen_last_sent[chat_id] = datetime.utcnow()
                        # One student is enough — all students in the same classroom share assignments
                        student = db.query(models.Student).filter_by(classroom_id=classroom.id).first()
                        if student:
                            from types import SimpleNamespace
                            await _handle_parent_resumen(
                                SimpleNamespace(student_ids=[student.id]), chat_id, db
                            )
                else:
                    wa.send_text(chat_id, "⛔ Solo los administradores del salón pueden usar este comando.")
                return {"status": "ok"}

            # Identify the actual sender first (parent or known contact)
            sender = db.query(models.Parent).filter_by(
                whatsapp_jid=raw_jid, is_active=True
            ).first()
            if not sender:
                sender = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
            if sender:
                await intent_agent.handle(raw_jid, chat_id, clean_text, db, sender)
            return {"status": "ok"}

        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550
        # DIRECT MESSAGES
        # \u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550

        # Accept text OR image messages for DM routing
        if not raw_text and not has_media:
            return {"status": "ok"}

        # /form join <code> — universal, handled before any role check
        if raw_text.strip().lstrip("/").lower().startswith("form join "):
            await form_admin.handle_join(raw_jid, chat_id, raw_text, db)
            return {"status": "ok"}

        # Maintenance message — shown to all non-admin DM senders
        if from_phone != settings.admin_phone:
            bot_status = db.query(models.BotStatus).first()
            if bot_status and bot_status.maintenance_msg:
                wa.send_text(chat_id, f"🟡 {bot_status.maintenance_msg}")
                return {"status": "ok"}

        # 1. Admin \u2014 matched by resolved phone
        if from_phone == settings.admin_phone:
            # Check for active fundraiser creation conversation
            conv = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
            if conv and conv.flow == "fundraiser_create":
                await fundraiser_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv)
                return {"status": "ok"}
            if conv and conv.flow in ("form_create", "form_addq", "form_editq"):
                await form_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv)
                return {"status": "ok"}
            handled = await admin_commands.handle(from_phone, chat_id, raw_text, db)  # / stripped inside handle()
            if handled:
                return {"status": "ok"}

        # 1.5. Form reader — /form list and /form results only
        if raw_text.strip().lstrip("/").lower().startswith("form"):
            reader = db.query(models.FormReader).filter(
                models.FormReader.jid == raw_jid,
                models.FormReader.jid.isnot(None),
            ).first()
            if reader:
                await form_admin.handle_reader_command(raw_jid, chat_id, raw_text, db)
                return {"status": "ok"}

        # 2. Active ConversationSession \u2014 route by flow
        conv_session = (
            db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
        )
        # Expire stale payment sessions after 4 hours of inactivity
        if conv_session and conv_session.flow == "payment":
            if conv_session.updated_at and (datetime.utcnow() - conv_session.updated_at) > timedelta(hours=4):
                db.delete(conv_session)
                db.commit()
                conv_session = None
        if conv_session:
            if conv_session.flow == "known_contact":
                await known_contact.handle(raw_jid, chat_id, raw_text, db, conv_session)
            elif conv_session.flow == "fundraiser_create":
                await fundraiser_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv_session)
            elif conv_session.flow in ("form_create", "form_addq", "form_editq"):
                await form_admin.handle_conversation(raw_jid, chat_id, raw_text, db, conv_session)
            elif conv_session.flow == "form_respond":
                await form_flow.handle(raw_jid, chat_id, raw_text, db, conv_session)
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

        # 4. Registered active parent \u2014 commands, "pay/pagar", or Q&A
        parent = db.query(models.Parent).filter_by(
            whatsapp_jid=raw_jid, is_active=True
        ).first()
        if parent:
            # \u2500\u2500 Parent slash commands (before LLM routing) \u2500\u2500
            cmd = raw_text.strip().lstrip("/").lower()
            if cmd in ("help", "ayuda"):
                wa.send_text(chat_id, _PARENT_HELP)
                return {"status": "ok"}
            if cmd.startswith("resumen"):
                await _handle_parent_resumen(parent, chat_id, db)
                return {"status": "ok"}
            if cmd.startswith("fundraiser") or cmd.startswith("actividad"):
                await fundraiser_admin.handle_command(raw_jid, chat_id, raw_text, db, caller_parent=parent)
                return {"status": "ok"}

            if cmd in ("mis pagos", "pagos", "mispagos", "my payments"):
                await _handle_parent_payments(parent, chat_id, db)
                return {"status": "ok"}

            if cmd.startswith("form"):
                await form_admin.handle_command(raw_jid, chat_id, raw_text, db, caller_parent=parent)
                return {"status": "ok"}

            if raw_text and raw_text.strip().upper().startswith("FORM-"):
                await form_flow.start_from_code(raw_jid, chat_id, raw_text.strip(), db)
                return {"status": "ok"}

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

        # 5. Known contact \u2014 FORM code, "pay/pagar", or brief help
        contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
        if contact:
            if raw_text and raw_text.strip().upper().startswith("FORM-"):
                await form_flow.start_from_code(raw_jid, chat_id, raw_text.strip(), db)
                return {"status": "ok"}
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

            # FORM-XXXXX from unregistered user — check group membership first
            if code.startswith("FORM-"):
                form = db.query(models.Form).filter_by(form_code=code, status="open").first()
                if form:
                    # Check if sender is in a group that belongs to the form's audience
                    audience_cls_ids = [
                        a.classroom_id for a in
                        db.query(models.FormAudience).filter_by(form_id=form.id).all()
                    ]
                    sender_phone = wa.resolve_phone(raw_jid)
                    sender_c_us = f"{sender_phone}@c.us"
                    form_group_id = None
                    for cid in audience_cls_ids:
                        cls = db.query(models.Classroom).get(cid)
                        if cls and cls.whatsapp_group_id:
                            try:
                                parts = wa.get_group_participants(cls.whatsapp_group_id)
                                if raw_jid in parts or sender_c_us in parts:
                                    form_group_id = cls.whatsapp_group_id
                                    break
                            except Exception:
                                pass
                    if form_group_id:
                        # In audience group — identify them first, then resume form
                        await known_contact.handle(
                            raw_jid, chat_id, raw_text, db, None,
                            source_group_id=form_group_id, pending_command=code,
                        )
                    else:
                        wa.send_text(
                            chat_id,
                            f"Para responder el formulario *{form.title}* necesitas estar registrado.\n"
                            "Solicita un código de invitación al administrador.",
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

    # Check classroom belongs to one of the parent's students (supports multiple parents)
    student = db.query(models.Student).filter(
        models.Student.classroom_id == classroom_id,
        models.Student.id.in_(parent.student_ids or []),
    ).first()
    if not student:
        wa.send_text(chat_id, f"\u274c El sal\u00f3n `{classroom_id}` no corresponde a tu registro.")
        return

    classroom = db.query(models.Classroom).get(classroom_id)
    classroom.whatsapp_group_id = chat_id
    db.commit()

    wa.send_text(
        chat_id,
        f"\u2705 *\u00a1Grupo vinculado al sal\u00f3n {classroom.name}!*\n\n"
        "\U0001f4da *\u00bfQu\u00e9 puedo hacer?*\n"
        "  \u2022 Responder preguntas sobre tareas y actividades\n"
        "  \u2022 Enviar res\u00famenes semanales autom\u00e1ticos\n"
        "  \u2022 Procesar pagos de actividades escolares\n\n"
        "Menci\u00f3name con *@Asistente Seduca* para consultarme.\n\n"
        "\u26a0\ufe0f *Aviso:* Este asistente es un proyecto *independiente*. "
        "*No es una aplicaci\u00f3n oficial* del colegio ni de Seduca/GSEpty.\n"
        "Preguntas o soporte: *67815352*",
    )


def _check_group_membership(raw_jid: str, db, wa: WahaClient) -> str | None:
    """Check if JID is a participant in any linked WhatsApp group. Returns group_id or None."""
    classrooms = db.query(models.Classroom).filter(
        models.Classroom.whatsapp_group_id.isnot(None),
        models.Classroom.is_active == True,
    ).all()

    # Resolve @lid to phone so we can compare with @c.us participants
    sender_phone = wa.resolve_phone(raw_jid)
    sender_c_us = f"{sender_phone}@c.us"

    for classroom in classrooms:
        try:
            participants = wa.get_group_participants(classroom.whatsapp_group_id)
            if raw_jid in participants or sender_c_us in participants:
                return classroom.whatsapp_group_id
        except Exception as e:
            logger.warning(f"Could not check participants for group {classroom.whatsapp_group_id}: {e}")
    return None


async def _handle_parent_resumen(parent: models.Parent, chat_id: str, db) -> None:
    """Send weekly text summary + PDF link to the calling parent."""
    from datetime import datetime, timedelta
    from app.utils.summary_formatter import generate_weekly_summary, generate_weekly_data
    from app.utils.pdf_generator import create_weekly_pdf
    import pytz
    import tempfile
    import os

    tz = pytz.timezone("America/Panama")
    today = datetime.now(tz).date()
    # Next Monday \u2192 Friday
    days_until_monday = (7 - today.weekday()) % 7
    start = today + timedelta(days=days_until_monday if days_until_monday else 7)
    end = start + timedelta(days=4)
    week_dates = [start + timedelta(days=i) for i in range(5)]

    student_ids = parent.student_ids or []
    if not student_ids:
        wa = WahaClient()
        wa.send_text(chat_id, "\u274c No hay estudiantes vinculados.")
        return

    wa_client = WahaClient()
    raw_conn = db.connection().connection.dbapi_connection
    any_summary_sent = False

    # Get last sync time for PDF footer
    bot_status = db.query(models.BotStatus).first()
    last_sync_str = None
    if bot_status and bot_status.last_sync_at:
        import pytz
        tz_obj = pytz.timezone("America/Panama")
        local_dt = bot_status.last_sync_at.replace(tzinfo=pytz.utc).astimezone(tz_obj)
        last_sync_str = local_dt.strftime("%d/%m/%Y %H:%M")

    for sid in student_ids:
        # Text summary
        message = generate_weekly_summary(raw_conn, sid, start, end)
        if message:
            wa_client.send_text(chat_id, message)
            any_summary_sent = True

        # PDF generation + S3 upload
        try:
            data_by_day = generate_weekly_data(raw_conn, sid, start, end)
            has_data = any(
                data_by_day.get(day, {}).get("sumativas") or data_by_day.get(day, {}).get("materials")
                for day in data_by_day
            )
            if not has_data:
                continue

            student = db.get(models.Student, sid)
            classroom = db.get(models.Classroom, student.classroom_id) if student and student.classroom_id else None
            student_label = student.name if student else f"estudiante_{sid}"
            class_label = classroom.name if classroom else student_label

            with tempfile.TemporaryDirectory() as tmpdir:
                filename = f"resumen_{class_label}_{start.strftime('%d%m')}.pdf"
                pdf_path = os.path.join(tmpdir, filename)
                create_weekly_pdf(data_by_day, pdf_path, week_dates, last_sync_at=last_sync_str)

                # Upload to S3 and send shortened link
                from app.utils.s3_upload import upload_file_to_s3, generate_presigned_url
                from app.utils.helpers import shorten_url
                s3_key = f"resumenes/{start.strftime('%Y-%m-%d')}/{filename}"
                upload_file_to_s3(pdf_path, s3_key)
                presigned = generate_presigned_url(s3_key)
                short_url = shorten_url(presigned)
                wa_client.send_text(
                    chat_id,
                    f"\U0001f4c4 *PDF de {class_label}:*\n{short_url}",
                )
        except Exception as e:
            logger.error(f"PDF generation/upload failed for student {sid}: {e}")

    if not any_summary_sent:
        wa_client.send_text(
            chat_id,
            f"\U0001f4ed No hay actividades para la semana del {start.strftime('%d/%m')}.",
        )


async def _handle_parent_payments(parent: models.Parent, chat_id: str, db) -> None:
    """Show the parent's payment history across all fundraisers."""
    wa_client = WahaClient()
    payments = (
        db.query(models.Payment)
        .filter_by(payer_jid=parent.whatsapp_jid)
        .order_by(models.Payment.submitted_at.desc())
        .all()
    )
    if not payments:
        wa_client.send_text(chat_id, "📋 No tienes pagos registrados.")
        return

    lines = ["📋 *Tus pagos registrados:*\n"]
    for p in payments:
        fund = db.query(models.Fundraiser).get(p.fundraiser_id)
        fund_name = fund.name if fund else f"Actividad {p.fundraiser_id}"
        status_icon = "✅" if p.status == "confirmed" else "⚠️"
        date_str = p.submitted_at.strftime("%d/%m/%Y") if p.submitted_at else "—"
        amount_str = f"${p.amount}" if p.amount else "—"
        lines.append(
            f"{status_icon} *{fund_name}*\n"
            f"   Estudiante: {p.child_name or '—'} | Monto: {amount_str} | {date_str}"
        )
    wa_client.send_text(chat_id, "\n\n".join(lines))


_PARENT_HELP = (
    "📋 *Comandos disponibles:*\n\n"
    "  `/resumen` — recibir resumen semanal + PDF\n"
    "  `/pagar <actividad>` — pagar una actividad escolar\n"
    "  `/mis pagos` — ver historial de tus pagos\n"
    "  `/fundraiser list` — ver actividades activas\n"
    "  `/fundraiser create <nombre>` — crear nueva actividad\n"
    "  `/form list` — ver tus formularios\n"
    "  `/form create` — crear nuevo formulario\n"
    "  `FORM-XXXXX` — responder un formulario del colegio\n"
    "  `/help` — mostrar este mensaje\n\n"
    "💬 O simplemente escríbeme tu pregunta sobre tareas y actividades."
)
