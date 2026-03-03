#!/usr/bin/env python3
"""
Batch debug: read all jump tests from MongoDB (read-only), re-run analysis locally,
and write a report to local files. No database writes.

Usage:
  PYTHONPATH=. python script/debug_jump_tests_batch.py [--output debug_report.csv] [--limit N] [--filter-hz 50]
  PYTHONPATH=. python script/debug_jump_tests_batch.py --export-dir ./debug_exports/  # also export per-test JSON

Uses .env (MONGODB_URI, MONGODB_DB) for connection. Run with filter: --filter-hz 50 to compare no-filter vs filtered.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Load .env via api.config (used by api.db)
from api.db import jump_tests_collection
from src.run_analysis import run_analysis


def _make_serializable(obj):
    """Convert numpy/types for JSON export."""
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
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def run_one(raw: dict, filter_cutoff_hz: int):
    """Run analysis on raw payload. Returns (status, error_message, result_dict)."""
    try:
        result = run_analysis(raw, filter_cutoff_hz=filter_cutoff_hz)
        validity = result.get("validity") or {}
        is_valid = validity.get("is_valid", True)
        flags = validity.get("flags") or []
        key_points = result.get("key_points") or []
        phases = result.get("phases") or []
        return (
            "ok",
            None,
            {
                "is_valid": is_valid,
                "validity_flags": flags,
                "key_points_count": len(key_points),
                "phases_count": len(phases),
                "result": result,
            },
        )
    except Exception as e:
        return ("exception", str(e), None)


def main():
    parser = argparse.ArgumentParser(description="Batch debug: read jump tests from DB (read-only), re-run analysis, write local report.")
    parser.add_argument("--output", "-o", default="debug_report.csv", help="Output CSV path (default: debug_report.csv)")
    parser.add_argument("--limit", type=int, default=0, help="Max number of tests to process (0 = all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N tests")
    parser.add_argument("--filter-hz", type=int, default=None, help="Also run with this filter cutoff (Hz) and report fixed_by_filter")
    parser.add_argument("--export-dir", type=str, default=None, help="If set, export each test result JSON to this directory (read-only DB; writes only here)")
    parser.add_argument("--no-filter-run", action="store_true", help="Skip the default run without filter (use with --filter-hz only)")
    args = parser.parse_args()

    coll = jump_tests_collection()
    cursor = coll.find({}).sort("created_at", -1).skip(args.offset)
    if args.limit > 0:
        cursor = cursor.limit(args.limit)

    export_dir = Path(args.export_dir) if args.export_dir else None
    if export_dir:
        export_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    summary = {"total": 0, "no_raw": 0, "exception": 0, "ok_valid": 0, "ok_invalid": 0, "fixed_by_filter": 0}

    for doc in cursor:
        summary["total"] += 1
        test_id = str(doc["_id"])
        raw = doc.get("raw")
        test_type = (doc.get("test_type") or "CMJ").strip().upper()
        athlete_id = doc.get("athlete_id") or ""
        created_at = doc.get("created_at")
        created_str = created_at.isoformat() if isinstance(created_at, datetime) else str(created_at) if created_at else ""

        if not raw:
            rows.append({
                "test_id": test_id,
                "test_type": test_type,
                "athlete_id": athlete_id,
                "created_at": created_str,
                "status": "no_raw",
                "error_message": "",
                "is_valid": "",
                "validity_flags": "",
                "key_points_count": "",
                "phases_count": "",
                "fixed_by_filter": "",
            })
            summary["no_raw"] += 1
            continue

        # Run without filter (unless disabled)
        if not args.no_filter_run:
            status1, err1, res1 = run_one(raw, 0)
        else:
            status1, err1, res1 = "skipped", None, None

        if status1 == "exception":
            summary["exception"] += 1
            is_valid = ""
            flags_str = ""
            kp_count = ""
            ph_count = ""
        elif status1 == "ok" and res1:
            if res1["is_valid"]:
                summary["ok_valid"] += 1
            else:
                summary["ok_invalid"] += 1
            is_valid = str(res1["is_valid"])
            flags_str = ";".join(res1["validity_flags"]) if res1["validity_flags"] else ""
            kp_count = str(res1["key_points_count"])
            ph_count = str(res1["phases_count"])
        else:
            is_valid = flags_str = kp_count = ph_count = ""

        fixed = ""
        if args.filter_hz and raw and status1 != "no_raw":
            status2, err2, res2 = run_one(raw, args.filter_hz)
            was_bad = status1 == "exception" or (res1 and not res1["is_valid"])
            now_good = status2 == "ok" and res2 and res2["is_valid"]
            if was_bad and now_good:
                fixed = "yes"
                summary["fixed_by_filter"] += 1
            elif status2 == "ok" and res2:
                fixed = "no"
            if export_dir and res2 and res2.get("result"):
                out_path = export_dir / f"{test_id}.json"
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(_make_serializable(res2["result"]), f, indent=2)
        elif export_dir and not args.no_filter_run and res1 and res1.get("result"):
            out_path = export_dir / f"{test_id}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(_make_serializable(res1["result"]), f, indent=2)

        rows.append({
            "test_id": test_id,
            "test_type": test_type,
            "athlete_id": athlete_id,
            "created_at": created_str,
            "status": status1,
            "error_message": err1 or "",
            "is_valid": is_valid,
            "validity_flags": flags_str,
            "key_points_count": kp_count,
            "phases_count": ph_count,
            "fixed_by_filter": fixed,
        })

    # Write CSV
    fieldnames = ["test_id", "test_type", "athlete_id", "created_at", "status", "error_message", "is_valid", "validity_flags", "key_points_count", "phases_count", "fixed_by_filter"]
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    # Summary
    print(f"Wrote {len(rows)} rows to {out_path}")
    print("Summary:")
    print(f"  total:       {summary['total']}")
    print(f"  no_raw:      {summary['no_raw']}")
    print(f"  exception:   {summary['exception']}")
    print(f"  ok (valid):  {summary['ok_valid']}")
    print(f"  ok (invalid): {summary['ok_invalid']}")
    if args.filter_hz:
        print(f"  fixed_by_filter ({args.filter_hz} Hz): {summary['fixed_by_filter']}")
    if export_dir:
        print(f"  Exported JSON: {export_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
