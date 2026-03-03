"""Export CMJ/DJ analysis to a single JSON for the JavaScript chart viewer."""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .analysis_response import build_analysis_response
from .data.types import CMJTrial, CMJEvents, TrialValidity
from .detect.drop_jump import DropJumpPoints, DropJumpPhases
from .detect.squat_jump import SquatJumpPoints, run_squat_jump_analysis


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

    # Key points in strict order: onset < min_force < P1 < P2 < take_off < landing
    # Only include points that lie in the correct temporal range so order is never mixed
    key_points: List[Dict[str, Any]] = []
    p1_idx = metrics.get("p1_peak_index")
    p2_idx = metrics.get("p2_peak_index")
    if onset is not None:
        key_points.append({
            "name": "Start of movement",
            "index": onset,
            "time_s": float(t[onset]),
            "value_N": float(trial.force[onset]),
        })
    if min_force is not None and (take_off is None or min_force < take_off) and (onset is None or min_force > onset):
        key_points.append({
            "name": "Minimum force (eccentric end)",
            "index": min_force,
            "time_s": float(t[min_force]),
            "value_N": float(trial.force[min_force]),
        })
    if p1_idx is not None and (min_force is None or p1_idx > min_force) and (take_off is None or p1_idx < take_off):
        key_points.append({
            "name": "P1 peak",
            "index": p1_idx,
            "time_s": float(t[p1_idx]),
            "value_N": float(trial.force[p1_idx]),
        })
    if p2_idx is not None and (p1_idx is None or p2_idx > p1_idx) and (take_off is None or p2_idx < take_off):
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
    # Ensure key_points are always in temporal order (by index)
    key_points.sort(key=lambda p: p["index"])

    # Flight line: value used for takeoff/landing (move line up until 2 crossings); draw on chart
    flight_mean_force_N: Optional[float] = getattr(events, "flight_line_N", None)
    if flight_mean_force_N is None and take_off is not None and landing is not None and landing > take_off and landing < n:
        flight_mean_force_N = float(np.mean(trial.force[take_off : landing + 1]))  # fallback

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
        "flight_mean_force_N": flight_mean_force_N,
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


