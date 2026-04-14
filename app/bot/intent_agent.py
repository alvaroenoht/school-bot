"""
LLM Intent Interpreter — understands free-form parent messages and
dispatches to the correct tool/handler.

Called by the webhook ONLY when no deterministic route matched:
  - Registered parent sends a non-command message
  - Known contact sends a non-command message
  - Group @mention that isn't a vincular command

Uses OpenAI function-calling to determine intent and call tool wrappers.
Multi-turn: info tools return data → LLM formulates a natural response.
Falls back to qa_handler on any LLM error.
"""
import json
import logging
import re
import time
from datetime import datetime, timedelta

import openai
import pytz
from sqlalchemy.orm import Session

from app.bot import intent_tools, qa_handler
from app.config import get_settings
from app.db import models
from app.whatsapp.client import WahaClient

PANAMA_TZ = pytz.timezone("America/Panama")

logger = logging.getLogger(__name__)
wa = WahaClient()

# ── Conversation memory (in-process, TTL-based) ──────────────────────────────
# {chat_id: [(timestamp, role, content), ...]}
_chat_history: dict[str, list[tuple[float, str, str]]] = {}
_HISTORY_TTL = 30 * 60      # 30 minutes
_HISTORY_MAX_MSGS = 10       # keep last N exchanges

# Brief notes saved to history when a tool sends messages directly (returns None)
_TOOL_HISTORY_NOTE = {
    "query_assignments_week": "[Ya envié el resumen semanal de actividades]",
    "start_payment": "[Se inició el flujo de pago]",
    "start_receipt_flow": "[Se inició el proceso de comprobante de pago]",
    "start_form": "[Se inició el formulario]",
}


def _get_history(chat_id: str) -> list[dict]:
    """Return recent messages for this chat as OpenAI message dicts."""
    entries = _chat_history.get(chat_id, [])
    if not entries:
        return []
    # Prune expired
    cutoff = time.time() - _HISTORY_TTL
    entries = [(ts, role, content) for ts, role, content in entries if ts > cutoff]
    _chat_history[chat_id] = entries
    return [{"role": role, "content": content} for _, role, content in entries]


def _append_history(chat_id: str, role: str, content: str):
    """Add a message to the chat history."""
    entries = _chat_history.setdefault(chat_id, [])
    entries.append((time.time(), role, content))
    # Trim to max
    if len(entries) > _HISTORY_MAX_MSGS:
        _chat_history[chat_id] = entries[-_HISTORY_MAX_MSGS:]

