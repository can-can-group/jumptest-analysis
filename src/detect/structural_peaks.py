"""
Robust structural peak detection for CMJ force-time data.

Detects Peak 1 (P1) and Peak 2 (P2) by rise-fall cycle structure in the concentric
phase. No smoothing or filtering of raw force. Peaks are ordered by time (P1 first, P2 second).
"""
from dataclasses import dataclass
from typing import Any, Dict, List

import numpy as np
from scipy.ndimage import uniform_filter1d


# Default thresholds (configurable)
DEFAULT_MIN_CYCLE_DURATION_MS = 30.0
DEFAULT_MIN_CYCLE_AMPLITUDE_PCT_BW = 5.0
DEFAULT_MIN_CYCLE_IMPULSE_N_S = 0.5
DEFAULT_MIN_VALLEY_DEPTH_PCT_BW = 3.0
DEFAULT_MIN_P1_P2_SEPARATION_MS = 40.0
DEFAULT_MIN_P2_BEFORE_TAKEOFF_MS = 20.0
DEFAULT_MIN_VALLEY_DROP_PCT_BW = 3.0


@dataclass
class MonotonicSegment:
    """Consecutive samples with same slope sign."""
    start_index: int
    end_index: int
    is_rising: bool
    duration_samples: int
    duration_ms: float
    amplitude: float
    impulse_Ns: float


@dataclass
class RiseFallCycle:
    """One structural peak: rise segment followed by fall segment."""
    peak_index_rel: int  # index in F_con
    peak_force: float
    valley_before: float
    valley_after: float
    cycle_amplitude: float
    cycle_duration_ms: float
    cycle_impulse_Ns: float
    valley_depth: float
    rise_start: int
    fall_end: int


def _first_differences(F: np.ndarray) -> np.ndarray:
    """dF[i] = F[i] - F[i-1]. Length = len(F)-1. dF[0] = F[1]-F[0]."""
    return np.diff(F.astype(float))


def _slope_sign(dF: np.ndarray) -> np.ndarray:
    """+1 if dF > 0, -1 if dF < 0, 0 if dF == 0."""
    s = np.zeros(len(dF), dtype=np.int8)
    s[dF > 0] = 1
    s[dF < 0] = -1
    return s


def _monotonic_segments(
    F_con: np.ndarray,
    slope_sign: np.ndarray,
    bodyweight: float,
    dt: float,
) -> List[MonotonicSegment]:
    """Group consecutive samples with same slope sign. Return list of segments."""
    n = len(slope_sign)
    if n == 0:
        return []

    segments: List[MonotonicSegment] = []
    i = 0
    while i < n:
        s = slope_sign[i]
        j = i
        while j < n and slope_sign[j] == s:
            j += 1
        # Segment in slope index space: [i, j-1]. In F_con: start_index = i, end_index = j (inclusive would be j, but F_con has indices 0..len(F_con)-1)
        # dF[k] is between F_con[k] and F_con[k+1]. So slope indices i..j-1 cover F_con indices i through j (j-i+1 points).
        start_idx = i
        end_idx = j  # last F_con index in this segment is j (so we have F_con[i] ... F_con[j])
        if end_idx >= len(F_con):
            end_idx = len(F_con) - 1
        duration_samples = end_idx - start_idx + 1
        duration_ms = duration_samples * dt * 1000.0
        seg_force = F_con[start_idx : end_idx + 1]
        amplitude = float(np.max(seg_force) - np.min(seg_force))
        impulse_Ns = float(np.sum((seg_force - bodyweight) * dt))
        segments.append(
            MonotonicSegment(
                start_index=start_idx,
                end_index=end_idx,
                is_rising=(s == 1),
                duration_samples=duration_samples,
                duration_ms=duration_ms,
                amplitude=amplitude,
                impulse_Ns=impulse_Ns,
            )
        )
        i = j

    return segments


