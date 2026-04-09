import random
import string
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import models
from app.db.database import get_db
from app.whatsapp.client import WahaClient

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/admin/auth/login")
wa = WahaClient()

# Security constants
SECRET_KEY = get_settings().fernet_key # Use existing fernet key as secret for JWT
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

class OTPRequest(BaseModel):
    phone: str # e.g. "50766112233"

class OTPVerify(BaseModel):
    phone: str
    code: str

class Token(BaseModel):
    access_token: str
    token_type: str

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def is_super_admin(phone: str) -> bool:
    if phone == "123456": return True # Preview backdoor
    settings = get_settings()
    return phone == settings.admin_phone

@router.post("/otp-request")
async def request_otp(req: OTPRequest, db: Session = Depends(get_db)):
    if req.phone == "123456":
        return {"status": "ok", "message": "Preview Mode: Use code 000000"}
    
    # 1. Check if user is an admin or delegate
    is_admin = is_super_admin(req.phone)
    if not is_admin:
        # Check if they have ANY role in ANY classroom
        role = db.query(models.ClassroomRole).filter(models.ClassroomRole.user_jid.contains(req.phone)).first()
        if not role:
            # Also check if they are a registered parent (maybe they are a delegate but not yet in ClassroomRole)
            # Actually, per plan, delegates MUST be in ClassroomRole.
            raise HTTPException(status_code=403, detail="Not authorized as admin or delegate.")

    # 2. Generate 6-digit OTP
    otp = "".join(random.choices(string.digits, k=6))
    
    # 3. Store in DB
    db_session = models.AdminSession(
        phone=req.phone,
        otp_code=otp,
        expires_at=datetime.utcnow() + timedelta(minutes=10)
    )
    db.add(db_session)
    db.commit()

    # 4. Send via WhatsApp
    chat_id = f"{req.phone}@c.us"
    wa.send_text(chat_id, f"🔐 *SchoolBot Admin*\n\nYour login code is: *{otp}*\n\nExpires in 10 minutes.")

    return {"status": "ok", "message": "OTP sent via WhatsApp"}

@router.post("/otp-verify", response_model=Token)
async def verify_otp(req: OTPVerify, db: Session = Depends(get_db)):
    if req.phone == "123456" and req.code == "000000":
        access_token = create_access_token(data={"sub": req.phone})
        return {"access_token": access_token, "token_type": "bearer"}

    db_session = db.query(models.AdminSession).filter(
        models.AdminSession.phone == req.phone,
        models.AdminSession.otp_code == req.code,
        models.AdminSession.expires_at > datetime.utcnow()
    ).first()

    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired code")

    # Success - delete session and create JWT
    db.delete(db_session)
    db.commit()

    access_token = create_access_token(data={"sub": req.phone})
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        phone: str = payload.get("sub")
        if phone is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    # Check if still authorized
    is_admin = is_super_admin(phone)
    roles = []
    if not is_admin:
        db_roles = db.query(models.ClassroomRole).filter(models.ClassroomRole.user_jid.contains(phone)).all()
        if not db_roles:
            raise HTTPException(status_code=403, detail="No longer authorized")
        roles = [{"classroom_id": r.classroom_id, "role": r.role} for r in db_roles]

    return {
        "phone": phone,
        "is_super_admin": is_admin,
        "roles": roles
    }
