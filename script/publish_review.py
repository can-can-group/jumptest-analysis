#!/usr/bin/env python3
"""
Publish review results: update jump_tests in MongoDB with reanalyzed result and review metadata,
then (optionally) send one email per user that their data is ready (with extra text for bad data).

Reads:
  - review_results.json: list of { test_id, type, verdict, note?, ... } (export from review UI).
  - reanalyzed/<type>/<test_id>.json: full viz payload to write into jump_tests.result.

Usage:
  PYTHONPATH=. python script/publish_review.py --review-json review_results.json --reanalyzed-dir reanalyzed
  PYTHONPATH=. python script/publish_review.py --review-json review_results.json --reanalyzed-dir reanalyzed --send-emails
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bson import ObjectId

# Load .env and DB/email from api
from api.db import jump_tests_collection, users_collection
from api.email_sender import send_results_ready_email


def _make_serializable(obj):
    """Convert ObjectId, datetime, and numpy types for JSON."""
    import numpy as np

    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
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


def main():
    parser = argparse.ArgumentParser(
        description="Publish review: update DB with reanalyzed result + review, optionally email users."
    )
    parser.add_argument(
        "--review-json",
        type=Path,
        default=Path("review_results.json"),
        help="Path to exported review_results.json (default: review_results.json)",
    )
    parser.add_argument(
        "--reanalyzed-dir",
        type=Path,
        default=Path("reanalyzed"),
        help="Path to reanalyzed output directory (default: reanalyzed)",
    )
    parser.add_argument(
        "--send-emails",
        action="store_true",
        help="Send one email per user (results ready; extra line if they have bad-data tests)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be updated/sent, do not write to DB or send email",
    )
    args = parser.parse_args()

    if not args.review_json.is_file():
        print(f"Error: {args.review_json} not found.", file=sys.stderr)
        return 1
    if not args.reanalyzed_dir.is_dir():
        print(f"Error: {args.reanalyzed_dir} is not a directory.", file=sys.stderr)
        return 1

    with open(args.review_json, encoding="utf-8") as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        print("Error: review JSON must be a list of objects.", file=sys.stderr)
        return 1

    reviewed = [r for r in rows if r.get("verdict")]
    if not reviewed:
        print("No verdicts in review file. Nothing to publish.")
        return 0

    coll = jump_tests_collection()
    published_at = datetime.utcnow()
    updated = 0
    missing_files = []
    user_tests = {}  # user_id -> list of { test_id, verdict, note }

    for r in reviewed:
        test_id = r.get("test_id")
        ttype = (r.get("type") or "cmj").lower()
        verdict = r.get("verdict")
        note = r.get("note")
        if not test_id or not verdict:
            continue
        reanalyzed_path = args.reanalyzed_dir / ttype / f"{test_id}.json"
        if not reanalyzed_path.is_file():
            missing_files.append(str(reanalyzed_path))
            continue
        with open(reanalyzed_path, encoding="utf-8") as f:
            new_result = json.load(f)
        try:
            oid = ObjectId(test_id)
        except Exception:
            continue
        doc = coll.find_one({"_id": oid}, projection={"user_id": 1})
        if not doc:
            continue
        user_id = doc.get("user_id") or "unknown"
        if user_id not in user_tests:
            user_tests[user_id] = []
        user_tests[user_id].append({"test_id": test_id, "verdict": verdict, "note": note})

        if not args.dry_run:
            result = coll.update_one(
                {"_id": oid},
                {
                    "$set": {
                        "result": _make_serializable(new_result),
                        "review.verdict": verdict,
                        "review.note": (note or "").strip() or None,
                        "review.published_at": published_at.isoformat() + "Z",
                    }
                },
            )
            if result.matched_count:
                updated += 1

    if missing_files:
        print(f"Warning: missing reanalyzed files ({len(missing_files)}):", file=sys.stderr)
        for p in missing_files[:5]:
            print(f"  {p}", file=sys.stderr)
        if len(missing_files) > 5:
            print(f"  ... and {len(missing_files) - 5} more", file=sys.stderr)

    print(f"Updated {updated} documents in DB.")
    if args.dry_run:
        print("(Dry run: no changes written.)")
        if args.send_emails:
            print("Would send emails to", len(user_tests), "users.")
        return 0

    if not args.send_emails:
        return 0

    sent = 0
    failed = 0
    for user_id, tests in user_tests.items():
        if user_id == "unknown":
            continue
        has_bad = any(t["verdict"] in ("data_bad", "points_wrong") for t in tests)
        bad_msg = None
        if has_bad:
            bad_list = [t for t in tests if t["verdict"] in ("data_bad", "points_wrong")]
            if len(bad_list) == 1:
                bad_msg = "One of your tests had quality issues."
            else:
                bad_msg = f"{len(bad_list)} of your tests had quality issues; details are visible in your dashboard."
        try:
            uid_oid = ObjectId(user_id)
        except Exception:
            failed += 1
            continue
        user_doc = users_collection().find_one(
            {"_id": uid_oid},
            projection={"email": 1, "name": 1, "last_name": 1},
        )
        email = (user_doc or {}).get("email")
        if not email:
            failed += 1
            continue
        ok, err = send_results_ready_email(
            to_email=email,
            user_id=user_id,
            has_bad_data=has_bad,
            bad_data_message=bad_msg,
            name=(user_doc or {}).get("name"),
            last_name=(user_doc or {}).get("last_name"),
        )
        if ok:
            sent += 1
        else:
            print(f"Failed to send to {email}: {err}", file=sys.stderr)
            failed += 1
    print(f"Emails sent: {sent}, failed: {failed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
