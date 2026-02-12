"""Take-off, landing, movement onset, and min-force detection."""
from typing import Optional

import numpy as np

from ..data.types import CMJTrial, CMJEvents

DEFAULT_TAKE_OFF_THRESHOLD_N = 20.0
DEFAULT_LANDING_THRESHOLD_N = 200.0
ONSET_BELOW_BW = 0.05
ONSET_N_SIGMA = 5.0
ONSET_SUSTAIN_MS = 30.0
LANDING_SUSTAIN_MS = 20.0
TAKE_OFF_CONSECUTIVE_SAMPLES = 4


def detect_events(
    trial: CMJTrial,
    bodyweight: float,
    sigma_quiet: float = 0.0,
    take_off_threshold: Optional[float] = None,
    take_off_consecutive_samples: int = TAKE_OFF_CONSECUTIVE_SAMPLES,
    landing_threshold: Optional[float] = None,
    landing_sustain_ms: float = LANDING_SUSTAIN_MS,
    onset_below_bw: float = ONSET_BELOW_BW,
    onset_n_sigma: float = ONSET_N_SIGMA,
    onset_sustain_ms: float = ONSET_SUSTAIN_MS,
) -> CMJEvents:
    """Detect movement onset, take-off, landing, and min_force from total force.

    - Take-off: first descending crossing with force sustained below threshold for
      take_off_consecutive_samples.
    - Landing: after take_off, find the highest force (peak); scan backward from that peak; first point
      where force is close to force[take_off] is landing (so takeoff and landing force match).
    - Movement onset: F < BW - onset_n_sigma*sigma_quiet (fallback F < (1-onset_below_bw)*BW),
      sustained for onset_sustain_ms.
    - min_force: argmin(F) in [onset, take_off) (strictly before takeoff).
    """
    if take_off_threshold is None:
        take_off_threshold = max(DEFAULT_TAKE_OFF_THRESHOLD_N, 0.05 * bodyweight)
    if landing_threshold is None:
        landing_threshold = max(DEFAULT_LANDING_THRESHOLD_N, 0.05 * bodyweight)

    force = trial.force
    n = len(force)
    sr = trial.sample_rate

    # Take-off: first descending crossing with K consecutive samples below threshold
    take_off: Optional[int] = None
    K = min(take_off_consecutive_samples, n - 1)
    i = 1
    while i < n:
        if force[i - 1] >= take_off_threshold and force[i] < take_off_threshold:
            # Check next K samples stay below
            end = min(i + 1 + K, n)
            if end - (i + 1) < K:
                i = end
                continue
            ok = True
            for j in range(i + 1, i + 1 + K):
                if force[j] >= take_off_threshold:
                    ok = False
                    i = j
                    break
            if ok:
                take_off = i
                break
        i += 1

    # Landing: start from highest force after takeoff, move backward; first point close to takeoff value = landing
    landing: Optional[int] = None
    if take_off is not None and take_off + 1 < n:
        f_to = float(force[take_off])
        post_to = force[take_off + 1 :]
        if len(post_to) > 0:
            peak_offset = int(np.argmax(post_to))
            peak_idx = take_off + 1 + peak_offset
            # "Close" to takeoff: within 3% bodyweight or 30 N so takeoff and landing force match
            close_tolerance = max(30.0, 0.03 * bodyweight)
            landing = None
            for idx in range(peak_idx, take_off, -1):
                if abs(float(force[idx]) - f_to) <= close_tolerance:
                    landing = idx
                    break
            if landing is None:
                landing = peak_idx

    # Movement onset: F < BW - 5*sigma_quiet (or 0.95*BW fallback), sustained 30 ms
    onset_threshold = bodyweight - onset_n_sigma * sigma_quiet
    if sigma_quiet <= 0 or onset_threshold <= 0:
        onset_threshold = (1.0 - onset_below_bw) * bodyweight
    onset_start = int(0.5 * sr)
    onset_end = take_off if take_off is not None else n
    sustain_onset = max(1, int(np.ceil(sr * onset_sustain_ms / 1000.0)))
    movement_onset: Optional[int] = None
    i = onset_start
    while i < min(onset_end, n - sustain_onset):
        if force[i] < onset_threshold:
            end = min(i + sustain_onset, n)
            if end - i < sustain_onset:
                i = end
                continue
            ok = True
            for j in range(i, end):
                if force[j] >= onset_threshold:
                    ok = False
                    i = j + 1
                    break
            if ok:
                movement_onset = i
                break
        i += 1

    # Min force: minimum total force strictly before takeoff [onset, take_off)
    min_force: Optional[int] = None
    if movement_onset is not None and take_off is not None and movement_onset < take_off:
        seg = force[movement_onset : take_off]
        if len(seg) > 0:
            min_force = movement_onset + int(np.argmin(seg))

    return CMJEvents(
        movement_onset=movement_onset,
        take_off=take_off,
        landing=landing,
        eccentric_end=None,
        velocity_zero=None,
        min_force=min_force,
    )
