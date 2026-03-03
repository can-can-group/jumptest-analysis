#!/usr/bin/env python3
"""
Update CMJ jump test results and visualization data in the database from reanalyzed JSON files.

Only the `result` field is updated ($set); `review` (verdict, note, published_at) is left unchanged.
The my-tests page shows quality tags (Correct, Bad data, Wrong detection, Invalid / No jump) from
the updated result.metrics and existing review.verdict.

Use --user-id first to update one user, verify in production viewer and emails, then run --all for bulk.

Usage:
  # Update a single user (test on production first)
  PYTHONPATH=. python script/update_cmj_results_in_db.py --user-id 507f1f77bcf86cd799439011
  PYTHONPATH=. python script/update_cmj_results_in_db.py --user-id 507f1f77bcf86cd799439011 --send-emails

  # Dry run: show what would be updated
  PYTHONPATH=. python script/update_cmj_results_in_db.py --user-id 507f1f77bcf86cd799439011 --dry-run

  # Bulk update all CMJ tests that have reanalyzed data (after single-user check)
  PYTHONPATH=. python script/update_cmj_results_in_db.py --all
  PYTHONPATH=. python script/update_cmj_results_in_db.py --all --send-emails
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bson import ObjectId

from api.db import jump_tests_collection, users_collection
from api.email_sender import send_results_ready_email


def _make_serializable(obj):
    """Convert ObjectId, datetime, numpy for MongoDB."""
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
        description="Update CMJ results in DB from reanalyzed JSON. Use --user-id first, then --all."
    )
    parser.add_argument(
        "--reanalyzed-dir",
        type=Path,
        default=Path("reanalyzed"),
        help="Path to reanalyzed output directory (default: reanalyzed)",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=None,
        help="Update only CMJ tests for this user_id (test in production before bulk)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Bulk update all CMJ tests that have a file in reanalyzed/cmj/",
    )
    parser.add_argument(
        "--send-emails",
        action="store_true",
        help="Send 'results ready' email to affected user(s) after update",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would be updated/sent, do not write to DB or send email",
    )
    args = parser.parse_args()

    if not args.reanalyzed_dir.is_dir():
        print(f"Error: {args.reanalyzed_dir} is not a directory.", file=sys.stderr)
        return 1
    cmj_dir = args.reanalyzed_dir / "cmj"
    if not cmj_dir.is_dir():
        print(f"Error: {cmj_dir} not found.", file=sys.stderr)
        return 1

    if bool(args.user_id) == bool(args.all):
        print("Error: provide exactly one of --user-id <id> or --all.", file=sys.stderr)
        print("  Use --user-id first to test one user, then --all for bulk.", file=sys.stderr)
        return 1

    coll = jump_tests_collection()
    updated = 0
    affected_users = set()  # user_id for email

    if args.user_id:
        try:
            uid_oid = ObjectId(args.user_id)
        except Exception:
            print(f"Error: --user-id must be a valid MongoDB ObjectId hex string.", file=sys.stderr)
            return 1
        cursor = coll.find(
            {"user_id": args.user_id, "test_type": "CMJ"},
            projection={"_id": 1, "user_id": 1},
        )
        test_ids = [str(doc["_id"]) for doc in cursor]
        if not test_ids:
            print(f"No CMJ tests found for user_id={args.user_id}.")
            return 0
        print(f"Found {len(test_ids)} CMJ test(s) for user_id={args.user_id}.")
        for test_id in test_ids:
            path = cmj_dir / f"{test_id}.json"
            if not path.is_file():
                print(f"  Skip {test_id}: no reanalyzed file.", file=sys.stderr)
                continue
            with open(path, encoding="utf-8") as f:
                new_result = json.load(f)
            if args.dry_run:
                print(f"  Would update {test_id}")
                updated += 1
                doc = coll.find_one({"_id": ObjectId(test_id)}, projection=["user_id"])
                if doc and doc.get("user_id"):
                    affected_users.add(doc["user_id"])
                continue
            # Only set result; preserve review (verdict, note) so my-tests quality tags stay correct
            result = coll.update_one(
                {"_id": ObjectId(test_id)},
                {"$set": {"result": _make_serializable(new_result)}},
            )
            if result.matched_count:
                updated += 1
                doc = coll.find_one({"_id": ObjectId(test_id)}, projection=["user_id"])
                if doc and doc.get("user_id"):
                    affected_users.add(doc["user_id"])
        print(f"Updated {updated} document(s).")
    else:
        # --all: every reanalyzed/cmj/*.json
        files = list(cmj_dir.glob("*.json"))
        print(f"Found {len(files)} reanalyzed CMJ file(s).")
        for path in files:
            test_id = path.stem
            try:
                oid = ObjectId(test_id)
            except Exception:
                continue
            doc = coll.find_one({"_id": oid}, projection=["test_type", "user_id"])
            if not doc or (doc.get("test_type") or "").upper() != "CMJ":
                continue
            with open(path, encoding="utf-8") as f:
                new_result = json.load(f)
            if args.dry_run:
                print(f"  Would update {test_id} (user_id={doc.get('user_id')})")
                updated += 1
                if doc.get("user_id"):
                    affected_users.add(doc["user_id"])
                continue
            # Only set result; preserve review so my-tests quality tags stay correct
            result = coll.update_one(
                {"_id": oid},
                {"$set": {"result": _make_serializable(new_result)}},
            )
            if result.matched_count:
                updated += 1
                if doc.get("user_id"):
                    affected_users.add(doc["user_id"])
        print(f"Updated {updated} document(s).")

    if args.dry_run:
        print("(Dry run: no changes written.)")
        if args.send_emails and affected_users:
            print(f"Would send results-ready email to {len(affected_users)} user(s).")
        return 0

    if not args.send_emails or not affected_users:
        return 0

    sent = 0
    for user_id in affected_users:
        if user_id == "unknown":
            continue
        try:
            uid_oid = ObjectId(user_id)
        except Exception:
            continue
        user_doc = users_collection().find_one(
            {"_id": uid_oid},
            projection=["email", "name", "last_name"],
        )
        email = (user_doc or {}).get("email")
        if not email:
            print(f"No email for user_id={user_id}, skip.", file=sys.stderr)
            continue
        ok, err = send_results_ready_email(
            to_email=email,
            user_id=user_id,
            has_bad_data=False,
            bad_data_message=None,
            name=(user_doc or {}).get("name"),
            last_name=(user_doc or {}).get("last_name"),
        )
        if ok:
            sent += 1
            print(f"Email sent to {email} (user_id={user_id}).")
        else:
            print(f"Failed to send to {email}: {err}", file=sys.stderr)
    print(f"Emails sent: {sent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
