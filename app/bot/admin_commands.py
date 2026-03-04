"""
Admin commands — only accepted from the admin's personal WhatsApp DM.

Commands:
    gencode [label]         generate a one-time invite code (label is optional, e.g. "Maria Garcia")
    list                    show all registered parents with ID, name, and group status
    disallow <id>           deactivate a parent by their numeric ID (from the list)
    sync                    trigger assignment sync for all classrooms
    sync <classroom_id>     trigger sync for a specific classroom
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
    cmd = text.strip().lower()

    # ── fundraiser ────────────────────────────────────────────────────────────────
    if cmd.startswith("fundraiser") or cmd.startswith("actividad"):
        from app.bot import fundraiser_admin
        return await fundraiser_admin.handle_command(admin_phone, chat_id, text, db)

    # ── gencode ────────────────────────────────────────────────────────────────
    if cmd.startswith("gencode"):
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
            "Para cancelarlo: `disallow <id>` (ver con `list`)",
        )
        return True

    # ── list ───────────────────────────────────────────────────────────────────
    if cmd == "list":
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
    if cmd.startswith("disallow "):
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
    if cmd.startswith("sync"):
        parts = text.split()
        classroom_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        wa.send_text(chat_id, "🔄 Sincronización iniciada...")
        import asyncio
        from app.scheduler.sync import run_sync
        asyncio.create_task(run_sync(classroom_id=classroom_id))
        return True

    return False   # not an admin command


# ── Helpers ────────────────────────────────────────────────────────────────────

def _generate_code() -> str:
    """Generate a human-readable one-time code like SCH-X7K2M."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(6))
    return f"SCH-{suffix}"
