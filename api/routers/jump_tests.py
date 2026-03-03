"""Jump test submit, get one, list (historical), and viz endpoints."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.config import FORCE_FILTER_CUTOFF_HZ, SMTP_HOST
from api.db import jump_tests_collection, users_collection
from api.email_sender import send_jump_test_link
from api.models import JumpTestDetail, JumpTestListResponse, JumpTestSubmit, JumpTestSummary

router = APIRouter(prefix="/jump-tests", tags=["jump-tests"])


def _make_serializable(obj: Any) -> Any:
    """Convert numpy types and nested structures to JSON-serializable form for MongoDB."""
    import numpy as np

    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(x) for x in obj]
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# Minimum jump height (m) to consider a valid jump; below this = invalid_jump (user mistake / wrong test)
MIN_JUMP_HEIGHT_M = 0.01


def _quality_tag(metrics: Dict[str, Any], review_verdict: Optional[str]) -> Optional[str]:
    """Compute quality_tag for list display: bad_data, wrong_detection, invalid_jump, correct, no_detection, skip."""
    jump_m = (
        metrics.get("jump_height_impulse_m")
        or metrics.get("jump_height_flight_m")
        or metrics.get("jump_height_m")
    )
    if jump_m is None or (isinstance(jump_m, (int, float)) and float(jump_m) < MIN_JUMP_HEIGHT_M):
        return "invalid_jump"
    if review_verdict == "data_bad":
        return "bad_data"
    if review_verdict == "points_wrong":
        return "wrong_detection"
    if review_verdict == "correct":
        return "correct"
    if review_verdict in ("no_detection", "skip"):
        return review_verdict
    return None


@router.post("")
def submit_jump_test(body: JumpTestSubmit):
    """
    Submit jump test data; run analysis, store raw + result in MongoDB, return result.
    Body: athlete_id, test_type, test_duration, force or total_force, left_force, right_force; optional user_id.
    """
    from src.run_analysis import run_analysis

    payload = body.to_analysis_payload()
    filter_hz = body.filter_cutoff_hz if body.filter_cutoff_hz is not None else FORCE_FILTER_CUTOFF_HZ
    try:
        result = run_analysis(payload, filter_cutoff_hz=filter_hz)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result_serialized = _make_serializable(result)
    now = datetime.utcnow()
    doc = {
        "user_id": str(body.user_id) if body.user_id else None,
        "athlete_id": (body.athlete_id or body.user_id or "unknown"),
        "test_type": (body.test_type or "").strip().upper() or "CMJ",
        "raw": _make_serializable(payload),
        "result": result_serialized,
        "created_at": now,
    }
    insert_result = jump_tests_collection().insert_one(doc)
    test_id = str(insert_result.inserted_id)
    return JSONResponse(content={"id": test_id, **result_serialized})


@router.get("/{test_id}", response_model=JumpTestDetail)
def get_jump_test(test_id: str, include_raw: bool = Query(False, description="Include raw request body")):
    """Get one stored jump test by ID (result + metadata; optional raw)."""
    try:
        oid = ObjectId(test_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Jump test not found")
    doc = jump_tests_collection().find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Jump test not found")
    return JumpTestDetail(
        id=str(doc["_id"]),
        user_id=doc.get("user_id"),
        athlete_id=doc["athlete_id"],
        test_type=doc["test_type"],
        result=doc["result"],
        created_at=doc["created_at"],
        raw=doc.get("raw") if include_raw else None,
    )


@router.get("/{test_id}/viz")
def get_jump_test_viz(test_id: str):
    """Return only the result payload (viz JSON shape) for the existing viewer."""
    try:
        oid = ObjectId(test_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Jump test not found")
    doc = jump_tests_collection().find_one(
        {"_id": oid}, projection={"result": 1, "user_id": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Jump test not found")
    result = doc["result"]
    uid = doc.get("user_id")
    if uid:
        try:
            user = users_collection().find_one(
                {"_id": ObjectId(uid)},
                projection={"name": 1, "last_name": 1, "gender": 1, "email": 1},
            )
        except Exception:
            user = None
        if user:
            result["athlete_details"] = {
                "first_name": user.get("name"),
                "last_name": user.get("last_name"),
                "gender": user.get("gender"),
                "email": user.get("email"),
            }
    return JSONResponse(content=result)


@router.get("", response_model=JumpTestListResponse)
def list_jump_tests(
    user_id: Optional[str] = Query(None),
    athlete_id: Optional[str] = Query(None),
    test_type: Optional[str] = Query(None),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List jump tests (historical) with optional filters and pagination."""
    filt: Dict[str, Any] = {}
    if user_id is not None:
        filt["user_id"] = user_id
    if athlete_id is not None:
        filt["athlete_id"] = athlete_id
    if test_type is not None:
        filt["test_type"] = test_type.strip().upper()
    if from_date is not None or to_date is not None:
        filt["created_at"] = {}
        if from_date is not None:
            filt["created_at"]["$gte"] = from_date
        if to_date is not None:
            filt["created_at"]["$lte"] = to_date

    coll = jump_tests_collection()
    total = coll.count_documents(filt)
    cursor = coll.find(filt).sort("created_at", -1).skip(offset).limit(limit)

    items: List[JumpTestSummary] = []
    for d in cursor:
        metrics = (d.get("result") or {}).get("metrics") or {}
        review_verdict = (d.get("review") or {}).get("verdict")
        tag = _quality_tag(metrics, review_verdict)
        items.append(
            JumpTestSummary(
                id=str(d["_id"]),
                athlete_id=d["athlete_id"],
                test_type=d["test_type"],
                created_at=d["created_at"],
                metrics=_make_serializable(metrics),
                quality_tag=tag,
            )
        )

    return JumpTestListResponse(items=items, total=total, limit=limit, offset=offset)


class SendLinkBody(BaseModel):
    email: Optional[str] = None


@router.post("/{test_id}/send-link")
def send_jump_test_link_email(test_id: str, body: Optional[SendLinkBody] = Body(None)):
    """
    Send an email with a link to view this jump test.
    Body: optional { "email": "override@example.com" }. If omitted, email is taken from the test's user_id (user document).
    Returns 200 { "sent": true } or 503 if email is not configured or send failed.
    """
    try:
        oid = ObjectId(test_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Jump test not found")
    doc = jump_tests_collection().find_one({"_id": oid}, projection={"user_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="Jump test not found")

    to_email = None
    if body and body.email and body.email.strip():
        to_email = body.email.strip()
    elif doc.get("user_id"):
        try:
            user_oid = ObjectId(doc["user_id"])
        except Exception:
            pass
        else:
            user_doc = users_collection().find_one({"_id": user_oid}, projection={"email": 1})
            if user_doc and user_doc.get("email"):
                to_email = user_doc["email"]

    if not to_email:
        raise HTTPException(status_code=400, detail="No email specified and jump test has no linked user with email")

    ok, err_msg = send_jump_test_link(to_email, test_id, user_id=doc.get("user_id"))
    if not ok:
        raise HTTPException(status_code=503, detail=err_msg or "Failed to send email")
    return {"sent": True}
