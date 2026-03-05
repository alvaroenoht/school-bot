"""
Tool wrappers for the LLM Intent Interpreter.

Each function wraps existing handler logic. The LLM calls these via
OpenAI function-calling; they never access WAHA or DB directly except
through the existing handler modules.
"""
import logging
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy.orm import Session

from app.db import models
from app.bot import payment_flow
from app.bot.qa_handler import _send_day, _next_weekday, PANAMA_TZ
from app.utils.summary_formatter import generate_weekly_summary
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

# ── Admin-only tools ───────────────────────────────────────────────────────────

ADMIN_ONLY_TOOLS: set[str] = set()  # none of the current tools are admin-only


def is_admin_only(fn_name: str) -> bool:
    return fn_name in ADMIN_ONLY_TOOLS


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
):
    """Route a tool call to the correct wrapper function."""
    handler = _TOOL_MAP.get(fn_name)
    if not handler:
        logger.warning(f"INTENT_TOOLS unknown tool: {fn_name}")
        wa.send_text(chat_id, "Hmm, no sé cómo ayudarte con eso. Intenta con: hoy, mañana, semana, pagar.")
        return
    await handler(
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


# ── Tool implementations ──────────────────────────────────────────────────────

async def query_assignments_day(args, *, chat_id, db, sender, **kw):
    """Fetch assignments for a specific day."""
    today = datetime.now(PANAMA_TZ).date()
    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        wa.send_text(chat_id, "No tienes estudiantes vinculados para consultar actividades.")
        return

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
        # Default to today
        target = today
        label = "hoy"

    logger.info(f"INTENT_TOOLS query_assignments_day target={target} label={label}")
    _send_day(chat_id, target, label, student_ids, db)


async def query_assignments_week(args, *, chat_id, db, sender, **kw):
    """Send full weekly summary."""
    today = datetime.now(PANAMA_TZ).date()
    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        wa.send_text(chat_id, "No tienes estudiantes vinculados para consultar actividades.")
        return

    start = _next_weekday(today, 0)  # next Monday
    end = start + timedelta(days=4)
    raw_conn = db.connection()
    sent = False
    for sid in student_ids:
        msg = generate_weekly_summary(raw_conn, sid, start, end)
        if msg:
            wa.send_chunked(chat_id, msg)
            sent = True

    if not sent:
        wa.send_text(chat_id, f"No hay actividades registradas para la semana del {start.strftime('%d/%m')}.")

    logger.info(f"INTENT_TOOLS query_assignments_week start={start}")


async def explain_assignment(args, *, chat_id, db, sender, **kw):
    """Search assignment by keyword, return summary + materials (never full description)."""
    search_term = args.get("search_term", "").strip()
    if not search_term:
        wa.send_text(chat_id, "¿Qué tarea quieres que busque? Dime la materia o tema.")
        return

    student_ids = _get_student_ids(sender, db)
    if not student_ids:
        wa.send_text(chat_id, "No tienes estudiantes vinculados para consultar actividades.")
        return

    # Search in recent assignments (next 2 weeks + past week)
    today = datetime.now(PANAMA_TZ).date()
    date_start = (today - timedelta(days=7)).isoformat()
    date_end = (today + timedelta(days=14)).isoformat()

    assignments = (
        db.query(models.Assignment)
        .filter(
            models.Assignment.student_id.in_(student_ids),
            models.Assignment.date >= date_start,
            models.Assignment.date <= date_end,
            models.Assignment.title.ilike(f"%{search_term}%"),
        )
        .order_by(models.Assignment.date)
        .limit(5)
        .all()
    )

    if not assignments:
        # Try searching in summary too
        assignments = (
            db.query(models.Assignment)
            .filter(
                models.Assignment.student_id.in_(student_ids),
                models.Assignment.date >= date_start,
                models.Assignment.date <= date_end,
                models.Assignment.summary.ilike(f"%{search_term}%"),
            )
            .order_by(models.Assignment.date)
            .limit(5)
            .all()
        )

    if not assignments:
        wa.send_text(chat_id, f"No encontré actividades relacionadas con *{search_term}* en las próximas 2 semanas.")
        return

    lines = [f"🔍 *Resultados para \"{search_term}\":*\n"]
    for a in assignments:
        subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
        icon = subject.icon if subject else "📘"
        name = subject.name if subject else f"Materia {a.subject_id}"
        lines.append(f"📅 *{a.date}* — {icon} *{name}*")
        lines.append(f"   {a.title}")
        if a.summary:
            lines.append(f"   _{a.summary}_")
        if a.materials:
            lines.append(f"   🎒 {a.materials}")
        lines.append("")

    wa.send_text(chat_id, "\n".join(lines))
    logger.info(f"INTENT_TOOLS explain_assignment term={search_term} found={len(assignments)}")


async def start_payment(args, *, raw_jid, chat_id, db, sender, **kw):
    """Start a payment flow for a fundraiser."""
    fundraiser_name = args.get("fundraiser_name", "").strip()
    if not fundraiser_name:
        wa.send_text(chat_id, "¿Cuál actividad quieres pagar? Dime el nombre.")
        return

    cmd_text = f"pagar {fundraiser_name}"
    await payment_flow.start_from_command(raw_jid, chat_id, cmd_text, db, sender)
    logger.info(f"INTENT_TOOLS start_payment fundraiser={fundraiser_name}")


async def start_receipt_flow(args, *, raw_jid, chat_id, db, sender, **kw):
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
        # Auto-select the only active fundraiser
        fundraiser = active_fundraisers[0]
    elif fundraiser_name:
        # Try to match by name
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
        # Multiple fundraisers, ask which one
        names = "\n".join(f"  • `/pagar {f.name}`" for f in active_fundraisers)
        wa.send_text(
            chat_id,
            f"Hay varias actividades activas:\n{names}\n\n"
            "Dime cuál quieres pagar.",
        )
        return

    # Start the payment flow using the standard entry point
    cmd_text = f"pagar {fundraiser.name}"
    await payment_flow.start_from_command(raw_jid, chat_id, cmd_text, db, sender)
    logger.info(f"INTENT_TOOLS start_receipt_flow fundraiser={fundraiser.name}")


async def list_active_fundraisers(args, *, chat_id, db, **kw):
    """List active fundraisers."""
    fundraisers = db.query(models.Fundraiser).filter_by(status="active").all()
    if not fundraisers:
        wa.send_text(chat_id, "No hay actividades activas en este momento.")
        return

    lines = ["📋 *Actividades activas:*\n"]
    for f in fundraisers:
        if f.type == "fixed":
            lines.append(f"  • *{f.name}* — ${f.fixed_amount} (monto fijo)")
        else:
            products = db.query(models.FundraiserProduct).filter_by(fundraiser_id=f.id).all()
            lines.append(f"  • *{f.name}* — catálogo ({len(products)} productos)")
        lines.append(f"    Para pagar: `/pagar {f.name}`")
        lines.append("")

    wa.send_text(chat_id, "\n".join(lines))
    logger.info(f"INTENT_TOOLS list_active_fundraisers count={len(fundraisers)}")


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
