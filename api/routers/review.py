"""Review (validation) endpoints: store verdicts, statistics, load verdicts, publish and notify."""
from datetime import datetime
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Body, HTTPException, Query

from api.db import jump_tests_collection, users_collection
from api.email_sender import send_results_ready_email
from api.models import (
    ReviewItem,
    ReviewPublishBody,
    ReviewStatisticsResponse,
    ReviewSubmit,
    VALID_VERDICTS,
)

router = APIRouter(prefix="/review", tags=["review"])


def _oid(test_id: str):
    try:
        return ObjectId(test_id)
    except Exception:
        return None


@router.post("")
def submit_review(body: ReviewSubmit):
    """
    Store review verdicts for jump tests.
    Body: { "verdicts": [ { "test_id": "...", "verdict": "correct"|"points_wrong"|"no_detection"|"data_bad"|"skip", "note": "..." } ] }
    """
    coll = jump_tests_collection()
    updated = 0
    errors: List[str] = []
    for item in body.verdicts:
        if item.verdict not in VALID_VERDICTS:
            errors.append(f"test_id={item.test_id}: invalid verdict '{item.verdict}'")
            continue
        oid = _oid(item.test_id)
        if not oid:
            errors.append(f"test_id={item.test_id}: invalid ObjectId")
            continue
        result = coll.update_one(
            {"_id": oid},
            {
                "$set": {
                    "review": {
                        "verdict": item.verdict,
                        "note": (item.note or "").strip() or None,
                        "reviewed_at": datetime.utcnow().isoformat() + "Z",
                    }
                }
            },
        )
        if result.matched_count == 0:
            errors.append(f"test_id={item.test_id}: not found")
        else:
            updated += 1
    return {"updated": updated, "errors": errors if errors else None}


@router.get("/statistics", response_model=ReviewStatisticsResponse)
def get_review_statistics():
    """
    Return aggregates for reviewed tests: total, by verdict, by test_type, by user;
    and list of bad-data tests (data_bad or points_wrong) with notes.
    """
    coll = jump_tests_collection()
    cursor = coll.find({"review": {"$exists": True, "$ne": None}})
    total_reviewed = 0
    by_verdict: Dict[str, int] = {}
    by_test_type: Dict[str, int] = {}
    by_user: Dict[str, Dict[str, int]] = {}
    bad_data_tests: List[Dict[str, Any]] = []

    for doc in cursor:
        rev = doc.get("review") or {}
        verdict = rev.get("verdict") or "skip"
        if verdict not in VALID_VERDICTS:
            continue
        total_reviewed += 1
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
        ttype = (doc.get("test_type") or "unknown").upper()
        by_test_type[ttype] = by_test_type.get(ttype, 0) + 1
        uid = doc.get("user_id") or "unknown"
        if uid not in by_user:
            by_user[uid] = {}
        by_user[uid][verdict] = by_user[uid].get(verdict, 0) + 1
        if verdict in ("data_bad", "points_wrong"):
            bad_data_tests.append({
                "test_id": str(doc["_id"]),
                "user_id": uid,
                "verdict": verdict,
                "note": rev.get("note"),
            })

    return ReviewStatisticsResponse(
        total_reviewed=total_reviewed,
        by_verdict=by_verdict,
        by_test_type=by_test_type,
        by_user=by_user,
        bad_data_tests=bad_data_tests,
    )


@router.get("")
def get_review_verdicts(
    test_ids: str = Query(..., description="Comma-separated test IDs to load verdicts for"),
):
    """
    Load stored verdicts for the given test_ids (for pre-filling the review UI).
    Returns { "verdicts": { "test_id": { "verdict", "note?", "reviewed_at?" } } }.
    """
    ids = [x.strip() for x in test_ids.split(",") if x.strip()]
    oids = []
    for tid in ids:
        oid = _oid(tid)
        if oid:
            oids.append(oid)
    if not oids:
        return {"verdicts": {}}
    coll = jump_tests_collection()
    cursor = coll.find({"_id": {"$in": oids}}, projection={"review": 1})
    verdicts: Dict[str, Dict[str, Any]] = {}
    for doc in cursor:
        rev = doc.get("review")
        if rev:
            verdicts[str(doc["_id"])] = {
                "verdict": rev.get("verdict"),
                "note": rev.get("note"),
                "reviewed_at": rev.get("reviewed_at"),
            }
    return {"verdicts": verdicts}


@router.post("/publish")
def publish_review(body: ReviewPublishBody = Body(None)):
    """
    Mark reviewed tests as published (set review.published_at) and send one email per user.
    Does not update result payload (use script/publish_review.py with reanalyzed dir for that).
    Body: optional { "test_ids": ["id1", "id2"] }. If omitted, all documents with review are used.
    """
    coll = jump_tests_collection()
    filt: Dict[str, Any] = {"review": {"$exists": True, "$ne": None}}
    if body and body.test_ids:
        oids = []
        for tid in body.test_ids:
            try:
                oids.append(ObjectId(tid))
            except Exception:
                pass
        if oids:
            filt["_id"] = {"$in": oids}
    published_at = datetime.utcnow().isoformat() + "Z"
    cursor = coll.find(filt, projection={"user_id": 1, "review": 1})
    user_tests: Dict[str, List[Dict[str, Any]]] = {}
    updated = 0
    for doc in cursor:
        oid = doc["_id"]
        rev = doc.get("review") or {}
        verdict = rev.get("verdict")
        note = rev.get("note")
        user_id = doc.get("user_id") or "unknown"
        if user_id not in user_tests:
            user_tests[user_id] = []
        user_tests[user_id].append({"test_id": str(oid), "verdict": verdict, "note": note})
        coll.update_one(
            {"_id": oid},
            {"$set": {"review.published_at": published_at}},
        )
        updated += 1
    sent = 0
    for user_id, tests in user_tests.items():
        if user_id == "unknown":
            continue
        has_bad = any(
            (t.get("verdict") or "") in ("data_bad", "points_wrong") for t in tests
        )
        bad_msg = None
        if has_bad:
            bad_list = [
                t for t in tests
                if (t.get("verdict") or "") in ("data_bad", "points_wrong")
            ]
            bad_msg = (
                f"{len(bad_list)} of your tests had quality issues; details are visible in your dashboard."
                if len(bad_list) > 1
                else "One of your tests had quality issues; details are visible in your dashboard."
            )
        try:
            uid_oid = ObjectId(user_id)
        except Exception:
            continue
        user_doc = users_collection().find_one(
            {"_id": uid_oid},
            projection={"email": 1, "name": 1, "last_name": 1},
        )
        email = (user_doc or {}).get("email")
        if not email:
            continue
        ok, _ = send_results_ready_email(
            to_email=email,
            user_id=user_id,
            has_bad_data=has_bad,
            bad_data_message=bad_msg,
            name=(user_doc or {}).get("name"),
            last_name=(user_doc or {}).get("last_name"),
        )
        if ok:
            sent += 1
    return {"updated": updated, "emails_sent": sent}
