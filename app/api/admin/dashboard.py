"""
Read-only parent dashboard for the always-on SEDUCA iPad kiosk.

Two audiences:
  * The kiosk page + its data endpoints, authenticated by a long-lived
    DashboardToken (not the admin JWT). Read-only, scoped to fixed student_ids.
  * Admin-gated token management (mint / list / revoke), reusing get_current_admin.

Window rule (America/Panama, 7 AM school-start cutoff), computed server-side so
the iPad never depends on its own clock:
  * Mon-Thu before 07:00 -> today + next school day     (2-day view)
  * Mon-Thu at/after 07:00 -> tomorrow + the day after   (2-day view)
  * Fri before 07:00      -> Friday + next Monday        (2-day view)
  * Fri at/after 07:00    -> full next week (Mon-Fri)
  * Sat/Sun               -> full next week (Mon-Fri)
"""
from datetime import datetime, timedelta
from html import unescape as html_unescape
from pathlib import Path
from typing import Optional

import pytz
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin.auth import get_current_admin, require_write_access
from app.config import get_settings
from app.db import models
from app.db.database import get_db
from app.utils.dashboard_tokens import TOKEN_TTL_DAYS, build_dashboard_path, new_token
from app.utils.dashboard_window import compute_window, relative_label
from app.utils.jid_utils import find_parent_by_jid
from app.utils.summary_formatter import _TYPE_ABBREV, days_es, translate_date

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

PANAMA_TZ = pytz.timezone(get_settings().timezone)
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


# ── Token auth (kiosk side) ──────────────────────────────────────────────────

def _resolve_token(db: Session, token_str: Optional[str]) -> models.DashboardToken:
    if not token_str:
        raise HTTPException(status_code=401, detail="Missing dashboard token")
    tok = (
        db.query(models.DashboardToken)
        .filter(models.DashboardToken.token == token_str,
                models.DashboardToken.is_active == True)  # noqa: E712
        .first()
    )
    if not tok:
        raise HTTPException(status_code=401, detail="Invalid or revoked token")
    if tok.expires_at and tok.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")
    tok.last_used_at = datetime.utcnow()
    db.commit()
    return tok


