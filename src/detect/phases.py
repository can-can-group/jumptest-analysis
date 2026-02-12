"""Eccentric end and velocity-zero (braking/concentric boundary) from COM velocity."""
from typing import Optional

import numpy as np

from ..data.types import CMJTrial, CMJEvents, CMJPhases


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

    # Min force = minimum total force in eccentric phase [onset, velocity_zero] (the unweighting dip)
    # so Unloading/Braking phases and impulse start are correct; fallback to events.min_force
    force = trial.force
    min_force = events.min_force
    if onset is not None and velocity_zero is not None and velocity_zero > onset:
        seg = force[onset : velocity_zero + 1]
        if len(seg) > 0:
            min_force = onset + int(np.argmin(seg))

    return CMJEvents(
        movement_onset=events.movement_onset,
        take_off=events.take_off,
        landing=events.landing,
        eccentric_end=eccentric_end,
        velocity_zero=velocity_zero,
        min_force=min_force,
    )
