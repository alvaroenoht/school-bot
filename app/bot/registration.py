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
            "Ingresa tu *usuario* del sistema escolar:",
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
                "Verifica e intenta de nuevo. Ingresa tu *usuario*:",
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
                "Ingresa tu *usuario*:",
            )
            _update(session, "awaiting_username", {
                "invite_code_id": data["invite_code_id"],
                "first_name":     data["first_name"],
                "last_name":      data["last_name"],
            }, db)
            return

        student_ids = [s["id"] for s in students]

        # Create classroom and parent records
        new_classroom = models.Classroom(
            name=f"Salón {data['first_name']} {data['last_name']}",
        )
        db.add(new_classroom)
        db.flush()

        parent = models.Parent(
            first_name=data["first_name"],
            last_name=data["last_name"],
            whatsapp_jid=raw_jid,
            classroom_id=new_classroom.id,
            encrypted_username=data["enc_username"],
            encrypted_password=data["enc_password"],
            student_ids=student_ids,
            registered_at=datetime.utcnow(),
        )
        db.add(parent)
        db.flush()

        # Mark invite code as used
        invite_obj = db.query(models.InviteCode).get(data["invite_code_id"])
        if invite_obj:
            invite_obj.status = "used"
            invite_obj.used_at = datetime.utcnow()
            invite_obj.parent_id = parent.id

        db.delete(session)
        db.commit()

        student_lines = "\n".join(f"  • {s['name']} ({s['grade']})" for s in students)
        wa.send_text(
            chat_id,
            f"✅ *¡Registro completado, {parent.first_name}!*\n\n"
            f"👤 *Estudiantes encontrados:*\n{student_lines}\n\n"
            f"📚 ID de tu salón: `{new_classroom.id}`\n\n"
            "Recibirás el resumen cada *jueves a las 6pm* y un recordatorio "
            "cada mañana de lunes a viernes. 🎉\n\n"
            "📌 *Último paso:* agrégame a tu grupo de WhatsApp y envía "
            f"`vincular {new_classroom.id}` desde el grupo _(sin necesidad de mencionarme)_.\n\n"
            "🧹 Por seguridad, te recomendamos borrar el historial de este chat.",
        )

    # ── verifying — login already running, ignore extra messages ──────────────
    elif state == "verifying":
        wa.send_text(chat_id, "⏳ Todavía verificando, un momento...")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _update(session: models.RegistrationSession, state: str, data: dict, db: Session):
    session.state = state
    session.data = data
    session.updated_at = datetime.utcnow()
    db.commit()
