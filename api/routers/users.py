"""User CRUD endpoints."""
from datetime import datetime
from typing import List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from api.auth import require_admin
from api.db import users_collection
from api.email_sender import send_welcome_email
from api.models import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _user_to_response(doc: dict) -> UserResponse:
    return UserResponse(
        id=str(doc["_id"]),
        email=doc["email"],
        name=doc.get("name"),
        last_name=doc.get("last_name"),
        phone_number=doc.get("phone_number"),
        student_number=doc.get("student_number"),
        gender=doc.get("gender"),
        appointment_at=doc.get("appointment_at"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post("", response_model=UserResponse)
def create_user(body: UserCreate, _: str = Depends(require_admin)):
    """Create a new user."""
    now = datetime.utcnow()
    doc = {
        "email": body.email.strip().lower(),
        "name": body.name,
        "last_name": body.last_name,
        "phone_number": body.phone_number,
        "student_number": body.student_number,
        "gender": body.gender,
        "appointment_at": body.appointment_at,
        "created_at": now,
        "updated_at": now,
    }
    try:
        result = users_collection().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="User with this email already exists")
    doc["_id"] = result.inserted_id
    user_id = str(result.inserted_id)
    # Send welcome email with link to my-tests (don't fail creation if email fails)
    parts = [doc.get("name"), doc.get("last_name")]
    display_name = " ".join(p for p in parts if p) or None
    send_welcome_email(to_email=doc["email"], user_id=user_id, name=display_name)
    return _user_to_response(doc)


def _get_user_or_404(user_id: str) -> dict:
    try:
        oid = ObjectId(user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")
    doc = users_collection().find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    return doc


@router.get("/{user_id}", response_model=UserResponse)
def get_user(user_id: str, _: str = Depends(require_admin)):
    """Get one user by ID."""
    doc = _get_user_or_404(user_id)
    return _user_to_response(doc)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(user_id: str, body: UserUpdate, _: str = Depends(require_admin)):
    """Update user (name and/or email)."""
    doc = _get_user_or_404(user_id)
    update: dict = {"updated_at": datetime.utcnow()}
    if body.name is not None:
        update["name"] = body.name
    if body.last_name is not None:
        update["last_name"] = body.last_name
    if body.email is not None:
        update["email"] = body.email.strip().lower()
    if body.phone_number is not None:
        update["phone_number"] = body.phone_number
    if body.student_number is not None:
        update["student_number"] = body.student_number
    if body.gender is not None:
        update["gender"] = body.gender
    if body.appointment_at is not None:
        update["appointment_at"] = body.appointment_at
    if len(update) == 1:
        return _user_to_response(doc)
    try:
        result = users_collection().update_one(
            {"_id": doc["_id"]},
            {"$set": update},
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="User with this email already exists")
    if result.modified_count == 0 and result.matched_count == 1:
        pass  # no change
    updated = users_collection().find_one({"_id": doc["_id"]})
    return _user_to_response(updated)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, _: str = Depends(require_admin)):
    """Delete user. Jump tests linked to this user are left as-is (user_id retained)."""
    doc = _get_user_or_404(user_id)
    users_collection().delete_one({"_id": doc["_id"]})
    return None


@router.get("", response_model=List[UserResponse])
def list_users(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: str = Depends(require_admin),
):
    """List users with pagination."""
    cursor = users_collection().find().sort("created_at", -1).skip(offset).limit(limit)
    return [_user_to_response(d) for d in cursor]
