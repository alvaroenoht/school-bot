"""
Admin commands — only accepted from the admin's personal WhatsApp DM.
All commands use the / prefix.

Commands:
    /help                              show all available commands
    /gencode [label]                   generate a one-time invite code
    /list                              show registered parents and active codes
    /disallow <id>                     deactivate a parent by ID
    /sync [classroom_id]               trigger assignment sync
    /resumen                           send weekly PDF summary to group
    /status [msg|clear]                view/set maintenance message
    /fundraiser create|list|close|delete|report   manage fundraisers
    /form create|list|open|close|archive|delete   manage forms
    /form results|report|ai|questions  form reporting
    /form addq|editq|delq|readers|fill form editing
"""
import logging
import secrets
import string
from datetime import datetime

from sqlalchemy.orm import Session

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()


async def handle(admin_phone: str, chat_id: str, text: str, db: Session) -> bool:
    """
    Process an admin command.
    Returns True if the text was a recognized command, False otherwise.
    """
    # Strip leading / if present
    cmd = text.strip()
    if cmd.startswith("/"):
        cmd = cmd[1:]
    cmd_lower = cmd.lower()

    # ── /help ──────────────────────────────────────────────────────────────────
    if cmd_lower == "help" or cmd_lower == "ayuda":
        wa.send_text(chat_id, _ADMIN_HELP)
        return True

    # ── /status ───────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("status") or cmd_lower.startswith("estado"):
        parts = text.strip().split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""
        status = db.query(models.BotStatus).first()

        if not arg or arg.lower() in ("show", "ver"):
            lines = ["📊 *Estado del bot:*\n"]
            if status and status.last_sync_at:
                import pytz
                from app.config import get_settings
                tz = pytz.timezone(get_settings().timezone)
                local_dt = status.last_sync_at.replace(tzinfo=pytz.utc).astimezone(tz)
                lines.append(f"🔄 Última sincronización: *{local_dt.strftime('%d/%m/%Y %H:%M')}*")
            else:
                lines.append("🔄 Última sincronización: _ninguna registrada_")
            if status and status.maintenance_msg:
                lines.append(f"\n🟡 Mensaje activo: _{status.maintenance_msg}_\n`/status clear` para desactivar")
            else:
                lines.append("\n✅ Sin mensaje de estado activo.")
            wa.send_text(chat_id, "\n".join(lines))
            return True

        if arg.lower() in ("clear", "limpiar", "off"):
            if status:
                status.maintenance_msg = None
                status.updated_at = datetime.utcnow()
                db.commit()
            wa.send_text(chat_id, "✅ Mensaje de mantenimiento eliminado.")
            return True

        # Set maintenance message
        if not status:
            status = models.BotStatus(maintenance_msg=arg)
            db.add(status)
        else:
            status.maintenance_msg = arg
            status.updated_at = datetime.utcnow()
        db.commit()
        wa.send_text(
            chat_id,
            f"🟡 *Mensaje de estado activado:*\n\n_{arg}_\n\n"
            "Se mostrará a todos los que envíen un mensaje al bot.\n"
            "`/status clear` para desactivar.",
        )
        return True

    # ── fundraiser ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("fundraiser") or cmd_lower.startswith("actividad"):
        from app.bot import fundraiser_admin
        return await fundraiser_admin.handle_command(chat_id, chat_id, text, db)

    # ── form ─────────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("form") or cmd_lower.startswith("formulario"):
        from app.bot import form_admin
        return await form_admin.handle_command(chat_id, chat_id, text, db)

    # ── gencode ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("gencode"):
        # Optional label after the command, e.g. "gencode Maria Garcia"
        parts = text.strip().split(" ", 1)
        label = parts[1].strip() if len(parts) > 1 else None

        code = _generate_code()
        while db.query(models.InviteCode).filter_by(code=code).first():
            code = _generate_code()   # ensure uniqueness (extremely unlikely collision)

        db.add(models.InviteCode(code=code, label=label, status="active"))
        db.commit()

        label_line = f"\n🏷️ Para: _{label}_" if label else ""
        wa.send_text(
            chat_id,
            f"🔑 *Código de invitación generado:*{label_line}\n\n"
            f"`{code}`\n\n"
            "Compártelo con el padre/madre. Solo puede usarse *una vez*.\n"
            "Para cancelarlo: `/disallow <id>` (ver con `/list`)",
        )
        return True

    # ── list ───────────────────────────────────────────────────────────────────
    if cmd_lower == "list" or cmd_lower == "lista":
        parents = db.query(models.Parent).filter_by(is_active=True).all()
        pending_codes = db.query(models.InviteCode).filter_by(status="active").all()

        lines = []

        if parents:
            lines.append("👨‍👩‍👧 *Padres registrados:*\n")
            for p in parents:
                students = db.query(models.Student).filter_by(parent_id=p.id).all()
                lines.append(f"• [ID `{p.id}`] *{p.first_name} {p.last_name}*")
                if students:
                    for s in students:
                        classroom = db.query(models.Classroom).get(s.classroom_id) if s.classroom_id else None
                        group_status = "✅ vinculado" if (classroom and classroom.whatsapp_group_id) else "⏳ sin grupo"
                        lines.append(
                            f"  └ {s.name} ({s.grade}) — Salón `{classroom.id if classroom else 'N/A'}` — {group_status}"
                        )
                else:
                    lines.append("  _Sin estudiantes registrados_")
        else:
            lines.append("👨‍👩‍👧 _No hay padres registrados._")

        if pending_codes:
            lines.append("\n🔑 *Códigos activos (sin usar):*\n")
            for c in pending_codes:
                label = f" _{c.label}_" if c.label else ""
                lines.append(f"• `{c.code}`{label} (generado {c.created_at.strftime('%d/%m %H:%M')})")

        wa.send_text(chat_id, "\n".join(lines))
        return True

    # ── disallow ───────────────────────────────────────────────────────────────
    if cmd_lower.startswith("disallow ") or cmd_lower.startswith("desactivar "):
        raw_id = text.split(" ", 1)[1].strip()
        if not raw_id.isdigit():
            wa.send_text(chat_id, "❌ Uso: `disallow <id>` — el ID es numérico (ver con `list`)")
            return True

        parent_id = int(raw_id)
        parent = db.query(models.Parent).get(parent_id)
        if not parent:
            wa.send_text(chat_id, f"❓ No encontré un padre con ID `{parent_id}`.")
            return True

        parent.is_active = False
        # Deactivate all classrooms linked to this parent's students
        students = db.query(models.Student).filter_by(parent_id=parent.id).all()
        for s in students:
            if s.classroom_id:
                classroom = db.query(models.Classroom).get(s.classroom_id)
                if classroom:
                    classroom.is_active = False
        db.commit()

        wa.send_text(
            chat_id,
            f"🚫 *{parent.first_name} {parent.last_name}* (ID `{parent_id}`) desactivado.\n"
            "Su salón ya no recibirá resúmenes ni recordatorios.",
        )
        return True

    # ── sync ───────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("sync") or cmd_lower.startswith("sincronizar"):
        parts = text.split()
        classroom_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        wa.send_text(chat_id, "🔄 Sincronización iniciada...")
        import asyncio
        from app.scheduler.sync import run_sync
        asyncio.create_task(run_sync(classroom_id=classroom_id))
        return True

    # ── profile ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("profile"):
        parts = text.strip().split(None, 2)
        sub = parts[1].lower() if len(parts) > 1 else ""
        value = parts[2].strip() if len(parts) > 2 else ""

        if not sub or not value:
            wa.send_text(chat_id, "Uso:\n  `/profile name <nombre>`\n  `/profile about <texto>`")
            return True

        if sub == "name":
            ok = wa.set_profile_name(value)
            wa.send_text(chat_id, f"✅ Nombre actualizado a *{value}*." if ok else "❌ Error al actualizar el nombre.")
        elif sub == "about":
            ok = wa.set_profile_about(value)
            wa.send_text(chat_id, f"✅ About actualizado." if ok else "❌ Error al actualizar el about.")
        else:
            wa.send_text(chat_id, "❌ Subcomando desconocido. Usa `name` o `about`.")
        return True

    # ── resumen ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("resumen"):
        # Find the admin's parent record
        parent = db.query(models.Parent).filter_by(
            whatsapp_jid=chat_id.replace("@c.us", "@lid").split("@")[0]
        ).first()
        if not parent:
            # Fallback: find any active parent
            parent = db.query(models.Parent).filter_by(is_active=True).first()

        if not parent or not parent.student_ids:
            wa.send_text(chat_id, "❌ No hay estudiantes vinculados.")
            return True

        # Use shared handler (same as parent /resumen — text + PDF + S3)
        from app.bot.webhook import _handle_parent_resumen
        await _handle_parent_resumen(parent, chat_id, db)
        return True

    return False   # not an admin command


