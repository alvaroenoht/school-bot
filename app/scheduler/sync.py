"""
Assignment sync job — fetches assignments from Seduca for all classrooms
and upserts them into the database via GPT analysis.

Refactored from the original seduca_sync.py AppDaemon class.
"""
import logging
import time
from collections import defaultdict
from datetime import datetime

from app.api.gpt_analyzer import analyze_materials, analyze_change
from app.api.seduca_client import SeducaClient
from app.db.database import SessionLocal
from app.db import models
from app.utils.crypto import decrypt
from app.utils.helpers import shorten_url
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

# Delay between Seduca API calls to avoid overloading the server (seconds)
_API_DELAY = 1.5

# ── Subject emoji auto-picker ─────────────────────────────────────────────────

# More specific rules FIRST — order matters (first match wins)
_EMOJI_RULES: list[tuple[list[str], str]] = [
    (["sociales", "social", "cívica", "historia", "history"],         "📜"),
    (["educación física", "deporte", "physical", "gimnasia"],         "⚽"),
    (["fe", "religión", "religion", "ética", "moral", "valores"],     "⛪"),
    (["familia", "fam.", "comunitar", "orientación", "tutoría", "consejería"], "👨‍👩‍👧"),
    (["matemática", "math", "álgebra", "geometría", "cálculo"],       "🔢"),
    (["ciencia", "science", "biología", "química", "física", "naturales"], "🔬"),
    (["español", "lengua", "literatura", "redacción"],                "📝"),
    (["lectura", "reading"],                                           "📖"),
    (["inglés", "english", "idioma"],                                  "🗣️"),
    (["geografía", "geography"],                                       "🌎"),
    (["arte", "art", "dibujo", "plástica"],                           "🎨"),
    (["música", "music", "canto", "instrumento"],                     "🎵"),
    (["tecnología", "informática", "computación", "robótica"],        "💻"),
    (["francés", "french", "alemán", "german", "mandarín"],           "🌐"),
]


def _pick_emoji(subject_name: str) -> str:
    """Pick an emoji based on the subject name using keyword matching."""
    lower = subject_name.lower()
    for keywords, emoji in _EMOJI_RULES:
        if any(kw in lower for kw in keywords):
            return emoji
    return "📘"  # default


def _ensure_subject(materia_id: int, materia_name: str, db) -> None:
    """Create a Subject row if this materia_id doesn't exist yet."""
    existing = db.query(models.Subject).filter_by(materia_id=materia_id).first()
    if existing:
        # Update name if it changed (rare but possible)
        if existing.name != materia_name:
            existing.name = materia_name
            existing.icon = _pick_emoji(materia_name)
            logger.info(f"  Updated subject {materia_id}: {materia_name}")
        return

    icon = _pick_emoji(materia_name)
    db.add(models.Subject(
        materia_id=materia_id,
        name=materia_name,
        icon=icon,
    ))
    db.flush()  # make visible to subsequent queries in the same transaction
    logger.info(f"  New subject {materia_id}: {materia_name} {icon}")


async def run_sync(classroom_id: int | None = None):
    """
    Sync assignments for all active classrooms (or one specific classroom).
    Safe to call from the scheduler or an admin command.

    After sync, sends change notifications to linked WhatsApp groups.
    """
    db = SessionLocal()
    # Track synced student IDs to avoid re-syncing with duplicate credentials
    synced_student_ids: set[int] = set()
    # Collect changes per student for notification: {student_id: [{"type", "title", "subject_name"}]}
    changes_by_student: dict[int, list[dict]] = defaultdict(list)

    try:
        # Get parents with credentials
        parent_query = db.query(models.Parent).filter(
            models.Parent.encrypted_username.isnot(None),
            models.Parent.is_active == True,
        )
        parents = parent_query.all()
        if not parents:
            logger.warning("No registered parents found for sync.")
            return

        for parent in parents:
            # Get students linked to this parent via student_ids (supports multiple parents)
            student_ids = parent.student_ids or []
            if not student_ids:
                continue

            student_query = db.query(models.Student).filter(
                models.Student.id.in_(student_ids)
            )
            if classroom_id:
                student_query = student_query.filter_by(classroom_id=classroom_id)
            students = student_query.all()
            if not students:
                continue

            # Skip students already synced by another parent with same credentials
            unseen = [s for s in students if s.id not in synced_student_ids]
            if not unseen:
                logger.info(f"Skipping parent {parent.id} — students already synced.")
                continue

            try:
                username = decrypt(parent.encrypted_username)
                password = decrypt(parent.encrypted_password)
            except Exception as e:
                logger.error(f"Could not decrypt credentials for parent {parent.id}: {e}")
                continue

            # Use school_url from the first student's classroom
            first_classroom = db.query(models.Classroom).get(unseen[0].classroom_id)
            if not first_classroom:
                continue

            time.sleep(_API_DELAY)  # rate limit: delay before login
            client = SeducaClient(username, password, base_url=first_classroom.school_url)
            if not client.login():
                logger.error(f"Login failed for parent {parent.id} ({parent.first_name} {parent.last_name})")
                continue

            logger.info(f"Syncing parent {parent.id} ({parent.first_name} {parent.last_name})")

            for student in unseen:
                classroom = db.query(models.Classroom).get(student.classroom_id)
                if not classroom or not classroom.is_active:
                    continue

                time.sleep(_API_DELAY)  # rate limit: delay before switching child
                if not client.switch_child(student.id):
                    logger.warning(f"Could not switch to student {student.id}")
                    continue

                time.sleep(_API_DELAY)  # rate limit: delay before fetching list
                items = client.fetch_assignment_list()
                logger.info(f"  {len(items)} assignments fetched for student {student.id}")

                for item in items:
                    try:
                        time.sleep(_API_DELAY)  # rate limit: delay between assignment details
                        change = _upsert_assignment(item, student.id, client, db)
                        if change:
                            changes_by_student[student.id].append(change)
                    except Exception as e:
                        logger.error(f"  Error processing assignment {item.get('asigId')}: {e}")

                db.commit()
                synced_student_ids.add(student.id)

            logger.info(f"Sync complete for parent {parent.id}")

        # ── Send change notifications to WhatsApp groups ──────────────────────
        _send_change_notifications(changes_by_student, db)

    finally:
        db.close()


