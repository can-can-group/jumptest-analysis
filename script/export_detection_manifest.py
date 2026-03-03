#!/usr/bin/env python3
"""
Run analysis on all downloaded jump tests and save a manifest of detection results:
indices, times, force values, and order checks for every test.

Use this to verify that onset < min_force < P1 < P2 < take_off < landing and that
index/time/value look correct across tests.

Output:
  - output/detection_manifest.json  (full detail per test)
  - output/detection_manifest.csv   (flat table: one row per test with columns for each point)

Usage:
  PYTHONPATH=. python script/export_detection_manifest.py
  PYTHONPATH=. python script/export_detection_manifest.py --input-dir downloaded_jump_tests --filter-hz 10 --limit 5
"""
import argparse
import csv
import json
import sys
from pathlib import Path

# Run from repo root so PYTHONPATH=. finds src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.run_analysis import run_analysis


def _n(x):
    """Convert to native int/float for JSON."""
    if x is None:
        return None
    if hasattr(x, "item"):
        x = x.item()
    return int(x) if isinstance(x, (float, int)) and x == int(x) else float(x)


def _make_serializable(obj):
    """Recursively convert numpy types for JSON."""
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


def _order_ok(events, metrics, sr):
    """Check strict order: onset < min_force < p1 < p2 < take_off < landing (with Nones)."""
    onset = events.get("movement_onset")
    mf = events.get("min_force")
    to = events.get("take_off")
    ld = events.get("landing")
    p1 = metrics.get("p1_peak_index")
    p2 = metrics.get("p2_peak_index")
    indices = [
        (onset, "onset"),
        (mf, "min_force"),
        (p1, "p1"),
        (p2, "p2"),
        (to, "take_off"),
        (ld, "landing"),
    ]
    last = -1
    for idx, name in indices:
        if idx is None:
            continue
        if idx <= last:
            return False, f"{name}({idx}) <= previous({last})"
        last = idx
    if to is not None and ld is not None and ld <= to:
        return False, "landing <= take_off"
    return True, None


