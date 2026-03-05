"""
Q&A handler — answers parent questions about assignments.

Triggered when a registered parent @mentions the bot in a group
or sends a DM. Only responds to recognized intents; otherwise
shows a help message.

Supported queries:
    hoy / today                       → today's assignments
    mañana / tomorrow                 → tomorrow's assignments
    lunes / martes / ... / viernes    → next occurrence of that weekday
    semana / week                     → full weekly summary
    materiales / traer / necesita     → materials for tomorrow
"""
import logging
from datetime import date, datetime, timedelta

import pytz
from sqlalchemy.orm import Session

from app.db import models
from app.utils.summary_formatter import generate_weekly_data, generate_weekly_summary
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

PANAMA_TZ = pytz.timezone("America/Panama")

# ── Intent detection ───────────────────────────────────────────────────────────

_DAY_KEYWORDS = {
    "lunes": 0, "monday": 0,
    "martes": 1, "tuesday": 1,
    "miércoles": 2, "miercoles": 2, "wednesday": 2,
    "jueves": 3, "thursday": 3,
    "viernes": 4, "friday": 4,
}

_MATERIAL_KEYWORDS = {"material", "materiales", "traer", "necesita", "llevar", "mochila"}
_WEEK_KEYWORDS = {"semana", "week", "próxima", "proxima"}
_TODAY_KEYWORDS = {"hoy", "today"}
_TOMORROW_KEYWORDS = {"mañana", "manana", "tomorrow"}


def _parse_intent(text: str):
    words = set(text.lower().split())
    if words & _TODAY_KEYWORDS:
        return ("day", 0)         # offset from today
    if words & _TOMORROW_KEYWORDS or words & _MATERIAL_KEYWORDS:
        return ("day", 1)
    if words & _WEEK_KEYWORDS:
        return ("week", None)
    for kw, wd in _DAY_KEYWORDS.items():
        if kw in text.lower():
            return ("weekday", wd)
    return ("unknown", None)


# ── Handler ────────────────────────────────────────────────────────────────────

async def handle(phone: str, chat_id: str, text: str, db: Session, parent: models.Parent):
    today = datetime.now(PANAMA_TZ).date()
    student_ids = parent.student_ids or []
    intent, value = _parse_intent(text)

    if intent == "day":
        target = today + timedelta(days=value)
        label = "hoy" if value == 0 else "mañana"
        _send_day(chat_id, target, label, student_ids, db)

    elif intent == "weekday":
        target = _next_weekday(today, value)
        day_names = ["lunes", "martes", "miércoles", "jueves", "viernes"]
        label = f"el {day_names[value]}"
        _send_day(chat_id, target, label, student_ids, db)

    elif intent == "week":
        start = _next_weekday(today, 0)   # next Monday
        end = start + timedelta(days=4)
        raw_conn = db.connection().connection.dbapi_connection
        for sid in student_ids:
            msg = generate_weekly_summary(raw_conn, sid, start, end)
            if msg:
                wa.send_text(chat_id, msg)

    else:
        wa.send_text(
            chat_id,
            "🤔 No entendí tu pregunta. Puedes preguntarme:\n\n"
            "• ¿Qué hay *hoy* o *mañana*?\n"
            "• ¿Qué hay el *lunes / martes / miércoles / jueves / viernes*?\n"
            "• ¿Qué hay esta *semana*?\n"
            "• ¿Qué *materiales* necesitan traer?",
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _send_day(chat_id: str, target: date, label: str, student_ids: list, db: Session):
    assignments = (
        db.query(models.Assignment)
        .filter(
            models.Assignment.student_id.in_(student_ids),
            models.Assignment.date == target.isoformat(),
        )
        .all()
    )

    if not assignments:
        wa.send_text(chat_id, f"✅ No hay actividades registradas para {label} ({target.strftime('%d/%m')}).")
        return

    lines = [f"📅 *Actividades para {label} {target.strftime('(%d/%m)')}:*\n"]
    for a in assignments:
        subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
        icon = subject.icon if subject else "📘"
        name = subject.name if subject else f"Materia {a.subject_id}"
        lines.append(f"{icon} *{name}*: {a.title}")
        if a.summary:
            lines.append(f"   _{a.summary}_")
        if a.materials:
            lines.append(f"   🎒 {a.materials}")
        lines.append("")

    wa.send_text(chat_id, "\n".join(lines))


def _next_weekday(ref: date, weekday: int) -> date:
    """Return the next occurrence of weekday (0=Mon) on or after tomorrow."""
    days = (weekday - ref.weekday()) % 7
    if days == 0:
        days = 7   # always go forward
    return ref + timedelta(days=days)
