import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin.auth import get_current_admin, require_write_access
from app.db import models
from app.db.database import get_db
from app.whatsapp.client import WahaClient

_wa_instance: WahaClient | None = None

def _get_wa() -> WahaClient:
    global _wa_instance
    if _wa_instance is None:
        _wa_instance = WahaClient()
    return _wa_instance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/classrooms", tags=["classrooms"])
wa = WahaClient()


class ClassroomCreate(BaseModel):
    name: str
    display_name: Optional[str] = None
    parent_id: Optional[int] = None  # for nesting under a school/grade


class ClassroomUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    whatsapp_group_id: Optional[str] = None
    settings: Optional[dict] = None


@router.post("")
async def create_classroom(
    req: ClassroomCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Create a new classroom. Super admin only."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")
    classroom = models.Classroom(
        name=req.name,
        display_name=req.display_name or req.name,
        parent_id=req.parent_id,
        is_active=True,
    )
    db.add(classroom)
    db.commit()
    db.refresh(classroom)
    return classroom


@router.get("")
async def list_classrooms(db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if admin["is_super_admin"]:
        classrooms = db.query(models.Classroom).all()
    else:
        my_ids = [r["classroom_id"] for r in admin["roles"]]
        classrooms = db.query(models.Classroom).filter(models.Classroom.id.in_(my_ids)).all()

    result = []
    for c in classrooms:
        # Count unique child_names (kids) in this classroom
        kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=c.id, active=True).all()
        child_names = {kcg.child_name.lower().strip() for kcg in kcgs if kcg.child_name}
        unnamed = sum(1 for kcg in kcgs if not kcg.child_name)
        obj = {col.name: getattr(c, col.name) for col in c.__table__.columns}
        obj["kids_count"] = len(child_names) + unnamed
        obj["members_count"] = len(kcgs)
        result.append(obj)
    return result


@router.patch("/{classroom_id}")
async def update_classroom(
    classroom_id: int,
    req: ClassroomUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404)

    if req.name:
        classroom.name = req.name
    if req.display_name:
        classroom.display_name = req.display_name
    if req.settings:
        curr = classroom.settings or {}
        curr.update(req.settings)
        classroom.settings = curr

    db.commit()
    return {"status": "updated"}


