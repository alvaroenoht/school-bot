"""
Admin commands — only accepted from the admin's personal WhatsApp DM.
All commands use the / prefix.

Commands:
    /help                    show all available commands
    /gencode [label]         generate a one-time invite code
    /list                    show all registered parents and pending codes
    /disallow <id>           deactivate a parent by ID
    /sync [classroom_id]     trigger assignment sync
    /fundraiser create|list|close|delete|report   manage fundraisers
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

    # ── fundraiser ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("fundraiser") or cmd_lower.startswith("actividad"):
        from app.bot import fundraiser_admin
        return await fundraiser_admin.handle_command(admin_phone, chat_id, text, db)

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

    # ── resumen ────────────────────────────────────────────────────────────────
    if cmd_lower.startswith("resumen"):
        wa.send_text(chat_id, "📋 Enviando resumen semanal a todos los grupos...")
        import asyncio
        from app.scheduler.summary import send_weekly_summaries
        asyncio.create_task(send_weekly_summaries())
        return True

    return False   # not an admin command


_ADMIN_HELP = (
    "\U0001f4cb *Comandos disponibles:*\n\n"
    "*\U0001f464 Padres y c\u00f3digos:*\n"
    "  `/gencode [nombre]` \u2014 generar c\u00f3digo de invitaci\u00f3n\n"
    "  `/list` \u2014 ver padres registrados y c\u00f3digos activos\n"
    "  `/disallow <id>` \u2014 desactivar un padre por ID\n\n"
    "*\U0001f504 Sincronizaci\u00f3n:*\n"
    "  `/sync` \u2014 sincronizar actividades de todos los salones\n"
    "  `/sync <id>` \u2014 sincronizar un sal\u00f3n espec\u00edfico\n"
    "  `/resumen` \u2014 enviar resumen semanal a todos los grupos\n\n"
    "*\U0001f4b3 Actividades (fundraisers):*\n"
    "  `/fundraiser create <nombre>` \u2014 crear nueva actividad\n"
    "  `/fundraiser list` \u2014 listar todas las actividades\n"
    "  `/fundraiser close <id>` \u2014 cerrar actividad\n"
    "  `/fundraiser delete <id>` \u2014 eliminar (sin pagos)\n"
    "  `/fundraiser report <id>` \u2014 generar reporte PDF\n\n"
    "*\u2139\ufe0f Otros:*\n"
    "  `/help` \u2014 mostrar este mensaje"
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _generate_code() -> str:
    """Generate a human-readable one-time code like SCH-X7K2M."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SCH-{suffix}"
