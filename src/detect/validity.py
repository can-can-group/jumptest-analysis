"""Trial validity checks: single take-off, plausible flight duration."""
from typing import Optional

from ..data.types import CMJTrial, CMJEvents, TrialValidity

FLIGHT_TIME_MIN_S = 0.1
FLIGHT_TIME_MAX_S = 2.0


def validate_trial(
    trial: CMJTrial,
    events: CMJEvents,
    bodyweight: float,
    take_off_threshold: Optional[float] = None,
    flight_time_min_s: float = FLIGHT_TIME_MIN_S,
    flight_time_max_s: float = FLIGHT_TIME_MAX_S,
) -> TrialValidity:
    """Check for single take-off and plausible flight duration. Return flags only (no exception)."""
    flags: list = []
    if take_off_threshold is None:
        take_off_threshold = max(20.0, 0.05 * bodyweight)

    force = trial.force
    n = len(force)
    sr = trial.sample_rate

    # Count descending crossings of take-off threshold
    crossings = 0
    for i in range(1, n):
        if force[i - 1] >= take_off_threshold and force[i] < take_off_threshold:
            crossings += 1
    if crossings > 1:
        flags.append("multiple_takeoff")
    if crossings == 0 and events.take_off is not None:
        flags.append("no_takeoff_crossing")

    # Flight duration
    if events.take_off is not None and events.landing is not None:
        t_flight = (events.landing - events.take_off) / sr
        if t_flight < flight_time_min_s:
            flags.append("short_flight")
        if t_flight > flight_time_max_s:
            flags.append("long_flight")

    is_valid = len(flags) == 0
    return TrialValidity(is_valid=is_valid, flags=flags)
