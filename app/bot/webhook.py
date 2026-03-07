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

    # 4. Quoted (replied-to) a bot message — check quotedParticipant
    _data = payload.get("_data", {})
    quoted_participant = _data.get("quotedParticipant") or ""
    if quoted_participant:
        wa = WahaClient()
        quoted_phone = wa.resolve_phone(quoted_participant)
        if quoted_phone == bot_phone:
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
                sub = cmd.split(None, 1)[1] if " " in cmd else ""
                if sub.startswith("list") or sub.startswith("lista"):
                    await fundraiser_admin.handle_command(from_phone, chat_id, raw_text, db)
                else:
                    wa.send_text(chat_id, "\u274c Ese comando de actividades es *solo para administradores*.")
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

    for classroom in classrooms:
        try:
            participants = wa.get_group_participants(classroom.whatsapp_group_id)
            if raw_jid in participants:
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

    for sid in student_ids:
        # Text summary
        message = generate_weekly_summary(raw_conn, sid, start, end)
        if message:
            wa_client.send_text(chat_id, message)

        # PDF generation + S3 upload
        try:
            data_by_day = generate_weekly_data(raw_conn, sid, start, end)
            # Check if there's any data
            has_data = any(
                data_by_day.get(day, {}).get("sumativas") or data_by_day.get(day, {}).get("materials")
                for day in data_by_day
            )
            if not has_data:
                continue

            student = db.query(models.Student).get(sid)
            student_label = student.name if student else f"estudiante_{sid}"

            with tempfile.TemporaryDirectory() as tmpdir:
                filename = f"resumen_{student_label}_{start.strftime('%d%m')}.pdf"
                pdf_path = os.path.join(tmpdir, filename)
                create_weekly_pdf(data_by_day, pdf_path, week_dates)

                # Upload to S3 and send short link
                from app.utils.s3_upload import upload_file_to_s3, create_short_link
                from app.config import get_settings
                settings = get_settings()
                s3_key = f"resumenes/{start.strftime('%Y-%m-%d')}/{filename}"
                upload_file_to_s3(pdf_path, s3_key, settings.s3_bucket)
                short_url = create_short_link(db, s3_key)
                wa_client.send_text(
                    chat_id,
                    f"\U0001f4c4 *PDF de {student_label}:*\n{short_url}",
                )
        except Exception as e:
            logger.error(f"PDF generation/upload failed for student {sid}: {e}")

    if not any(
        generate_weekly_summary(raw_conn, sid, start, end) for sid in student_ids
    ):
        wa_client.send_text(
            chat_id,
            f"\U0001f4ed No hay actividades para la semana del {start.strftime('%d/%m')}.",
        )


_PARENT_HELP = (
    "\U0001f4cb *Comandos disponibles:*\n\n"
    "  `/resumen` \u2014 recibir resumen semanal + PDF\n"
    "  `/pagar <actividad>` \u2014 pagar una actividad escolar\n"
    "  `/fundraiser list` \u2014 ver actividades activas\n"
    "  `/help` \u2014 mostrar este mensaje\n\n"
    "\U0001f4ac O simplemente escr\u00edbeme tu pregunta sobre tareas y actividades."
)
