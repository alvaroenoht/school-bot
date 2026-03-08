"""
Parent self-registration state machine.

Entry condition:
    The webhook has already validated the invite code before calling handle().
    handle() is only ever called for:
      - A new sender whose first message was a valid invite code  (session=None, invite=<obj>)
      - A sender with an in-progress session                      (session=<obj>)

States:
    awaiting_first_name  → parent types their first name
    awaiting_last_name   → parent types their last name
    awaiting_username    → parent types their school portal username
    awaiting_password    → parent types their password (encrypted immediately, then login + auto-discover students)
    verifying            → login in progress — ignore further messages until done

Security:
    Username and password messages are deleted from WhatsApp immediately after
    being received. The parent is also advised to clear the chat history.

After registration completes the parent is asked to:
  1. Add the bot to their WhatsApp group
  2. Send  vincular <classroom_id>  from inside the group (no @mention needed)
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.api.seduca_client import SeducaClient
from app.db import models
from app.utils.crypto import decrypt, encrypt
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

_ONBOARDING = """\
✅ Código válido. ¡Bienvenido al *Asistente Escolar*!

Aquí te explico cómo funciona:

📋 *¿Qué hace el asistente?*
• Revisa el portal escolar automáticamente
• Cada *jueves a las 6pm* envía el resumen semanal de actividades
• Cada *mañana (lun–vie)* recuerda las tareas del día
• Responde preguntas sobre tareas cuando alguien lo menciona en el grupo

🔒 *Tu privacidad*
• Tu usuario y contraseña se cifran al instante
• Nadie — ni el administrador — puede leerlos
• Los mensajes con tus credenciales se borran automáticamente del chat

📱 *Al terminar el registro*
Deberás agregar este bot a tu grupo de WhatsApp y vincularlo. ¡Es el último paso!

