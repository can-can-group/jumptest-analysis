#!/usr/bin/env python3
"""
Debug why CMJ trials get only "Start of movement" (no take-off, landing, P1, P2).

For each CMJ file (or raw payload), runs event detection and reports:
- bodyweight, take_off_threshold, min(force), where min occurs
- number of descending crossings of take_off_threshold
- for first few crossings: whether we find a run of 4 consecutive below in the search window
- outcome: take_off found or reason it failed

Usage:
  PYTHONPATH=. python script/debug_cmj_events.py downloaded_jump_tests/cmj/69a01a067d1bd36d267086cb.json
  PYTHONPATH=. python script/debug_cmj_events.py downloaded_jump_tests/cmj/ --limit 5 --verbose
  PYTHONPATH=. python script/debug_cmj_events.py downloaded_jump_tests/cmj/ --limit 20 --output cmj_debug.csv
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

from src.data import load_trial_from_dict
from src.data.types import CMJTrial
from src.detect import compute_baseline, detect_events
from src.detect.events import (
    TAKE_OFF_CONSECUTIVE_SAMPLES,
    TAKE_OFF_SEARCH_WINDOW_MS,
    DEFAULT_TAKE_OFF_THRESHOLD_N,
)


def analyze_takeoff_candidates(force: np.ndarray, sr: float, take_off_threshold: float):
    """Return diagnostics: crossings, min force, and first run found (if any)."""
    n = len(force)
    K = TAKE_OFF_CONSECUTIVE_SAMPLES
    window_samples = min(n, max(K + 1, int(sr * TAKE_OFF_SEARCH_WINDOW_MS / 1000.0)))

    crossings = []
    i = 1
    while i < n and len(crossings) < 20:
        if force[i - 1] >= take_off_threshold and force[i] < take_off_threshold:
            crossings.append(i)
            # Check if we have K consecutive below in the next window
            search_end = min(i + window_samples, n - K)
            run_found = None
            for start in range(i, search_end):
                run = 0
                for j in range(start, min(start + K, n)):
                    if force[j] < take_off_threshold:
                        run += 1
                    else:
                        break
                if run >= K:
                    run_found = start
                    break
            crossings[-1] = (i, run_found)
            i = min(i + window_samples, n - 1)
        i += 1

    min_force_val = float(np.min(force))
    min_force_idx = int(np.argmin(force))
    return {
        "crossings": crossings,
        "min_force_N": min_force_val,
        "min_force_index": min_force_idx,
        "min_force_time_s": min_force_idx / sr if sr > 0 else 0,
        "window_samples": window_samples,
        "K": K,
    }


def run_debug_on_payload(raw: dict, filter_cutoff_hz: int = 50) -> dict:
    """Run baseline + event detection and return diagnostics."""
    trial = load_trial_from_dict(raw)
    if filter_cutoff_hz and filter_cutoff_hz > 0:
        from src.run_analysis import _apply_lowpass
        trial = _apply_lowpass(trial, filter_cutoff_hz)
    bw, _mass, sigma_quiet = compute_baseline(trial)
    take_off_threshold = max(DEFAULT_TAKE_OFF_THRESHOLD_N, 0.05 * bw)
    diag = analyze_takeoff_candidates(trial.force, trial.sample_rate, take_off_threshold)
    events = detect_events(trial, bodyweight=bw, sigma_quiet=sigma_quiet)
    diag["bodyweight_N"] = bw
    diag["take_off_threshold_N"] = take_off_threshold
    diag["sample_rate"] = trial.sample_rate
    diag["n_samples"] = len(trial.force)
    diag["take_off_found"] = events.take_off is not None
    diag["movement_onset_found"] = events.movement_onset is not None
    diag["landing_found"] = events.landing is not None
    diag["min_force_found"] = events.min_force is not None
    diag["take_off_index"] = events.take_off
    diag["below_threshold_at_min"] = diag["min_force_N"] < take_off_threshold
    return diag


def main():
    parser = argparse.ArgumentParser(description="Debug CMJ event detection (why only Start of movement).")
    parser.add_argument("path", nargs="+", help="JSON file(s) or directory with cmj/*.json")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process per dir (0 = all)")
    parser.add_argument("--filter-hz", type=int, default=50, help="Low-pass filter Hz (0 = none)")
    parser.add_argument("--output", "-o", help="Write summary to CSV")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print full diagnostics per file")
    args = parser.parse_args()

    files = []
    for p in args.path:
        path = Path(p)
        if path.is_file() and path.suffix.lower() == ".json":
            files.append(path)
        elif path.is_dir():
            for sub in ["cmj", ""]:
                d = path / sub if sub else path
                if d.is_dir():
                    for f in sorted(d.glob("*.json"))[: args.limit if args.limit > 0 else None]:
                        files.append(f)
                    break
            else:
                for f in sorted(path.glob("*.json"))[: args.limit if args.limit > 0 else None]:
                    files.append(f)

    if not files:
        print("No JSON files found.", file=sys.stderr)
        return 1

    rows = []
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Skip {fp}: {e}", file=sys.stderr)
            continue
        raw = data.get("raw") if isinstance(data, dict) else data
        if not raw:
            print(f"Skip {fp}: no 'raw' key", file=sys.stderr)
            continue
        try:
            diag = run_debug_on_payload(raw, filter_cutoff_hz=args.filter_hz)
        except Exception as e:
            print(f"Error {fp}: {e}", file=sys.stderr)
            rows.append({
                "file": str(fp),
                "error": str(e),
                "take_off_found": False,
            })
            continue
        diag["file"] = str(fp.name)
        rows.append(diag)

        if args.verbose:
            print(f"\n--- {fp.name} ---")
            print(f"  bodyweight_N = {diag['bodyweight_N']:.1f}")
            print(f"  take_off_threshold_N = {diag['take_off_threshold_N']:.1f}")
            print(f"  min(force) = {diag['min_force_N']:.1f} N at index {diag['min_force_index']} ({diag['min_force_time_s']:.3f} s)")
            print(f"  min(force) < threshold? {diag['below_threshold_at_min']}")
            print(f"  descending crossings of threshold: {len(diag['crossings'])}")
            for idx, (cross_i, run_start) in enumerate(diag["crossings"][:5]):
                print(f"    crossing #{idx+1} at sample {cross_i}, run of 4 consecutive below: {run_start}")
            print(f"  take_off found: {diag['take_off_found']}, movement_onset: {diag['movement_onset_found']}, landing: {diag['landing_found']}")

    if args.output:
        import csv
        fieldnames = [
            "file", "bodyweight_N", "take_off_threshold_N", "min_force_N", "min_force_index",
            "below_threshold_at_min", "n_crossings", "take_off_found", "movement_onset_found", "landing_found",
            "take_off_index", "error",
        ]
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                r["n_crossings"] = len(r.get("crossings", []))
                w.writerow({k: r.get(k, "") for k in fieldnames})
        print(f"Wrote {len(rows)} rows to {args.output}")

    # Summary
    n = len(rows)
    n_to = sum(1 for r in rows if r.get("take_off_found"))
    n_below = sum(1 for r in rows if r.get("below_threshold_at_min"))
    n_cross = sum(1 for r in rows if len(r.get("crossings", [])) > 0)
    print(f"\nSummary: {n} files, take_off found: {n_to}, min(force) below threshold: {n_below}, any crossing: {n_cross}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