def run():
    parser = argparse.ArgumentParser(
        description="Export detection manifest: indices, times, values, order check for all tests."
    )
    parser.add_argument(
        "--input-dir", "-i",
        default="downloaded_jump_tests",
        help="Root with cmj/, sj/, dj/ subdirs",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        help="Where to write detection_manifest.json and .csv",
    )
    parser.add_argument(
        "--filter-hz",
        type=int,
        default=10,
        help="Low-pass filter Hz (0 = no filter)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max tests per type (0 = all)",
    )
    parser.add_argument(
        "--types",
        default="cmj,sj,dj",
        help="Comma-separated: cmj,sj,dj",
    )
    args = parser.parse_args()

    root = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        return 1

    types = [t.strip().lower() for t in args.types.split(",")]
    manifest = []
    order_failures = []

    for sub in types:
        src_dir = root / sub
        if not src_dir.is_dir():
            continue
        files = sorted(src_dir.glob("*.json"))[: args.limit if args.limit > 0 else None]
        for fp in files:
            test_id = fp.stem
            try:
                with open(fp, encoding="utf-8") as f:
                    doc = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                manifest.append({
                    "test_id": test_id,
                    "type": sub,
                    "status": "read_error",
                    "error": str(e),
                    "order_ok": None,
                    "order_error": None,
                    "points": [],
                    "events": {},
                    "metrics": {},
                })
                continue

            raw = doc.get("raw")
            if not raw:
                manifest.append({
                    "test_id": test_id,
                    "type": sub,
                    "status": "no_raw",
                    "order_ok": None,
                    "points": [],
                    "events": {},
                    "metrics": {},
                })
                continue

            try:
                result = run_analysis(raw, filter_cutoff_hz=args.filter_hz)
            except Exception as e:
                manifest.append({
                    "test_id": test_id,
                    "type": sub,
                    "status": "analysis_error",
                    "error": str(e),
                    "order_ok": None,
                    "points": [],
                    "events": {},
                    "metrics": {},
                })
                continue

            events = result.get("events") or {}
            metrics = result.get("metrics") or {}
            key_points = result.get("key_points") or []
            # Use result's force_N and time_s (filtered data the algorithm used)
            force = result.get("force_N") or raw.get("force") or raw.get("total_force") or []
            time_s = result.get("time_s")
            n = len(force)
            dur = float(raw.get("test_duration") or 0)
            sr = n / dur if dur > 0 else 0

            def t_at(i):
                if i is None or not n:
                    return None
                if time_s and i < len(time_s):
                    return round(float(time_s[i]), 4)
                return round(i / sr, 4) if sr else None

            def pt(index, value_n=None):
                if index is None:
                    return {"index": None, "time_s": None, "value_N": value_n}
                return {"index": int(index), "time_s": t_at(index), "value_N": _n(value_n)}

            def force_at(i):
                if i is None or not force or i >= len(force):
                    return None
                return _n(force[i])

            events_detail = {
                "movement_onset": pt(events.get("movement_onset"), force_at(events.get("movement_onset"))),
                "min_force": pt(events.get("min_force"), force_at(events.get("min_force"))),
                "take_off": pt(events.get("take_off"), force_at(events.get("take_off"))),
                "landing": pt(events.get("landing"), force_at(events.get("landing"))),
            }
            metrics_detail = {}
            if events.get("min_force") is not None and events.get("take_off") is not None:
                p1 = metrics.get("p1_peak_index")
                p2 = metrics.get("p2_peak_index")
                metrics_detail["p1_peak"] = pt(p1, force_at(p1))
                metrics_detail["p2_peak"] = pt(p2, force_at(p2))

            order_ok, order_error = _order_ok(events, metrics, sr)
            if not order_ok:
                order_failures.append({"test_id": test_id, "type": sub, "error": order_error})

            points_list = []
            for k in key_points:
                points_list.append({
                    "name": k.get("name"),
                    "index": k.get("index"),
                    "time_s": _n(k.get("time_s")),
                    "value_N": _n(k.get("value_N")),
                })

            manifest.append({
                "test_id": test_id,
                "type": sub,
                "status": "ok",
                "sample_rate": round(sr, 2) if sr else None,
                "n_samples": n,
                "duration_s": round(dur, 4) if dur else None,
                "order_ok": order_ok,
                "order_error": order_error,
                "events": events_detail,
                "metrics": metrics_detail,
                "points": points_list,
                "key_points_count": len(points_list),
            })

    out_dir.mkdir(parents=True, exist_ok=True)

    # Full JSON manifest
    out_json = {
        "filter_hz": args.filter_hz,
        "input_dir": str(root),
        "total_tests": len(manifest),
        "order_ok_count": sum(1 for m in manifest if m.get("order_ok") is True),
        "order_fail_count": len(order_failures),
        "order_failures": order_failures,
        "tests": manifest,
    }
    with open(out_dir / "detection_manifest.json", "w", encoding="utf-8") as f:
        json.dump(_make_serializable(out_json), f, indent=2)

    # CSV: one row per test, columns test_id, type, status, order_ok, then for each point index, time_s, value_N
    csv_path = out_dir / "detection_manifest.csv"
    fieldnames = [
        "test_id", "type", "status", "order_ok", "order_error",
        "onset_idx", "onset_time_s", "onset_value_N",
        "min_force_idx", "min_force_time_s", "min_force_value_N",
        "p1_idx", "p1_time_s", "p1_value_N",
        "p2_idx", "p2_time_s", "p2_value_N",
        "take_off_idx", "take_off_time_s", "take_off_value_N",
        "landing_idx", "landing_time_s", "landing_value_N",
        "key_points_count",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for m in manifest:
            ev = m.get("events") or {}
            mt = m.get("metrics") or {}
            row = {
                "test_id": m["test_id"],
                "type": m["type"],
                "status": m.get("status", ""),
                "order_ok": m.get("order_ok"),
                "order_error": m.get("order_error") or "",
            }
            for key, label in [
                ("movement_onset", "onset"),
                ("min_force", "min_force"),
                ("take_off", "take_off"),
                ("landing", "landing"),
            ]:
                p = ev.get(key) or {}
                row[f"{label}_idx"] = p.get("index")
                row[f"{label}_time_s"] = p.get("time_s")
                row[f"{label}_value_N"] = p.get("value_N")
            for key, label in [("p1_peak", "p1"), ("p2_peak", "p2")]:
                p = mt.get(key) or {}
                row[f"{label}_idx"] = p.get("index")
                row[f"{label}_time_s"] = p.get("time_s")
                row[f"{label}_value_N"] = p.get("value_N")
            row["key_points_count"] = m.get("key_points_count", 0)
            w.writerow(row)

    print(f"Wrote {out_dir / 'detection_manifest.json'}")
    print(f"Wrote {out_dir / 'detection_manifest.csv'}")
    print(f"Total tests: {len(manifest)}")
    print(f"Order OK: {out_json['order_ok_count']}")
    print(f"Order failures: {len(order_failures)}")
    if order_failures:
        for x in order_failures[:10]:
            print(f"  - {x['test_id']} ({x['type']}): {x['error']}")
        if len(order_failures) > 10:
            print(f"  ... and {len(order_failures) - 10} more")
    return 0


if __name__ == "__main__":
    sys.exit(run())
