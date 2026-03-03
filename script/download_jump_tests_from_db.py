#!/usr/bin/env python3
"""
Download all jump test documents from MongoDB and save them locally (read-only; no DB writes).

Each test is saved as a JSON file containing: _id, user_id, athlete_id, test_type, raw, result, created_at.
A manifest (index) JSON lists all downloaded test IDs and paths.

Usage:
  PYTHONPATH=. python script/download_jump_tests_from_db.py
  PYTHONPATH=. python script/download_jump_tests_from_db.py --output-dir ./my_jump_tests
  PYTHONPATH=. python script/download_jump_tests_from_db.py --limit 100 --offset 0
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bson import ObjectId

# Load .env via api.config (used by api.db)
from api.db import jump_tests_collection


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
        description="Download jump tests from MongoDB to local JSON files (read-only)."
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="downloaded_jump_tests",
        help="Directory to save JSON files (default: downloaded_jump_tests)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max number of tests to download (0 = all)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip first N tests",
    )
    parser.add_argument(
        "--manifest",
        default="manifest.json",
        help="Filename for manifest in output-dir (default: manifest.json)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    coll = jump_tests_collection()
    cursor = coll.find({}).sort("created_at", -1).skip(args.offset)
    if args.limit > 0:
        cursor = cursor.limit(args.limit)

    manifest_entries = []
    count = 0

    for doc in cursor:
        test_id = str(doc["_id"])
        # Safe filename (avoid path separators)
        safe_id = test_id.replace("/", "_")
        filepath = out_dir / f"{safe_id}.json"

        doc_serializable = _make_serializable(doc)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(doc_serializable, f, indent=2)

        manifest_entries.append({
            "test_id": test_id,
            "file": filepath.name,
            "test_type": doc.get("test_type"),
            "athlete_id": doc.get("athlete_id"),
            "created_at": doc_serializable.get("created_at"),
        })
        count += 1

    manifest_path = out_dir / args.manifest
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "count": count,
                "offset": args.offset,
                "limit": args.limit if args.limit > 0 else "all",
                "tests": manifest_entries,
            },
            f,
            indent=2,
        )

    print(f"Downloaded {count} jump tests to {out_dir.resolve()}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