Vamos a comenzar. ¿Cuál es tu *nombre*?\
"""


async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    session: models.RegistrationSession | None,
    invite: models.InviteCode | None = None,
    message_id: str = "",
):
    """Drive the registration state machine for a given sender JID."""

    # ── Start new session (invite already validated by webhook) ───────────────
    if session is None:
        if invite is None:
            logger.warning(f"registration.handle called without session or invite for {raw_jid}")
            return

        # Delete the invite code message so it disappears from the chat
        if message_id:
            wa.delete_message(chat_id, message_id)

        session = models.RegistrationSession(
            chat_jid=raw_jid,
            state="awaiting_first_name",
            data={"invite_code_id": invite.id},
        )
        db.add(session)
        db.commit()
        wa.send_text(chat_id, _ONBOARDING)
        return

    state = session.state
    data: dict = session.data or {}

    # ── Cancel / restart at any step ──────────────────────────────────────────
    if text.lower().strip().lstrip("/") in ("cancelar", "reiniciar", "cancel", "restart"):
        db.delete(session)
        db.commit()
        wa.send_text(
            chat_id,
            "🔄 Registro cancelado.\n\n"
            "Si quieres volver a intentar, envía tu código de invitación.",
        )
        logger.info(f"Registration cancelled by user {raw_jid} at state={state}")
        return

    # ── awaiting_first_name ────────────────────────────────────────────────────
    if state == "awaiting_first_name":
        data["first_name"] = text.strip()
        _update(session, "awaiting_last_name", data, db)
        wa.send_text(chat_id, f"Hola *{data['first_name']}*! ¿Cuál es tu *apellido*?")

    # ── awaiting_last_name ─────────────────────────────────────────────────────
    elif state == "awaiting_last_name":
        data["last_name"] = text.strip()
        _update(session, "awaiting_username", data, db)
        wa.send_text(
            chat_id,
            f"✅ Perfecto, *{data['first_name']} {data['last_name']}*.\n\n"
            "Ingresa tu *usuario* del sistema escolar:\n"
            "_(o escribe /cancelar para salir)_",
        )

    # ── awaiting_username ──────────────────────────────────────────────────────
    elif state == "awaiting_username":
        data["username"] = text.strip()
        _update(session, "awaiting_password", data, db)
        # Delete the username message immediately
        if message_id:
            wa.delete_message(chat_id, message_id)
        wa.send_text(
            chat_id,
            "✅ Usuario recibido y borrado del chat.\n\n"
            "Ahora ingresa tu *contraseña*\n"
            "_(se cifrará y borrará del chat de inmediato)_:",
        )

    # ── awaiting_password → encrypt, login, auto-discover students ────────────
    elif state == "awaiting_password":
        # Delete the password message FIRST, before doing anything else
        if message_id:
            wa.delete_message(chat_id, message_id)

        # Encrypt credentials immediately — plaintext never stored
        data["enc_username"] = encrypt(data.pop("username"))
        data["enc_password"] = encrypt(text)
        text = ""   # clear plaintext from memory
        _update(session, "verifying", data, db)
        wa.send_text(
            chat_id,
            "🔒 Contraseña cifrada y borrada del chat.\n"
            "🔄 Verificando acceso y buscando estudiantes...",
        )

        username = decrypt(data["enc_username"])
        password = decrypt(data["enc_password"])
        client = SeducaClient(username, password)

        if not client.login():
            wa.send_text(
                chat_id,
                "❌ No pude iniciar sesión con esas credenciales.\n\n"
                "Verifica e intenta de nuevo. Ingresa tu *usuario*:\n"
                "_(o escribe /cancelar para salir)_",
            )
            _update(session, "awaiting_username", {
                "invite_code_id": data["invite_code_id"],
                "first_name":     data["first_name"],
                "last_name":      data["last_name"],
            }, db)
            return

        students = client.fetch_students()
        if not students:
            wa.send_text(
                chat_id,
                "⚠️ Credenciales correctas pero no encontré estudiantes vinculados a tu cuenta.\n\n"
                "Verifica en el portal que tengas estudiantes asignados e intenta de nuevo.\n"
                "Ingresa tu *usuario*:\n"
                "_(o escribe /cancelar para salir)_",
            )
            _update(session, "awaiting_username", {
                "invite_code_id": data["invite_code_id"],
                "first_name":     data["first_name"],
                "last_name":      data["last_name"],
            }, db)
            return

        student_ids = [s["id"] for s in students]

        # Create parent record (no single classroom_id -- one per student)
        parent = models.Parent(
            first_name=data["first_name"],
            last_name=data["last_name"],
            whatsapp_jid=raw_jid,
            classroom_id=None,
            encrypted_username=data["enc_username"],
            encrypted_password=data["enc_password"],
            student_ids=student_ids,
            registered_at=datetime.utcnow(),
        )
        db.add(parent)
        db.flush()

        # Check if these students already exist (second parent with same creds)
        classroom_info = []  # [(student_dict, classroom_id)]
        for s in students:
            existing_student = db.get(models.Student, s["id"])
            if existing_student:
                # Reuse existing Student + Classroom — don't touch parent_id or classroom_id
                logger.info(
                    f"  Reusing existing student {s['id']} / classroom {existing_student.classroom_id} "
                    f"(second parent registration)"
                )
                classroom_info.append((s, existing_student.classroom_id))
            else:
                # First parent — create new Classroom + Student records
                classroom = models.Classroom(
                    name=f"{s['name']} - {s['grade']}",
                )
                db.add(classroom)
                db.flush()

                student_rec = models.Student(
                    id=s["id"],
                    name=s["name"],
                    grade=s["grade"],
                    classroom_id=classroom.id,
                    parent_id=parent.id,
                )
                db.add(student_rec)
                db.flush()
                classroom_info.append((s, classroom.id))

        # Mark invite code as used
        invite_obj = db.query(models.InviteCode).get(data["invite_code_id"])
        if invite_obj:
            invite_obj.status = "used"
            invite_obj.used_at = datetime.utcnow()
            invite_obj.parent_id = parent.id

        db.delete(session)
        db.commit()

        student_lines = "\n".join(
            f"  \u2022 *{s['name']}* ({s['grade']}) \u2014 sal\u00f3n `{cid}`"
            for s, cid in classroom_info
        )
        vincular_lines = "\n".join(
            f"  \u2022 Grupo de *{s['grade']}* \u2192 `/vincular {cid}`"
            for s, cid in classroom_info
        )
        wa.send_text(
            chat_id,
            f"\u2705 *\u00a1Registro completado, {parent.first_name}!*\n\n"
            f"\ud83d\udc64 *Estudiantes encontrados:*\n{student_lines}\n\n"
            "\ud83d\udccc *\u00daltimo paso:* agr\u00e9game a tus grupos de WhatsApp "
            "y env\u00eda el comando correspondiente:\n"
            f"{vincular_lines}\n\n"
            "\ud83e\uddf9 Por seguridad, te recomendamos borrar el historial de este chat.",
        )
        # Disclaimer — not an official school/Seduca app
        wa.send_text(
            chat_id,
            "\u26a0\ufe0f *Aviso importante:* Este asistente es un proyecto "
            "*independiente*. *No es una aplicaci\u00f3n oficial* del colegio "
            "ni de Seduca/GSEpty.\n\n"
            "Para preguntas o soporte: *67815352*",
        )

    # ── verifying — login already running, ignore extra messages ──────────────
    elif state == "verifying":
        wa.send_text(chat_id, "⏳ Todavía verificando, un momento...")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _update(session: models.RegistrationSession, state: str, data: dict, db: Session):
    session.state = state
    session.data = dict(data)
    flag_modified(session, "data")  # required: SQLAlchemy won't detect JSON mutations otherwise
    session.updated_at = datetime.utcnow()
    db.commit()
