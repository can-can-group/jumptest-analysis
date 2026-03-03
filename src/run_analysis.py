"""Run CMJ/DJ/SJ analysis from in-memory data (API entry point). No file I/O or plotting.

This module is the single API entry point for all three test types (CMJ, SJ, DJ);
the backend calls run_analysis(data) with test_type in the payload and receives
the same visualization payload shape for the viewer.
"""
import dataclasses
import os
from typing import Any, Dict, Optional

import numpy as np

from .data import load_trial_from_dict
from .data.types import CMJTrial, TrialValidity
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
from .detect.takeoff_landing_standalone import detect_takeoff_landing
from .export_viz import (
    build_visualization_payload,
    build_sj_visualization_payload,
    build_dj_visualization_payload,
)
from .physics import compute_asymmetry, compute_kinematics, compute_metrics


def _apply_tare(trial: CMJTrial) -> CMJTrial:
    """Tare force so all values are >= 0. If min(force) < 0, subtract it so the signal has no negative values."""
    force = trial.force
    offset = float(np.min(force))
    if offset >= 0:
        return trial
    return CMJTrial(
        athlete_id=trial.athlete_id,
        test_type=trial.test_type,
        test_duration=trial.test_duration,
        sample_count=trial.sample_count,
        force=force - offset,
        left_force=trial.left_force - offset,
        right_force=trial.right_force - offset,
        sample_rate=trial.sample_rate,
        t=trial.t,
    )


def _apply_lowpass(trial: CMJTrial, cutoff_hz: int) -> CMJTrial:
    """Return a new CMJTrial with force, left_force, right_force low-pass filtered. Baseline from raw."""
    from .signal.filter import lowpass_filter

    sr = trial.sample_rate
    force_f = lowpass_filter(trial.force, sr, float(cutoff_hz))
    left_f = lowpass_filter(trial.left_force, sr, float(cutoff_hz))
    right_f = lowpass_filter(trial.right_force, sr, float(cutoff_hz))
    return CMJTrial(
        athlete_id=trial.athlete_id,
        test_type=trial.test_type,
        test_duration=trial.test_duration,
        sample_count=trial.sample_count,
        force=force_f,
        left_force=left_f,
        right_force=right_f,
        sample_rate=trial.sample_rate,
        t=trial.t,
    )


def run_analysis(data: Dict[str, Any], filter_cutoff_hz: Optional[int] = None) -> Dict[str, Any]:
    """Run the full pipeline on in-memory data and return the visualization payload.

    Dispatches by test_type (CMJ, SJ, DJ); all return the same payload shape:
    - CMJ: counter movement jump (events, phases, metrics). Takeoff/landing use
      flight-line refinement: tare (force ≥ 0), band ±8%%, rolling-window smoothing,
      min 150 ms gap; see detect.events and docs/TAKEOFF_LANDING_ALGORITHM_ASCII.md.
    - SJ: squat jump detection, metrics, and classification (optimal_squat_jump vs injured_or_fatigued_squat_jump).
    - DJ: drop jump (reactive strength; events, phases, metrics).

    Input dict should contain: athlete_id, test_type, test_duration, and either
    "force" or "total_force", plus left_force, right_force (all arrays).

    Returns:
        Full visualization payload dict: time_s, force_N, phases, key_points,
        metrics, events, validity, and the structured "analysis" block for UI.

    Raises:
        ValueError: If required keys are missing or data is invalid.

    Optional filter_cutoff_hz: low-pass cutoff in Hz (0 or None = use env FORCE_FILTER_CUTOFF_HZ, no filter if 0).
    """
    if filter_cutoff_hz is None:
        filter_cutoff_hz = int(os.environ.get("FORCE_FILTER_CUTOFF_HZ", "0"))
    trial = load_trial_from_dict(data)
    # Tare: subtract min(force) when negative so all force values are >= 0 (CMJ, SJ, DJ)
    trial = _apply_tare(trial)
    # Baseline (bodyweight) from tared force; thresholds are stable when filter is applied
    bw_raw, mass_raw, sigma_quiet_raw = compute_baseline(trial)
    if filter_cutoff_hz and filter_cutoff_hz > 0:
        trial = _apply_lowpass(trial, filter_cutoff_hz)
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

    # CMJ path: use same takeoff/landing as debug (standalone detector) so reanalyze matches debug viewer
    # Baseline from filtered trial so thresholds match debug script
    bw_cmj, _, sigma_quiet_cmj = compute_baseline(trial)
    events = detect_events(
        trial,
        bodyweight=bw_cmj,
        sigma_quiet=sigma_quiet_cmj,
    )
    # Override takeoff/landing with standalone detector (flight-line refinement, 150 ms min gap)
    to_idx, land_idx, flight_line_N, _ = detect_takeoff_landing(
        trial.force, trial.sample_rate, bw_cmj
    )
    events = dataclasses.replace(
        events,
        take_off=to_idx,
        landing=land_idx,
        flight_line_N=flight_line_N,
    )
    v, _a = compute_kinematics(
        trial,
        bodyweight=bw_cmj,
        onset_idx=events.movement_onset,
        take_off_idx=events.take_off,
    )
    events = compute_phases(trial, events, v)
    validity = validate_trial(trial, events, bodyweight=bw_cmj)
    metrics = compute_metrics(trial, events, bodyweight=bw_cmj, velocity=v)
    asym = compute_asymmetry(trial, events)
    for k, val in asym.items():
        metrics[k] = val
    payload = build_visualization_payload(trial, events, bw_cmj, metrics, validity)
    return payload