# ── OpenAI function-calling tool schemas ───────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "start_payment",
            "description": (
                "Inicia el flujo de pago para una actividad escolar. "
                "Usa cuando el usuario quiere pagar, dice 'ya pagué', 'quiero pagar', "
                "menciona comprobante, pregunta cuánto cuesta, o habla de dinero/cuenta/transferencia "
                "en relación a una actividad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fundraiser_name": {
                        "type": "string",
                        "description": "Nombre o parte del nombre de la actividad a pagar",
                    },
                },
                "required": ["fundraiser_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_receipt_flow",
            "description": (
                "Recibe o procesa un comprobante de pago. Usa cuando el usuario "
                "envía una imagen que parece un recibo, dice que ya pagó y quiere "
                "enviar comprobante, o envía una imagen sin contexto (probablemente recibo)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fundraiser_name": {
                        "type": "string",
                        "description": "Nombre de la actividad si se puede determinar del contexto",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_form",
            "description": (
                "Inicia un formulario para que el padre lo responda directamente por chat. "
                "Usa cuando el usuario dice que quiere responder/llenar/completar un formulario, "
                "pregunta cómo responder uno, o menciona un formulario abierto por nombre (ej. "
                "'jersey', 'tallas', 'encuesta'). Si hay más de un formulario abierto y el usuario "
                "no identifica claramente cuál, pasa `form_title_or_code` con lo que dijo; la "
                "herramienta pedirá aclaración si hace falta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "form_title_or_code": {
                        "type": "string",
                        "description": "Código (FORM-XXXXX) o palabra del título del formulario",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_fundraisers",
            "description": (
                "Lista las actividades escolares activas que están aceptando pagos. "
                "Usa cuando el usuario pregunta qué puede pagar, qué actividades hay, "
                "o quiere ver las opciones disponibles."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ── System prompt ──────────────────────────────────────────────────────────────

_DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_SYSTEM_TEMPLATE = """\
Eres el asistente escolar de WhatsApp del colegio La Salle. \
Hablas español panameño informal y amigable — como un chat real. \
Usa emojis con moderación (1-2 por mensaje).

Hoy es {today_weekday} {today_date}.

Tu rol:
- Ayudar a padres con consultas sobre tareas y actividades escolares
- Guiar pagos de actividades escolares
- Responder preguntas sobre el calendario escolar
- Avisar sobre formularios abiertos e indicar el código para responderlos

Reglas estrictas:
- Respuestas CORTAS (2-4 líneas máximo, estilo WhatsApp)
- Usa los DATOS DE ACTIVIDADES que se proporcionan abajo para responder preguntas sobre tareas, materias y calendario
- NUNCA inventes datos — si no aparece en las actividades de abajo, di que no hay información
- {student_name_rule}
- NUNCA des respuestas a tareas escolares ni ayudes a hacer trampa
- Si te piden ayuda con una tarea, explica los pasos o conceptos pero no des la respuesta final
- Cuando presentes datos de actividades, usa formato WhatsApp con emojis y negritas
- Las actividades, materiales y cualquier dato son ESTRICTAMENTE por fecha: SOLO reporta información que aparezca listada bajo la fecha específica consultada. Nunca atribuyas datos de otro día aunque estén en el contexto
- Cuando el usuario quiere pagar, pregunta cómo pagar, dice "cómo hago", o muestra intención de pago → SIEMPRE usa la herramienta start_payment. NUNCA expliques el proceso de pago con texto, solo inicia el flujo.
- Si el usuario quiere responder/llenar/completar un formulario, o menciona un formulario por nombre → SIEMPRE usa la herramienta start_form. NO le pidas al usuario que envíe el código — la herramienta inicia el flujo automáticamente. Si pregunta simplemente *qué* formularios hay, basta con listarlos
- NUNCA termines tu respuesta con una pregunta — responde de forma concisa y directa, sin preguntar "¿necesitas algo más?" ni similares
- SIEMPRE incluye el link (🔗) de las actividades que menciones en tu respuesta, si está disponible en los datos

{sender_context}

{fundraiser_context}

{forms_context}

{events_context}

{assignments_context}\
"""


def _build_system_prompt(sender, is_admin: bool, db: Session, chat_id: str = "") -> str:
    """Build system prompt with sender context, fundraisers, and assignments."""
    today = datetime.now(PANAMA_TZ).date()
    sender_ctx = _build_sender_context(sender, is_admin, db)
    sender_classroom_ids = _sender_classroom_ids(sender, db)
    fundraiser_ctx = _build_fundraiser_context(db, sender_classroom_ids)
    forms_ctx = _build_forms_context(sender, db, sender_classroom_ids)
    events_ctx = _build_events_context(sender, db)
    assignments_ctx = _build_assignments_context(sender, db, chat_id)

    is_group = chat_id and "@g.us" in chat_id
    if is_group:
        name_rule = "NUNCA menciones el nombre del estudiante en tus respuestas — mantén la respuesta impersonal"
    else:
        name_rule = "En mensajes directos, usa el nombre del estudiante para distinguir entre hijos si hay más de uno"

    return _SYSTEM_TEMPLATE.format(
        today_weekday=_DAY_NAMES[today.weekday()],
        today_date=today.strftime("%d/%m/%Y"),
        sender_context=sender_ctx,
        fundraiser_context=fundraiser_ctx,
        forms_context=forms_ctx,
        events_context=events_ctx,
        assignments_context=assignments_ctx,
        student_name_rule=name_rule,
    )


def _sender_classroom_ids(sender, db: Session) -> list[int]:
    """Return the classroom IDs this sender belongs to (for audience filtering)."""
    if isinstance(sender, models.Parent):
        students = (
            db.query(models.Student)
            .filter(models.Student.id.in_(sender.student_ids or []))
            .all()
        )
        return [s.classroom_id for s in students if s.classroom_id]
    if isinstance(sender, models.KnownContact):
        kcgs = db.query(models.KnownContactGroup).filter_by(contact_jid=sender.jid, active=True).all()
        return [kcg.classroom_id for kcg in kcgs if kcg.classroom_id]
    return []


def _build_sender_context(sender, is_admin: bool, db: Session) -> str:
    """Build the sender context section of the system prompt."""
    if isinstance(sender, models.Parent):
        students = (
            db.query(models.Student)
            .filter(models.Student.id.in_(sender.student_ids or []))
            .all()
        )
        student_info = ", ".join(f"{s.name} ({s.grade})" for s in students)
        return (
            f"Usuario: {sender.first_name} {sender.last_name} (padre registrado)\n"
            f"Estudiantes: {student_info}\n"
            f"Admin: {'sí' if is_admin else 'no'}"
        )
    elif isinstance(sender, models.KnownContact):
        active_kcgs = (
            db.query(models.KnownContactGroup)
            .filter_by(contact_jid=sender.jid, active=True)
            .all()
        )
        if active_kcgs:
            names = [kcg.classroom.name for kcg in active_kcgs if kcg.classroom]
            classroom_line = "Salones vinculados: " + ", ".join(names)
        else:
            classroom_line = "Sin salón vinculado"
        child_names = [kcg.child_name for kcg in active_kcgs if kcg.child_name]
        child_line = ", ".join(child_names) if child_names else "no registrado"
        return (
            f"Usuario: {sender.name} (contacto del grupo, no registrado)\n"
            f"Hijo/a: {child_line}\n"
            f"{classroom_line}"
        )
    return "Usuario: desconocido"


def _build_fundraiser_context(db: Session, sender_classroom_ids: list[int]) -> str:
    """Build a brief list of active fundraisers SCOPED to the sender's classrooms.

    A fundraiser is visible when its audience is empty/null (global) OR
    intersects the sender's classrooms.
    """
    active = db.query(models.Fundraiser).filter_by(status="active").all()
    sender_set = set(sender_classroom_ids or [])
    visible = []
    for f in active:
        aud = f.audience_classroom_ids or []
        if not aud:
            visible.append(f)
        elif sender_set & set(aud):
            visible.append(f)
    if not visible:
        return "Actividades activas: ninguna para tu salón."
    lines = ["Actividades activas (para pagar, usa start_payment con el nombre):"]
    for f in visible:
        if f.type == "fixed":
            lines.append(f"- {f.name} [código: {f.code}] (monto fijo ${f.fixed_amount})")
        else:
            lines.append(f"- {f.name} [código: {f.code}] (catálogo de productos)")
    return "\n".join(lines)


def _build_forms_context(sender, db: Session, sender_classroom_ids: list[int]) -> str:
    """Open/active forms targeting the sender's classrooms, excluding forms
    the sender has already submitted.
    """
    if not sender_classroom_ids:
        return "Formularios abiertos: ninguno para tu salón."

    q = (
        db.query(models.Form)
        .join(models.FormAudience, models.FormAudience.form_id == models.Form.id)
        .filter(
            models.Form.status.in_(["open", "active"]),
            models.FormAudience.classroom_id.in_(sender_classroom_ids),
        )
        .distinct()
    )
    forms = q.all()
    if not forms:
        return "Formularios abiertos: ninguno para tu salón."

    # Exclude already-submitted by this sender
    sender_jid = getattr(sender, "jid", None) or getattr(sender, "whatsapp_jid", None)
    submitted_ids: set[int] = set()
    if sender_jid:
        rows = (
            db.query(models.FormSubmission.form_id)
            .filter(
                models.FormSubmission.respondent_jid == sender_jid,
                models.FormSubmission.status == "submitted",
            )
            .all()
        )
        submitted_ids = {r[0] for r in rows}

    pending = [f for f in forms if f.id not in submitted_ids]
    if not pending:
        return "Formularios abiertos: ya respondiste todos los que te corresponden."

    lines = [
        "Formularios abiertos para tu salón (usa start_form para iniciarlos):",
    ]
    for f in pending:
        closes = f" (cierra {f.closes_at.strftime('%d/%m')})" if f.closes_at else ""
        lines.append(f"- {f.title} [código: {f.form_code}]{closes}")
    return "\n".join(lines)


def _build_events_context(sender, db: Session) -> str:
    """Upcoming events (next 14 days) filtered by sender's classrooms or is_global."""
    today = datetime.now(PANAMA_TZ).date()
    horizon = today + timedelta(days=14)

    # Determine sender's classroom IDs
    classroom_ids: list[int] = []
    if isinstance(sender, models.Parent):
        students = (
            db.query(models.Student)
            .filter(models.Student.id.in_(sender.student_ids or []))
            .all()
        )
        classroom_ids = [s.classroom_id for s in students if s.classroom_id]
    elif isinstance(sender, models.KnownContact):
        kcgs = db.query(models.KnownContactGroup).filter_by(contact_jid=sender.jid, active=True).all()
        classroom_ids = [kcg.classroom_id for kcg in kcgs if kcg.classroom_id]

    # Query upcoming events: global OR audience intersects sender's classrooms
    q = (
        db.query(models.Event)
        .outerjoin(models.EventAudience)
        .filter(
            models.Event.date >= datetime.combine(today, datetime.min.time()),
            models.Event.date <  datetime.combine(horizon, datetime.min.time()),
        )
    )
    if classroom_ids:
        q = q.filter(
            (models.Event.is_global == True)  # noqa: E712
            | (models.EventAudience.classroom_id.in_(classroom_ids))
        )
    else:
        q = q.filter(models.Event.is_global == True)  # noqa: E712

    events = q.distinct().order_by(models.Event.date).limit(20).all()
    if not events:
        return "Eventos próximos: ninguno en los próximos 14 días."

    icon = {"birthday": "🎂", "holiday": "🎉", "exam": "📝", "general": "📅"}
    lines = ["Eventos próximos (próximos 14 días):"]
    for e in events:
        d = e.date.strftime("%d/%m")
        ic = icon.get(e.type, "📅")
        loc = f" — {e.location}" if e.location else ""
        lines.append(f"- {ic} {d} {e.title}{loc}")
    return "\n".join(lines)


_DAYS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles",
    3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo",
}


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _append_assignment_lines(assignments, subjects: dict, lines: list) -> None:
    """Append formatted assignment lines grouped by date to the lines list."""
    current_date = None
    for a in assignments:
        if a.date != current_date:
            current_date = a.date
            try:
                d = datetime.strptime(a.date, "%Y-%m-%d").date()
                day_name = _DAYS_ES.get(d.weekday(), "")
                lines.append(f"\n[{day_name} {d.strftime('%d/%m')}]")
            except ValueError:
                lines.append(f"\n[{a.date}]")

        subj_name, subj_icon = subjects.get(a.subject_id, (f"Materia {a.subject_id}", "📘"))
        lines.append(f"  {subj_icon} {subj_name} — {a.title} ({a.type})")
        if a.description:
            desc = _strip_html(a.description)
            lines.append(f"    Descripción: {desc}")
        if a.materials:
            lines.append(f"    🎒 Materiales: {a.materials}")
        if a.short_url:
            lines.append(f"    🔗 {a.short_url}")


def _build_assignments_context(sender, db: Session, chat_id: str = "") -> str:
    """Load this week + next week assignments for the scoped student(s) into context.

    In DMs with multiple students, groups assignments under student name headers.
    In groups, shows only the classroom-scoped student (no names).
    """
    if not isinstance(sender, models.Parent):
        if not isinstance(sender, models.KnownContact):
            return "Actividades escolares: no disponible (usuario no registrado)."

        active_kcgs = (
            db.query(models.KnownContactGroup)
            .filter_by(contact_jid=sender.jid, active=True)
            .all()
        )
        if not active_kcgs:
            return "Actividades escolares: no disponible (sin salón vinculado activo)."

        today = datetime.now(PANAMA_TZ).date()
        this_monday = today - timedelta(days=today.weekday())
        next_friday = this_monday + timedelta(days=11)
        subjects = {s.materia_id: (s.name, s.icon or "📘") for s in db.query(models.Subject).all()}

        all_lines = []
        for kcg in active_kcgs:
            classroom = kcg.classroom
            if not classroom:
                continue
            student_ids = [s.id for s in db.query(models.Student).filter_by(classroom_id=classroom.id).all()]
            if not student_ids:
                continue
            assignments = (
                db.query(models.Assignment)
                .filter(
                    models.Assignment.student_id.in_(student_ids),
                    models.Assignment.date >= this_monday.isoformat(),
                    models.Assignment.date <= next_friday.isoformat(),
                )
                .order_by(models.Assignment.date)
                .all()
            )
            if assignments:
                section = [f"DATOS DE ACTIVIDADES — {classroom.name} ({this_monday.strftime('%d/%m')} al {next_friday.strftime('%d/%m')}):"]
                _append_assignment_lines(assignments, subjects, section)
                all_lines.extend(section)

        if not all_lines:
            return "Actividades escolares: no hay actividades registradas para esta semana ni la próxima."
        return "\n".join(all_lines)

    all_ids = sender.student_ids or []
    if not all_ids:
        return "Actividades escolares: no hay estudiantes vinculados."

    is_group = chat_id and "@g.us" in chat_id

    # Scope to classroom if in a group
    student_ids = all_ids
    if is_group:
        classroom = (
            db.query(models.Classroom)
            .filter_by(whatsapp_group_id=chat_id, is_active=True)
            .first()
        )
        if classroom:
            scoped = [
                s.id for s in db.query(models.Student)
                .filter(models.Student.id.in_(all_ids), models.Student.classroom_id == classroom.id)
                .all()
            ]
            if scoped:
                student_ids = scoped

    # Date range: this week Monday → next week Friday
    today = datetime.now(PANAMA_TZ).date()
    this_monday = today - timedelta(days=today.weekday())
    next_friday = this_monday + timedelta(days=11)  # 2 full weeks

    # Build subject lookup
    subjects = {s.materia_id: (s.name, s.icon or "📘") for s in db.query(models.Subject).all()}

    # Build student name lookup (for DMs with multiple students)
    student_names = {}
    if not is_group and len(student_ids) > 1:
        for s in db.query(models.Student).filter(models.Student.id.in_(student_ids)).all():
            student_names[s.id] = s.name

    assignments = (
        db.query(models.Assignment)
        .filter(
            models.Assignment.student_id.in_(student_ids),
            models.Assignment.date >= this_monday.isoformat(),
            models.Assignment.date <= next_friday.isoformat(),
        )
        .order_by(models.Assignment.date)
        .all()
    )

    if not assignments:
        return "Actividades escolares: no hay actividades registradas para esta semana ni la próxima."

    lines = [f"DATOS DE ACTIVIDADES ({this_monday.strftime('%d/%m')} al {next_friday.strftime('%d/%m')}):"]

    # DM with multiple students → group by student name
    if student_names:
        from collections import defaultdict
        by_student: dict[int, list] = defaultdict(list)
        for a in assignments:
            by_student[a.student_id].append(a)

        for sid in student_ids:
            name = student_names.get(sid, f"Estudiante {sid}")
            lines.append(f"\n👤 *{name}*:")
            student_assignments = by_student.get(sid, [])
            if student_assignments:
                _append_assignment_lines(student_assignments, subjects, lines)
            else:
                lines.append("  (sin actividades)")
    else:
        # Single student or group — flat list
        _append_assignment_lines(assignments, subjects, lines)

    return "\n".join(lines)


# ── Main handler ───────────────────────────────────────────────────────────────

async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    sender: models.Parent | models.KnownContact,
    is_admin: bool = False,
    has_media: bool = False,
    media_type: str = "",
    message_id: str = "",
    payload: dict | None = None,
) -> None:
    """
    LLM Intent Interpreter entry point.

    1. Build context + system prompt
    2. Call OpenAI with function-calling tools
    3. If tool returns data → feed back to LLM for natural response (multi-turn)
    4. If tool returns None → it already sent a WA message (payment flows)
    5. On error, fall back to qa_handler (parents) or brief help (contacts)
    """
    settings = get_settings()

    # Build user message content
    if has_media and "image" in (media_type or ""):
        if text:
            user_content = f"[El usuario envió una imagen con el mensaje: {text}]"
        else:
            user_content = "[El usuario envió una imagen sin texto — probablemente un comprobante de pago]"
    elif text:
        user_content = text
    else:
        # No text and no image — nothing to process
        return

    system_prompt = _build_system_prompt(sender, is_admin, db, chat_id)

    # Save user message to history
    _append_history(chat_id, "user", user_content)

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        # Build messages: system + recent history (already includes current msg)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(_get_history(chat_id))

        response = client.chat.completions.create(
            model=settings.openai_intent_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
            max_completion_tokens=500,
        )

        message = response.choices[0].message

        # ── Tool calls ────────────────────────────────────────────────────
        if message.tool_calls:
            # Dispatch ALL tool calls (LLM may request multiple)
            has_data = False
            tool_results: list[tuple[str, str, str | None]] = []  # (call_id, fn_name, result)

            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)

                logger.info(
                    "INTENT route=llm jid=%s intent=%s args=%s",
                    raw_jid, fn_name, fn_args,
                )

                # Permission check
                if intent_tools.is_admin_only(fn_name) and not is_admin:
                    tool_results.append((tool_call.id, fn_name, "Comando solo para administradores."))
                    continue

                result = await intent_tools.dispatch(
                    fn_name,
                    fn_args,
                    raw_jid=raw_jid,
                    chat_id=chat_id,
                    text=text,
                    db=db,
                    sender=sender,
                    is_admin=is_admin,
                    message_id=message_id,
                    payload=payload,
                )
                tool_results.append((tool_call.id, fn_name, result))
                if result is not None:
                    has_data = True

            # If any tool returned data, feed ALL results back to the LLM
            if has_data:
                first_fn = tool_results[0][1]
                logger.info("INTENT route=llm_multiturn jid=%s tools=%d first=%s",
                            raw_jid, len(tool_results), first_fn)

                messages.append(message.model_dump())
                for call_id, fn_name, result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": result or _TOOL_HISTORY_NOTE.get(fn_name, f"[{fn_name} ejecutado]"),
                    })

                followup = client.chat.completions.create(
                    model=settings.openai_intent_model,
                    messages=messages,
                    temperature=0.3,
                    max_completion_tokens=500,
                )

                reply = followup.choices[0].message.content
                if reply:
                    _append_history(chat_id, "assistant", reply)
                    wa.send_text(chat_id, reply)
                else:
                    combined = "\n\n".join(r for _, _, r in tool_results if r)
                    _append_history(chat_id, "assistant", combined)
                    wa.send_text(chat_id, combined)
            else:
                # All tools sent WA messages directly — save a note to history
                notes = [_TOOL_HISTORY_NOTE.get(fn, f"[Se ejecutó {fn}]")
                         for _, fn, _ in tool_results]
                _append_history(chat_id, "assistant", " ".join(notes))
            return

        # ── Plain text response ───────────────────────────────────────────
        if message.content:
            logger.info("INTENT route=llm_text jid=%s", raw_jid)
            _append_history(chat_id, "assistant", message.content)
            wa.send_text(chat_id, message.content)
            return

        # ── Empty response — should not happen, but handle gracefully ─────
        logger.warning("INTENT route=llm_empty jid=%s", raw_jid)
        _fallback(raw_jid, chat_id, text, db, sender)

    except Exception as e:
        logger.error("INTENT route=llm_error jid=%s error=%s", raw_jid, e)
        _fallback(raw_jid, chat_id, text, db, sender)


