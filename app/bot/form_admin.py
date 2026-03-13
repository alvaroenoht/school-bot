"""
Form admin commands and form_create conversation flow.

Admin commands:
    /form create           — start multi-step form creation flow
    /form list             — list all forms
    /form open <id>        — transition draft → open (notifies audience)
    /form close <id>       — transition open → closed
    /form archive <id>     — transition closed → archived
    /form results <id>     — text report of submissions
    /form delete <id>      — delete a draft form

Conversational flow: form_create
    Step order:
        awaiting_title → awaiting_purpose → awaiting_description
        → awaiting_audience → awaiting_group_reminders
        [→ awaiting_reminder_interval] → awaiting_questions
        [→ awaiting_q_type [→ awaiting_q_options]] (loop)
        → awaiting_open_schedule → confirm
"""
import logging
import secrets
import string
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

_PURPOSE_MAP = {
    "1": "intake",
    "2": "survey",
    "3": "event_registration",
    "4": "volunteer_signup",
}
_PURPOSE_LABELS = {
    "intake": "Datos / Perfil",
    "survey": "Encuesta",
    "event_registration": "Registro de evento",
    "volunteer_signup": "Voluntariado",
}
_TYPE_MAP = {
    "1": "yes_no",
    "2": "text",
    "3": "single_choice",
}
_TYPE_LABELS = {
    "yes_no": "Sí/No",
    "text": "Texto corto",
    "single_choice": "Opción única",
}


# ── Public command handler ─────────────────────────────────────────────────────

def _check_form_access(form: models.Form, caller_parent: models.Parent | None) -> bool:
    """Super admin (caller_parent=None) has unrestricted access. Others must own the form."""
    if caller_parent is None:
        return True
    return form.created_by_jid == caller_parent.whatsapp_jid