def build_dj_visualization_payload(
    trial: CMJTrial,
    bodyweight: float,
    points: DropJumpPoints,
    phases: DropJumpPhases,
    validity: TrialValidity,
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a visualization payload for a Drop Jump trial.

    Same JSON shape as CMJ (time_s, force_N, phases, key_points, metrics, validity)
    but with DJ-specific phases and key points.
    """
    t = trial.t
    n = trial.sample_count

    def _phase(start_t: float, end_t: float, **kwargs: Any) -> Dict[str, Any]:
        d = dict(kwargs)
        d["duration_s"] = float(end_t - start_t)
        return d

    # DJ Phases: Pre-jump, Contact, Flight, Landing
    dj_phases: List[Dict[str, Any]] = []
    contact_start = points.drop_landing
    take_off = points.take_off
    flight_land = points.flight_land

    if contact_start is not None and contact_start > 0:
        st, et = 0.0, float(t[contact_start])
        dj_phases.append(_phase(st, et, name="Pre-jump",
            description="Athlete on the box or in freefall before landing",
            start_index=0, end_index=contact_start - 1, start_time_s=st, end_time_s=et))

    if contact_start is not None and take_off is not None:
        st, et = float(t[contact_start]), float(t[take_off])
        dj_phases.append(_phase(st, et, name="Contact",
            description="Ground contact from drop landing through propulsion to take-off",
            start_index=contact_start, end_index=take_off, start_time_s=st, end_time_s=et))

    if take_off is not None and flight_land is not None:
        st, et = float(t[take_off]), float(t[flight_land])
        dj_phases.append(_phase(st, et, name="Flight",
            description="Airborne; force plate reads near zero",
            start_index=take_off, end_index=flight_land, start_time_s=st, end_time_s=et))

    if flight_land is not None:
        st, et = float(t[flight_land]), float(t[-1])
        dj_phases.append(_phase(st, et, name="Landing",
            description="Impact and absorption after reactive jump",
            start_index=flight_land, end_index=n - 1, start_time_s=st, end_time_s=et))

    # DJ Key Points (only include non-None)
    key_points: List[Dict[str, Any]] = []
    _dj_kp_defs = [
        ("Drop Landing", points.drop_landing),
        ("Peak Impact Force", points.peak_impact_force),
        ("Contact Through Point", points.contact_through_point),
        ("Start of Concentric", points.start_of_concentric),
        ("Peak Drive-Off Force", points.peak_drive_off_force),
        ("Take-off", points.take_off),
        ("Flight Land", points.flight_land),
        ("Peak Landing Force", points.peak_landing_force),
    ]
    for kp_name, kp_idx in _dj_kp_defs:
        if kp_idx is not None and 0 <= kp_idx < n:
            key_points.append({
                "name": kp_name,
                "index": kp_idx,
                "time_s": float(t[kp_idx]),
                "value_N": float(trial.force[kp_idx]),
            })

    # Serialize metrics
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

    events = {**points.to_dict(), "landing": points.flight_land}
    payload = {
        "athlete_id": trial.athlete_id,
        "test_type": "DJ",
        "sample_rate": trial.sample_rate,
        "bodyweight_N": bodyweight,
        "validity": {"is_valid": validity.is_valid, "flags": validity.flags},
        "time_s": _to_list(trial.t),
        "force_N": _to_list(trial.force),
        "left_force_N": _to_list(trial.left_force),
        "right_force_N": _to_list(trial.right_force),
        "phases": dj_phases,
        "key_points": key_points,
        "events": events,
        "metrics": metrics_ser,
    }
    payload["classification"] = metrics.get("dj_classification")
    payload["analysis"] = build_analysis_response(payload)
    return payload


def build_sj_visualization_payload(
    trial: CMJTrial,
    bodyweight: float,
    points: SquatJumpPoints,
    validity: TrialValidity,
    metrics: Dict[str, Any],
    flags: Dict[str, bool],
    classification: str,
) -> Dict[str, Any]:
    """Build visualization payload for a Squat Jump trial.

    Phases: Quiet, Contraction (concentric), Flight, Landing.
    Key points: Contraction start, Peak force, Take-off, Landing, Peak landing force.
    """
    t = trial.t
    n = trial.sample_count

    def _phase(start_t: float, end_t: float, **kwargs: Any) -> Dict[str, Any]:
        d = dict(kwargs)
        d["duration_s"] = float(end_t - start_t)
        return d

    phases: List[Dict[str, Any]] = []
    cs = points.contraction_start
    to_idx = points.takeoff_index
    land_idx = points.landing_index

    if cs is not None and cs > 0:
        st, et = 0.0, float(t[cs])
        phases.append(_phase(st, et, name="Quiet",
            description="Standing still; force represents body weight",
            start_index=0, end_index=cs - 1, start_time_s=st, end_time_s=et))
    if cs is not None and to_idx is not None:
        st, et = float(t[cs]), float(t[to_idx])
        phases.append(_phase(st, et, name="Concentric",
            description="Concentric phase from contraction start to take-off",
            start_index=cs, end_index=to_idx, start_time_s=st, end_time_s=et))
    if to_idx is not None and land_idx is not None:
        st, et = float(t[to_idx]), float(t[land_idx])
        phases.append(_phase(st, et, name="Flight",
            description="Airborne; force plate reads near zero",
            start_index=to_idx, end_index=land_idx, start_time_s=st, end_time_s=et))
    if land_idx is not None:
        st, et = float(t[land_idx]), float(t[-1])
        phases.append(_phase(st, et, name="Landing",
            description="Impact and absorption after landing",
            start_index=land_idx, end_index=n - 1, start_time_s=st, end_time_s=et))

    key_points: List[Dict[str, Any]] = []
    _sj_kp_defs: List[Tuple[str, Optional[int]]] = [
        ("Contraction start", points.contraction_start),
        ("Peak force", points.peak_force_index),
        ("Take-off", points.takeoff_index),
        ("Landing", points.landing_index),
        ("Peak landing force", points.peak_landing_index),
    ]
    if getattr(points, "first_peak_index", None) is not None:
        _sj_kp_defs.append(("First peak (bimodal)", points.first_peak_index))
    if getattr(points, "trough_between_peaks_index", None) is not None:
        _sj_kp_defs.append(("Trough between peaks (bimodal)", points.trough_between_peaks_index))
    if getattr(points, "second_peak_index", None) is not None:
        _sj_kp_defs.append(("Second peak (bimodal)", points.second_peak_index))
    for kp_name, kp_idx in _sj_kp_defs:
        if kp_idx is not None and 0 <= kp_idx < n:
            key_points.append({
                "name": kp_name,
                "index": kp_idx,
                "time_s": float(t[kp_idx]),
                "value_N": float(trial.force[kp_idx]),
            })

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
    metrics_ser["sj_classification"] = classification

    payload = {
        "athlete_id": trial.athlete_id,
        "test_type": "SJ",
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
            "contraction_start": points.contraction_start,
            "peak_force_index": points.peak_force_index,
            "takeoff_index": points.takeoff_index,
            "landing_index": points.landing_index,
            "peak_landing_index": points.peak_landing_index,
            "take_off": points.takeoff_index,
            "landing": points.landing_index,
            **({"first_peak_index": points.first_peak_index} if getattr(points, "first_peak_index", None) is not None else {}),
            **({"trough_between_peaks_index": points.trough_between_peaks_index} if getattr(points, "trough_between_peaks_index", None) is not None else {}),
            **({"second_peak_index": points.second_peak_index} if getattr(points, "second_peak_index", None) is not None else {}),
        },
        "metrics": metrics_ser,
        "sj_classification": classification,
        "sj_flags": flags,
    }
    payload["classification"] = classification
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