# ── Private helpers ────────────────────────────────────────────────────────────

def _upsert_assignment(item: dict, student_id: int, client: SeducaClient, db) -> dict | None:
    """Upsert an assignment. Returns change info dict if new/updated, None otherwise."""
    asig_id     = int(item["asigId"])
    title       = item["asigNombre"]
    date        = item["asigFecha"]
    created_at  = item["asigCreado"]
    type_       = item["asigTipo"]
    subject_id  = int(item["asigMateriaId"])

    # Auto-populate subjects table from Seduca data
    materia_name = (item.get("asigMateriaNombre") or "").strip()
    if materia_name:
        _ensure_subject(subject_id, materia_name, db)

    existing = db.query(models.Assignment).filter_by(
        id=asig_id, student_id=student_id
    ).first()

    description_html = client.fetch_assignment_description(asig_id)
    if not description_html:
        logger.warning(f"  No description for assignment {asig_id}, skipping.")
        return None

    link      = f"{client.base_url}/2/parent/assignments/show?id={asig_id}"
    short_url = shorten_url(link)

    # Only call GPT if description changed or summary is missing
    if existing and existing.description == description_html and existing.summary and existing.materials is not None:
        materials = existing.materials
        summary   = existing.summary
        needs_update = (
            existing.title != title
            or existing.date != date
            or existing.short_url != short_url
        )
    else:
        logger.debug(f"  Calling GPT for assignment {asig_id}...")
        analysis  = analyze_materials(title, description_html)
        materials = ", ".join(analysis["materials"]) if analysis.get("needs_materials") else ""
        summary   = analysis.get("summary", "")
        needs_update = True

    if not needs_update and existing:
        return None

    now = datetime.utcnow().isoformat()
    change_type = None
    old_data = None

    if existing:
        old_data = {
            "title":     existing.title,
            "date":      existing.date,
            "summary":   existing.summary,
            "materials": existing.materials,
        }
        existing.title       = title
        existing.date        = date
        existing.created_at  = created_at
        existing.type        = type_
        existing.subject_id  = subject_id
        existing.description = description_html
        existing.materials   = materials
        existing.summary     = summary
        existing.updated_at  = now
        existing.short_url   = short_url
        change_type = "updated"
        logger.debug(f"  Updated assignment {asig_id}")
    else:
        db.add(models.Assignment(
            id=asig_id,
            student_id=student_id,
            title=title,
            subject_id=subject_id,
            type=type_,
            date=date,
            created_at=created_at,
            description=description_html,
            materials=materials,
            summary=summary,
            updated_at=now,
            short_url=short_url,
        ))
        change_type = "new"
        logger.debug(f"  Inserted new assignment {asig_id}")

    return {
        "type":         change_type,
        "title":        title,
        "subject_name": materia_name or f"Materia {subject_id}",
        "summary":      summary,
        "materials":    materials,
        "date":         date,
        "old":          old_data,
    }


def _send_change_notifications(
    changes_by_student: dict[int, list[dict]], db
) -> None:
    """Send grouped change notifications to WhatsApp groups after sync."""
    if not changes_by_student:
        return

    for student_id, changes in changes_by_student.items():
        student = db.query(models.Student).get(student_id)
        if not student or not student.classroom_id:
            continue
        classroom = db.query(models.Classroom).get(student.classroom_id)
        if not classroom or not classroom.whatsapp_group_id:
            continue

        lines = []
        for c in changes:
            try:
                result = analyze_change(c)
            except Exception as e:
                logger.error(f"  analyze_change failed for '{c.get('title')}': {e}")
                result = {"worth_notifying": True, "message": f"*{c['subject_name']}*: {c['title']}"}

            if not result["worth_notifying"]:
                logger.info(f"  Skipping notification for '{c['title']}' (not worth notifying)")
                continue

            icon = "🆕" if c["type"] == "new" else "✏️"
            lines.append(f"{icon} {result['message']}")

        if lines:
            header = "📝 *Cambios detectados en asignaciones:*\n"
            wa.send_text(classroom.whatsapp_group_id, header + "\n".join(lines))