async def handle_command(
    caller_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    caller_parent: models.Parent | None = None,
) -> bool:
    """Handle all /form admin commands. Returns True if handled."""
    parts = text.strip().lstrip("/").split(None, 2)
    # parts[0] = "form", parts[1] = sub-command, parts[2] = argument (optional)
    if len(parts) < 2:
        wa.send_text(chat_id, _HELP)
        return True

    sub = parts[1].lower()

    # ── /form create ──────────────────────────────────────────────────────
    if sub == "create" or sub == "crear":
        session_data: dict = {}
        if caller_parent:
            # Registered parent: restrict audience to their classrooms
            allowed_ids = [
                s.classroom_id
                for s in db.query(models.Student).filter(
                    models.Student.id.in_(caller_parent.student_ids or [])
                ).all()
                if s.classroom_id
            ]
            if not allowed_ids:
                wa.send_text(chat_id, "❌ No tienes salones vinculados para crear un formulario.")
                return True
            session_data["allowed_classroom_ids"] = allowed_ids

        existing = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
        if existing:
            db.delete(existing)
            db.flush()

        session = models.ConversationSession(
            chat_jid=chat_id,
            flow="form_create",
            step="awaiting_title",
            data=session_data,
        )
        db.add(session)
        db.commit()

        wa.send_text(
            chat_id,
            "📋 *Crear nuevo formulario*\n\n"
            "¿Cuál es el *título* del formulario?\n"
            "(Ej: _Datos de salud_ o _Registro de viaje de estudios_)",
        )
        return True

    # ── /form list ────────────────────────────────────────────────────────
    if sub == "list" or sub == "lista":
        query = db.query(models.Form).order_by(models.Form.created_at.desc())
        if caller_parent:
            query = query.filter(models.Form.created_by_jid == caller_parent.whatsapp_jid)
        forms = query.all()
        if not forms:
            wa.send_text(chat_id, "📋 _No hay formularios registrados._")
            return True

        lines = ["📋 *Formularios:*\n"]
        status_icons = {"draft": "📝", "open": "✅", "closed": "🔒", "archived": "🗄️"}
        for f in forms:
            icon = status_icons.get(f.status, "❓")
            sub_count = db.query(models.FormSubmission).filter_by(
                form_id=f.id, status="submitted"
            ).count()
            purpose_label = _PURPOSE_LABELS.get(f.purpose, f.purpose)
            lines.append(
                f"{icon} [ID `{f.id}`] *{f.title}*\n"
                f"   {purpose_label} — {f.status} — {sub_count} respuestas"
            )

        wa.send_text(chat_id, "\n".join(lines))
        return True

    # ── /form open <id> ───────────────────────────────────────────────────
    if sub == "open" or sub == "abrir":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form open <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status not in ("draft", "closed"):
            wa.send_text(
                chat_id,
                f"⚠️ El formulario *{form.title}* ya está en estado `{form.status}`.\n"
                "Solo se puede abrir desde `draft` o `closed`."
            )
            return True

        questions = db.query(models.FormQuestion).filter_by(form_id=form.id).count()
        if questions == 0:
            wa.send_text(
                chat_id,
                f"❌ El formulario *{form.title}* no tiene preguntas.\n"
                "Agrega preguntas antes de abrirlo."
            )
            return True

        form.status = "open"
        form.opens_at = datetime.utcnow()
        db.commit()

        wa.send_text(chat_id, f"✅ Formulario *{form.title}* abierto. Notificando a la audiencia...")
        _notify_form_open(form, db)
        wa.send_text(chat_id, _format_instructions(form))
        return True

    # ── /form close <id> ──────────────────────────────────────────────────
    if sub == "close" or sub == "cerrar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form close <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status != "open":
            wa.send_text(chat_id, f"⚠️ El formulario no está abierto (estado: `{form.status}`).")
            return True

        form.status = "closed"
        db.commit()

        # Remove pending form_respond sessions for this form
        _cleanup_form_sessions(form.id, db)
        _notify_form_close(form, db)
        sub_count = db.query(models.FormSubmission).filter_by(
            form_id=form.id, status="submitted"
        ).count()
        wa.send_text(
            chat_id,
            f"🔒 Formulario *{form.title}* cerrado.\n"
            f"Total de respuestas: *{sub_count}*\n\n"
            f"Ver resultados: `/form results {form.id}`"
        )
        return True

    # ── /form archive <id> ────────────────────────────────────────────────
    if sub == "archive" or sub == "archivar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form archive <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status != "closed":
            wa.send_text(chat_id, f"⚠️ Solo se pueden archivar formularios cerrados (estado actual: `{form.status}`).")
            return True

        form.status = "archived"
        form.archived_at = datetime.utcnow()
        db.commit()
        wa.send_text(chat_id, f"🗄️ Formulario *{form.title}* archivado.")
        return True

    # ── /form results <id> ────────────────────────────────────────────────
    if sub == "results" or sub == "resultados":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form results <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para ver ese formulario.")
            return True

        from app.utils.form_report import send_form_report
        send_form_report(form, chat_id, db)
        return True

    # ── /form report <id> ─────────────────────────────────────────────────
    if sub == "report" or sub == "reporte":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form report <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para ver ese formulario.")
            return True

        from app.utils.form_report import send_form_summary
        send_form_summary(form, chat_id, db)
        return True

    # ── /form ai <id> <question> ──────────────────────────────────────────
    if sub == "ai":
        rest = parts[2].strip() if len(parts) > 2 else ""
        ai_parts = rest.split(None, 1)
        fid = ai_parts[0] if ai_parts else ""
        question = ai_parts[1].strip() if len(ai_parts) > 1 else ""

        if not fid.isdigit() or not question:
            wa.send_text(chat_id, "Uso: `/form ai <id> <pregunta>`\nEj: `/form ai 1 ¿cuántos niños tienen alergias?`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para ver ese formulario.")
            return True

        from app.utils.form_report import form_ai_analysis
        await form_ai_analysis(form, question, chat_id, db)
        return True

    # ── /form append ──────────────────────────────────────────────────────
    if sub == "append":
        code = _generate_reader_code(db)
        db.add(models.FormReader(code=code))
        db.commit()
        wa.send_text(
            chat_id,
            f"🔑 *Código de lector de formularios generado:*\n\n"
            f"`{code}`\n\n"
            "Compártelo con quien quieras. Deben enviarte al bot:\n"
            f"`/form join {code}`",
        )
        return True

    # ── /form readers ─────────────────────────────────────────────────────
    if sub == "readers" or sub == "lectores":
        readers = db.query(models.FormReader).all()
        if not readers:
            wa.send_text(chat_id, "📋 _No hay lectores registrados._")
            return True
        lines = ["📋 *Lectores de formularios:*\n"]
        for r in readers:
            if r.jid:
                lines.append(f"  ✅ {r.name or r.jid} — `{r.code}`")
            else:
                lines.append(f"  ⏳ _(pendiente)_ — `{r.code}`")
        wa.send_text(chat_id, "\n".join(lines))
        return True

    # ── /form fill <code|id> ──────────────────────────────────────────────
    if sub == "fill" or sub == "llenar" or sub == "responder":
        arg = parts[2].strip() if len(parts) > 2 else ""
        if not arg:
            wa.send_text(chat_id, "Uso: `/form fill <código>` o `/form fill <id>`")
            return True

        # Accept both FORM-XXXXX code and numeric ID
        if arg.upper().startswith("FORM-"):
            form = db.query(models.Form).filter_by(form_code=arg.upper()).first()
        elif arg.isdigit():
            form = db.query(models.Form).get(int(arg))
        else:
            form = None

        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con código/ID `{arg}`.")
            return True

        if form.status != "open":
            wa.send_text(chat_id, f"⚠️ El formulario *{form.title}* no está abierto (estado: `{form.status}`).")
            return True

        from app.bot import form_flow
        await form_flow.start_from_code(chat_id, chat_id, form.form_code, db, admin_override=True)
        return True

    # ── /form questions <id> ──────────────────────────────────────────────
    if sub == "questions" or sub == "preguntas":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form questions <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para ver ese formulario.")
            return True

        questions = (
            db.query(models.FormQuestion)
            .filter_by(form_id=form.id)
            .order_by(models.FormQuestion.order)
            .all()
        )
        if not questions:
            wa.send_text(chat_id, f"📋 El formulario *{form.title}* no tiene preguntas.")
            return True

        lines = [f"📋 *{form.title}* — preguntas ({form.status}):\n"]
        for q in questions:
            t = _TYPE_LABELS.get(q.type, q.type)
            opts = ""
            if q.options:
                opts = " (" + ", ".join(q.options) + ")"
            req = "" if q.required else " *(opcional)*"
            hint_txt = f"\n     _{q.hint}_" if q.hint else ""
            lines.append(f"  *{q.order}.* {q.text} [{t}{opts}{req}]{hint_txt}")

        lines.append(
            f"\nEditar pregunta: `/form editq {form.id} <num>`\n"
            f"Borrar pregunta: `/form delq {form.id} <num>`\n"
            f"Añadir pregunta: `/form addq {form.id}`"
        )
        wa.send_text(chat_id, "\n".join(lines))
        return True

    # ── /form delq <id> <num> ─────────────────────────────────────────────
    if sub == "delq":
        args = (parts[2] if len(parts) > 2 else "").split()
        if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
            wa.send_text(chat_id, "Uso: `/form delq <form_id> <num_pregunta>`")
            return True

        form = db.query(models.Form).get(int(args[0]))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{args[0]}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        q_num = int(args[1])
        question = (
            db.query(models.FormQuestion)
            .filter_by(form_id=form.id, order=q_num)
            .first()
        )
        if not question:
            wa.send_text(chat_id, f"❓ No encontré la pregunta *{q_num}* en el formulario.")
            return True

        # Cascade: delete all answers for this question
        answer_count = db.query(models.FormAnswer).filter_by(question_id=question.id).count()
        db.query(models.FormAnswer).filter_by(question_id=question.id).delete()

        q_text = question.text
        db.delete(question)
        db.flush()

        # Re-order remaining questions
        remaining = (
            db.query(models.FormQuestion)
            .filter_by(form_id=form.id)
            .order_by(models.FormQuestion.order)
            .all()
        )
        for i, q in enumerate(remaining, 1):
            q.order = i
        db.commit()

        msg = f"🗑️ Pregunta *{q_num}* eliminada: _{q_text}_"
        if answer_count:
            msg += f"\n⚠️ Se eliminaron *{answer_count}* respuesta(s) existentes."
        wa.send_text(chat_id, msg)
        return True

    # ── /form addq <id> ───────────────────────────────────────────────────
    if sub == "addq":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form addq <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status not in ("draft", "open"):
            wa.send_text(chat_id, f"❌ No se pueden agregar preguntas a un formulario en estado `{form.status}`.")
            return True

        existing = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
        if existing:
            db.delete(existing)
            db.flush()

        max_order = db.query(models.FormQuestion).filter_by(form_id=form.id).count()
        session = models.ConversationSession(
            chat_jid=chat_id,
            flow="form_addq",
            step="awaiting_q_text",
            data={"form_id": form.id, "next_order": max_order + 1},
        )
        db.add(session)
        db.commit()

        wa.send_text(
            chat_id,
            f"📋 *Agregar pregunta a:* _{form.title}_\n\n"
            "Escribe el *texto de la nueva pregunta*.\n"
            "O escribe `cancelar` para salir.",
        )
        return True

    # ── /form editq <id> <num> ────────────────────────────────────────────
    if sub == "editq":
        args = (parts[2] if len(parts) > 2 else "").split()
        if len(args) < 2 or not args[0].isdigit() or not args[1].isdigit():
            wa.send_text(chat_id, "Uso: `/form editq <form_id> <num_pregunta>`")
            return True

        form = db.query(models.Form).get(int(args[0]))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{args[0]}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status not in ("draft", "open"):
            wa.send_text(chat_id, f"❌ No se puede editar un formulario en estado `{form.status}`.")
            return True

        q_num = int(args[1])
        question = (
            db.query(models.FormQuestion)
            .filter_by(form_id=form.id, order=q_num)
            .first()
        )
        if not question:
            wa.send_text(chat_id, f"❓ No encontré la pregunta *{q_num}* en el formulario.")
            return True

        existing = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
        if existing:
            db.delete(existing)
            db.flush()

        session = models.ConversationSession(
            chat_jid=chat_id,
            flow="form_editq",
            step="awaiting_edit_text",
            data={
                "form_id": form.id,
                "question_id": question.id,
                "q_num": q_num,
                "q_type": question.type,
            },
        )
        db.add(session)
        db.commit()

        t = _TYPE_LABELS.get(question.type, question.type)
        opts = ""
        if question.options:
            opts = "\n   Opciones: " + ", ".join(question.options)
        hint_txt = f"\n   Nota: _{question.hint}_" if question.hint else ""
        req = "Sí" if question.required else "No"

        wa.send_text(
            chat_id,
            f"✏️ *Editando pregunta {q_num}:*\n\n"
            f"   Texto: _{question.text}_\n"
            f"   Tipo: {t}{opts}{hint_txt}\n"
            f"   Obligatoria: {req}\n\n"
            "¿Nuevo texto para la pregunta? (o `skip` para conservar):",
        )
        return True

    # ── /form delete <id> ─────────────────────────────────────────────────
    if sub == "delete" or sub == "eliminar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form delete <id>`")
            return True

        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return True

        if not _check_form_access(form, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar ese formulario.")
            return True

        if form.status != "draft":
            wa.send_text(
                chat_id,
                f"❌ Solo se pueden eliminar formularios en borrador.\n"
                f"Usa `close` primero o `archive` si ya está cerrado."
            )
            return True

        db.delete(form)
        db.commit()
        wa.send_text(chat_id, f"🗑️ Formulario *{form.title}* eliminado.")
        return True

    wa.send_text(chat_id, _HELP)
    return True


# ── Conversation handler ───────────────────────────────────────────────────────

async def handle_conversation(
    raw_jid: str, chat_id: str, text: str, db: Session,
    session: models.ConversationSession,
):
    """Drive the form_create state machine."""
    data: dict = session.data or {}
    step = session.step
    text = text.strip()

    # Universal cancel
    if text.lower() in ("cancelar", "cancel", "/cancelar"):
        db.delete(session)
        db.commit()
        wa.send_text(chat_id, "❌ Creación de formulario cancelada.")
        return

    # ── awaiting_title ────────────────────────────────────────────────────
    if step == "awaiting_title":
        if len(text) < 3:
            wa.send_text(chat_id, "El título debe tener al menos 3 caracteres.")
            return
        data["title"] = text
        _advance(session, "awaiting_purpose", data, db)
        wa.send_text(
            chat_id,
            "¿Cuál es el *propósito* del formulario?\n\n"
            "  `1` — Datos / Perfil\n"
            "  `2` — Encuesta\n"
            "  `3` — Registro de evento\n"
            "  `4` — Voluntariado\n\n"
            "Responde *1*, *2*, *3* o *4*:",
        )

    # ── awaiting_purpose ─────────────────────────────────────────────────
    elif step == "awaiting_purpose":
        purpose = _PURPOSE_MAP.get(text)
        if not purpose:
            wa.send_text(chat_id, "Responde *1*, *2*, *3* o *4*:")
            return
        data["purpose"] = purpose
        _advance(session, "awaiting_description", data, db)
        wa.send_text(
            chat_id,
            "Escribe una *descripción breve* del formulario (aparece en la notificación a los padres).\n"
            "O escribe `skip` para omitir.",
        )

    # ── awaiting_description ──────────────────────────────────────────────
    elif step == "awaiting_description":
        data["description"] = "" if text.lower() == "skip" else text
        _advance(session, "awaiting_audience", data, db)
        # List available classrooms (filtered if non-super-admin)
        allowed = data.get("allowed_classroom_ids")
        if allowed:
            classrooms = db.query(models.Classroom).filter(
                models.Classroom.id.in_(allowed), models.Classroom.is_active == True
            ).all()
        else:
            classrooms = db.query(models.Classroom).filter_by(is_active=True).all()
        if classrooms:
            cls_list = "\n".join(f"  `{c.id}` — {c.name}" for c in classrooms)
            wa.send_text(
                chat_id,
                f"¿A qué *salones* va dirigido este formulario?\n\n"
                f"Salones disponibles:\n{cls_list}\n\n"
                "Envía los IDs separados por comas (ej: `1, 3, 5`) o `todos` para incluir todos.",
            )
        else:
            wa.send_text(
                chat_id,
                "¿A qué *salones* va dirigido?\n"
                "Envía los IDs separados por comas o `todos`.",
            )

    # ── awaiting_audience ─────────────────────────────────────────────────
    elif step == "awaiting_audience":
        allowed = data.get("allowed_classroom_ids")  # None = super admin, list = restricted
        if text.lower() in ("todos", "all"):
            if allowed:
                audience_ids = allowed
            else:
                classrooms = db.query(models.Classroom).filter_by(is_active=True).all()
                audience_ids = [c.id for c in classrooms]
        else:
            raw_ids = [x.strip() for x in text.replace(",", " ").split()]
            audience_ids = []
            invalid = []
            for rid in raw_ids:
                if rid.isdigit():
                    cid = int(rid)
                    if allowed and cid not in allowed:
                        invalid.append(f"{rid} (no permitido)")
                        continue
                    cls = db.query(models.Classroom).get(cid)
                    if cls:
                        audience_ids.append(cid)
                    else:
                        invalid.append(rid)
                else:
                    invalid.append(rid)

            if invalid:
                wa.send_text(
                    chat_id,
                    f"⚠️ IDs inválidos o no permitidos: {', '.join(invalid)}\n"
                    "Intenta de nuevo con IDs válidos:",
                )
                return

            if not audience_ids:
                wa.send_text(chat_id, "Debes incluir al menos un salón.")
                return

        data["audience"] = audience_ids
        _advance(session, "awaiting_group_reminders", data, db)
        wa.send_text(
            chat_id,
            "¿Deseas enviar *recordatorios al grupo* de WhatsApp cuando quedan padres sin responder?\n\n"
            "Responde *si* o *no*:",
        )

    # ── awaiting_group_reminders ──────────────────────────────────────────
    elif step == "awaiting_group_reminders":
        if text.lower() in ("si", "sí", "yes", "s"):
            data["send_group_reminders"] = True
            _advance(session, "awaiting_reminder_interval", data, db)
            wa.send_text(
                chat_id,
                "¿Cada cuántos días recordar a los padres que no han respondido?\n"
                "Escribe un número (ej: `2` para cada 2 días):",
            )
        elif text.lower() in ("no", "n"):
            data["send_group_reminders"] = False
            data["reminder_interval_days"] = 0
            _advance(session, "awaiting_questions", data, db)
            data.setdefault("questions", [])
            _prompt_add_question(chat_id, data)
        else:
            wa.send_text(chat_id, "Responde *si* o *no*:")

    # ── awaiting_reminder_interval ────────────────────────────────────────
    elif step == "awaiting_reminder_interval":
        if not text.isdigit() or int(text) < 1:
            wa.send_text(chat_id, "Ingresa un número entero positivo (ej: `2`):")
            return
        data["reminder_interval_days"] = int(text)
        data.setdefault("questions", [])
        _advance(session, "awaiting_questions", data, db)
        _prompt_add_question(chat_id, data)

    # ── awaiting_questions (loop entry) ───────────────────────────────────
    elif step == "awaiting_questions":
        if text.lower() in ("listo", "done", "fin"):
            if not data.get("questions"):
                wa.send_text(chat_id, "❌ Debes agregar al menos una pregunta.")
                return
            _advance(session, "awaiting_open_schedule", data, db)
            wa.send_text(
                chat_id,
                "¿Cuándo deseas abrir el formulario?\n\n"
                "  `1` — Abrir ahora\n"
                "  `2` — Guardar como borrador (abrir manualmente después)\n\n"
                "Responde *1* o *2*:",
            )
        else:
            # Start adding a new question
            data["current_q_text"] = text
            data["current_q_type"] = None
            _advance(session, "awaiting_q_type", data, db)
            wa.send_text(
                chat_id,
                f"Pregunta *{len(data.get('questions', [])) + 1}*: _{text}_\n\n"
                "¿Qué tipo de respuesta?\n\n"
                "  `1` — Sí/No\n"
                "  `2` — Texto corto\n"
                "  `3` — Opción única (menú de opciones)\n\n"
                "Responde *1*, *2* o *3*:",
            )

    # ── awaiting_q_type ───────────────────────────────────────────────────
    elif step == "awaiting_q_type":
        q_type = _TYPE_MAP.get(text)
        if not q_type:
            wa.send_text(chat_id, "Responde *1*, *2* o *3*:")
            return

        data["current_q_type"] = q_type

        if q_type == "single_choice":
            data["current_q_options_raw"] = []
            _advance(session, "awaiting_q_options", data, db)
            wa.send_text(
                chat_id,
                "Envía las *opciones*, una por línea:\n\n"
                "Ej:\n  Opción A\n  Opción B\n  Opción C\n\n"
                "Cuando termines, escribe `listo`.",
            )
        else:
            _advance(session, "awaiting_q_required", data, db)
            wa.send_text(chat_id, "¿Es esta pregunta *obligatoria*?\n\n  *si* — el padre debe responderla\n  *no* — puede dejarla en blanco")

    # ── awaiting_q_options ────────────────────────────────────────────────
    elif step == "awaiting_q_options":
        if text.lower() in ("listo", "done", "fin"):
            opts = data.get("current_q_options_raw", [])
            if not opts:
                wa.send_text(chat_id, "❌ Debes agregar al menos una opción.")
                return
            _advance(session, "awaiting_q_required", data, db)
            wa.send_text(chat_id, "¿Es esta pregunta *obligatoria*?\n\n  *si* — el padre debe responderla\n  *no* — puede dejarla en blanco")
        else:
            # Each message line is one option (or multiple lines in one message)
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            data.setdefault("current_q_options_raw", []).extend(lines)
            flag_modified(session, "data")
            db.commit()
            count = len(data["current_q_options_raw"])
            wa.send_text(
                chat_id,
                f"✅ {count} opción(es) registradas.\n"
                "Agrega más o escribe `listo` para continuar.",
            )

    # ── awaiting_q_required ───────────────────────────────────────────────
    elif step == "awaiting_q_required":
        if text.lower() in ("si", "sí", "yes", "s"):
            data["current_q_required"] = True
        elif text.lower() in ("no", "n"):
            data["current_q_required"] = False
        else:
            wa.send_text(chat_id, "Responde *si* (obligatoria) o *no* (opcional):")
            return
        _advance(session, "awaiting_q_hint", data, db)
        wa.send_text(
            chat_id,
            "¿Deseas agregar una *nota de ayuda* para esta pregunta?\n"
            "_(Se mostrará en cursiva debajo del texto de la pregunta)_\n\n"
            "Escribe la nota o `skip` para omitir.",
        )

    # ── awaiting_q_hint ───────────────────────────────────────────────────
    elif step == "awaiting_q_hint":
        data["current_q_hint"] = None if text.lower() in ("skip", "omitir", "no") else text

        if session.flow == "form_addq":
            # Persist question directly to the form
            form_id = data["form_id"]
            order = data.get("next_order", 1)
            db.add(models.FormQuestion(
                form_id=form_id,
                order=order,
                text=data.pop("current_q_text", ""),
                hint=data.get("current_q_hint"),
                type=data.pop("current_q_type", "text"),
                answer_scope="parent",
                required=data.pop("current_q_required", True),
                options=data.pop("current_q_options_raw", None) or None,
            ))
            data["next_order"] = order + 1
            data.pop("current_q_hint", None)
            _advance(session, "awaiting_q_text", data, db)
            form = db.query(models.Form).get(form_id)
            q_count = db.query(models.FormQuestion).filter_by(form_id=form_id).count()
            wa.send_text(
                chat_id,
                f"✅ Pregunta {order} guardada. El formulario tiene *{q_count}* pregunta(s).\n\n"
                "Escribe el texto de la siguiente pregunta o `listo` para terminar.\n"
                "O `cancelar` para salir.",
            )
        else:
            _save_current_question(data)
            _advance(session, "awaiting_questions", data, db)
            _prompt_add_question(chat_id, data)

    # ── awaiting_open_schedule ────────────────────────────────────────────
    elif step == "awaiting_open_schedule":
        if text == "1":
            data["open_now"] = True
        elif text == "2":
            data["open_now"] = False
        else:
            wa.send_text(chat_id, "Responde *1* (ahora) o *2* (borrador):")
            return
        _advance(session, "confirm", data, db)
        _send_form_summary(chat_id, data, db)

    # ── confirm ───────────────────────────────────────────────────────────
    elif step == "confirm":
        if text.lower() in ("confirmar", "confirm", "si", "sí", "yes"):
            _create_form(chat_id, data, db, session)
        elif text.lower() in ("no", "cancelar", "cancel"):
            db.delete(session)
            db.commit()
            wa.send_text(chat_id, "❌ Creación de formulario cancelada.")
        else:
            wa.send_text(chat_id, "Responde *confirmar* para guardar o *cancelar* para cancelar.")

    # ══ form_addq flow ════════════════════════════════════════════════════

    # ── addq: awaiting_q_text ─────────────────────────────────────────────
    elif step == "awaiting_q_text":
        if text.lower() in ("listo", "done", "fin"):
            form_id = data["form_id"]
            q_count = db.query(models.FormQuestion).filter_by(form_id=form_id).count()
            db.delete(session)
            db.commit()
            form = db.query(models.Form).get(form_id)
            wa.send_text(
                chat_id,
                f"✅ Listo. El formulario *{form.title if form else form_id}* "
                f"ahora tiene *{q_count}* pregunta(s).\n\n"
                f"Ver preguntas: `/form questions {form_id}`",
            )
            return

        data["current_q_text"] = text
        data["current_q_type"] = None
        _advance(session, "awaiting_q_type", data, db)
        wa.send_text(
            chat_id,
            f"Pregunta: _{text}_\n\n"
            "¿Qué tipo de respuesta?\n\n"
            "  `1` — Sí/No\n"
            "  `2` — Texto corto\n"
            "  `3` — Opción única (menú de opciones)\n\n"
            "Responde *1*, *2* o *3*:",
        )

    # ══ form_editq flow ════════════════════════════════════════════════════

    # ── editq: awaiting_edit_text ─────────────────────────────────────────
    elif step == "awaiting_edit_text":
        if text.lower() not in ("skip", "omitir"):
            data["new_text"] = text
        _advance(session, "awaiting_edit_hint", data, db)
        q = db.query(models.FormQuestion).get(data["question_id"])
        current_hint = q.hint if q else None
        hint_display = f"_{current_hint}_" if current_hint else "_(ninguna)_"
        wa.send_text(
            chat_id,
            f"Nota de ayuda actual: {hint_display}\n\n"
            "¿Nueva nota? (o `skip` para conservar, `borrar` para eliminarla):",
        )

    # ── editq: awaiting_edit_hint ─────────────────────────────────────────
    elif step == "awaiting_edit_hint":
        t = text.lower()
        if t in ("skip", "omitir"):
            pass  # keep current
        elif t in ("borrar", "delete", "none", "ninguna"):
            data["new_hint"] = None
            data["hint_set"] = True
        else:
            data["new_hint"] = text
            data["hint_set"] = True

        q = db.query(models.FormQuestion).get(data["question_id"])
        current_req = q.required if q else True
        req_display = "Sí" if current_req else "No"
        _advance(session, "awaiting_edit_required", data, db)
        wa.send_text(
            chat_id,
            f"¿Obligatoria? Actualmente: *{req_display}*\n\n"
            "  *si* — obligatoria\n"
            "  *no* — opcional\n"
            "  *skip* — conservar",
        )

    # ── editq: awaiting_edit_required ─────────────────────────────────────
    elif step == "awaiting_edit_required":
        t = text.lower()
        if t in ("si", "sí", "yes", "s"):
            data["new_required"] = True
        elif t in ("no", "n"):
            data["new_required"] = False
        elif t in ("skip", "omitir"):
            pass
        else:
            wa.send_text(chat_id, "Responde *si*, *no* o *skip*:")
            return

        q_type = data.get("q_type")
        if q_type == "single_choice":
            q = db.query(models.FormQuestion).get(data["question_id"])
            current_opts = ", ".join(q.options) if q and q.options else "_(ninguna)_"
            _advance(session, "awaiting_edit_options", data, db)
            wa.send_text(
                chat_id,
                f"Opciones actuales: {current_opts}\n\n"
                "Envía las nuevas opciones *una por línea* y luego `listo`,\n"
                "o escribe `skip` para conservar las actuales.",
            )
        else:
            _apply_edit(session, data, db)
            wa.send_text(chat_id, "✅ Pregunta actualizada.")

    # ── editq: awaiting_edit_options ──────────────────────────────────────
    elif step == "awaiting_edit_options":
        if text.lower() in ("skip", "omitir"):
            _apply_edit(session, data, db)
            wa.send_text(chat_id, "✅ Pregunta actualizada.")
        elif text.lower() in ("listo", "done", "fin"):
            opts = data.get("new_options_raw", [])
            if not opts:
                wa.send_text(chat_id, "❌ Debes agregar al menos una opción.")
                return
            data["new_options"] = opts
            _apply_edit(session, data, db)
            wa.send_text(chat_id, "✅ Pregunta actualizada.")
        else:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            data.setdefault("new_options_raw", []).extend(lines)
            flag_modified(session, "data")
            db.commit()
            count = len(data["new_options_raw"])
            wa.send_text(
                chat_id,
                f"✅ {count} opción(es). Agrega más o escribe `listo`.",
            )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()


def _save_current_question(data: dict):
    """Move current_q_* temps into the questions list."""
    q = {
        "text": data.pop("current_q_text", ""),
        "hint": data.pop("current_q_hint", None),
        "type": data.pop("current_q_type", "text"),
        "options": data.pop("current_q_options_raw", None) or None,
        "required": data.pop("current_q_required", True),
        "answer_scope": "parent",
        "order": len(data.get("questions", [])) + 1,
    }
    data.setdefault("questions", []).append(q)


def _apply_edit(session: models.ConversationSession, data: dict, db: Session):
    """Apply collected edits to the FormQuestion and close the session."""
    q = db.query(models.FormQuestion).get(data["question_id"])
    if q:
        if "new_text" in data:
            q.text = data["new_text"]
        if data.get("hint_set"):
            q.hint = data.get("new_hint")
        if "new_required" in data:
            q.required = data["new_required"]
        if "new_options" in data:
            q.options = data["new_options"]
            # Cascade: delete existing answers for this question since options changed
            deleted = db.query(models.FormAnswer).filter_by(question_id=q.id).delete()
            if deleted:
                logger.info("FORM editq: deleted %d answers for question_id=%d (options changed)", deleted, q.id)
    db.delete(session)
    db.commit()


def _generate_form_code(db: Session) -> str:
    """Generate a unique short form code like FORM-XK4M2."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(5))
        code = f"FORM-{suffix}"
        if not db.query(models.Form).filter_by(form_code=code).first():
            return code


def _format_instructions(form: models.Form) -> str:
    """Return a copyable instructions block with the wa.me deep link."""
    from app.config import get_settings
    bot_phone = get_settings().waha_bot_phone
    wa_link = f"https://wa.me/{bot_phone}?text={form.form_code}"
    purpose_label = _PURPOSE_LABELS.get(form.purpose, form.purpose)

    return (
        f"📢 *Cómo compartir este formulario:*\n\n"
        f"Código: `{form.form_code}`\n"
        f"ID: `{form.id}` | {purpose_label}\n\n"
        f"📲 *Enlace directo* (toca para abrir en WhatsApp):\n"
        f"{wa_link}\n\n"
        f"💬 *Mensaje para copiar y pegar:*\n"
        f"─────────────────────\n"
        f"📋 El colegio te envió un formulario:\n"
        f"*{form.title}*\n\n"
        f"Toca el enlace para responder:\n"
        f"{wa_link}\n"
        f"─────────────────────"
    )


def _prompt_add_question(chat_id: str, data: dict):
    q_num = len(data.get("questions", [])) + 1
    if data.get("questions"):
        done_txt = "O escribe `listo` si ya terminaste."
    else:
        done_txt = ""
    wa.send_text(
        chat_id,
        f"Pregunta *{q_num}* — escribe el texto de la pregunta.\n{done_txt}",
    )


def _send_form_summary(chat_id: str, data: dict, db: Session):
    """Send confirmation summary before creating the form."""
    audience = data.get("audience", [])
    cls_names = []
    for cid in audience:
        cls = db.query(models.Classroom).get(cid)
        cls_names.append(cls.name if cls else str(cid))

    questions = data.get("questions", [])
    q_lines = []
    for i, q in enumerate(questions, 1):
        t = _TYPE_LABELS.get(q["type"], q["type"])
        opts = ""
        if q.get("options"):
            opts = " (" + ", ".join(q["options"]) + ")"
        req = "" if q.get("required", True) else " *(opcional)*"
        hint_txt = f"\n     _{q['hint']}_" if q.get("hint") else ""
        q_lines.append(f"  {i}. {q['text']} [{t}{opts}{req}]{hint_txt}")

    open_status = "Ahora" if data.get("open_now") else "Borrador"
    reminders = "Sí" if data.get("send_group_reminders") else "No"
    interval = data.get("reminder_interval_days", 2)

    summary = (
        f"📋 *Resumen del formulario:*\n\n"
        f"  • Título: *{data['title']}*\n"
        f"  • Propósito: {_PURPOSE_LABELS.get(data['purpose'], data['purpose'])}\n"
        f"  • Descripción: _{data.get('description') or '(ninguna)'}_\n"
        f"  • Salones: {', '.join(cls_names)}\n"
        f"  • Recordatorios al grupo: {reminders}"
    )
    if data.get("send_group_reminders"):
        summary += f" (cada {interval} días)"
    summary += f"\n  • Apertura: {open_status}\n\n"
    summary += "*Preguntas:*\n" + "\n".join(q_lines)
    summary += "\n\n¿Confirmar? Responde *confirmar* o *cancelar*."
    wa.send_text(chat_id, summary)


def _create_form(chat_id: str, data: dict, db: Session, session: models.ConversationSession):
    """Persist the form and all related records."""
    open_now = data.get("open_now", False)
    form = models.Form(
        title=data["title"],
        description=data.get("description") or None,
        purpose=data["purpose"],
        status="open" if open_now else "draft",
        form_code=_generate_form_code(db),
        created_by_jid=chat_id,
        opens_at=datetime.utcnow() if open_now else None,
        send_group_reminders=data.get("send_group_reminders", True),
        reminder_interval_days=data.get("reminder_interval_days", 2),
    )
    db.add(form)
    db.flush()

    # Questions
    for q in data.get("questions", []):
        db.add(models.FormQuestion(
            form_id=form.id,
            order=q["order"],
            text=q["text"],
            hint=q.get("hint"),
            type=q["type"],
            answer_scope=q["answer_scope"],
            required=q["required"],
            options=q.get("options"),
        ))

    # Audience
    for cid in data.get("audience", []):
        db.add(models.FormAudience(form_id=form.id, classroom_id=cid))

    db.delete(session)
    db.commit()

    status_line = "Notificando a la audiencia..." if open_now else f"Para abrirlo: `/form open {form.id}`"
    wa.send_text(
        chat_id,
        f"✅ *Formulario creado* (ID `{form.id}`).\n\n"
        f"Título: *{form.title}*\n"
        f"Estado: *{form.status}*\n\n"
        f"{status_line}",
    )

    if open_now:
        _notify_form_open(form, db)
        wa.send_text(chat_id, _format_instructions(form))
    else:
        # Show instructions even for drafts so admin can copy the link for later
        wa.send_text(chat_id, _format_instructions(form))


def _parents_in_audience(classroom_ids: list[int], db: Session) -> list[models.Parent]:
    """
    Return all active registered parents who have at least one student
    in any of the given classroom IDs.
    Uses student membership, not parent.classroom_id, to cover multi-classroom families.
    """
    students = db.query(models.Student).filter(
        models.Student.classroom_id.in_(classroom_ids)
    ).all()
    parent_ids = {s.parent_id for s in students if s.parent_id}
    if not parent_ids:
        return []
    return db.query(models.Parent).filter(
        models.Parent.id.in_(parent_ids),
        models.Parent.is_active == True,
    ).all()


def _notify_form_open(form: models.Form, db: Session):
    """No automatic notifications — admin shares the form code manually."""
    audience_rows = db.query(models.FormAudience).filter_by(form_id=form.id).all()
    classroom_ids = [a.classroom_id for a in audience_rows]
    logger.info("FORM opened form_id=%d audience_classrooms=%s (no auto-notifications)", form.id, classroom_ids)


def _notify_form_close(form: models.Form, db: Session):
    """Send close notification to linked groups."""
    if not form.send_group_reminders:
        return

    audience_rows = db.query(models.FormAudience).filter_by(form_id=form.id).all()
    classroom_ids = [a.classroom_id for a in audience_rows]

    total_audience = len(_parents_in_audience(classroom_ids, db))

    submitted = db.query(models.FormSubmission).filter_by(
        form_id=form.id, status="submitted"
    ).count()

    for cid in classroom_ids:
        cls = db.query(models.Classroom).get(cid)
        if cls and cls.whatsapp_group_id:
            wa.send_text(
                cls.whatsapp_group_id,
                f"🔒 *Formulario cerrado:* _{form.title}_\n"
                f"Respuestas recibidas: *{submitted}* de {total_audience} padres.",
            )


def _cleanup_form_sessions(form_id: int, db: Session):
    """Delete form_respond ConversationSessions pointing to this form."""
    sessions = db.query(models.ConversationSession).filter_by(flow="form_respond").all()
    for s in sessions:
        if (s.data or {}).get("form_id") == form_id:
            db.delete(s)
    db.commit()


async def handle_join(raw_jid: str, chat_id: str, text: str, db: Session):
    """Handle /form join <code> from any DM sender."""
    parts = text.strip().lstrip("/").split(None, 2)
    code = parts[2].strip().upper() if len(parts) > 2 else ""
    if not code:
        wa.send_text(chat_id, "Uso: `/form join <código>`")
        return

    reader = db.query(models.FormReader).filter_by(code=code).first()
    if not reader:
        wa.send_text(chat_id, "❌ Código inválido. Pide uno nuevo al administrador.")
        return
    if reader.jid and reader.jid != raw_jid:
        wa.send_text(chat_id, "⚠️ Este código ya fue usado.")
        return

    if not reader.jid:
        reader.jid = raw_jid
        reader.joined_at = datetime.utcnow()
        db.commit()

    wa.send_text(
        chat_id,
        "✅ *¡Acceso de lectura activado!*\n\n"
        "Ahora puedes consultar formularios:\n"
        "  `/form list` — ver todos los formularios\n"
        "  `/form results <id>` — ver resultados de un formulario",
    )


async def handle_reader_command(raw_jid: str, chat_id: str, text: str, db: Session):
    """Handle /form list and /form results <id> for form readers."""
    parts = text.strip().lstrip("/").split(None, 2)
    sub = parts[1].lower() if len(parts) > 1 else ""

    if sub in ("list", "lista"):
        forms = db.query(models.Form).order_by(models.Form.created_at.desc()).all()
        if not forms:
            wa.send_text(chat_id, "📋 _No hay formularios registrados._")
            return
        lines = ["📋 *Formularios:*\n"]
        status_icons = {"draft": "📝", "open": "✅", "closed": "🔒", "archived": "🗄️"}
        for f in forms:
            icon = status_icons.get(f.status, "❓")
            sub_count = db.query(models.FormSubmission).filter_by(
                form_id=f.id, status="submitted"
            ).count()
            lines.append(
                f"{icon} [ID `{f.id}`] *{f.title}*\n"
                f"   {_PURPOSE_LABELS.get(f.purpose, f.purpose)} — {f.status} — {sub_count} respuestas"
            )
        wa.send_text(chat_id, "\n".join(lines))

    elif sub in ("results", "resultados"):
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/form results <id>`")
            return
        form = db.query(models.Form).get(int(fid))
        if not form:
            wa.send_text(chat_id, f"❓ No encontré formulario con ID `{fid}`.")
            return
        from app.utils.form_report import send_form_report
        send_form_report(form, chat_id, db)

    else:
        wa.send_text(
            chat_id,
            "📋 *Comandos disponibles:*\n\n"
            "  `/form list` — ver todos los formularios\n"
            "  `/form results <id>` — ver resultados de un formulario",
        )


def _generate_reader_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "READ-" + "".join(secrets.choice(alphabet) for _ in range(5))
        if not db.query(models.FormReader).filter_by(code=code).first():
            return code


_HELP = (
    "📋 *Comandos de formularios:*\n\n"
    "  `/form create` — crear nuevo formulario\n"
    "  `/form list` — listar todos los formularios\n"
    "  `/form open <id>` — abrir formulario\n"
    "  `/form close <id>` — cerrar formulario\n"
    "  `/form archive <id>` — archivar formulario cerrado\n"
    "  `/form results <id>` — reporte detallado por pregunta\n"
    "  `/form report <id>` — resumen + CSV en S3\n"
    "  `/form ai <id> <pregunta>` — análisis con IA\n"
    "  `/form fill <código|id>` — responder un formulario abierto\n"
    "  `/form append` — generar código para nuevo lector\n"
    "  `/form readers` — ver lectores registrados\n"
    "  `/form delete <id>` — eliminar borrador\n\n"
    "*Gestión de preguntas:*\n"
    "  `/form questions <id>` — ver preguntas\n"
    "  `/form addq <id>` — agregar pregunta(s)\n"
    "  `/form editq <id> <num>` — editar una pregunta\n"
    "  `/form delq <id> <num>` — eliminar una pregunta"
)
