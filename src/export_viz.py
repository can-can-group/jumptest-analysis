"""Export CMJ analysis to a single JSON for the JavaScript chart viewer."""
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from .analysis_response import build_analysis_response
from .data.types import CMJTrial, CMJEvents, TrialValidity


def _to_list(arr: np.ndarray) -> List[float]:
    return arr.tolist()


def build_visualization_payload(
    trial: CMJTrial,
    events: CMJEvents,
    bodyweight: float,
    metrics: Dict[str, Any],
    validity: TrialValidity,
) -> Dict[str, Any]:
    """Build a single dict with time, force, phases, key_points, and metrics for the JS viewer."""
    t = trial.t
    sr = trial.sample_rate
    n = trial.sample_count
    onset = events.movement_onset
    take_off = events.take_off
    landing = events.landing
    v_zero = events.velocity_zero
    min_force = events.min_force

    def _phase(start_t: float, end_t: float, **kwargs: Any) -> Dict[str, Any]:
        d = dict(kwargs)
        d["duration_s"] = float(end_t - start_t)
        return d

    # Phases: Quiet, Eccentric (Unloading, Braking), Concentric, Flight, Landing
    phases: List[Dict[str, Any]] = []
    quiet_end = float(t[onset]) if onset is not None and onset < n else 0.0
    phases.append(_phase(0.0, quiet_end, name="Quiet", description="Standing still; force represents body weight",
        start_index=0, end_index=onset if onset is not None else 0, start_time_s=0.0, end_time_s=quiet_end))
    p1_idx = metrics.get("p1_peak_index")
    braking_end = p1_idx if p1_idx is not None else v_zero
    if onset is not None:
        if min_force is not None:
            st, et = float(t[onset]), float(t[min_force])
            phases.append(_phase(st, et, name="Eccentric - Unloading", description="Force decreases as the body lowers",
                start_index=onset, end_index=min_force, start_time_s=st, end_time_s=et))
        if min_force is not None and braking_end is not None and braking_end > min_force:
            st, et = float(t[min_force]), float(t[braking_end])
            phases.append(_phase(st, et, name="Eccentric - Braking", description="Force increases as individual prepares to push off",
                start_index=min_force, end_index=braking_end, start_time_s=st, end_time_s=et))
        if braking_end is not None and take_off is not None and take_off >= braking_end:
            st, et = float(t[braking_end]), float(t[take_off])
            phases.append(_phase(st, et, name="Concentric", description="Push upwards; force increases (P1 and P2 peaks)",
                start_index=braking_end, end_index=take_off, start_time_s=st, end_time_s=et))
        if take_off is not None and landing is not None:
            st, et = float(t[take_off]), float(t[landing])
            phases.append(_phase(st, et, name="Flight", description="Airborne; force plate reads zero",
                start_index=take_off, end_index=landing, start_time_s=st, end_time_s=et))
        if landing is not None:
            st, et = float(t[landing]), float(t[-1])
            phases.append(_phase(st, et, name="Landing", description="Impact and absorption",
                start_index=landing, end_index=n - 1, start_time_s=st, end_time_s=et))

    # Key points
    key_points: List[Dict[str, Any]] = []
    if onset is not None:
        key_points.append({
            "name": "Start of movement",
            "index": onset,
            "time_s": float(t[onset]),
            "value_N": float(trial.force[onset]),
        })
    if min_force is not None:
        key_points.append({
            "name": "Minimum force (eccentric end)",
            "index": min_force,
            "time_s": float(t[min_force]),
            "value_N": float(trial.force[min_force]),
        })
    # Max RFD kept in metrics only; not drawn on chart
    p1_idx = metrics.get("p1_peak_index")
    if p1_idx is not None:
        key_points.append({
            "name": "P1 peak",
            "index": p1_idx,
            "time_s": float(t[p1_idx]),
            "value_N": float(trial.force[p1_idx]),
        })
    p2_idx = metrics.get("p2_peak_index")
    if p2_idx is not None:
        key_points.append({
            "name": "P2 peak",
            "index": p2_idx,
            "time_s": float(t[p2_idx]),
            "value_N": float(trial.force[p2_idx]),
        })
    if take_off is not None:
        key_points.append({
            "name": "Take-off",
            "index": take_off,
            "time_s": float(t[take_off]),
            "value_N": float(trial.force[take_off]),
        })
    if landing is not None:
        key_points.append({
            "name": "Landing",
            "index": landing,
            "time_s": float(t[landing]),
            "value_N": float(trial.force[landing]),
        })

    # Serialize metrics (convert numpy/types for JSON)
    metrics_ser: Dict[str, Any] = {}
    for k, v in metrics.items():
        if v is None:
            metrics_ser[k] = None
        elif isinstance(v, (int, float, str, bool)):
            metrics_ser[k] = v
        elif isinstance(v, np.floating):
            metrics_ser[k] = float(v)
        elif isinstance(v, np.integer):
            metrics_ser[k] = int(v)
        else:
            metrics_ser[k] = v

    payload = {
        "athlete_id": trial.athlete_id,
        "test_type": trial.test_type,
        "sample_rate": trial.sample_rate,
        "bodyweight_N": bodyweight,
        "validity": {"is_valid": validity.is_valid, "flags": validity.flags},
        "time_s": _to_list(trial.t),
        "force_N": _to_list(trial.force),
        "left_force_N": _to_list(trial.left_force),
        "right_force_N": _to_list(trial.right_force),
        "phases": phases,
        "key_points": key_points,
        "events": {
            "movement_onset": events.movement_onset,
            "min_force": events.min_force,
            "velocity_zero": events.velocity_zero,
            "take_off": events.take_off,
            "landing": events.landing,
            "eccentric_end": events.eccentric_end,
        },
        "metrics": metrics_ser,
    }
    payload["analysis"] = build_analysis_response(payload)
    return payload


def export_visualization_json(
    payload: Dict[str, Any],
    path: Path,
) -> None:
    """Write the visualization payload to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