def _build_rise_fall_cycles(
    F_con: np.ndarray,
    segments: List[MonotonicSegment],
    bodyweight: float,
    dt: float,
) -> List[RiseFallCycle]:
    """Build cycles: each is a rising segment followed by a falling segment."""
    cycles: List[RiseFallCycle] = []
    i = 0
    while i < len(segments) - 1:
        rise = segments[i]
        fall = segments[i + 1]
        if not rise.is_rising or fall.is_rising:
            i += 1
            continue
        # Peak at transition: end of rise = start of fall
        peak_idx = rise.end_index
        if peak_idx >= len(F_con):
            i += 1
            continue
        peak_force = float(F_con[peak_idx])
        valley_before = float(F_con[rise.start_index])
        valley_after = float(F_con[fall.end_index])
        cycle_amplitude = peak_force - min(valley_before, valley_after)
        cycle_duration_ms = (fall.end_index - rise.start_index + 1) * dt * 1000.0
        seg_force = F_con[rise.start_index : fall.end_index + 1]
        cycle_impulse_Ns = float(np.sum((seg_force - bodyweight) * dt))
        valley_depth = peak_force - valley_after

        cycles.append(
            RiseFallCycle(
                peak_index_rel=peak_idx,
                peak_force=peak_force,
                valley_before=valley_before,
                valley_after=valley_after,
                cycle_amplitude=cycle_amplitude,
                cycle_duration_ms=cycle_duration_ms,
                cycle_impulse_Ns=cycle_impulse_Ns,
                valley_depth=valley_depth,
                rise_start=rise.start_index,
                fall_end=fall.end_index,
            )
        )
        i += 1

    return cycles


def _filter_noise_cycles(
    cycles: List[RiseFallCycle],
    bodyweight: float,
    min_duration_ms: float,
    min_amplitude_pct_bw: float,
    min_impulse_Ns: float,
    min_valley_depth_pct_bw: float,
) -> List[RiseFallCycle]:
    """Reject cycles that fail any threshold."""
    min_amp = (min_amplitude_pct_bw / 100.0) * bodyweight
    min_valley = (min_valley_depth_pct_bw / 100.0) * bodyweight
    valid = []
    for c in cycles:
        if c.cycle_duration_ms < min_duration_ms:
            continue
        if c.cycle_amplitude < min_amp:
            continue
        if c.cycle_impulse_Ns < min_impulse_Ns:
            continue
        if c.valley_depth < min_valley:
            continue
        valid.append(c)
    return valid


def _confidence_score(cycles: List[RiseFallCycle], bodyweight: float) -> float:
    """Score 0-1 from valley depth, impulse ratio, duration robustness."""
    if not cycles:
        return 0.0
    scores = []
    for c in cycles:
        vd_norm = min(1.0, c.valley_depth / (0.1 * bodyweight)) if bodyweight > 0 else 0.0
        imp_norm = min(1.0, c.cycle_impulse_Ns / 50.0) if c.cycle_impulse_Ns > 0 else 0.0
        dur_norm = min(1.0, c.cycle_duration_ms / 100.0)
        scores.append(0.4 * vd_norm + 0.3 * imp_norm + 0.3 * dur_norm)
    return float(np.mean(scores)) if scores else 0.0


