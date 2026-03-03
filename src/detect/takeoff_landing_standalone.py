"""
Standalone takeoff/landing detection for CMJ/SJ: no onset, no phases, no validity.
Used for debugging and for a dedicated viewer. Returns indices + flight line + debug info.
"""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .events import (
    _concentric_peak_index,
    _detect_flight_adaptive,
    _detect_flight_crossing,
    _detect_flight_longest_run,
    _detect_flight_unified,
    _detect_flight_valley,
    _expand_flight_to_dip,
    _refine_landing,
    _refine_takeoff,
    _refine_takeoff_landing_to_mean_line_crossings,
)
from .events import (
    DEFAULT_TAKE_OFF_THRESHOLD_N,
    FLIGHT_LINE_TOLERANCE_PCT,
    FLIGHT_THRESHOLD_PCT_BW,
)


def detect_takeoff_landing(
    force: np.ndarray,
    sample_rate: float,
    bodyweight: float,
) -> Tuple[Optional[int], Optional[int], Optional[float], Dict[str, Any]]:
    """Run only the takeoff/landing detection chain (same logic as detect_events).

    Returns:
        (take_off_index, landing_index, flight_line_N, debug_info).
        If detection fails, take_off/landing may be None; flight_line_N then None.
    """
    n = len(force)
    sr = sample_rate
    take_off_threshold = max(DEFAULT_TAKE_OFF_THRESHOLD_N, FLIGHT_THRESHOLD_PCT_BW * bodyweight)
    landing_threshold = max(200.0, 0.05 * bodyweight)

    concentric_peak_idx = _concentric_peak_index(force, sr)
    take_off, landing = _detect_flight_unified(force, sr, bodyweight, take_off_threshold)
    if take_off is None:
        take_off, landing = _detect_flight_longest_run(
            force, sr, bodyweight, take_off_threshold, flight_search_start=concentric_peak_idx
        )
    if take_off is None:
        take_off, landing = _detect_flight_adaptive(
            force, sr, bodyweight,
            flight_search_start=concentric_peak_idx,
            take_off_threshold=take_off_threshold,
        )
    if take_off is None:
        take_off, landing = _detect_flight_valley(
            force, sr, bodyweight, flight_search_start=concentric_peak_idx
        )
    if take_off is None:
        take_off, landing = _detect_flight_crossing(
            force, n, sr, take_off_threshold, 4, bodyweight,
            flight_search_start=concentric_peak_idx,
        )
    if take_off is not None and landing is None and take_off + 1 < n:
        f_to = float(force[take_off])
        post_to = force[take_off + 1:]
        peak_offset = int(np.argmax(post_to))
        peak_idx = take_off + 1 + peak_offset
        close_tolerance = max(30.0, 0.03 * bodyweight)
        for idx in range(peak_idx, take_off, -1):
            if abs(float(force[idx]) - f_to) <= close_tolerance:
                landing = idx
                break
        if landing is None:
            landing = peak_idx

    if take_off is not None and landing is not None and landing > take_off:
        take_off, landing = _expand_flight_to_dip(
            force, take_off, landing, bodyweight, concentric_peak_idx
        )

    if take_off is not None:
        take_off = _refine_takeoff(force, take_off, take_off_threshold)

    run_end_right = landing
    if take_off is not None and landing is not None and landing > take_off:
        landing = _refine_landing(force, take_off, landing, bodyweight, sr)
        if landing < run_end_right:
            landing = run_end_right
        if landing <= take_off:
            landing = take_off + 1
        take_off, landing, flight_line_N = _refine_takeoff_landing_to_mean_line_crossings(
            force, take_off, landing, concentric_peak_idx, bodyweight, sample_rate=sr
        )
    else:
        flight_line_N = None

    # Build debug info
    debug: Dict[str, Any] = {
        "concentric_peak_index": int(concentric_peak_idx),
        "take_off_index": int(take_off) if take_off is not None else None,
        "landing_index": int(landing) if landing is not None else None,
        "flight_line_N": float(flight_line_N) if flight_line_N is not None else None,
        "issues": [],
    }
    if take_off is not None and landing is not None and flight_line_N is not None and landing > take_off:
        seg = force[take_off : landing + 1]
        valley_offset = int(np.argmin(seg))
        valley_idx = take_off + valley_offset
        debug["valley_index"] = int(valley_idx)
        f_to = float(force[take_off])
        f_land = float(force[landing])
        tol = FLIGHT_LINE_TOLERANCE_PCT
        line_lo = flight_line_N * (1.0 - tol)
        line_hi = flight_line_N * (1.0 + tol)
        debug["force_at_takeoff_N"] = f_to
        debug["force_at_landing_N"] = f_land
        debug["line_lo_N"] = line_lo
        debug["line_hi_N"] = line_hi
        in_band_to = line_lo <= f_to <= line_hi
        in_band_land = line_lo <= f_land <= line_hi
        debug["takeoff_in_band"] = in_band_to
        debug["landing_in_band"] = in_band_land
        force_diff = abs(f_land - f_to)
        debug["force_diff_N"] = force_diff
        if not in_band_to:
            debug["issues"].append("takeoff_not_in_band")
        if not in_band_land:
            debug["issues"].append("landing_not_in_band")
        if force_diff > 0.15 * bodyweight:
            debug["issues"].append("force_diff_large")
        if landing <= valley_idx:
            debug["issues"].append("landing_at_or_before_valley")
    else:
        debug["issues"].append("no_flight_detected")

    return take_off, landing, flight_line_N, debug
