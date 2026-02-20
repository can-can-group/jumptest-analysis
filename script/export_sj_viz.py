"""Export raw Squat Jump JSON files to visualization JSON for the viewer.

Loads all JSON files from a directory (default: saved_raw_data/sj-data/),
runs squat jump detection and classification, and writes:
  - output/<stem>_viz.json for each (viewer payload)
  - output/sj_detection_results.json (summary: points, metrics, classification)

Run from project root:
  PYTHONPATH=. python script/export_sj_viz.py [path_to_sj_jsons]
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.data import load_trial
from src.data.types import TrialValidity
from src.detect.squat_jump import run_squat_jump_analysis
from src.export_viz import build_sj_visualization_payload, export_visualization_json


def _serialize_result(result: Dict[str, Any], trial, path: Path) -> Dict[str, Any]:
    """Build one entry for sj_detection_results.json (no _points etc.)."""
    points = result["_points"]
    metrics = result["_metrics_full"]
    validity = result["validity"]
    sr = trial.sample_rate
    pts = points.to_dict()
    points_time_s = {}
    for k, idx in pts.items():
        if idx is not None and sr > 0:
            points_time_s[k] = round(idx / sr, 4)
        else:
            points_time_s[k] = None
    return {
        "file": path.name,
        "stem": path.stem,
        "sample_rate": trial.sample_rate,
        "bodyweight_N": round(float(result["_bodyweight"]), 2),
        "points_index": pts,
        "points_time_s": points_time_s,
        "metrics": {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in metrics.items()
        },
        "flags": result["flags"],
        "classification": result["classification"],
        "validity": validity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export raw SJ JSON files to visualization JSON and detection results"
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=None,
        help="Directory containing raw SJ JSON files (default: saved_raw_data/sj-data)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory for *_viz.json and sj_detection_results.json (default: output)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    input_dir = Path(args.input_dir) if args.input_dir else root / "saved_raw_data" / "sj-data"
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

        if (trial.test_type or "").strip().upper() != "SJ":
            print(f"Skip {path.name}: test_type is not SJ", file=sys.stderr)
            continue

        result = run_squat_jump_analysis(trial)
        validity = TrialValidity(
            is_valid=result["validity"]["is_valid"],
            flags=result["validity"]["flags"],
        )
        payload = build_sj_visualization_payload(
            trial,
            result["_bodyweight"],
            result["_points"],
            validity,
            result["_metrics_full"],
            result["flags"],
            result["classification"],
        )
        viz_path = output_dir / f"{path.stem}_viz.json"
        export_visualization_json(payload, viz_path)
        print(f"Wrote {viz_path}  classification={result['classification']}")

        results.append(_serialize_result(result, trial, path))

    if results:
        results_path = output_dir / "sj_detection_results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {results_path} ({len(results)} trials)")


if __name__ == "__main__":
    main()
