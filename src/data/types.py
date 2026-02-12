"""Typed structures for CMJ trial data."""
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class CMJTrial:
    """Single CMJ trial from force plate export."""

    athlete_id: str
    test_type: str
    test_duration: float
    sample_count: int
    force: np.ndarray
    left_force: np.ndarray
    right_force: np.ndarray
    sample_rate: float
    t: np.ndarray

    def __post_init__(self) -> None:
        n = self.sample_count
        if len(self.force) != n or len(self.left_force) != n or len(self.right_force) != n:
            raise ValueError(
                f"Array length mismatch: force={len(self.force)}, "
                f"left_force={len(self.left_force)}, right_force={len(self.right_force)}, "
                f"sample_count={n}"
            )


@dataclass
class CMJEvents:
    """Detected event indices (sample indices into trial arrays).

    - eccentric_end: index of peak eccentric (downward) velocity (min v).
    - velocity_zero: bottom of countermovement (first v=0 after eccentric_end).
    - min_force: index of minimum force in [onset, take_off]; end of unweighting phase.
    """

    movement_onset: Optional[int] = None
    take_off: Optional[int] = None
    landing: Optional[int] = None
    eccentric_end: Optional[int] = None  # peak eccentric velocity (min v)
    velocity_zero: Optional[int] = None  # bottom of dip (first v=0 after eccentric_end)
    min_force: Optional[int] = None  # argmin(F) in contact; end of unweighting


@dataclass
class CMJPhases:
    """Phase boundary indices (start inclusive, end exclusive or inclusive per convention)."""

    weighing_end: int
    unweighting_start: int
    unweighting_end: int
    braking_start: int
    braking_end: int
    propulsion_start: int
    propulsion_end: int
    flight_start: int
    flight_end: int
    landing_start: int


@dataclass
class TrialValidity:
    """Result of trial validity checks."""

    is_valid: bool
    flags: list