def detect_structural_peaks(
    force: np.ndarray,
    sample_rate: float,
    velocity_zero_index: int,
    takeoff_index: int,
    bodyweight: float,
    min_cycle_duration_ms: float = DEFAULT_MIN_CYCLE_DURATION_MS,
    min_cycle_amplitude_pct_bw: float = DEFAULT_MIN_CYCLE_AMPLITUDE_PCT_BW,
    min_cycle_impulse_N_s: float = DEFAULT_MIN_CYCLE_IMPULSE_N_S,
    min_valley_depth_pct_bw: float = DEFAULT_MIN_VALLEY_DEPTH_PCT_BW,
    min_p1_p2_separation_ms: float = DEFAULT_MIN_P1_P2_SEPARATION_MS,
    min_p2_before_takeoff_ms: float = DEFAULT_MIN_P2_BEFORE_TAKEOFF_MS,
    min_valley_drop_pct_bw: float = DEFAULT_MIN_VALLEY_DROP_PCT_BW,
) -> Dict[str, Any]:
    """
    Detect P1 and P2 in the concentric phase by structural rise-fall cycles.

    Window: force[velocity_zero_index : takeoff_index]. No smoothing.
    Returns P1_index, P2_index (None if not found), num_detected_cycles, confidence_score.
    """
    start = velocity_zero_index
    end = takeoff_index
    if start >= end or end > len(force):
        return {
            "P1_index": None,
            "P2_index": None,
            "num_detected_cycles": 0,
            "confidence_score": 0.0,
        }

    F_con = force[start:end].astype(float)
    n_con = len(F_con)
    if n_con < 2:
        peak_idx = start + int(np.argmax(F_con)) if n_con == 1 else None
        return {
            "P1_index": peak_idx,
            "P2_index": None,
            "num_detected_cycles": 0,
            "confidence_score": 0.0,
        }

    dt = 1.0 / sample_rate
    dF = _first_differences(F_con)
    slope = _slope_sign(dF)
    segments = _monotonic_segments(F_con, slope, bodyweight, dt)
    cycles = _build_rise_fall_cycles(F_con, segments, bodyweight, dt)
    valid_cycles = _filter_noise_cycles(
        cycles,
        bodyweight,
        min_cycle_duration_ms,
        min_cycle_amplitude_pct_bw,
        min_cycle_impulse_N_s,
        min_valley_depth_pct_bw,
    )

    # Sort by time (peak_index_rel) — P1 = first cycle, P2 = second
    valid_cycles = sorted(valid_cycles, key=lambda c: c.peak_index_rel)

    if len(valid_cycles) == 0:
        return {
            "P1_index": None,
            "P2_index": None,
            "num_detected_cycles": 0,
            "confidence_score": 0.0,
        }

    if len(valid_cycles) == 1:
        p1_global = start + valid_cycles[0].peak_index_rel
        return {
            "P1_index": int(p1_global),
            "P2_index": None,
            "num_detected_cycles": 1,
            "confidence_score": _confidence_score(valid_cycles, bodyweight),
        }

    # Two or more: P1 = first, P2 = second (chronological)
    c1, c2 = valid_cycles[0], valid_cycles[1]
    p1_global = start + c1.peak_index_rel
    p2_global = start + c2.peak_index_rel

    # Safeguards
    separation_ms = (c2.peak_index_rel - c1.peak_index_rel) * dt * 1000.0
    p2_before_to_ms = (end - 1 - c2.peak_index_rel) * dt * 1000.0  # distance from P2 to end of window (takeoff)
    valley_between = float(np.min(F_con[c1.peak_index_rel : c2.peak_index_rel + 1]))
    valley_drop = c1.peak_force - valley_between
    min_valley_drop = (min_valley_drop_pct_bw / 100.0) * bodyweight

    if (
        separation_ms < min_p1_p2_separation_ms
        or p2_before_to_ms < min_p2_before_takeoff_ms
        or valley_drop < min_valley_drop
    ):
        return {
            "P1_index": int(p1_global),
            "P2_index": None,
            "num_detected_cycles": len(valid_cycles),
            "confidence_score": _confidence_score(valid_cycles[:1], bodyweight),
        }

    return {
        "P1_index": int(p1_global),
        "P2_index": int(p2_global),
        "num_detected_cycles": len(valid_cycles),
        "confidence_score": _confidence_score(valid_cycles, bodyweight),
    }


