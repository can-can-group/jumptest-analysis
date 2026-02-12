"""Run CMJ analysis from in-memory data (API entry point). No file I/O or plotting."""
from typing import Any, Dict

from .data import load_trial_from_dict
from .detect import compute_baseline, detect_events, compute_phases, validate_trial
from .export_viz import build_visualization_payload
from .physics import compute_asymmetry, compute_kinematics, compute_metrics


def run_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full CMJ pipeline on in-memory data and return the visualization payload.

    Intended for API use: no files are written, no plots are generated.
    Input dict should contain: athlete_id, test_type, test_duration, and either
    "force" or "total_force", plus left_force, right_force (all arrays).

    Args:
        data: Trial data (force/total_force, left_force, right_force, athlete_id,
              test_type, test_duration). Optional: sample_count.

    Returns:
        Full visualization payload dict: time_s, force_N, phases, key_points,
        metrics, events, validity, and the structured "analysis" block for UI.
        Suitable for JSON response or storage.

    Raises:
        ValueError: If required keys are missing or data is invalid.
    """
    trial = load_trial_from_dict(data)
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