_ADMIN_HELP = (
    "📋 *Comandos disponibles:*\n\n"
    "*👤 Padres y códigos:*\n"
    "  `/gencode [nombre]` — generar código de invitación\n"
    "  `/list` — ver padres registrados y códigos activos\n"
    "  `/disallow <id>` — desactivar un padre por ID\n\n"
    "*🔄 Sincronización y resúmenes:*\n"
    "  `/sync` — sincronizar actividades de todos los salones\n"
    "  `/sync <id>` — sincronizar un salón específico\n"
    "  `/resumen` — enviar resumen semanal (PDF) al grupo\n\n"
    "*💳 Actividades / Fundraisers:*\n"
    "  `/fundraiser create <nombre>` — crear nueva actividad\n"
    "  `/fundraiser list` — listar todas las actividades\n"
    "  `/fundraiser close <id>` — cerrar actividad\n"
    "  `/fundraiser delete <id>` — eliminar (sin pagos registrados)\n"
    "  `/fundraiser report <id>` — reporte de pagos en PDF\n"
    "  `/fundraiser subscribe <id> <teléfono>` — suscribir número a notificaciones de pagos\n"
    "  `/fundraiser unsubscribe <id> <teléfono>` — quitar suscripción\n\n"
    "*📝 Formularios:*\n"
    "  `/form create` — crear nuevo formulario (flujo guiado)\n"
    "  `/form list` — listar formularios\n"
    "  `/form open <id>` — abrir formulario (envía invitación)\n"
    "  `/form close <id>` — cerrar formulario\n"
    "  `/form archive <id>` — archivar formulario\n"
    "  `/form delete <id>` — eliminar formulario\n"
    "  `/form results <id>` — reporte detallado por pregunta\n"
    "  `/form report <id>` — resumen compacto + CSV\n"
    "  `/form ai <id> <pregunta>` — análisis IA de respuestas\n"
    "  `/form questions <id>` — ver preguntas del formulario\n"
    "  `/form addq <id>` — agregar pregunta\n"
    "  `/form editq <id> <#>` — editar una pregunta\n"
    "  `/form delq <id> <#>` — eliminar una pregunta\n"
    "  `/form readers <id>` — ver quién ha respondido\n"
    "  `/form fill <id>` — responder formulario tú mismo\n\n"
    "*⚙️ Perfil del bot:*\n"
    "  `/profile name <nombre>` — cambiar nombre del bot\n"
    "  `/profile about <texto>` — cambiar mensaje \"about\"\n\n"
    "*ℹ️ Sistema:*\n"
    "  `/status` — ver última sincronización y mensaje activo\n"
    "  `/status <mensaje>` — activar mensaje de mantenimiento\n"
    "  `/status clear` — desactivar mensaje\n"
    "  `/help` — mostrar este mensaje"
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _generate_code() -> str:
    """Generate a human-readable one-time code like SCH-X7K2M."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SCH-{suffix}"
