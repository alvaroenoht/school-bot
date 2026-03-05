"""
Tool wrappers for the LLM Intent Interpreter.

Each function wraps existing handler logic. The LLM calls these via
OpenAI function-calling.

Tools return either:
  - str  → data to feed back to the LLM for a natural response
  - None → tool already sent a WhatsApp message (payment flows, etc.)
"""
import logging
import re
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy.orm import Session

from app.db import models
from app.bot import payment_flow
from app.bot.qa_handler import _next_weekday, PANAMA_TZ
from app.utils.summary_formatter import generate_weekly_summary
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

# ── Admin-only tools ───────────────────────────────────────────────────────────

ADMIN_ONLY_TOOLS: set[str] = set()  # none of the current tools are admin-only


def is_admin_only(fn_name: str) -> bool:
    return fn_name in ADMIN_ONLY_TOOLS


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace to get clean text."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── Dispatch ───────────────────────────────────────────────────────────────────

async def dispatch(
    fn_name: str,
    fn_args: dict,
    *,
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    sender,
    is_admin: bool,
    message_id: str = "",
    payload: dict | None = None,
) -> str | None:
    """Route a tool call. Returns data string for LLM follow-up, or None if already handled."""
    handler = _TOOL_MAP.get(fn_name)
    if not handler:
        logger.warning(f"INTENT_TOOLS unknown tool: {fn_name}")
        return "No encontré esa herramienta. Las opciones son: consultar tareas de hoy/mañana/semana, buscar tareas, pagar actividades."
    return await handler(
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


# ── Info tools (return data for LLM) ─────────────────────────────────────────

async def query_assignments_day(args, *, db, sender, **kw) -> str:
    """Fetch assignments for a specific day and return as structured text."""
    today = datetime.now(PANAMA_TZ).date()
    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        return "El usuario no tiene estudiantes vinculados."

    offset = args.get("offset_days")
    weekday = args.get("weekday")

    if offset is not None:
        target = today + timedelta(days=int(offset))
        if offset == 0:
            label = "hoy"
        elif offset == 1:
            label = "mañana"
        else:
            label = target.strftime("%d/%m")
    elif weekday is not None:
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes"]
        wd = int(weekday)
        if 0 <= wd <= 4:
            target = _next_weekday(today, wd)
            label = f"el {day_names[wd]}"
        else:
            target = today
            label = "hoy"
    else:
        target = today
        label = "hoy"

    assignments = (
        db.query(models.Assignment)
        .filter(
            models.Assignment.student_id.in_(student_ids),
            models.Assignment.date == target.isoformat(),
        )
        .all()
    )

    if not assignments:
        return f"No hay actividades registradas para {label} ({target.strftime('%d/%m')})."

    lines = [f"Actividades para {label} ({target.strftime('%d/%m')}):"]
    for a in assignments:
        subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
        name = subject.name if subject else f"Materia {a.subject_id}"
        lines.append(f"\n- Materia: {name}")
        lines.append(f"  Título: {a.title}")
        if a.description:
            desc_text = _strip_html(a.description)
            # Limit description to ~500 chars to stay within token budget
            if len(desc_text) > 500:
                desc_text = desc_text[:500] + "..."
            lines.append(f"  Descripción: {desc_text}")
        if a.summary:
            lines.append(f"  Resumen: {a.summary}")
        if a.materials:
            lines.append(f"  Materiales: {a.materials}")

    logger.info(f"INTENT_TOOLS query_assignments_day target={target} label={label} count={len(assignments)}")
    return "\n".join(lines)


async def query_assignments_week(args, *, chat_id, db, sender, **kw) -> str | None:
    """Send full weekly summary. Uses existing formatter which sends directly."""
    today = datetime.now(PANAMA_TZ).date()
    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        return "El usuario no tiene estudiantes vinculados."

    start = _next_weekday(today, 0)  # next Monday
    end = start + timedelta(days=4)
    raw_conn = db.connection().connection.dbapi_connection
    sent = False
    for sid in student_ids:
        msg = generate_weekly_summary(raw_conn, sid, start, end)
        if msg:
            wa.send_chunked(chat_id, msg)
            sent = True

    logger.info(f"INTENT_TOOLS query_assignments_week start={start}")

    if not sent:
        return f"No hay actividades registradas para la semana del {start.strftime('%d/%m')}."

    # Weekly summary already sent via send_chunked, no need for LLM follow-up
    return None


async def explain_assignment(args, *, db, sender, **kw) -> str:
    """Search assignment by keyword, return full details including description."""
    search_term = args.get("search_term", "").strip()
    if not search_term:
        return "El usuario no especificó qué tarea buscar."

    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        return "El usuario no tiene estudiantes vinculados."

    # Search in recent assignments (next 2 weeks + past week)
    today = datetime.now(PANAMA_TZ).date()
    date_start = (today - timedelta(days=7)).isoformat()
    date_end = (today + timedelta(days=14)).isoformat()

    # Search in title first, then summary, then description
    assignments = None
    for field in [models.Assignment.title, models.Assignment.summary, models.Assignment.description]:
        assignments = (
            db.query(models.Assignment)
            .filter(
                models.Assignment.student_id.in_(student_ids),
                models.Assignment.date >= date_start,
                models.Assignment.date <= date_end,
                field.ilike(f"%{search_term}%"),
            )
            .order_by(models.Assignment.date)
            .limit(5)
            .all()
        )
        if assignments:
            break

    if not assignments:
        return f"No encontré actividades relacionadas con '{search_term}' en las próximas 2 semanas."

    lines = [f"Resultados para '{search_term}':"]
    for a in assignments:
        subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
        name = subject.name if subject else f"Materia {a.subject_id}"
        lines.append(f"\n--- {a.date} | {name} ---")
        lines.append(f"Título: {a.title}")
        lines.append(f"Tipo: {a.type}")
        if a.description:
            desc_text = _strip_html(a.description)
            lines.append(f"Descripción completa: {desc_text}")
        if a.summary:
            lines.append(f"Resumen: {a.summary}")
        if a.materials:
            lines.append(f"Materiales necesarios: {a.materials}")
        if a.short_url:
            lines.append(f"Link: {a.short_url}")

    logger.info(f"INTENT_TOOLS explain_assignment term={search_term} found={len(assignments)}")
    return "\n".join(lines)


async def list_active_fundraisers(args, *, db, **kw) -> str:
    """List active fundraisers — return data for LLM."""
    fundraisers = db.query(models.Fundraiser).filter_by(status="active").all()
    if not fundraisers:
        return "No hay actividades activas en este momento."

    lines = ["Actividades activas:"]
    for f in fundraisers:
        if f.type == "fixed":
            lines.append(f"- {f.name}: ${f.fixed_amount} (monto fijo). Comando: /pagar {f.name}")
        else:
            products = db.query(models.FundraiserProduct).filter_by(fundraiser_id=f.id).all()
            lines.append(f"- {f.name}: catálogo con {len(products)} productos. Comando: /pagar {f.name}")

    logger.info(f"INTENT_TOOLS list_active_fundraisers count={len(fundraisers)}")
    return "\n".join(lines)


# ── Action tools (send WA messages directly, return None) ────────────────────

async def start_payment(args, *, raw_jid, chat_id, db, sender, **kw) -> None:
    """Start a payment flow for a fundraiser."""
    fundraiser_name = args.get("fundraiser_name", "").strip()
    if not fundraiser_name:
        wa.send_text(chat_id, "¿Cuál actividad quieres pagar? Dime el nombre.")
        return

    cmd_text = f"pagar {fundraiser_name}"
    await payment_flow.start_from_command(raw_jid, chat_id, cmd_text, db, sender)
    logger.info(f"INTENT_TOOLS start_payment fundraiser={fundraiser_name}")


async def start_receipt_flow(args, *, raw_jid, chat_id, db, sender, **kw) -> None:
    """Handle 'ya pagué' or receipt image — start/resume payment flow."""
    fundraiser_name = args.get("fundraiser_name", "").strip()

    # Check if there's already a ConversationSession
    existing = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
    if existing:
        wa.send_text(
            chat_id,
            "Ya tienes un proceso activo. Complétalo o escribe *cancelar* para empezar de nuevo.",
        )
        return

    # Find the fundraiser
    active_fundraisers = db.query(models.Fundraiser).filter_by(status="active").all()
    if not active_fundraisers:
        wa.send_text(chat_id, "No hay actividades activas para recibir pagos en este momento.")
        return

    if len(active_fundraisers) == 1:
        fundraiser = active_fundraisers[0]
    elif fundraiser_name:
        fundraiser = None
        for f in active_fundraisers:
            if fundraiser_name.lower() in f.name.lower():
                fundraiser = f
                break
        if not fundraiser:
            names = "\n".join(f"  • *{f.name}*" for f in active_fundraisers)
            wa.send_text(
                chat_id,
                f"No encontré \"{fundraiser_name}\". Las actividades activas son:\n{names}\n\n"
                "Dime cuál quieres pagar.",
            )
            return
    else:
        names = "\n".join(f"  • `/pagar {f.name}`" for f in active_fundraisers)
        wa.send_text(
            chat_id,
            f"Hay varias actividades activas:\n{names}\n\n"
            "Dime cuál quieres pagar.",
        )
        return

    cmd_text = f"pagar {fundraiser.name}"
    await payment_flow.start_from_command(raw_jid, chat_id, cmd_text, db, sender)
    logger.info(f"INTENT_TOOLS start_receipt_flow fundraiser={fundraiser.name}")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_student_ids(sender, db: Session) -> list[int]:
    """Extract student IDs from Parent or KnownContact."""
    if isinstance(sender, models.Parent):
        return sender.student_ids or []
    # KnownContact — no student IDs available
    return []


# ── Tool registry ─────────────────────────────────────────────────────────────

_TOOL_MAP = {
    "query_assignments_day": query_assignments_day,
    "query_assignments_week": query_assignments_week,
    "explain_assignment": explain_assignment,
    "start_payment": start_payment,
    "start_receipt_flow": start_receipt_flow,
    "list_active_fundraisers": list_active_fundraisers,
}