async def get_dashboard_scope(
    x_dashboard_token: Optional[str] = Header(default=None),
    token: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> models.DashboardToken:
    """Accept the kiosk token from the X-Dashboard-Token header or ?token= query."""
    return _resolve_token(db, x_dashboard_token or token)


# ── Serialization ────────────────────────────────────────────────────────────

def _serialize_assignment(a: models.Assignment, subjects: dict) -> dict:
    icon, name = subjects.get(a.subject_id, ("📘", f"Materia {a.subject_id}"))
    return {
        "id": a.id,
        "title": (a.title or "").strip(),
        "type": a.type,
        "type_abbrev": _TYPE_ABBREV.get(a.type),
        "subject": {"name": name, "icon": icon or "📘"},
        "summary": a.summary,
        "materials": a.materials,
        "short_url": a.short_url,
        "has_description": bool(a.description),
    }


def _safe_date_label(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    try:
        return translate_date(datetime.strptime(date_str, "%Y-%m-%d").date())
    except (ValueError, TypeError):
        return date_str


def _html_to_text(raw: Optional[str]) -> str:
    """Flatten SEDUCA's HTML description to clean, readable plain text.

    Entities are decoded until stable first, so even double-escaped markup
    (`&lt;p&gt;`) collapses to real tags that then get stripped — the kiosk shows
    text, not markup. Blocks and <br> become newlines so it isn't crammed onto
    one line.
    """
    if not raw:
        return ""
    # SEDUCA's description is scraped from a JS string literal, which leaves
    # backslash-escaped punctuation behind — closing tags arrive as `<\/p>`.
    # Undo those escapes so the tags parse instead of leaking as visible chars.
    text = raw.replace("\\/", "/").replace('\\"', '"').replace("\\'", "'")
    # Decode entities repeatedly so double-encoded HTML surfaces as real tags.
    for _ in range(3):
        decoded = html_unescape(text)
        if decoded == text:
            break
        text = decoded

    soup = BeautifulSoup(text, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"]):
        block.append("\n")
    text = soup.get_text().replace("\xa0", " ")

    # Trim each line and collapse runs of blank lines to a single separator.
    out, blank = [], False
    for line in text.splitlines():
        line = line.strip()
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    return "\n".join(out).strip()


# ── Kiosk page + data ────────────────────────────────────────────────────────

@router.get("")
def dashboard_page():
    """Serve the self-contained kiosk HTML (auth happens client-side via token)."""
    path = STATIC_DIR / "dashboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="dashboard.html not found")
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-cache"})


@router.get("/board")
def dashboard_board(
    scope: models.DashboardToken = Depends(get_dashboard_scope),
    db: Session = Depends(get_db),
):
    now = datetime.now(PANAMA_TZ)
    win = compute_window(now)
    today = now.date()
    student_ids = scope.student_ids or []

    subjects = {s.materia_id: (s.icon or "📘", s.name) for s in db.query(models.Subject).all()}

    children = []
    for sid in student_ids:
        student = db.query(models.Student).filter_by(id=sid).first()
        if not student:
            continue
        classroom = student.classroom
        classroom_name = (classroom.display_name or classroom.name) if classroom else None

        days = []
        for d in win["dates"]:
            rows = (
                db.query(models.Assignment)
                .filter(models.Assignment.student_id == sid,
                        models.Assignment.date == d.isoformat())
                .all()
            )
            days.append({
                "date": d.isoformat(),
                "label": translate_date(d),
                "weekday_es": days_es[d.strftime("%A")],
                "day_num": d.day,
                "relative": relative_label(today, d),
                "assignments": [_serialize_assignment(a, subjects) for a in rows],
            })

        children.append({
            "student_id": sid,
            "name": student.name,
            "classroom": classroom_name,
            "days": days,
        })

    return {
        "mode": win["mode"],
        "relative": win["relative"],
        "range_label": win["range_label"],
        "badge": win["badge"],
        "generated_at": now.isoformat(),
        "children": children,
    }


@router.get("/assignment")
def dashboard_assignment(
    student_id: int,
    id: int,
    scope: models.DashboardToken = Depends(get_dashboard_scope),
    db: Session = Depends(get_db),
):
    if student_id not in (scope.student_ids or []):
        raise HTTPException(status_code=403, detail="Student not in scope")

    a = db.query(models.Assignment).filter_by(id=id, student_id=student_id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")

    subject = db.query(models.Subject).filter_by(materia_id=a.subject_id).first()
    return {
        "id": a.id,
        "title": (a.title or "").strip(),
        "type": a.type,
        "type_abbrev": _TYPE_ABBREV.get(a.type),
        "date": a.date,
        "date_label": _safe_date_label(a.date),
        "subject": {
            "name": subject.name if subject else f"Materia {a.subject_id}",
            "icon": (subject.icon if subject else "📘") or "📘",
        },
        "summary": a.summary,
        "materials": a.materials,
        "description_text": _html_to_text(a.description),
    }


# ── Token management (admin-gated) ───────────────────────────────────────────

class TokenCreate(BaseModel):
    label: Optional[str] = None
    student_ids: Optional[list[int]] = None


def _token_row(t: models.DashboardToken, include_secret: bool = False) -> dict:
    out = {
        "id": t.id,
        "label": t.label,
        "student_ids": t.student_ids,
        "is_active": t.is_active,
        "created_at": t.created_at,
        "last_used_at": t.last_used_at,
        "expires_at": t.expires_at,
        "path": build_dashboard_path(t.token),
    }
    if include_secret:
        out["token"] = t.token
    return out


@router.post("/tokens")
async def create_token(
    req: TokenCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)

    student_ids = req.student_ids
    if not student_ids:
        # Default scope = the admin's own children.
        parent = find_parent_by_jid(db, admin["phone"] + "@c.us", None, require_active=False)
        student_ids = (parent.student_ids if parent else None) or []
    if not student_ids:
        raise HTTPException(status_code=400, detail="No students to scope. Provide student_ids.")

    tok = models.DashboardToken(
        token=new_token(),
        label=req.label,
        student_ids=student_ids,
        created_by_jid=admin["phone"] + "@c.us",
        expires_at=datetime.utcnow() + timedelta(days=TOKEN_TTL_DAYS),
    )
    db.add(tok)
    db.commit()
    db.refresh(tok)
    return _token_row(tok, include_secret=True)


@router.get("/tokens")
async def list_tokens(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    q = db.query(models.DashboardToken)
    if not admin["is_super_admin"]:
        q = q.filter(models.DashboardToken.created_by_jid == admin["phone"] + "@c.us")
    toks = q.order_by(models.DashboardToken.created_at.desc()).all()
    return [_token_row(t, include_secret=True) for t in toks]


@router.delete("/tokens/{token_id}")
async def revoke_token(
    token_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    t = db.query(models.DashboardToken).filter_by(id=token_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Token not found")
    if not admin["is_super_admin"] and t.created_by_jid != admin["phone"] + "@c.us":
        raise HTTPException(status_code=403, detail="Not your token")
    t.is_active = False
    db.commit()
    return {"status": "revoked"}
