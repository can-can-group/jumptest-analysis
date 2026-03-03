"""Eccentric end and velocity-zero (braking/concentric boundary) from COM velocity."""
from typing import Optional

import numpy as np

from ..data.types import CMJTrial, CMJEvents, CMJPhases

# Search for first force dip (unweighting); extended for slow/uncalibrated data
UNWEIGHTING_SEARCH_MAX_S = 0.85
# Local minimum: sample is lower than neighbors within this half-width (samples)
LOCAL_MIN_HALF_WINDOW = 3
# Accept dip if force below this fraction of BW (relaxed for uncalibrated/noisy)
DIP_THRESHOLD_PCT_BW = 0.98


def _first_force_dip_after_onset(
    force: np.ndarray,
    onset: int,
    take_off: int,
    sample_rate: float,
    bodyweight: float,
) -> Optional[int]:
    """Find the first local minimum of force after onset (unweighting dip), not a later dip or landing.

    Search in [onset, onset + UNWEIGHTING_SEARCH_MAX_S]. Uses relaxed dip threshold for uncalibrated data.
    """
    n = len(force)
    if take_off <= onset + LOCAL_MIN_HALF_WINDOW * 2:
        return None
    max_search = min(
        take_off - LOCAL_MIN_HALF_WINDOW,
        onset + int(sample_rate * UNWEIGHTING_SEARCH_MAX_S),
        n - 1 - LOCAL_MIN_HALF_WINDOW,
    )
    if max_search <= onset + LOCAL_MIN_HALF_WINDOW:
        return None
    dip_threshold = DIP_THRESHOLD_PCT_BW * bodyweight
    for i in range(onset + LOCAL_MIN_HALF_WINDOW, max_search + 1):
        if force[i] > dip_threshold:
            continue
        window = force[i - LOCAL_MIN_HALF_WINDOW : i + LOCAL_MIN_HALF_WINDOW + 1]
        if len(window) < LOCAL_MIN_HALF_WINDOW * 2 + 1:
            continue
        if float(force[i]) <= float(np.min(window)):
            return i
    return None


def compute_phases(
    trial: CMJTrial,
    events: CMJEvents,
    v: np.ndarray,
) -> CMJEvents:
    """Set eccentric_end and velocity_zero in events using COM velocity.

    Eccentric end = index where v is minimum (most negative) between movement_onset and take_off.
    Velocity zero = first index after eccentric_end where v crosses zero (upward).

    Args:
        trial: Loaded CMJ trial (for length).
        events: Events with movement_onset and take_off set; eccentric_end and velocity_zero updated.
        v: Full-length velocity array from kinematics.

    Returns:
        Same CMJEvents with eccentric_end and velocity_zero set (or left None if not found).
    """
    onset = events.movement_onset
    take_off = events.take_off
    if onset is None or take_off is None:
        return events

    start = onset
    end = take_off + 1
    v_seg = v[start:end]
    if len(v_seg) == 0:
        return events

    # Eccentric end: index of minimum v in [onset, take_off]
    local_min_idx = int(np.argmin(v_seg))
    eccentric_end = start + local_min_idx

    # First zero crossing (v goes from negative to positive) after eccentric_end
    velocity_zero: Optional[int] = None
    for i in range(local_min_idx, len(v_seg) - 1):
        if v_seg[i] <= 0 and v_seg[i + 1] > 0:
            velocity_zero = start + i + 1
            break
    # If v never crosses zero, use eccentric_end + 1 as fallback so we have a concentric "phase"
    if velocity_zero is None and local_min_idx < len(v_seg) - 1:
        velocity_zero = start + local_min_idx + 1

    # Min force: prefer events.min_force when already set and valid (eccentric dip before concentric push from detect_events).
    # Otherwise use first force dip after onset so we don't overwrite the correct unweighting dip with a later dip (e.g. pre–take-off).
    force = trial.force
    sr = trial.sample_rate
    bodyweight = float(np.mean(force[: min(int(sr), len(force))]))
    min_force: Optional[int] = None
    if (
        events.min_force is not None
        and onset is not None
        and take_off is not None
        and onset <= events.min_force < take_off
    ):
        min_force = events.min_force
    if min_force is None:
        min_force = _first_force_dip_after_onset(
            force, onset, take_off, sr, bodyweight
        )
    if min_force is None and onset is not None and take_off is not None and take_off > onset + 5:
        # Fallback: global min in first 0.65s after onset (for slow/uncalibrated data)
        win = min(int(sr * 0.65), take_off - onset - 2)
        if win > 5:
            seg = force[onset : onset + win]
            min_force = onset + int(np.argmin(seg))
    if min_force is None:
        min_force = events.min_force
    # Enforce order: min_force must be strictly before take_off and after onset
    if min_force is not None and (take_off is not None and min_force >= take_off or (onset is not None and min_force < onset)):
        min_force = None

    return CMJEvents(
        movement_onset=events.movement_onset,
        take_off=events.take_off,
        landing=events.landing,
        eccentric_end=eccentric_end,
        velocity_zero=velocity_zero,
        min_force=min_force,
        flight_line_N=getattr(events, "flight_line_N", None),
    )
