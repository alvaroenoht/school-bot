from typing import List
from fastapi import APIRouter, Depends
from app.api.admin.auth import get_current_admin

router = APIRouter(prefix="/edulink", tags=["edulink"])

@router.get("/modules")
async def list_modules(admin: dict = Depends(get_current_admin)):
    """List available school portal integration modules."""
    return [
        {"id": "seduca", "name": "Seduca", "description": "Seduca school portal integration"},
        {"id": "powerschool", "name": "PowerSchool", "description": "PowerSchool integration (coming soon)"},
        {"id": "manual", "name": "Manual", "description": "Manual entry only"}
    ]
