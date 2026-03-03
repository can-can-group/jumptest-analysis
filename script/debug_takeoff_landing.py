#!/usr/bin/env python3
"""
Run the standalone takeoff/landing detector on downloaded tests and write debug JSON
plus an index for the takeoff/landing debug viewer. Use this to verify and debug the
takeoff/landing algorithm without the full pipeline.

Output: reanalyzed/debug_takeoff_landing/<type>/<test_id>.json and index.html + manifest.

Usage:
  PYTHONPATH=. python script/debug_takeoff_landing.py
  PYTHONPATH=. python script/debug_takeoff_landing.py --input-dir downloaded_jump_tests --output-dir reanalyzed/debug_takeoff_landing --limit 50
  Then run: PYTHONPATH=. python script/serve_local_viewer.py
  Open http://localhost:8766/reanalyzed/debug_takeoff_landing/index.html and click "View" to use the debug viewer.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data import load_trial_from_dict
from src.detect.baseline import compute_baseline
from src.detect.takeoff_landing_standalone import detect_takeoff_landing
from src.run_analysis import _apply_tare


def _ensure_force_in_raw(raw: dict) -> dict:
    """If raw has left_force and right_force but no force, set force = left + right."""
    if "force" in raw or "total_force" in raw:
        return raw
    if "left_force" in raw and "right_force" in raw:
        left = raw["left_force"]
        right = raw["right_force"]
        n = min(len(left), len(right))
        raw = dict(raw)
        raw["force"] = [float(left[i]) + float(right[i]) for i in range(n)]
    return raw


def _make_serializable(obj):
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
        description="Run standalone takeoff/landing detection on tests and write debug JSON for the debug viewer."
    )
    parser.add_argument(
        "--input-dir", "-i",
        default=str(PROJECT_ROOT / "downloaded_jump_tests"),
        help="Root directory with cmj/, sj/, dj/ subdirs",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=str(PROJECT_ROOT / "reanalyzed" / "debug_takeoff_landing"),
        help="Output directory for debug JSON and index",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max tests per type (0 = all)",
    )
    parser.add_argument(
        "--filter-hz",
        type=int,
        default=50,
        help="Low-pass filter cutoff (0 = no filter)",
    )
    args = parser.parse_args()

    root = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    if not root.is_dir():
        print(f"Error: {root} is not a directory.", file=sys.stderr)
        return 1

    # Optional low-pass filter
    def maybe_filter(trial):
        if args.filter_hz and args.filter_hz > 0:
            from src.signal.filter import lowpass_filter
            from src.data.types import CMJTrial
            sr = trial.sample_rate
            force_f = lowpass_filter(trial.force, sr, float(args.filter_hz))
            return CMJTrial(
                athlete_id=trial.athlete_id,
                test_type=trial.test_type,
                test_duration=trial.test_duration,
                sample_count=trial.sample_count,
                force=force_f,
                left_force=trial.left_force,
                right_force=trial.right_force,
                sample_rate=trial.sample_rate,
                t=trial.t,
            )
        return trial

    subdirs = ["cmj", "sj", "dj"]
    manifest_entries = []
    total_ok = 0
    total_err = 0

    for sub in subdirs:
        src_dir = root / sub
        dst_dir = out_dir / sub
        if not src_dir.is_dir():
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(src_dir.glob("*.json"))[: args.limit if args.limit > 0 else None]
        for fp in files:
            test_id = fp.stem
            try:
                with open(fp, encoding="utf-8") as f:
                    doc = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "read_error",
                    "error": str(e),
                    "take_off": None,
                    "landing": None,
                    "issues": ["read_error"],
                })
                total_err += 1
                continue
            raw = doc.get("raw")
            if not raw:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "no_raw",
                    "error": "Missing raw",
                    "take_off": None,
                    "landing": None,
                    "issues": ["no_raw"],
                })
                total_err += 1
                continue
            raw = _ensure_force_in_raw(raw)
            try:
                trial = load_trial_from_dict(raw)
                trial = _apply_tare(trial)  # force >= 0 so flight line is never negative
            except Exception as e:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "load_error",
                    "error": str(e),
                    "take_off": None,
                    "landing": None,
                    "issues": ["load_error"],
                })
                total_err += 1
                continue
            trial = maybe_filter(trial)
            try:
                bodyweight, _, _ = compute_baseline(trial)
            except Exception:
                bodyweight = float(np.mean(trial.force[: max(1, int(trial.sample_rate * 0.5))]))
            try:
                take_off, landing, flight_line_N, debug = detect_takeoff_landing(
                    trial.force, trial.sample_rate, bodyweight
                )
            except Exception as e:
                manifest_entries.append({
                    "test_id": test_id,
                    "type": sub,
                    "file": f"{sub}/{test_id}.json",
                    "status": "detect_error",
                    "error": str(e),
                    "take_off": None,
                    "landing": None,
                    "issues": ["detect_error"],
                })
                total_err += 1
                continue

            t = trial.t
            key_points = []
            if take_off is not None:
                key_points.append({
                    "name": "Take-off",
                    "index": int(take_off),
                    "time_s": float(t[take_off]),
                    "value_N": float(trial.force[take_off]),
                })
            if landing is not None:
                key_points.append({
                    "name": "Landing",
                    "index": int(landing),
                    "time_s": float(t[landing]),
                    "value_N": float(trial.force[landing]),
                })
            key_points.sort(key=lambda p: p["index"])

            payload = {
                "test_id": test_id,
                "athlete_id": getattr(trial, "athlete_id", "unknown"),
                "test_type": trial.test_type,
                "sample_rate": trial.sample_rate,
                "bodyweight_N": float(bodyweight),
                "time_s": trial.t.tolist(),
                "force_N": trial.force.tolist(),
                "take_off": int(take_off) if take_off is not None else None,
                "landing": int(landing) if landing is not None else None,
                "flight_line_N": float(flight_line_N) if flight_line_N is not None else None,
                "key_points": key_points,
                "debug": _make_serializable(debug),
            }

            out_path = dst_dir / f"{test_id}.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(_make_serializable(payload), f, indent=2)

            issues = debug.get("issues") or []
            manifest_entries.append({
                "test_id": test_id,
                "type": sub,
                "file": f"{sub}/{test_id}.json",
                "status": "ok",
                "take_off": int(take_off) if take_off is not None else None,
                "landing": int(landing) if landing is not None else None,
                "flight_line_N": float(flight_line_N) if flight_line_N is not None else None,
                "issues": issues,
                "force_at_takeoff": debug.get("force_at_takeoff_N"),
                "force_at_landing": debug.get("force_at_landing_N"),
            })
            total_ok += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "count": len(manifest_entries),
        "ok": total_ok,
        "errors": total_err,
        "tests": manifest_entries,
        "generated_at": generated_at,
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Index HTML: list tests and link to debug viewer (viz_url = debug JSON)
    rows = []
    for t in manifest_entries:
        view_url = f"/web/takeoff_landing_debug.html?viz_url=/reanalyzed/debug_takeoff_landing/{t['file']}"
        issues_str = ", ".join(t.get("issues") or []) or "—"
        to_idx = t.get("take_off")
        land_idx = t.get("landing")
        fl_n = t.get("flight_line_N")
        fl_str = f"{fl_n:.1f}" if fl_n is not None else "—"
        rows.append(
            f"    <tr data-test-id=\"{t['test_id']}\" data-type=\"{t['type']}\">\n"
            f"      <td>{t['test_id']}</td>\n"
            f"      <td>{t['type'].upper()}</td>\n"
            f"      <td>{to_idx if to_idx is not None else '—'}</td>\n"
            f"      <td>{land_idx if land_idx is not None else '—'}</td>\n"
            f"      <td>{fl_str}</td>\n"
            f"      <td>{issues_str}</td>\n"
            f"      <td><a href=\"{view_url}\" target=\"_blank\">View</a></td>\n"
            f"    </tr>"
        )
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Takeoff/Landing debug — standalone detector</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1rem 2rem; background: #f5f5f5; }}
    h1 {{ font-size: 1.25rem; }}
    table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 0.5rem 0.75rem; text-align: left; border-bottom: 1px solid #eee; }}
    th {{ background: #333; color: #fff; font-size: 0.85rem; }}
    a {{ color: #2563eb; }}
    .summary {{ margin-bottom: 1rem; color: #666; }}
    td.issues {{ font-size: 0.85rem; color: #922; }}
  </style>
</head>
<body>
  <h1>Takeoff/Landing debug (standalone algorithm)</h1>
  <p class="summary">Total: {len(manifest_entries)} — OK: {total_ok} — Errors: {total_err}. <strong>Generated: {generated_at}</strong>. Click "View" to open the debug chart for that test.</p>
  <p class="summary" style="font-size:0.9rem;">To refresh: <code>PYTHONPATH=. python script/debug_takeoff_landing.py</code> then reload. Server: <code>PYTHONPATH=. python script/serve_local_viewer.py</code></p>
  <table>
    <thead>
      <tr>
        <th>Test ID</th>
        <th>Type</th>
        <th>Take-off index</th>
        <th>Landing index</th>
        <th>Flight line (N)</th>
        <th>Issues</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    with open(out_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(index_html)

    print(f"Debug takeoff/landing: {total_ok} tests written ({total_err} errors). Output: {out_dir.resolve()}")
    print("  Open: http://localhost:8766/reanalyzed/debug_takeoff_landing/index.html (after starting serve_local_viewer.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