@router.delete("/{classroom_id}")
async def delete_classroom(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Delete empty classroom. Super admin only."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404)

    # Only allow if no members
    member_count = db.query(models.KnownContactGroup).filter_by(
        classroom_id=classroom_id, active=True
    ).count()
    if member_count > 0:
        raise HTTPException(status_code=400, detail="No se puede eliminar un grupo con miembros")

    db.delete(classroom)
    db.commit()
    return {"status": "deleted"}


@router.get("/{classroom_id}/members")
async def list_members(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Members = WhatsApp group contacts only. Grouped by child_name so 2 parents/1 kid merge."""
    kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=classroom_id, active=True).all()

    # Group identified contacts by child_name; collect unidentified separately
    groups: dict[str, list[dict]] = {}
    display_names: dict[str, str] = {}
    unidentified: list[dict] = []
    for kcg in kcgs:
        kc = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
        if kc:
            phone = kc.phone or kc.jid.replace("@c.us", "").replace("@lid", "")
            entry = {
                "id": kc.id,
                "kcg_id": kcg.id,
                "name": kc.name or kc.jid,
                "jid": kc.jid,
                "phone": phone,
                "is_primary_payer": bool(kcg.is_primary_payer),
            }
        else:
            phone = kcg.contact_jid.replace("@c.us", "").replace("@lid", "")
            entry = {
                "id": None,
                "kcg_id": kcg.id,
                "name": kcg.contact_jid,
                "jid": kcg.contact_jid,
                "phone": phone,
                "is_primary_payer": False,
            }
        raw = (kcg.child_name or "").strip()
        if not raw:
            unidentified.append(entry)
            continue
        key = raw.lower()
        if key not in display_names or raw[0:1].isupper():
            display_names[key] = raw
        groups.setdefault(key, []).append(entry)

    members = []
    for key, parent_entries in groups.items():
        members.append({
            "child_name": display_names.get(key) or "—",
            "parents": parent_entries,
        })
    members.sort(key=lambda r: r["child_name"].lower())

    # Fetch live WA participants and find those not tracked in KCG
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    wa_untracked: list[dict] = []
    if classroom and classroom.whatsapp_group_id:
        # Build set of phones already tracked (KCG uses @lid JIDs, WA returns @c.us)
        tracked_phones: set[str] = set()
        for kcg in kcgs:
            kc = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
            if kc and kc.phone:
                tracked_phones.add(kc.phone)

        live_jids = wa.get_group_participants(classroom.whatsapp_group_id)
        for jid in live_jids:
            if not jid or "@c.us" not in jid:
                continue
            phone = jid.replace("@c.us", "")
            if phone in tracked_phones:
                continue
            # Check if they have a KnownContact record (from another group)
            kc = db.query(models.KnownContact).filter_by(phone=phone).first()
            wa_untracked.append({
                "jid": jid,
                "name": kc.name if kc else phone,
                "phone": phone,
            })

    return {"members": members, "unidentified": unidentified, "wa_untracked": wa_untracked}


class ContactUpdate(BaseModel):
    child_name: Optional[str] = None
    name: Optional[str] = None  # parent display name
    is_primary_payer: Optional[bool] = None


@router.patch("/{classroom_id}/contacts/{contact_id}")
async def update_contact(
    classroom_id: int,
    contact_id: int,
    req: ContactUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Edit kid name (per-classroom on KCG) or parent display name (on KC)."""
    require_write_access(admin, classroom_id)
    kc = db.query(models.KnownContact).filter_by(id=contact_id).first()
    if not kc:
        raise HTTPException(status_code=404, detail="Contact not found")

    kcg = db.query(models.KnownContactGroup).filter_by(
        contact_jid=kc.jid, classroom_id=classroom_id, active=True
    ).first()
    if not kcg:
        raise HTTPException(status_code=403, detail="Contact not in this classroom")

    if req.child_name is not None:
        kcg.child_name = req.child_name.strip() or None
    if req.name is not None:
        kc.name = req.name.strip() or None
    if req.is_primary_payer is not None:
        kcg.is_primary_payer = req.is_primary_payer
    db.commit()
    return {"status": "updated"}


class AddContactRequest(BaseModel):
    jid: str
    child_name: str


@router.post("/{classroom_id}/contacts")
async def add_contact(
    classroom_id: int,
    req: AddContactRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Add an untracked WhatsApp group member as a known contact."""
    require_write_access(admin, classroom_id)
    phone = req.jid.replace("@c.us", "").replace("@lid", "")
    # Get or create KnownContact — match by phone since JID format may differ (@lid vs @c.us)
    kc = db.query(models.KnownContact).filter_by(phone=phone).first()
    if not kc:
        kc = db.query(models.KnownContact).filter_by(jid=req.jid).first()
    if not kc:
        kc = models.KnownContact(jid=req.jid, phone=phone, name=req.child_name.strip())
        db.add(kc)
        db.flush()
    # Get or create KnownContactGroup — check by phone match too
    kcg = db.query(models.KnownContactGroup).filter_by(
        contact_jid=kc.jid, classroom_id=classroom_id
    ).first()
    if kcg:
        kcg.child_name = req.child_name.strip()
        kcg.active = True
    else:
        kcg = models.KnownContactGroup(
            contact_jid=kc.jid,
            classroom_id=classroom_id,
            child_name=req.child_name.strip(),
            active=True,
        )
        db.add(kcg)
    db.commit()
    return {"status": "created", "contact_id": kc.id, "kcg_id": kcg.id}


# ── WhatsApp group binding ─────────────────────────────────────────────────────

@router.get("/all-roles")
async def list_all_roles(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """List all classroom roles across all classrooms. Super admin only."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")

    roles = db.query(models.ClassroomRole).all()
    result = []
    for r in roles:
        cls = db.query(models.Classroom).get(r.classroom_id)
        parent = db.query(models.Parent).filter_by(whatsapp_jid=r.user_jid).first()
        result.append({
            "user_jid": r.user_jid,
            "phone": r.user_jid.replace("@c.us", "").replace("@lid", ""),
            "name": f"{parent.first_name} {parent.last_name}" if parent else None,
            "role": r.role,
            "classroom_id": r.classroom_id,
            "classroom_name": (cls.display_name or cls.name) if cls else str(r.classroom_id),
            "created_at": r.created_at,
        })
    return result


@router.get("/whatsapp-groups")
async def list_whatsapp_groups(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """List all WhatsApp groups the bot has joined, enriched with bound classroom info.
    Super admin only.
    """
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")

    groups = wa.list_groups()

    # Build lookup: whatsapp_group_id → classroom
    bound = {
        c.whatsapp_group_id: c
        for c in db.query(models.Classroom).filter(
            models.Classroom.whatsapp_group_id.isnot(None)
        ).all()
    }

    result = []
    for g in groups:
        gid = g.get("id", {})
        if isinstance(gid, dict):
            group_jid = gid.get("_serialized") or gid.get("id", "")
        else:
            group_jid = str(gid)

        classroom = bound.get(group_jid)
        result.append({
            "id": group_jid,
            "name": g.get("name", group_jid),
            "participant_count": len(g.get("participants", [])),
            "bound_classroom_id": classroom.id if classroom else None,
            "bound_classroom_name": (classroom.display_name or classroom.name) if classroom else None,
        })

    return result


class BindGroupRequest(BaseModel):
    whatsapp_group_id: str


@router.post("/{classroom_id}/bind-group")
async def bind_group(
    classroom_id: int,
    req: BindGroupRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Bind a WhatsApp group to this classroom. Super admin or classroom delegate."""
    require_write_access(admin, classroom_id)
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    # Auth: super admin or delegate of this classroom
    if not admin["is_super_admin"]:
        role = db.query(models.ClassroomRole).filter_by(
            user_jid=f"{admin['phone']}@c.us", classroom_id=classroom_id
        ).first()
        if not role:
            raise HTTPException(status_code=403)

    # Check if another classroom already owns this group
    existing = db.query(models.Classroom).filter(
        models.Classroom.whatsapp_group_id == req.whatsapp_group_id,
        models.Classroom.id != classroom_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Group already bound to classroom '{existing.display_name or existing.name}'"
        )

    classroom.whatsapp_group_id = req.whatsapp_group_id
    if not classroom.display_name:
        # Will be overwritten below once we fetch the group name from WAHA
        classroom.display_name = classroom.name
    db.commit()

    # Seed KnownContactGroup from group participants (async-safe — runs synchronously here)
    try:
        from app.scheduler.jobs import _sync_known_contact_groups_job
        import asyncio
        asyncio.ensure_future(_sync_known_contact_groups_job())
    except Exception as e:
        logger.warning(f"Post-bind KCG sync failed: {e}")

    return {"status": "bound", "classroom_id": classroom_id, "whatsapp_group_id": req.whatsapp_group_id}


class BindGroupLinkRequest(BaseModel):
    invite_link: str


@router.post("/{classroom_id}/bind-group-link")
async def bind_group_via_link(
    classroom_id: int,
    req: BindGroupLinkRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Join a WhatsApp group via invite link and bind it to this classroom."""
    require_write_access(admin, classroom_id)
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    if not admin["is_super_admin"]:
        role = db.query(models.ClassroomRole).filter_by(
            user_jid=f"{admin['phone']}@c.us", classroom_id=classroom_id
        ).first()
        if not role:
            raise HTTPException(status_code=403)

    # Join the group via WAHA
    result = wa.join_group_via_link(req.invite_link)
    if not result:
        raise HTTPException(status_code=400, detail="No se pudo unir al grupo. Verifica el enlace.")

    # Extract group JID from various possible response shapes
    group_jid: str | None = None
    if isinstance(result, dict):
        # Try common WAHA response shapes
        gid = result.get("gid") or result.get("id") or result.get("chatId") or {}
        if isinstance(gid, dict):
            group_jid = gid.get("_serialized") or gid.get("id")
        elif isinstance(gid, str):
            group_jid = gid
        if not group_jid:
            # Some versions return chatId as top-level string
            group_jid = result.get("chatId") or result.get("groupId")

    if not group_jid:
        raise HTTPException(status_code=500, detail=f"No se pudo extraer el JID del grupo: {result}")

    # Check not already bound to another classroom
    existing = db.query(models.Classroom).filter(
        models.Classroom.whatsapp_group_id == group_jid,
        models.Classroom.id != classroom_id,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Grupo ya vinculado al salón '{existing.display_name or existing.name}'"
        )

    classroom.whatsapp_group_id = group_jid
    if not classroom.display_name:
        classroom.display_name = classroom.name
    db.commit()

    try:
        from app.scheduler.jobs import _sync_known_contact_groups_job
        import asyncio
        asyncio.ensure_future(_sync_known_contact_groups_job())
    except Exception as e:
        logger.warning(f"Post-bind KCG sync failed: {e}")

    return {"status": "bound", "classroom_id": classroom_id, "whatsapp_group_id": group_jid}


@router.post("/{classroom_id}/unbind-group")
async def unbind_group(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Unbind the WhatsApp group from this classroom."""
    require_write_access(admin, classroom_id)
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    if not admin["is_super_admin"]:
        role = db.query(models.ClassroomRole).filter_by(
            user_jid=f"{admin['phone']}@c.us", classroom_id=classroom_id
        ).first()
        if not role:
            raise HTTPException(status_code=403)

    classroom.whatsapp_group_id = None
    db.commit()
    return {"status": "unbound"}


# ── Role assignment ────────────────────────────────────────────────────────────

class RoleAssign(BaseModel):
    phone: str   # parent phone number, e.g. "50766112233"
    role: str = "admin"  # admin | delegate | sub_delegate | support


@router.post("/{classroom_id}/roles")
async def assign_role(
    classroom_id: int,
    req: RoleAssign,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Assign or update a delegate role on a classroom. Super admin only."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")

    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    user_jid = f"{req.phone}@c.us"

    # Upsert: update role if row already exists for this user+classroom
    existing = db.query(models.ClassroomRole).filter_by(
        user_jid=user_jid, classroom_id=classroom_id
    ).first()
    if existing:
        existing.role = req.role
    else:
        db.add(models.ClassroomRole(
            user_jid=user_jid,
            classroom_id=classroom_id,
            role=req.role,
        ))
    db.commit()
    return {"status": "assigned", "user_jid": user_jid, "role": req.role}


@router.delete("/{classroom_id}/roles/{phone}")
async def remove_role(
    classroom_id: int,
    phone: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Remove a delegate role. Super admin only."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")

    user_jid = f"{phone}@c.us"
    role = db.query(models.ClassroomRole).filter_by(
        user_jid=user_jid, classroom_id=classroom_id
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    db.delete(role)
    db.commit()
    return {"status": "removed"}


@router.get("/{classroom_id}/roles")
async def list_roles(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """List delegates for a classroom."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super admin only")

    roles = db.query(models.ClassroomRole).filter_by(classroom_id=classroom_id).all()
    result = []
    for r in roles:
        parent = db.query(models.Parent).filter_by(whatsapp_jid=r.user_jid).first()
        result.append({
            "user_jid": r.user_jid,
            "phone": r.user_jid.replace("@c.us", "").replace("@lid", ""),
            "name": f"{parent.first_name} {parent.last_name}" if parent else None,
            "role": r.role,
            "created_at": r.created_at,
        })
    return result
