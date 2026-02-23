"""Auth: admin login and admin registration (curl/Postman only)."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from passlib.context import CryptContext
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel

from api.auth import create_admin_token
from api.config import ADMIN_SECRET
from api.db import admin_users_collection

router = APIRouter(tags=["auth"])
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt has a 72-byte limit; truncate to avoid ValueError
def _truncate_password(pwd: str) -> str:
    if not pwd:
        return pwd
    encoded = pwd.encode("utf-8")
    if len(encoded) <= 72:
        return pwd
    return encoded[:72].decode("utf-8", errors="ignore")


class LoginBody(BaseModel):
    email: str
    password: str


class RegisterBody(BaseModel):
    email: str
    password: str
    secret: Optional[str] = None


@router.post("/auth/login")
def login(body: LoginBody):
    """Admin login: body { email, password }. Returns { access_token, token_type }."""
    email = (body.email or "").strip().lower()
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="email and password required")
    doc = admin_users_collection().find_one({"email": email})
    if not doc or not pwd_ctx.verify(_truncate_password(body.password), doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_admin_token(str(doc["_id"]))
    return {"access_token": token, "token_type": "bearer"}


@router.post("/admin/register")
def register_admin(
    body: RegisterBody,
    x_admin_secret: Optional[str] = Header(None, alias="X-Admin-Secret"),
):
    """Create an admin account. Requires header X-Admin-Secret (env ADMIN_SECRET). Use curl/Postman."""
    secret = x_admin_secret or body.secret
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    email = (body.email or "").strip().lower()
    if not email or not body.password:
        raise HTTPException(status_code=400, detail="email and password required")
    now = datetime.utcnow()
    doc = {
        "email": email,
        "password_hash": pwd_ctx.hash(_truncate_password(body.password)),
        "created_at": now,
    }
    try:
        admin_users_collection().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Admin with this email already exists")
    return {"email": email, "created": True}
