#!/usr/bin/env python3
"""
Standalone debug script: load one DJ JSON, run detection, plot force + all detected points.
Usage (from project root):
  PYTHONPATH=. python3 script/debug_dj_single.py [path_to.json]
Default path: saved_raw_data/dj-data/emirhan_DJ_2026-02-18-1714.json
Saves figure to output/debug_dj_<stem>.png and opens the plot window.
"""
import argparse
import sys
from pathlib import Path

# Project root on path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np

from src.data import load_trial
from src.detect import compute_baseline_drop_jump, detect_drop_jump_events
from src.detect.drop_jump import plot_drop_jump_debug


def main() -> None:
    default_path = _root / "saved_raw_data" / "dj-data" / "emirhan_DJ_2026-02-18-1714.json"
    parser = argparse.ArgumentParser(description="Debug DJ detection on a single file; plot force and events.")
    parser.add_argument("file", nargs="?", default=str(default_path), help="Path to raw DJ JSON")
    parser.add_argument("--no-show", action="store_true", help="Only save PNG, do not open plot window")
    parser.add_argument("-o", "--output", type=str, default=None, help="Output PNG path (default: output/debug_dj_<stem>.png)")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.is_absolute():
        path = _root / path
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading: {path}")
    try:
        trial = load_trial(path)
    except Exception as e:
        print(f"Load failed: {e}", file=sys.stderr)
        sys.exit(1)

    if (trial.test_type or "").strip().upper() != "DJ":
        print(f"Warning: test_type is '{trial.test_type}', not DJ. Proceeding anyway.")

    print("Computing bodyweight (drop jump baseline)...")
    bodyweight, _, _ = compute_baseline_drop_jump(trial)
    print(f"  Bodyweight: {bodyweight:.1f} N")

    print("Running detect_drop_jump_events...")
    points, phases = detect_drop_jump_events(
        trial.force,
        trial.sample_rate,
        bodyweight,
    )

    # Build events dict for plot_drop_jump_debug
    events = {
        "contact_start_index": points.drop_landing,
        "peak1_index": points.peak_impact_force,
        "contact_trough_index": points.contact_through_point,
        "peak2_index": points.peak_drive_off_force,
        "takeoff_index": points.take_off,
        "landing_contact_index": points.flight_land,
        "landing_peak_index": points.peak_landing_force,
    }

    # Report detected indices and force values at those points
    force = trial.force
    n = len(force)
    print("\nDetected points (index, time_s, force_N):")
    labels = [
        ("drop_landing", "Drop Landing"),
        ("peak_impact_force", "Peak Impact"),
        ("contact_through_point", "CTP"),
        ("start_of_concentric", "Start Concentric"),
        ("peak_drive_off_force", "Peak Drive-Off"),
        ("take_off", "Take-off"),
        ("flight_land", "Flight Land"),
        ("peak_landing_force", "Peak Landing"),
    ]
    for attr, name in labels:
        idx = getattr(points, attr, None)
        if idx is not None and 0 <= idx < n:
            t_s = idx / trial.sample_rate
            f_n = float(force[idx])
            print(f"  {name}: index={idx}, t={t_s:.3f}s, F={f_n:.1f} N (BW={bodyweight:.1f})")
        else:
            print(f"  {name}: not found")

    # Plot
    import matplotlib
    if args.no_show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(14, 6))
    plot_drop_jump_debug(
        trial.force,
        trial.sample_rate,
        events,
        bw=bodyweight,
        title=f"DJ Debug: {path.name} (BW={bodyweight:.0f} N)",
        ax=ax,
    )
    ax.set_xlabel("Time (s)")

    out_path = args.output
    if out_path is None:
        out_dir = _root / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"debug_dj_{path.stem}.png"
    else:
        out_path = Path(out_path)
        if not out_path.is_absolute():
            out_path = _root / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    print(f"\nSaved: {out_path}")

    if not args.no_show:
        plt.show()
    plt.close()


if __name__ == "__main__":
    main()
