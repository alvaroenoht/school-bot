"""
form_flow.py — parent-facing form response flow.

Handles ConversationSession with flow="form_respond".

Steps:
    awaiting_start  — parent received invitation, waiting for "1" or "skip"
    answering       — answering questions one by one (uses data["question_index"])
    awaiting_submit — all questions answered, waiting for "yes" / "edit" / "cancel"
    review_edit     — listing Q&A pairs, waiting for question number to re-answer
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

_YES_TOKENS = {"si", "sí", "yes", "s", "y"}
_NO_TOKENS  = {"no", "n"}


async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    session: models.ConversationSession,
):
    """Drive the form_respond state machine."""
    data: dict = session.data or {}
    step = session.step
    text = text.strip()

    form_id = data.get("form_id")
    form = db.query(models.Form).get(form_id) if form_id else None

    # Guard: form was deleted or doesn't exist
    if not form:
        db.delete(session)
        db.commit()
        return

    # ── selecting_student ─────────────────────────────────────────────────
    if step == "selecting_student":
        student_options = data.get("student_options", [])
        class_options = data.get("class_options", {})
        total = len(student_options) or len(class_options)

        if text.isdigit():
            idx = int(text) - 1
            # Parent case: list of student IDs
            if student_options and 0 <= idx < len(student_options):
                data["student_id"] = student_options[idx]
                if form.status != "open":
                    db.delete(session)
                    db.commit()
                    wa.send_text(chat_id, f"⚠️ El formulario *{form.title}* ya no está disponible.")
                    return
                _start_form(raw_jid, chat_id, form, session, data, db)
                return
            # KnownContact case: dict keyed by "1", "2", ...
            if class_options:
                option = class_options.get(text)
                if option:
                    data["student_id"] = option["student_id"]
                    if form.status != "open":
                        db.delete(session)
                        db.commit()
                        wa.send_text(chat_id, f"⚠️ El formulario *{form.title}* ya no está disponible.")
                        return
                    _start_form(raw_jid, chat_id, form, session, data, db)
                    return
        wa.send_text(chat_id, f"Responde con el número (1-{total}).")
        return

    # ── awaiting_start ────────────────────────────────────────────────────
    if step == "awaiting_start":
        if text.lower() in ("skip", "ignorar", "omitir", "cancelar"):
            db.delete(session)
            db.commit()
            wa.send_text(chat_id, "Entendido. Puedes volver a responder el formulario más tarde escribiéndome.")
            return

        if text == "1" or text.lower() in ("si", "sí", "yes", "comenzar", "iniciar", "start"):
            if form.status != "open":
                db.delete(session)
                db.commit()
                wa.send_text(chat_id, f"⚠️ El formulario *{form.title}* ya no está disponible.")
                return
            _start_form(raw_jid, chat_id, form, session, data, db)
        else:
            wa.send_text(
                chat_id,
                f"📋 Formulario pendiente: *{form.title}*\n\n"
                "Responde *1* para comenzar o *skip* para ignorarlo.",
            )

    # ── answering ─────────────────────────────────────────────────────────
    elif step == "answering":
        if form.status != "open":
            wa.send_text(
                chat_id,
                "⚠️ Este formulario ha sido cerrado. Tus respuestas parciales no fueron enviadas.",
            )
            db.delete(session)
            db.commit()
            return

        question_index = data.get("question_index", 0)
        questions = _get_ordered_questions(form, db)

        if question_index >= len(questions):
            # Shouldn't happen, but guard
            _go_to_submit(chat_id, session, data, form, db)
            return

        q = questions[question_index]
        answer_ok, answer_value, error_msg = _validate_answer(text, q)

        if not answer_ok:
            wa.send_text(chat_id, error_msg)
            return

        # Save/update the answer
        submission_id = data.get("submission_id")
        _upsert_answer(submission_id, q.id, answer_value, db)

        # Move to next question or confirm
        next_index = question_index + 1
        return_to_review = data.get("return_to_review", False)

        if return_to_review:
            data["return_to_review"] = False
            data["question_index"] = question_index
            _advance(session, "awaiting_submit", data, db)
            _send_review_summary(chat_id, form, data, questions, db)
        elif next_index < len(questions):
            data["question_index"] = next_index
            _advance(session, "answering", data, db)
            _send_question(chat_id, questions[next_index], next_index + 1, len(questions))
        else:
            _go_to_submit(chat_id, session, data, form, db)

    # ── awaiting_submit ───────────────────────────────────────────────────
    elif step == "awaiting_submit":
        if text.lower() in ("si", "sí", "yes", "enviar", "submit", "confirmar"):
            _submit_form(raw_jid, chat_id, form, session, data, db)

        elif text.lower() in ("editar", "edit", "revisar", "review", "cambiar"):
            questions = _get_ordered_questions(form, db)
            _advance(session, "review_edit", data, db)
            _send_edit_menu(chat_id, form, data, questions, db)

        elif text.lower() in ("cancelar", "cancel", "no"):
            db.delete(session)
            db.commit()
            wa.send_text(
                chat_id,
                "❌ Formulario cancelado. Tus respuestas no fueron guardadas.\n"
                "Puedes volver a comenzar cuando quieras.",
            )
        else:
            wa.send_text(
                chat_id,
                "Responde:\n"
                "  *si* — enviar respuestas\n"
                "  *editar* — cambiar alguna respuesta\n"
                "  *cancelar* — descartar",
            )

    # ── review_edit ───────────────────────────────────────────────────────
    elif step == "review_edit":
        questions = _get_ordered_questions(form, db)

        if text.lower() in ("enviar", "submit", "si", "sí", "yes", "listo"):
            _submit_form(raw_jid, chat_id, form, session, data, db)
            return

        if text.isdigit():
            q_num = int(text)
            if 1 <= q_num <= len(questions):
                target_index = q_num - 1
                data["question_index"] = target_index
                data["return_to_review"] = True
                _advance(session, "answering", data, db)
                q = questions[target_index]
                wa.send_text(chat_id, f"✏️ Editando pregunta {q_num}:")
                _send_question(chat_id, q, q_num, len(questions))
                return

        wa.send_text(
            chat_id,
            f"Envía el *número* de la pregunta que quieres cambiar (1-{len(questions)}),\n"
            "o escribe *enviar* para confirmar tus respuestas.",
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()


def _get_ordered_questions(form: models.Form, db: Session) -> list[models.FormQuestion]:
    return (
        db.query(models.FormQuestion)
        .filter_by(form_id=form.id)
        .order_by(models.FormQuestion.order)
        .all()
    )


def _start_form(
    raw_jid: str,
    chat_id: str,
    form: models.Form,
    session: models.ConversationSession,
    data: dict,
    db: Session,
):
    """Create FormSubmission and start asking questions."""
    parent = db.query(models.Parent).filter_by(whatsapp_jid=raw_jid, is_active=True).first()
    if parent:
        respondent_name = f"{parent.first_name} {parent.last_name}"
    else:
        contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
        respondent_name = contact.name if contact else raw_jid

    # For registered parents: determine which student this submission is for
    target_student_id = data.get("student_id")  # pre-set if coming from selecting_student step
    if parent and target_student_id is None:
        audience_cls_ids = {
            a.classroom_id
            for a in db.query(models.FormAudience).filter_by(form_id=form.id).all()
        }
        students_in_audience = [
            s for s in db.query(models.Student)
            .filter(models.Student.id.in_(parent.student_ids or []))
            .all()
            if s.classroom_id in audience_cls_ids
        ]
        if len(students_in_audience) > 1:
            opts = "\n".join(
                f"  `{i+1}` — {s.name} ({s.grade})"
                for i, s in enumerate(students_in_audience)
            )
            wa.send_text(
                chat_id,
                f"📋 ¿Para cuál de tus hijos/as es el formulario *{form.title}*?\n\n{opts}",
            )
            data["student_options"] = [s.id for s in students_in_audience]
            _advance(session, "selecting_student", data, db)
            return
        elif len(students_in_audience) == 1:
            target_student_id = students_in_audience[0].id

    # For KnownContacts with multiple audience classrooms: show classroom selection
    if not parent and target_student_id is None:
        contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
        audience_cls_ids = [
            a.classroom_id
            for a in db.query(models.FormAudience).filter_by(form_id=form.id).all()
        ]
        if len(audience_cls_ids) > 1:
            class_entries = []
            for cid in sorted(audience_cls_ids):
                cls = db.query(models.Classroom).get(cid)
                if cls and cls.is_active:
                    rep_student = db.query(models.Student).filter_by(classroom_id=cid).first()
                    class_entries.append((cls, rep_student.id if rep_student else None))

            if len(class_entries) > 1:
                child_hint = f" _(hijo/a: {contact.child_name})_" if contact and contact.child_name else ""
                opts = "\n".join(
                    f"  `{i+1}` — {cls.name}"
                    for i, (cls, sid) in enumerate(class_entries)
                )
                wa.send_text(
                    chat_id,
                    f"📋 ¿Para cuál salón es el formulario *{form.title}*?{child_hint}\n\n{opts}",
                )
                data["class_options"] = {
                    str(i + 1): {"classroom_id": cls.id, "student_id": sid}
                    for i, (cls, sid) in enumerate(class_entries)
                }
                _advance(session, "selecting_student", data, db)
                return

    # Check for existing submission for this (form, respondent, student)
    submission = db.query(models.FormSubmission).filter_by(
        form_id=form.id,
        respondent_jid=raw_jid,
        student_id=target_student_id,
    ).first()

    if submission and submission.status == "submitted":
        # Already submitted — ask if they want to edit
        wa.send_text(
            chat_id,
            f"✅ Ya enviaste el formulario *{form.title}*.\n\n"
            "¿Deseas editar tus respuestas? (*si* / *no*)",
        )
        data["submission_id"] = submission.id
        data["student_id"] = target_student_id
        data["question_index"] = 0
        data["return_to_review"] = False
        _advance(session, "awaiting_submit", data, db)
        return

    if not submission:
        submission = models.FormSubmission(
            form_id=form.id,
            respondent_jid=raw_jid,
            respondent_name=respondent_name,
            student_id=target_student_id,
            status="in_progress",
        )
        db.add(submission)
        db.flush()

    data["submission_id"] = submission.id
    data["student_id"] = target_student_id
    data["question_index"] = 0
    data["return_to_review"] = False
    _advance(session, "answering", data, db)

    questions = _get_ordered_questions(form, db)
    wa.send_text(
        chat_id,
        f"📋 *{form.title}*\n"
        f"{len(questions)} pregunta(s). Puedes cancelar en cualquier momento escribiendo *cancelar*.\n",
    )
    _send_question(chat_id, questions[0], 1, len(questions))


def _send_question(chat_id: str, q: models.FormQuestion, num: int, total: int):
    """Send the question text (with hint in italics and menu if choice type)."""
    header = f"*Pregunta {num}/{total}:*\n{q.text}"
    hint_line = f"\n_{q.hint}_" if q.hint else ""
    required_note = "" if q.required else "\n_(opcional — responde 'skip' para omitir)_"

    if q.type == "yes_no":
        wa.send_text(chat_id, f"{header}{hint_line}{required_note}\n\nResponde *si* o *no*:")
    elif q.type == "single_choice" and q.options:
        opts = "\n".join(f"  `{i+1}` — {opt}" for i, opt in enumerate(q.options))
        wa.send_text(chat_id, f"{header}{hint_line}{required_note}\n\n{opts}")
    else:
        wa.send_text(chat_id, f"{header}{hint_line}{required_note}")


def _validate_answer(text: str, q: models.FormQuestion) -> tuple[bool, str | None, str]:
    """Returns (ok, normalized_value, error_message)."""
    t = text.strip()
    lower = t.lower()

    # Skip for optional
    if not q.required and lower in ("skip", "omitir", "saltar"):
        return True, None, ""

    if q.type == "yes_no":
        if lower in _YES_TOKENS:
            return True, "yes", ""
        if lower in _NO_TOKENS:
            return True, "no", ""
        return False, None, "Responde *si* o *no*:"

    elif q.type == "text":
        if not t:
            return False, None, "La respuesta no puede estar vacía."
        return True, t, ""

    elif q.type == "single_choice":
        options = q.options or []
        if t.isdigit():
            idx = int(t) - 1
            if 0 <= idx < len(options):
                return True, options[idx], ""
            return False, None, f"Responde con un número del 1 al {len(options)}."
        # Also accept the text of the option directly
        for opt in options:
            if lower == opt.lower():
                return True, opt, ""
        opts = "\n".join(f"  `{i+1}` — {opt}" for i, opt in enumerate(options))
        return False, None, f"Elige una opción:\n{opts}"

    return True, t, ""


def _upsert_answer(submission_id: int, question_id: int, value: str | None, db: Session):
    """Insert or update a FormAnswer record."""
    existing = db.query(models.FormAnswer).filter_by(
        submission_id=submission_id,
        question_id=question_id,
    ).first()
    if existing:
        existing.value = value
        existing.answered_at = datetime.utcnow()
    else:
        db.add(models.FormAnswer(
            submission_id=submission_id,
            question_id=question_id,
            value=value,
            answered_at=datetime.utcnow(),
        ))
    db.commit()


def _go_to_submit(
    chat_id: str,
    session: models.ConversationSession,
    data: dict,
    form: models.Form,
    db: Session,
):
    """Transition to awaiting_submit and show summary."""
    _advance(session, "awaiting_submit", data, db)
    questions = _get_ordered_questions(form, db)
    _send_review_summary(chat_id, form, data, questions, db)


def _send_review_summary(
    chat_id: str,
    form: models.Form,
    data: dict,
    questions: list,
    db: Session,
):
    """Show all answers and prompt for submit/edit/cancel."""
    submission_id = data.get("submission_id")
    answers_map: dict[int, str | None] = {}
    if submission_id:
        rows = db.query(models.FormAnswer).filter_by(submission_id=submission_id).all()
        answers_map = {r.question_id: r.value for r in rows}

    lines = [f"📋 *{form.title}* — Resumen de respuestas:\n"]
    for i, q in enumerate(questions, 1):
        val = answers_map.get(q.id)
        display_val = _display_value(val, q)
        lines.append(f"  *{i}.* {q.text}\n     ↳ {display_val}")

    wa.send_text(chat_id, "\n".join(lines))
    wa.send_text(
        chat_id,
        "¿Qué deseas hacer?\n"
        "  *si* — enviar respuestas\n"
        "  *editar* — cambiar alguna respuesta\n"
        "  *cancelar* — descartar",
    )


def _send_edit_menu(
    chat_id: str,
    form: models.Form,
    data: dict,
    questions: list,
    db: Session,
):
    """List questions numbered for editing."""
    submission_id = data.get("submission_id")
    answers_map: dict[int, str | None] = {}
    if submission_id:
        rows = db.query(models.FormAnswer).filter_by(submission_id=submission_id).all()
        answers_map = {r.question_id: r.value for r in rows}

    lines = ["✏️ ¿Qué pregunta quieres cambiar?\n"]
    for i, q in enumerate(questions, 1):
        val = answers_map.get(q.id)
        display_val = _display_value(val, q)
        lines.append(f"  *{i}* — {q.text[:60]}\n     Respuesta actual: {display_val}")
    lines.append("\nEnvía el número o escribe *enviar* para confirmar.")
    wa.send_text(chat_id, "\n".join(lines))


def _display_value(val: str | None, q: models.FormQuestion) -> str:
    if val is None:
        return "_(sin respuesta)_"
    if q.type == "yes_no":
        return "✅ Sí" if val == "yes" else "❌ No"
    return val


def _submit_form(
    raw_jid: str,
    chat_id: str,
    form: models.Form,
    session: models.ConversationSession,
    data: dict,
    db: Session,
):
    """Mark submission as submitted and notify manager."""
    submission_id = data.get("submission_id")
    if not submission_id:
        wa.send_text(chat_id, "❌ Error interno al enviar. Intenta de nuevo.")
        return

    submission = db.query(models.FormSubmission).get(submission_id)
    if not submission:
        wa.send_text(chat_id, "❌ No se encontró tu respuesta. Intenta de nuevo.")
        return

    now = datetime.utcnow()
    if submission.status == "submitted":
        submission.last_edited_at = now
    else:
        submission.status = "submitted"
        submission.submitted_at = now

    db.delete(session)
    db.commit()

    wa.send_text(
        chat_id,
        f"✅ *¡Respuestas enviadas!*\n"
        f"Formulario: *{form.title}*\n\n"
        "Gracias por completar el formulario.",
    )

    # Notify creator (admin/manager) via DM
    _notify_manager_submission(form, submission, db)
    logger.info("FORM submitted form_id=%d submission_id=%d jid=%s", form.id, submission_id, raw_jid)


async def start_from_code(raw_jid: str, chat_id: str, code: str, db: Session, admin_override: bool = False):
    """
    Handle a parent sending FORM-XXXXX directly (e.g. from a wa.me deep link).
    Called from webhook when no active session exists and text matches the code pattern.
    """
    form = db.query(models.Form).filter_by(form_code=code.upper(), status="open").first()
    if not form:
        wa.send_text(
            chat_id,
            "❌ Ese código de formulario no es válido o el formulario ya está cerrado.",
        )
        return

    # Admin override: skip all audience checks
    if admin_override:
        existing = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
        if existing:
            if existing.flow == "form_respond" and (existing.data or {}).get("form_id") == form.id:
                wa.send_text(chat_id, f"📋 Ya estás respondiendo *{form.title}*. Continúa donde lo dejaste.")
            else:
                wa.send_text(chat_id, "Tienes otra conversación activa. Escribe *cancelar* para terminarla primero.")
            return
        session = models.ConversationSession(
            chat_jid=raw_jid, flow="form_respond", step="awaiting_start", data={"form_id": form.id},
        )
        db.add(session)
        db.commit()
        session = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
        _start_form(raw_jid, chat_id, form, session, {"form_id": form.id}, db)
        logger.info("FORM admin start_from_code form_id=%d jid=%s", form.id, raw_jid)
        return

    audience_rows = db.query(models.FormAudience).filter_by(form_id=form.id).all()
    audience_classroom_ids = {a.classroom_id for a in audience_rows}

    # Check registered parent first
    parent = db.query(models.Parent).filter_by(whatsapp_jid=raw_jid, is_active=True).first()
    if parent:
        parent_classroom_ids = {
            s.classroom_id
            for s in db.query(models.Student).filter_by(parent_id=parent.id).all()
            if s.classroom_id
        }
        if not parent_classroom_ids & audience_classroom_ids:
            wa.send_text(
                chat_id,
                f"⚠️ El formulario *{form.title}* no está dirigido a tu salón.",
            )
            return
    else:
        # Allow known contacts whose source group is linked to an audience classroom
        contact = db.query(models.KnownContact).filter_by(jid=raw_jid).first()
        if not contact:
            wa.send_text(
                chat_id,
                f"Para responder el formulario *{form.title}* necesitas estar registrado.\n"
                "Solicita un código de invitación al administrador.",
            )
            return

        linked_classroom = (
            db.query(models.Classroom)
            .filter(
                models.Classroom.whatsapp_group_id == contact.source_group_id,
                models.Classroom.id.in_(audience_classroom_ids),
                models.Classroom.is_active == True,
            )
            .first()
        )
        if not linked_classroom:
            wa.send_text(
                chat_id,
                f"⚠️ El formulario *{form.title}* no está dirigido al grupo de tu salón.",
            )
            return

    # Check if already has a different active session
    existing = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
    if existing:
        if existing.flow == "form_respond" and (existing.data or {}).get("form_id") == form.id:
            wa.send_text(
                chat_id,
                f"📋 Ya estás respondiendo *{form.title}*. Continúa donde lo dejaste.",
            )
        else:
            wa.send_text(
                chat_id,
                "Tienes otra conversación activa. Escribe *cancelar* para terminarla primero.",
            )
        return

    # Create session and kick off the form immediately
    session = models.ConversationSession(
        chat_jid=raw_jid,
        flow="form_respond",
        step="awaiting_start",
        data={"form_id": form.id},
    )
    db.add(session)
    db.commit()

    # Refresh to get the persisted session then start directly
    session = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
    _start_form(raw_jid, chat_id, form, session, {"form_id": form.id}, db)
    logger.info("FORM start_from_code form_id=%d jid=%s code=%s", form.id, raw_jid, code)


def _notify_manager_submission(
    form: models.Form,
    submission: models.FormSubmission,
    db: Session,
):
    """Send a brief DM to the form creator when a parent submits."""
    creator_jid = form.created_by_jid
    if not creator_jid:
        return
    try:
        wa.send_text(
            creator_jid,
            f"✅ *{submission.respondent_name}* respondió el formulario *{form.title}*.\n"
            f"Ver resultados: `/form results {form.id}`",
        )
    except Exception as e:
        logger.warning("FORM could not notify creator form_id=%d error=%s", form.id, e)
