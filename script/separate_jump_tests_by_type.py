#!/usr/bin/env python3
"""
Separate downloaded jump test JSON files into subfolders by test_type (cmj, sj, dj).

Reads each <dir>/*.json (except manifest.json), moves it to <dir>/<type>/<filename>.
Updates manifest.json so "file" reflects the new path (e.g. cmj/69a01a....json).

Usage:
  PYTHONPATH=. python script/separate_jump_tests_by_type.py
  PYTHONPATH=. python script/separate_jump_tests_by_type.py --dir downloaded_jump_tests
"""
import argparse
import json
import shutil
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Separate downloaded jump tests into cmj/, sj/, dj/ subfolders by test_type."
    )
    parser.add_argument(
        "--dir", "-d",
        default="downloaded_jump_tests",
        help="Directory containing the downloaded JSON files (default: downloaded_jump_tests)",
    )
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        return 1

    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        tests = manifest.get("tests") or []
    else:
        tests = []
        manifest = {"count": 0, "tests": []}

    # Build test_id -> file from manifest (current paths)
    id_to_file = {t["test_id"]: t["file"] for t in tests}
    # Also discover any JSON not in manifest
    for p in root.glob("*.json"):
        if p.name == "manifest.json":
            continue
        test_id = p.stem
        if test_id not in id_to_file:
            id_to_file[test_id] = p.name

    moved = []  # (test_id, type_folder, new_file_path)
    for test_id, filename in id_to_file.items():
        if "/" in filename:
            # Already in a subdir from a previous run
            continue
        filepath = root / filename
        if not filepath.is_file():
            continue
        try:
            with open(filepath, encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: skip {filename}: {e}", file=sys.stderr)
            continue
        raw_type = (doc.get("test_type") or "CMJ").strip().upper()
        if raw_type == "CMJ":
            folder = "cmj"
        elif raw_type == "SJ":
            folder = "sj"
        elif raw_type == "DJ":
            folder = "dj"
        else:
            folder = "other"
        subdir = root / folder
        subdir.mkdir(parents=True, exist_ok=True)
        dest = subdir / filename
        shutil.move(str(filepath), str(dest))
        new_path = f"{folder}/{filename}"
        moved.append((test_id, folder, new_path))

    # Update manifest with new paths
    file_by_id = {tid: path for tid, _folder, path in moved}
    for t in tests:
        tid = t.get("test_id")
        if tid in file_by_id:
            t["file"] = file_by_id[tid]
    manifest["count"] = len(tests)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Moved {len(moved)} files into subfolders under {root.resolve()}")
    by_type = {}
    for _tid, folder, _path in moved:
        by_type[folder] = by_type.get(folder, 0) + 1
    for k, v in sorted(by_type.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
