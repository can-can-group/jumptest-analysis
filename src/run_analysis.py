"""Run CMJ/DJ/SJ analysis from in-memory data (API entry point). No file I/O or plotting."""
from typing import Any, Dict

from .data import load_trial_from_dict
from .data.types import TrialValidity
from .detect import (
    compute_baseline,
    compute_baseline_drop_jump,
    detect_events,
    detect_drop_jump_events,
    compute_phases,
    validate_trial,
    run_squat_jump_analysis,
)
from .detect.drop_jump import compute_dj_metrics
from .export_viz import (
    build_visualization_payload,
    build_sj_visualization_payload,
    build_dj_visualization_payload,
)
from .physics import compute_asymmetry, compute_kinematics, compute_metrics


def run_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full pipeline on in-memory data and return the visualization payload.

    Dispatches by test_type (CMJ, SJ, DJ); all return the same payload shape:
    - CMJ: counter movement jump (events, phases, metrics).
    - SJ: squat jump detection, metrics, and classification (optimal_squat_jump vs injured_or_fatigued_squat_jump).
    - DJ: drop jump (reactive strength; events, phases, metrics).

    Input dict should contain: athlete_id, test_type, test_duration, and either
    "force" or "total_force", plus left_force, right_force (all arrays).

    Returns:
        Full visualization payload dict: time_s, force_N, phases, key_points,
        metrics, events, validity, and the structured "analysis" block for UI.

    Raises:
        ValueError: If required keys are missing or data is invalid.
    """
    trial = load_trial_from_dict(data)
    test_type = (trial.test_type or "").strip().upper()

    if test_type == "SJ":
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
        return payload

    if test_type == "DJ":
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
        return build_dj_visualization_payload(
            trial, bodyweight, points, phases, validity, metrics
        )

    # CMJ path
    bw, _mass, sigma_quiet = compute_baseline(trial)
    events = detect_events(
        trial,
        bodyweight=bw,
        sigma_quiet=sigma_quiet,
    )
    v, _a = compute_kinematics(
        trial,
        bodyweight=bw,
        onset_idx=events.movement_onset,
        take_off_idx=events.take_off,
    )
    events = compute_phases(trial, events, v)
    validity = validate_trial(trial, events, bodyweight=bw)
    metrics = compute_metrics(trial, events, bodyweight=bw, velocity=v)
    asym = compute_asymmetry(trial, events)
    for k, val in asym.items():
        metrics[k] = val
    payload = build_visualization_payload(trial, events, bw, metrics, validity)
    return payload
