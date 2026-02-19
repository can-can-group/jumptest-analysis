"""Export raw drop jump JSON files to visualization JSON for the viewer.

Loads all JSON files from a directory (default: saved_raw_data/dj-data/),
runs drop jump detection, and writes:
  - output/<stem>_viz.json for each (viewer payload)
  - output/dj_detection_results.json (summary of all detected points)

Run from project root with deps installed:
  pip install -r requirements.txt
  PYTHONPATH=. python script/export_dj_viz.py [path_to_dj_jsons]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Allow running from project root without PYTHONPATH
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.data import load_trial
from src.data.types import TrialValidity
from src.detect import compute_baseline_drop_jump, detect_drop_jump_events
from src.detect.drop_jump import compute_dj_metrics
from src.export_viz import build_dj_visualization_payload, export_visualization_json


def _points_to_times(
    points_dict: Dict[str, Any], sample_rate: float
) -> Dict[str, Any]:
    """Convert point indices to times (s)."""
    out: Dict[str, Any] = {}
    for k, idx in points_dict.items():
        if idx is not None and sample_rate > 0:
            out[k] = round(idx / sample_rate, 4)
        else:
            out[k] = None
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export raw DJ JSON files to visualization JSON and save detection results"
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=None,
        help="Directory containing raw DJ JSON files (default: saved_raw_data/dj-data)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory for *_viz.json and dj_detection_results.json (default: output)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    input_dir = Path(args.input_dir) if args.input_dir else root / "saved_raw_data" / "dj-data"
    output_dir = root / args.output_dir if not Path(args.output_dir).is_absolute() else Path(args.output_dir)

    if not input_dir.is_dir():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        print(f"No JSON files in {input_dir}", file=sys.stderr)
        sys.exit(0)

    results: List[Dict[str, Any]] = []
    for path in json_files:
        try:
            trial = load_trial(path)
        except Exception as e:
            print(f"Skip {path.name}: load failed - {e}", file=sys.stderr)
            continue

        if (trial.test_type or "").strip().upper() != "DJ":
            print(f"Skip {path.name}: test_type is not DJ", file=sys.stderr)
            continue

        bodyweight, _, _ = compute_baseline_drop_jump(trial)
        points, phases = detect_drop_jump_events(
            trial.force,
            trial.sample_rate,
            bodyweight,
        )
        validity = TrialValidity(is_valid=True, flags=[])
        metrics = compute_dj_metrics(
            trial.force, trial.sample_rate, bodyweight, points, phases
        )

        payload = build_dj_visualization_payload(
            trial,
            bodyweight,
            points,
            phases,
            validity,
            metrics,
        )
        viz_path = output_dir / f"{path.stem}_viz.json"
        export_visualization_json(payload, viz_path)
        print(f"Wrote {viz_path}")

        pts = points.to_dict()
        results.append({
            "file": path.name,
            "stem": path.stem,
            "sample_rate": trial.sample_rate,
            "bodyweight_N": round(float(bodyweight), 2),
            "points_index": pts,
            "points_time_s": _points_to_times(pts, trial.sample_rate),
            "phases": phases.to_dict(),
            "metrics": metrics,
        })

    if results:
        results_path = output_dir / "dj_detection_results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {results_path} ({len(results)} trials)")


if __name__ == "__main__":
    main()