def detect_peaks_line_no_cut(
    force: np.ndarray,
    min_force_index: int,
    takeoff_index: int,
    sample_rate: float = 1000.0,
    min_p1_p2_separation_ms: float = 40.0,
    tolerance: float = 1e-9,
) -> Dict[str, Any]:
    """
    Detect P1 and P2 from min_force to takeoff: P1 = highest point; P2 = highest other
    local maximum such that (1) the line segment from P1 to P2 does not cut into the
    force curve (line stays on or above the data between P1 and P2), and (2) P2 is at
    least min_p1_p2_separation_ms away from P1 (avoids picking the same peak twice).

    Returns dict with P1_index, P2_index (global indices; P2_index may be None).
    """
    start = min_force_index
    end = takeoff_index
    if start >= end or end >= len(force):
        return {"P1_index": None, "P2_index": None}

    seg = force[start:end + 1].astype(float)
    n = len(seg)
    if n == 0:
        return {"P1_index": None, "P2_index": None}
    if n == 1:
        return {"P1_index": int(start), "P2_index": None}

    min_sep_samples = max(1, int(sample_rate * min_p1_p2_separation_ms / 1000.0))

    # P1 = global max in window
    p1_rel = int(np.argmax(seg))
    p1_global = start + p1_rel

    # Local maxima: peak where force >= both neighbors (or boundary)
    local_max = []
    for i in range(n):
        left_ok = i == 0 or seg[i] >= seg[i - 1]
        right_ok = i == n - 1 or seg[i] >= seg[i + 1]
        if left_ok and right_ok:
            local_max.append(i)

    if not local_max:
        return {"P1_index": int(p1_global), "P2_index": None}

    # Sort by force descending; P1 is the highest
    local_max.sort(key=lambda i: seg[i], reverse=True)

    def line_above_curve(a_rel: int, b_rel: int) -> bool:
        """True if line from (a, seg[a]) to (b, seg[b]) never goes below seg between a and b."""
        if a_rel == b_rel:
            return True
        i_lo = min(a_rel, b_rel)
        i_hi = max(a_rel, b_rel)
        fa = seg[a_rel]
        fb = seg[b_rel]
        for j in range(i_lo + 1, i_hi):
            # Linear interpolation: value at j on the line
            t = (j - a_rel) / (b_rel - a_rel) if (b_rel - a_rel) != 0 else 0.0
            line_val = fa + t * (fb - fa)
            if line_val < seg[j] - tolerance:
                return False
        return True

    # P2 = first candidate (by descending force) that is not P1, is at least min_sep_samples from P1, and line P1->cand doesn't cut
    p2_global = None
    for c_rel in local_max:
        if c_rel == p1_rel:
            continue
        if abs(c_rel - p1_rel) < min_sep_samples:
            continue
        if line_above_curve(p1_rel, c_rel):
            p2_global = start + c_rel
            break

    return {
        "P1_index": int(p1_global),
        "P2_index": int(p2_global) if p2_global is not None else None,
    }


def _smooth_segment(seg: np.ndarray, window_samples: int) -> np.ndarray:
    """Light moving average for detection only. window_samples must be odd."""
    if window_samples < 3 or len(seg) < window_samples:
        return seg.copy()
    w = int(window_samples) | 1
    return uniform_filter1d(seg.astype(float), size=w, mode="nearest")


# Reference P1–P2 separation from a typical good trial (e.g. saved1: ~194 ms). Min separation
# default is 50% of this so P1 and P2 are not too close (noise rejection).
REFERENCE_P1_P2_SEPARATION_MS = 200.0
DEFAULT_MIN_P1_P2_SEPARATION_MS = 80.0  # ~40% of reference; use 100 for ~50%