def _fallback(raw_jid, chat_id, text, db, sender):
    """Fall back to keyword-based qa_handler or brief help message."""
    if isinstance(sender, models.Parent):
        # Use the synchronous qa_handler — it doesn't actually await anything
        import asyncio
        asyncio.ensure_future(
            qa_handler.handle(raw_jid, chat_id, text, db, sender)
        )
    else:
        wa.send_text(
            chat_id,
            f"Hola *{sender.name}*! 👋 Puedes usar:\n"
            "  • `/pagar <nombre>` — pagar una actividad escolar\n"
            "  • Pregúntame qué actividades hay disponibles",
        )


# ── Payment assist (Issue #2) ──────────────────────────────────────────────────

async def handle_payment_assist(chat_id: str, user_text: str, context: dict) -> dict | None:
    """
    Called when a parent is struggling in the payment flow.
    Returns a structured action dict or None on failure.

    Action types:
      {"type": "set_order", "cart": [...]}   — agent parsed the order
      {"type": "restart"}                     — reset catalog/receipt step
      {"type": "natural_reply", "text": "…"} — send freeform message
    """
    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    step = context.get("step", "unknown")
    reason = context.get("reason", "unknown")
    products = context.get("products", [])
    recent = context.get("recent_inputs", [])

    product_list = "\n".join(f"  {i+1}. {p['name']} — ${p['price']}" for i, p in enumerate(products)) or "N/A"

    system = (
        "Eres un asistente experto en flujos de pago escolar por WhatsApp. "
        "Un padre está teniendo dificultades en el paso del flujo de pago. "
        "Tu tarea es interpretar lo que quiere hacer y devolver UNA acción JSON estructurada. "
        "NUNCA respondas texto libre — responde SOLO con JSON.\n\n"
        f"Paso actual: {step}\n"
        f"Motivo de escalación: {reason}\n"
        f"Actividad: {context.get('fundraiser_name')} ({context.get('fundraiser_type')})\n"
        f"Nombre del estudiante: {context.get('child_name')}\n"
        f"Catálogo de productos:\n{product_list}\n"
        f"Últimas entradas del padre: {recent}\n\n"
        "Acciones posibles:\n"
        '  {"type":"set_order","cart":[{"name":"...","price":"X.XX","qty":N},...]}  — si puedes inferir el pedido\n'
        '  {"type":"restart"}                                                        — si el padre está muy perdido\n'
        '  {"type":"natural_reply","text":"..."}                                     — para aclarar o guiar con palabras\n'
    )

    try:
        response = client.chat.completions.create(
            model=settings.openai_intent_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_text or "(sin texto — posiblemente imagen)"},
            ],
            temperature=0.2,
            timeout=20,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        action = json.loads(raw)
        logger.info("Payment assist action=%s reason=%s chat=%s", action.get("type"), reason, chat_id)
        return action
    except Exception as e:
        logger.error("Payment assist failed: %s", e)
        return None