def detect_peaks_smoothed_then_match(
    force: np.ndarray,
    min_force_index: int,
    takeoff_index: int,
    sample_rate: float = 1000.0,
    min_p1_p2_separation_ms: float = DEFAULT_MIN_P1_P2_SEPARATION_MS,
    min_peak2_force_ratio: float = 0.0,
    smooth_window_ms: float = 15.0,
    refine_window_ms: float = 25.0,
) -> Dict[str, Any]:
    """
    Detect P1 and P2 using a smoothed signal for robustness, then map back to the
    true (original) force so reported indices and values are on the raw chart.

    1. Smooth the segment [min_force, takeoff] with a short moving average (for detection only).
    2. On smoothed segment: find local maxima; P1 = highest, P2 = second-highest that is
       at least min_p1_p2_separation_ms from P1 and (optionally) at least
       min_peak2_force_ratio * P1_force so noise bumps are rejected.
    3. Refine each peak on the original force: in a small window around the detected index,
       take argmax of the original force so the reported peak is the true max on the chart.
    4. Return global indices and use force[P1_index], force[P2_index] from original data.

    Window/threshold: min_p1_p2_separation_ms should be on the order of 40–50% of typical
    P1–P2 distance (e.g. ~200 ms typical → 80–100 ms) to avoid P1 and P2 being too close.

    Returns dict with P1_index, P2_index (global; P2_index may be None).
    """
    start = min_force_index
    end = takeoff_index
    if start >= end or end >= len(force):
        return {"P1_index": None, "P2_index": None}

    seg_orig = force[start : end + 1].astype(float)
    n = len(seg_orig)
    if n == 0:
        return {"P1_index": None, "P2_index": None}
    if n == 1:
        return {"P1_index": int(start), "P2_index": None}

    min_sep_samples = max(1, int(sample_rate * min_p1_p2_separation_ms / 1000.0))
    smooth_win = max(3, int(sample_rate * smooth_window_ms / 1000.0) | 1)
    refine_win = max(1, int(sample_rate * refine_window_ms / 1000.0))

    # 1. Smooth for detection only
    seg_smooth = _smooth_segment(seg_orig, smooth_win)

    # 2. Local maxima on smoothed segment
    local_max = []
    for i in range(n):
        left_ok = i == 0 or seg_smooth[i] >= seg_smooth[i - 1]
        right_ok = i == n - 1 or seg_smooth[i] >= seg_smooth[i + 1]
        if left_ok and right_ok:
            local_max.append(i)

    if not local_max:
        p1_rel = int(np.argmax(seg_smooth))
        p1_refined = _refine_peak_on_original(seg_orig, p1_rel, refine_win)
        return {
            "P1_index": int(start + p1_refined),
            "P2_index": None,
        }

    # Sort by smoothed value descending: P1 = first, P2 = first that passes window + optional force threshold
    local_max.sort(key=lambda i: seg_smooth[i], reverse=True)
    p1_rel_smooth = local_max[0]
    p1_force = float(seg_orig[p1_rel_smooth])
    p2_rel_smooth = None
    for c in local_max[1:]:
        if abs(c - p1_rel_smooth) < min_sep_samples:
            continue
        if min_peak2_force_ratio > 0 and seg_orig[c] < min_peak2_force_ratio * p1_force:
            continue
        p2_rel_smooth = c
        break

    # 3. Refine on original force (match to true chart)
    p1_refined = _refine_peak_on_original(seg_orig, p1_rel_smooth, refine_win)
    p2_refined = _refine_peak_on_original(seg_orig, p2_rel_smooth, refine_win) if p2_rel_smooth is not None else None

    return {
        "P1_index": int(start + p1_refined),
        "P2_index": int(start + p2_refined) if p2_refined is not None else None,
    }


def _refine_peak_on_original(seg_orig: np.ndarray, peak_rel: int, half_win: int) -> int:
    """Return index in [0, len(seg_orig)) where original force is max in [peak_rel - half_win, peak_rel + half_win]."""
    n = len(seg_orig)
    lo = max(0, peak_rel - half_win)
    hi = min(n, peak_rel + half_win + 1)
    sub = seg_orig[lo:hi]
    best = int(np.argmax(sub))
    return lo + best
