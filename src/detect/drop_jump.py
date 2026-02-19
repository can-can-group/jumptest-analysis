"""
Robust event detection for drop jump (DJ) reactive strength tests from raw vertical GRF.

Two test types: High Reactive (fast SSC) and Low Reactive (slow SSC).
Phases: Pre-jump -> Contact (landing -> push-off) -> Flight -> Landing.
Uses slope segmentation and structural peak/valley detection; no smoothing.
Peak identity by temporal/morphological structure, not amplitude.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# Configurable constants (no magic numbers)
# ---------------------------------------------------------------------------
DEFAULT_DROP_LANDING_THRESHOLD_N = 20.0
DEFAULT_CONTACT_SUSTAIN_MS = 10.0
DEFAULT_TAKEOFF_PCT_BW = 0.05
DEFAULT_TAKEOFF_FLOOR_N = 20.0
DEFAULT_SECOND_LANDING_THRESHOLD_N = 200.0
DEFAULT_LANDING_SUSTAIN_MS = 20.0
DEFAULT_PEAK1_WINDOW_MS = 120.0
DEFAULT_PEAK1_PROMINENCE_PCT_BW = 10.0
DEFAULT_PEAK2_PROMINENCE_PCT_BW_MIN = 5.0
DEFAULT_PEAK2_PROMINENCE_PCT_BW_MAX = 10.0
DEFAULT_MIN_VALLEY_AMPLITUDE_PCT_BW = 2.0
DEFAULT_MIN_PEAK_SEPARATION_MS = 15.0
DEFAULT_MIN_RISE_AMPLITUDE_PCT_BW = 3.0
DEFAULT_LANDING_PEAK_WINDOW_MS = 150.0
# Episodes: for grouping only (not biomechanical contact definition). Use low threshold so light athletes / soft landings still get episodes.
DEFAULT_EPISODE_THRESHOLD_N = 30.0
DEFAULT_EPISODE_THRESHOLD_PCT_BW = 0.10
DEFAULT_EPISODE_MIN_DURATION_MS = 40.0
DEFAULT_EPISODE_MIN_PEAK_PCT_BW = 0.35
DEFAULT_EPISODE_FLIGHT_GAP_MS = 50.0
# Pre-contact: first episode only valid if preceded by sustained low force (avoids pre-jump noise)
DEFAULT_PRE_CONTACT_LOW_FORCE_MS = 50.0
DEFAULT_PRE_CONTACT_THRESHOLD_PCT_BW = 0.5
# Peaks (impact, drive-off, landing) must be at or above bodyweight to ignore pre-jump noise
DEFAULT_MIN_PEAK_ABOVE_BW_PCT = 1.0
# Light smoothing for peak/valley detection only (reduces noise spikes)
DEFAULT_PEAK_SMOOTH_WINDOW_MS = 15.0
# Contact start validation: after candidate, force must rise (real landing) not drop (noise)
DEFAULT_CONTACT_START_VALID_WINDOW_MS = 60.0
DEFAULT_CONTACT_START_MIN_MEAN_SLOPE_N_PER_SAMPLE = 0.0  # require mean slope >= this after candidate
DEFAULT_CONTACT_START_MIN_PEAK_IN_WINDOW_PCT_BW = 0.5   # max force in window must be >= this fraction of BW
# Window validation for other points (trajectory after point must match expected shape)
DEFAULT_PEAK_VALID_WINDOW_MS = 40.0       # after a peak, force should decrease (mean slope <= 0)
DEFAULT_VALLEY_VALID_WINDOW_MS = 40.0     # after a valley (CTP), force should increase (mean slope >= 0)
DEFAULT_TAKEOFF_VALID_WINDOW_MS = 30.0    # after take-off, force should stay low
DEFAULT_FLIGHT_LAND_VALID_WINDOW_MS = 50.0  # same idea as contact start: force rises after landing
# Take-off must be at least this long after contact start (avoids impact-phase dips being labeled as take-off)
DEFAULT_MIN_TAKEOFF_AFTER_CONTACT_MS = 80.0
# After take-off (flight), max force in window must stay below this fraction of BW
DEFAULT_TAKEOFF_MAX_FORCE_IN_WINDOW_PCT_BW = 0.45
# Peak impact in first fraction of contact; peak drive-off in last 50% (drive_start = contact_start + peak2_start_fraction * duration)
DEFAULT_PEAK2_START_FRACTION_OF_CONTACT = 0.40
# Start of concentric: slope positive sustained (ms)
DEFAULT_CONCENTRIC_SLOPE_SUSTAIN_MS = 10.0
# DJ classification: contact time threshold (ms) — kept for optional reporting only; classification uses structure + clamped window
DEFAULT_HIGH_REACTIVE_CONTACT_TIME_MS = 250.0
# Rolling window (ms): if 2+ of the four contact-phase points fall inside any window of this length, classify as high reactive (clamped)
DEFAULT_CLAMPED_WINDOW_MS = 50.0
# Peak impact force and peak drive-off force (DJ-specific, not CMJ P1/P2) must be above BW; peak drive-off must be one of the highest in segment
DEFAULT_PEAK2_MIN_FRACTION_OF_SEGMENT_MAX = 0.80
# Contact-phase detection: only consider samples with force >= this fraction of bodyweight (1.0 = BW, 1.30 = 30% above BW)
DEFAULT_CONTACT_ABOVE_BW_PCT = 1.0
# Minimum force for a point to be valid: reject points "at bodyweight level" (e.g. 1.30 = 30% above BW)
DEFAULT_MIN_VALID_FORCE_PCT_BW = 1.30
# Peak impact: validation window (ms) to verify candidate is the highest in neighborhood (reduces noise)
DEFAULT_PEAK_IMPACT_VALIDATION_WINDOW_MS = 50.0
# Impact window as fraction of contact (0.50 = first half); increase to avoid missing late impact peak
DEFAULT_PEAK1_FRACTION_OF_CONTACT = 0.50
# CTP: must be clearly above bodyweight (not a noise dip); require at least this fraction of BW (1.20 = 20% above BW)
DEFAULT_CTP_MIN_FORCE_PCT_BW = 1.10
# CTP: minimum trough depth (fraction of BW) from preceding high to CTP — must be a visible reversal (not noise)
DEFAULT_CTP_MIN_TROUGH_DEPTH_PCT_BW = 0.08
# CTP: window (ms) for slope validation (force down into trough, up out of trough)
DEFAULT_CTP_SLOPE_WINDOW_MS = 50.0
# CTP: candidate must be the minimum in a neighborhood of this size (ms) to reject noise
DEFAULT_CTP_VALIDATION_WINDOW_MS = 30.0
_SLOPE_MARGIN = 2


def _are_contact_points_clamped(
    peak_impact: Optional[int],
    contact_through_point: Optional[int],
    start_of_concentric: Optional[int],
    peak_drive_off: Optional[int],
    sample_rate: float,
    window_ms: float = DEFAULT_CLAMPED_WINDOW_MS,
) -> bool:
    """
    True if contact-phase points are "clamped" (too close in time) = high reactive.
    Uses (1) consecutive gap check: any two consecutive points (in order) < window_ms apart,
    and (2) sliding window: any window of length window_ms contains 2+ points.
    All checks use time in ms to avoid sample-rate rounding issues.
    """
    indices = [i for i in [peak_impact, contact_through_point, start_of_concentric, peak_drive_off] if i is not None]
    if len(indices) < 2:
        return False
    if sample_rate <= 0:
        return False
    # Work in time (ms) for clarity and to avoid rounding
    times_ms = sorted((i * 1000.0 / sample_rate for i in indices))
    # (1) Consecutive gap: if any two consecutive points are closer than window_ms, clamped
    for j in range(len(times_ms) - 1):
        if times_ms[j + 1] - times_ms[j] < window_ms:
            return True
    # (2) Sliding window in time: if any window of length window_ms contains 2+ points, clamped
    step_ms = 1.0  # check every 1 ms
    t_ms = times_ms[0]
    end_ms = times_ms[-1]
    while t_ms <= end_ms:
        window_end_ms = t_ms + window_ms
        count = sum(1 for tm in times_ms if t_ms <= tm <= window_end_ms)
        if count >= 2:
            return True
        t_ms += step_ms
    return False


def _ms_to_samples(ms: float, fs: float) -> int:
    return max(1, int(round(fs * ms / 1000.0)))


def _smooth_for_peaks(force: np.ndarray, fs: float, window_ms: float = DEFAULT_PEAK_SMOOTH_WINDOW_MS) -> np.ndarray:
    """Light low-pass for peak/valley detection only. Returns a copy; use for find_peaks, not for thresholds."""
    try:
        from scipy.signal import savgol_filter
    except ImportError:
        return np.asarray(force, dtype=float)
    n = len(force)
    if n < 10:
        return np.asarray(force, dtype=float)
    w = _ms_to_samples(window_ms, fs)
    w = min(n - 1 if n % 2 == 0 else n, max(5, w | 1))
    if w < 5:
        return np.asarray(force, dtype=float)
    return savgol_filter(force.astype(float), window_length=w, polyorder=3, mode="nearest")


def _first_differences(force: np.ndarray) -> np.ndarray:
    return np.diff(force.astype(float))


def segment_by_slope(force: np.ndarray) -> List[Tuple[int, int, bool]]:
    """Segment force by sign of slope. Returns (start_idx, end_idx, is_rising)."""
    d = _first_differences(force)
    s = np.zeros(len(d), dtype=np.int8)
    s[d > 0] = 1
    s[d < 0] = -1
    out: List[Tuple[int, int, bool]] = []
    i, n = 0, len(s)
    while i < n:
        sign = s[i]
        j = i
        while j < n and s[j] == sign:
            j += 1
        end_force = min(j, len(force) - 1)
        out.append((i, end_force, sign == 1))
        i = j
    return out


def first_crossing_above(
    force: np.ndarray, threshold: float, start: int, end: int, min_samples: int
) -> Optional[int]:
    """First index where force rises above threshold and stays above for min_samples."""
    n = len(force)
    i = max(0, start)
    end = min(end, n - 1)
    while i <= end - min_samples + 1:
        if force[i] > threshold:
            ok = True
            for j in range(i, min(i + min_samples, n)):
                if j >= n or force[j] <= threshold:
                    ok = False
                    break
            if ok:
                return i
        i += 1
    return None


def _contact_start_valid(
    force: np.ndarray,
    candidate_idx: int,
    window_samples: int,
    bw: float,
    min_mean_slope: float = DEFAULT_CONTACT_START_MIN_MEAN_SLOPE_N_PER_SAMPLE,
    min_peak_pct_bw: float = DEFAULT_CONTACT_START_MIN_PEAK_IN_WINDOW_PCT_BW,
) -> bool:
    """
    Validate a candidate contact start by checking the force trajectory *after* the point.
    Real landing: force rises (positive slope) and/or builds to a clear peak above BW.
    Noise: force drops or stays flat after a brief crossing.
    """
    n = len(force)
    end_idx = min(candidate_idx + window_samples, n - 1)
    if end_idx <= candidate_idx + 1:
        return True
    seg = force[candidate_idx : end_idx + 1].astype(float)
    if len(seg) < 2:
        return True
    # Mean slope (N per sample): positive = force rising after contact
    diff = np.diff(seg)
    mean_slope = float(np.mean(diff))
    # Peak in window: must see some loading (e.g. >= 50% BW)
    peak_in_window = float(np.max(seg))
    min_peak = bw * min_peak_pct_bw
    if mean_slope < min_mean_slope:
        return False
    if peak_in_window < min_peak:
        return False
    return True


def _peak_valid_after(
    force: np.ndarray,
    peak_idx: int,
    window_samples: int,
    max_mean_slope: float = 0.0,
) -> bool:
    """After a true peak, force should decrease (mean slope <= 0). Rejects noise spikes."""
    n = len(force)
    end_idx = min(peak_idx + window_samples, n - 1)
    if end_idx <= peak_idx + 1:
        return True
    seg = force[peak_idx : end_idx + 1].astype(float)
    if len(seg) < 2:
        return True
    mean_slope = float(np.mean(np.diff(seg)))
    return mean_slope <= max_mean_slope


def _valley_valid_after(
    force: np.ndarray,
    valley_idx: int,
    window_samples: int,
    min_mean_slope: float = 0.0,
) -> bool:
    """After a true valley (e.g. CTP), force should increase (mean slope >= 0)."""
    n = len(force)
    end_idx = min(valley_idx + window_samples, n - 1)
    if end_idx <= valley_idx + 1:
        return True
    seg = force[valley_idx : end_idx + 1].astype(float)
    if len(seg) < 2:
        return True
    mean_slope = float(np.mean(np.diff(seg)))
    return mean_slope >= min_mean_slope


def _slope_positive_sustained(force: np.ndarray, start: int, sustain_samples: int) -> bool:
    """True if mean slope over [start, start+sustain_samples] is positive (force rising)."""
    n = len(force)
    end = min(start + sustain_samples, n - 1)
    if end <= start + 1:
        return True
    seg = force[start : end + 1].astype(float)
    return float(np.mean(np.diff(seg))) > 0.0


def _takeoff_valid_after(
    force: np.ndarray,
    candidate_idx: int,
    window_samples: int,
    max_mean_force: float,
    max_force_in_window: Optional[float] = None,
) -> bool:
    """After take-off (flight), force should stay low: mean and optionally max below thresholds."""
    n = len(force)
    end_idx = min(candidate_idx + window_samples, n - 1)
    if end_idx <= candidate_idx:
        return True
    seg = force[candidate_idx : end_idx + 1].astype(float)
    if float(np.mean(seg)) > max_mean_force:
        return False
    if max_force_in_window is not None and float(np.max(seg)) > max_force_in_window:
        return False  # must be true flight (no spike), not a brief dip during contact
    return True


def first_crossing_below(
    force: np.ndarray, threshold: float, start: int, end: int, min_samples: int
) -> Optional[int]:
    """First index where force drops below threshold and stays below for min_samples."""
    n = len(force)
    i = max(0, start)
    end = min(end, n - 1)
    while i <= end - min_samples + 1:
        if force[i] < threshold:
            ok = True
            for j in range(i, min(i + min_samples, n)):
                if j >= n or force[j] >= threshold:
                    ok = False
                    break
            if ok:
                return i
        i += 1
    return None


def _slope_before_positive(force: np.ndarray, idx: int) -> bool:
    if idx < _SLOPE_MARGIN:
        return True
    return force[idx] > force[idx - _SLOPE_MARGIN]


def _slope_after_negative(force: np.ndarray, idx: int) -> bool:
    n = len(force)
    if idx + _SLOPE_MARGIN >= n:
        return True
    return force[idx] > force[idx + _SLOPE_MARGIN]


def _slope_before_negative(force: np.ndarray, idx: int) -> bool:
    if idx < _SLOPE_MARGIN:
        return True
    return force[idx] < force[idx - _SLOPE_MARGIN]


def _slope_after_positive(force: np.ndarray, idx: int) -> bool:
    n = len(force)
    if idx + _SLOPE_MARGIN >= n:
        return True
    return force[idx] < force[idx + _SLOPE_MARGIN]


def find_valleys_in_range(
    force: np.ndarray,
    start: int,
    end: int,
    min_prominence: float,
    min_separation_samples: int,
) -> List[Tuple[int, float]]:
    """Local minima in [start,end] with prominence >= min_prominence. Returns (index, value)."""
    if end <= start + 1:
        return []
    seg = force[start : end + 1]
    neg = -seg.astype(float)
    peaks, _ = find_peaks(neg, prominence=min_prominence, distance=min_separation_samples)
    return [(start + int(i), float(force[start + int(i)])) for i in peaks]


def find_peaks_in_range(
    force: np.ndarray,
    start: int,
    end: int,
    min_prominence: float,
    min_separation_samples: int,
    slope_validate: bool = True,
) -> List[int]:
    """Local maxima in [start,end] with prominence; optionally validate slope before/after."""
    if end <= start + 1:
        return []
    seg = force[start : end + 1]
    peaks, _ = find_peaks(seg, prominence=min_prominence, distance=min_separation_samples)
    out: List[int] = []
    for i in peaks:
        idx = start + int(i)
        if slope_validate and not (_slope_before_positive(force, idx) and _slope_after_negative(force, idx)):
            continue
        out.append(idx)
    return out


def impulse_area_above_bw(force: np.ndarray, bw: float, start: int, end: int, dt: float) -> float:
    """Impulse (N·s) = integral of (F - BW) over [start, end]."""
    if start >= end or end >= len(force):
        return 0.0
    seg = force[start : end + 1].astype(float) - bw
    return float(np.sum(seg) * dt)


def _peak_is_max_in_window(force: np.ndarray, peak_idx: int, half_win: int) -> bool:
    """True if force[peak_idx] is the maximum in [peak_idx - half_win, peak_idx + half_win]."""
    n = len(force)
    lo = max(0, peak_idx - half_win)
    hi = min(n - 1, peak_idx + half_win)
    return force[peak_idx] >= float(np.max(force[lo : hi + 1]))


def _valley_is_min_in_window(force: np.ndarray, valley_idx: int, half_win: int) -> bool:
    """True if force[valley_idx] is the minimum in the window around valley_idx."""
    n = len(force)
    lo = max(0, valley_idx - half_win)
    hi = min(n - 1, valley_idx + half_win)
    return force[valley_idx] <= float(np.min(force[lo : hi + 1]))


def _detect_contact_phase_points_above_bw(
    force: np.ndarray,
    contact_start: int,
    contact_end: int,
    bodyweight: float,
    sample_rate: float,
    *,
    above_bw_pct: float = DEFAULT_CONTACT_ABOVE_BW_PCT,
    min_valid_force_pct_bw: float = DEFAULT_MIN_VALID_FORCE_PCT_BW,
    peak1_fraction: float = DEFAULT_PEAK1_FRACTION_OF_CONTACT,
    peak2_start_fraction: float = DEFAULT_PEAK2_START_FRACTION_OF_CONTACT,
    min_peak_separation_samples: int = 5,
    concentric_sustain_ms: float = DEFAULT_CONCENTRIC_SLOPE_SUSTAIN_MS,
    force_smooth: Optional[np.ndarray] = None,
    peak_impact_validation_window_ms: float = DEFAULT_PEAK_IMPACT_VALIDATION_WINDOW_MS,
    ctp_min_force_pct_bw: float = DEFAULT_CTP_MIN_FORCE_PCT_BW,
    ctp_min_trough_depth_pct_bw: float = DEFAULT_CTP_MIN_TROUGH_DEPTH_PCT_BW,
    ctp_slope_window_ms: float = DEFAULT_CTP_SLOPE_WINDOW_MS,
    ctp_validation_window_ms: float = DEFAULT_CTP_VALIDATION_WINDOW_MS,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """
    Detect peak impact, CTP, start of concentric, and peak drive-off with multi-pass validation
    to reduce noise. Peak impact must be the highest point in a neighborhood; CTP must be a
    clear visual trough (depth, slope, and min-in-window checks).
    """
    n = len(force)
    if contact_end <= contact_start + 10:
        return None, None, None, None
    seg_force = force[contact_start : contact_end + 1]
    contact_duration = contact_end - contact_start
    peak1_end_offset = max(1, int(contact_duration * peak1_fraction))
    search_end = min(contact_start + peak1_end_offset, contact_end - 1)
    drive_start_offset = max(0, int(contact_duration * peak2_start_fraction))
    drive_start = contact_start + drive_start_offset
    smooth = force_smooth if force_smooth is not None else force
    concentric_sustain_samples = _ms_to_samples(concentric_sustain_ms, sample_rate)
    min_valid = bodyweight * min_valid_force_pct_bw
    min_ctp_force = bodyweight * ctp_min_force_pct_bw
    min_trough_depth = bodyweight * ctp_min_trough_depth_pct_bw
    peak_impact_half_win = _ms_to_samples(peak_impact_validation_window_ms / 2.0, sample_rate)
    ctp_half_win = _ms_to_samples(ctp_validation_window_ms / 2.0, sample_rate)
    ctp_slope_win = _ms_to_samples(ctp_slope_window_ms, sample_rate)

    # --- Peak impact: use smoothed force for candidates, then validate each is the highest in a neighborhood (raw force)
    peak_impact_idx: Optional[int] = None
    if search_end > contact_start + 2:
        seg_smooth = smooth[contact_start : search_end + 1]
        seg_raw = force[contact_start : search_end + 1]
        prom = max(0.01 * bodyweight, (DEFAULT_PEAK1_PROMINENCE_PCT_BW / 100.0) * bodyweight)
        peaks, _ = find_peaks(seg_smooth, prominence=prom, distance=min_peak_separation_samples)
        candidates = [
            contact_start + int(i) for i in peaks
            if force[contact_start + int(i)] >= min_valid
        ]
        if not candidates:
            above_valid = seg_raw >= min_valid
            if np.any(above_valid):
                candidates = [contact_start + int(np.argmax(np.where(above_valid, seg_raw, -np.inf)))]
        # Sort by raw force descending; validate first that is max in ±validation window
        candidates = sorted(candidates, key=lambda i: force[i], reverse=True)
        for cand in candidates:
            if _peak_is_max_in_window(force, cand, peak_impact_half_win):
                peak_impact_idx = cand
                break
        # Required: always report peak impact if there is any force >= min_valid in impact window (fallback)
        if peak_impact_idx is None and np.any(seg_raw >= min_valid):
            peak_impact_idx = contact_start + int(np.argmax(np.where(seg_raw >= min_valid, seg_raw, -np.inf)))

    # --- CTP: find valley candidates (local minima on smoothed force in trough), validate each: force >= min_ctp_force, depth, min-in-window, slope
    trough_start = (peak_impact_idx if peak_impact_idx is not None else contact_start) + 1
    trough_end = contact_end - 1
    ctp_idx: Optional[int] = None
    if trough_end > trough_start + 4:
        seg_smooth_trough = smooth[trough_start : trough_end + 1]
        # Local minima in trough (peaks of -force)
        valleys, _ = find_peaks(-seg_smooth_trough, prominence=0.02 * bodyweight, distance=min_peak_separation_samples)
        candidates_ctp = [trough_start + int(i) for i in valleys]
        slope_tolerance = 0.5
        for candidate_ctp in sorted(candidates_ctp, key=lambda i: force[i]):
            if force[candidate_ctp] < min_ctp_force:
                continue
            peak_high = float(np.max(force[trough_start : candidate_ctp + 1]))
            depth = peak_high - force[candidate_ctp]
            if depth < min_trough_depth:
                continue
            if not _valley_is_min_in_window(force, candidate_ctp, ctp_half_win):
                continue
            lo_before = max(0, candidate_ctp - ctp_slope_win)
            hi_after = min(n - 1, candidate_ctp + ctp_slope_win)
            if lo_before < candidate_ctp - 1:
                seg_before = force[lo_before : candidate_ctp + 1].astype(float)
                if float(np.mean(np.diff(seg_before))) > slope_tolerance:
                    continue
            if hi_after > candidate_ctp + 1:
                seg_after = force[candidate_ctp : hi_after + 1].astype(float)
                if float(np.mean(np.diff(seg_after))) < -slope_tolerance:
                    continue
            ctp_idx = candidate_ctp
            break
        if ctp_idx is None:
            search_ctp_thresh = bodyweight * 1.0
            above_search = seg_smooth_trough >= search_ctp_thresh
            if np.any(above_search):
                valid_vals = np.where(above_search, seg_smooth_trough, np.inf)
                local_min_smooth = int(np.argmin(valid_vals))
                candidate_ctp = trough_start + local_min_smooth
                if (force[candidate_ctp] >= min_ctp_force
                    and _valley_is_min_in_window(force, candidate_ctp, ctp_half_win)):
                    peak_high = float(np.max(force[trough_start : candidate_ctp + 1]))
                    if peak_high - force[candidate_ctp] >= min_trough_depth:
                        ctp_idx = candidate_ctp

    # --- Start of concentric: must be after peak impact and after CTP (if any). First index where force >= min_valid and sustained positive slope.
    conc_start_search = (ctp_idx + 1) if ctp_idx is not None else (peak_impact_idx + 1 if peak_impact_idx is not None else trough_start)
    if peak_impact_idx is not None and conc_start_search <= peak_impact_idx:
        conc_start_search = peak_impact_idx + 1
    start_of_concentric_idx: Optional[int] = None
    search_limit = contact_end
    for i in range(conc_start_search, search_limit):
        if i + concentric_sustain_samples >= n or i + concentric_sustain_samples > contact_end:
            break
        if force[i] < min_valid:
            continue
        if _slope_positive_sustained(force, i, concentric_sustain_samples):
            start_of_concentric_idx = i
            break

    # --- Peak drive-off: after CTP (or after peak impact if no CTP), last local max with force >= min_valid
    peak_drive_off_idx: Optional[int] = None
    drive_search_start = (ctp_idx + 1) if ctp_idx is not None else (peak_impact_idx + 1 if peak_impact_idx is not None else drive_start)
    if contact_end > drive_search_start + 2:
        seg_drive = smooth[drive_search_start : contact_end]
        prom2 = max(0.01 * bodyweight, (DEFAULT_PEAK2_PROMINENCE_PCT_BW_MIN / 100.0) * bodyweight)
        peaks2, _ = find_peaks(seg_drive, prominence=prom2, distance=min_peak_separation_samples)
        candidates2 = [
            drive_search_start + int(i) for i in peaks2
            if force[drive_search_start + int(i)] >= min_valid
            and _slope_before_positive(smooth, drive_search_start + int(i))
            and _slope_after_negative(smooth, drive_search_start + int(i))
        ]
        if candidates2:
            peak_drive_off_idx = max(candidates2, key=lambda i: i)
        else:
            candidates2_relaxed = [
                drive_search_start + int(i) for i in peaks2
                if force[drive_search_start + int(i)] >= min_valid
            ]
            if candidates2_relaxed:
                peak_drive_off_idx = max(candidates2_relaxed, key=lambda i: i)
            else:
                seg_above_drive = force[drive_search_start : contact_end]
                above_valid_drive = seg_above_drive >= min_valid
                if np.any(above_valid_drive):
                    local_idx = int(np.argmax(np.where(above_valid_drive, seg_above_drive, -np.inf)))
                    peak_drive_off_idx = drive_search_start + local_idx

    # Enforce order: peak_impact < (ctp if any) < start_of_concentric < peak_drive_off
    if peak_impact_idx is not None and peak_impact_idx <= contact_start:
        peak_impact_idx = None
    if ctp_idx is not None and peak_impact_idx is not None and ctp_idx <= peak_impact_idx:
        ctp_idx = None
    if start_of_concentric_idx is not None and peak_impact_idx is not None and start_of_concentric_idx <= peak_impact_idx:
        start_of_concentric_idx = None
    if start_of_concentric_idx is not None and ctp_idx is not None and start_of_concentric_idx <= ctp_idx:
        start_of_concentric_idx = None
    if peak_drive_off_idx is not None:
        if peak_impact_idx is not None and peak_drive_off_idx <= peak_impact_idx:
            peak_drive_off_idx = None
        if ctp_idx is not None and peak_drive_off_idx <= ctp_idx:
            peak_drive_off_idx = None
        if start_of_concentric_idx is not None and peak_drive_off_idx <= start_of_concentric_idx:
            peak_drive_off_idx = None
        elif peak_drive_off_idx >= contact_end:
            peak_drive_off_idx = None
    if peak_impact_idx is not None and ctp_idx is not None and peak_impact_idx >= ctp_idx:
        peak_impact_idx = None
    if peak_impact_idx is not None and peak_drive_off_idx is not None and peak_impact_idx >= peak_drive_off_idx:
        peak_drive_off_idx = None

    if peak_impact_idx is not None and force[peak_impact_idx] < min_valid:
        peak_impact_idx = None
    if ctp_idx is not None and force[ctp_idx] < min_ctp_force:
        ctp_idx = None
    if start_of_concentric_idx is not None and force[start_of_concentric_idx] < min_valid:
        start_of_concentric_idx = None
    if peak_drive_off_idx is not None and force[peak_drive_off_idx] < min_valid:
        peak_drive_off_idx = None

    return peak_impact_idx, ctp_idx, start_of_concentric_idx, peak_drive_off_idx


def _detect_contact_phase_three_peaks(
    force: np.ndarray,
    contact_start: int,
    contact_end: int,
    bodyweight: float,
    sample_rate: float,
    *,
    force_smooth: Optional[np.ndarray] = None,
    min_valid_force_pct_bw: float = DEFAULT_MIN_VALID_FORCE_PCT_BW,
    min_peak_separation_ms: float = DEFAULT_MIN_PEAK_SEPARATION_MS,
    ctp_min_force_pct_bw: float = DEFAULT_CTP_MIN_FORCE_PCT_BW,
) -> Tuple[Optional[int], Optional[int], Optional[int], Optional[int]]:
    """
    Three-peak + one-valley model: Peak1 = peak impact, Peak2 = start of concentric, Peak3 = peak drive-off,
    valley between P1 and P2 = contact through point (CTP).
    """
    n = len(force)
    if contact_end <= contact_start + 10:
        return None, None, None, None
    smooth = force_smooth if force_smooth is not None else force
    min_valid = bodyweight * min_valid_force_pct_bw
    min_ctp_force = bodyweight * ctp_min_force_pct_bw
    min_peak_separation_samples = max(1, _ms_to_samples(min_peak_separation_ms, sample_rate))
    prom = max(0.01 * bodyweight, (DEFAULT_PEAK1_PROMINENCE_PCT_BW / 100.0) * bodyweight)

    # Step 1: Find all peaks in contact segment (smoothed), force >= min_valid, then take first three by time
    seg_smooth = smooth[contact_start : contact_end]
    seg_force = force[contact_start : contact_end]
    peaks, _ = find_peaks(seg_smooth, prominence=prom, distance=min_peak_separation_samples)
    peak_indices = [
        contact_start + int(i)
        for i in peaks
        if force[contact_start + int(i)] >= min_valid
    ]
    peak_indices.sort()
    peak_impact_idx: Optional[int] = peak_indices[0] if len(peak_indices) >= 1 else None
    start_of_concentric_idx: Optional[int] = peak_indices[1] if len(peak_indices) >= 2 else None
    peak_drive_off_idx: Optional[int] = peak_indices[2] if len(peak_indices) >= 3 else None

    # Step 2: Valley (CTP) strictly between P1 and P2, force >= min_ctp_force
    ctp_idx: Optional[int] = None
    if peak_impact_idx is not None and start_of_concentric_idx is not None and start_of_concentric_idx > peak_impact_idx + 1:
        between_start = peak_impact_idx + 1
        between_end = start_of_concentric_idx - 1
        seg_between = force[between_start : between_end + 1]
        above_ctp = seg_between >= min_ctp_force
        if np.any(above_ctp):
            local_idx = int(np.argmin(np.where(above_ctp, seg_between, np.inf)))
            ctp_idx = between_start + local_idx
        else:
            # No sample >= min_ctp_force; take global min in range if force at min >= BW
            min_idx = between_start + int(np.argmin(seg_between))
            if force[min_idx] >= bodyweight:
                ctp_idx = min_idx

    # Post-checks: force at each point must meet minimums
    if peak_impact_idx is not None and force[peak_impact_idx] < min_valid:
        peak_impact_idx = None
    if ctp_idx is not None and force[ctp_idx] < min_ctp_force:
        ctp_idx = None
    if start_of_concentric_idx is not None and force[start_of_concentric_idx] < min_valid:
        start_of_concentric_idx = None
    if peak_drive_off_idx is not None and force[peak_drive_off_idx] < min_valid:
        peak_drive_off_idx = None

    return peak_impact_idx, ctp_idx, start_of_concentric_idx, peak_drive_off_idx


def _had_pre_contact_low_force(
    force: np.ndarray,
    episode_start: int,
    bw: float,
    low_force_pct_bw: float,
    min_duration_samples: int,
) -> bool:
    """True if before episode_start there were at least min_duration_samples with force < low_force_pct_bw * bw."""
    if episode_start <= 0 or min_duration_samples <= 0:
        return True
    thresh = low_force_pct_bw * bw
    start = max(0, episode_start - min_duration_samples * 3)
    run = 0
    for i in range(episode_start - 1, start - 1, -1):
        if i < 0:
            break
        if force[i] < thresh:
            run += 1
            if run >= min_duration_samples:
                return True
        else:
            run = 0
    return run >= min_duration_samples


def _find_contact_episodes(
    force: np.ndarray,
    fs: float,
    bw: float,
    episode_threshold_n: float,
    episode_threshold_pct_bw: float,
    min_duration_samples: int,
    min_peak_pct_bw: float,
    flight_gap_ms: float,
    pre_contact_low_force_ms: float = DEFAULT_PRE_CONTACT_LOW_FORCE_MS,
    pre_contact_threshold_pct_bw: float = DEFAULT_PRE_CONTACT_THRESHOLD_PCT_BW,
) -> List[Tuple[int, int]]:
    """First two contact episodes: high-force regions separated by flight_gap_ms of low force.
    First episode is only accepted if preceded by sustained low force (pre-jump / flight).
    """
    n = len(force)
    thresh = max(episode_threshold_n, episode_threshold_pct_bw * bw)
    min_peak = min_peak_pct_bw * bw
    gap_samples = max(1, _ms_to_samples(flight_gap_ms, fs))
    pre_contact_samples = _ms_to_samples(pre_contact_low_force_ms, fs)
    episodes: List[Tuple[int, int]] = []
    i = 0
    cur_start: Optional[int] = None
    cur_end: Optional[int] = None
    while i < n and len(episodes) < 2:
        if force[i] > thresh:
            if cur_start is None:
                cur_start = i
            cur_end = i
            i += 1
            continue
        if cur_start is not None and cur_end is not None:
            gap_len = 0
            j = i
            while j < n and force[j] <= thresh and gap_len < gap_samples:
                gap_len += 1
                j += 1
            if gap_len >= gap_samples:
                dur = cur_end - cur_start + 1
                if dur >= min_duration_samples:
                    peak = float(np.max(force[cur_start : cur_end + 1]))
                    if peak >= min_peak:
                        is_first = len(episodes) == 0
                        if is_first:
                            if _had_pre_contact_low_force(
                                force, cur_start, bw,
                                pre_contact_threshold_pct_bw, pre_contact_samples,
                            ):
                                episodes.append((cur_start, cur_end))
                        else:
                            episodes.append((cur_start, cur_end))
                cur_start = None
                cur_end = None
                i = j
            else:
                i = j
        else:
            i += 1
    if len(episodes) < 2 and cur_start is not None and cur_end is not None:
        dur = cur_end - cur_start + 1
        if dur >= min_duration_samples:
            peak = float(np.max(force[cur_start : cur_end + 1]))
            if peak >= min_peak and (not episodes or (cur_start, cur_end) != episodes[-1]):
                is_first = len(episodes) == 0
                if is_first:
                    if _had_pre_contact_low_force(
                        force, cur_start, bw,
                        pre_contact_threshold_pct_bw, pre_contact_samples,
                    ):
                        episodes.append((cur_start, cur_end))
                else:
                    episodes.append((cur_start, cur_end))
    return episodes


@dataclass
class DropJumpPhases:
    contact_start: Optional[int] = None
    contact_end: Optional[int] = None
    flight_start: Optional[int] = None
    flight_end: Optional[int] = None
    landing_start: Optional[int] = None
    landing_end: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact_start": self.contact_start,
            "contact_end": self.contact_end,
            "flight_start": self.flight_start,
            "flight_end": self.flight_end,
            "landing_start": self.landing_start,
            "landing_end": self.landing_end,
        }


@dataclass
class DropJumpPoints:
    drop_landing: Optional[int] = None
    peak_impact_force: Optional[int] = None
    contact_through_point: Optional[int] = None
    start_of_concentric: Optional[int] = None
    peak_drive_off_force: Optional[int] = None
    take_off: Optional[int] = None
    flight_land: Optional[int] = None
    peak_landing_force: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drop_landing": self.drop_landing,
            "peak_impact_force": self.peak_impact_force,
            "contact_through_point": self.contact_through_point,
            "start_of_concentric": self.start_of_concentric,
            "peak_drive_off_force": self.peak_drive_off_force,
            "take_off": self.take_off,
            "flight_land": self.flight_land,
            "peak_landing_force": self.peak_landing_force,
        }


def detect_drop_jump_events(
    force: np.ndarray,
    sample_rate: float,
    bodyweight: float,
    *,
    drop_landing_threshold_n: float = DEFAULT_DROP_LANDING_THRESHOLD_N,
    contact_sustain_ms: float = DEFAULT_CONTACT_SUSTAIN_MS,
    takeoff_pct_bw: float = DEFAULT_TAKEOFF_PCT_BW,
    takeoff_floor_n: float = DEFAULT_TAKEOFF_FLOOR_N,
    second_landing_threshold_n: float = DEFAULT_SECOND_LANDING_THRESHOLD_N,
    landing_sustain_ms: float = DEFAULT_LANDING_SUSTAIN_MS,
    peak1_window_ms: float = DEFAULT_PEAK1_WINDOW_MS,
    peak1_prominence_pct_bw: float = DEFAULT_PEAK1_PROMINENCE_PCT_BW,
    peak2_prominence_pct_bw_min: float = DEFAULT_PEAK2_PROMINENCE_PCT_BW_MIN,
    peak2_prominence_pct_bw_max: float = DEFAULT_PEAK2_PROMINENCE_PCT_BW_MAX,
    min_valley_amplitude_pct_bw: float = DEFAULT_MIN_VALLEY_AMPLITUDE_PCT_BW,
    min_peak_separation_ms: float = DEFAULT_MIN_PEAK_SEPARATION_MS,
    min_rise_amplitude_pct_bw: float = DEFAULT_MIN_RISE_AMPLITUDE_PCT_BW,
    landing_peak_window_ms: float = DEFAULT_LANDING_PEAK_WINDOW_MS,
    episode_threshold_n: float = DEFAULT_EPISODE_THRESHOLD_N,
    episode_threshold_pct_bw: float = DEFAULT_EPISODE_THRESHOLD_PCT_BW,
    episode_min_duration_ms: float = DEFAULT_EPISODE_MIN_DURATION_MS,
    episode_min_peak_pct_bw: float = DEFAULT_EPISODE_MIN_PEAK_PCT_BW,
    episode_flight_gap_ms: float = DEFAULT_EPISODE_FLIGHT_GAP_MS,
    pre_contact_low_force_ms: float = DEFAULT_PRE_CONTACT_LOW_FORCE_MS,
    pre_contact_threshold_pct_bw: float = DEFAULT_PRE_CONTACT_THRESHOLD_PCT_BW,
    min_peak_above_bw_pct: float = DEFAULT_MIN_PEAK_ABOVE_BW_PCT,
    peak_smooth_window_ms: float = DEFAULT_PEAK_SMOOTH_WINDOW_MS,
    contact_start_valid_window_ms: float = DEFAULT_CONTACT_START_VALID_WINDOW_MS,
    contact_start_min_mean_slope: float = DEFAULT_CONTACT_START_MIN_MEAN_SLOPE_N_PER_SAMPLE,
    contact_start_min_peak_in_window_pct_bw: float = DEFAULT_CONTACT_START_MIN_PEAK_IN_WINDOW_PCT_BW,
    peak_valid_window_ms: float = DEFAULT_PEAK_VALID_WINDOW_MS,
    valley_valid_window_ms: float = DEFAULT_VALLEY_VALID_WINDOW_MS,
    takeoff_valid_window_ms: float = DEFAULT_TAKEOFF_VALID_WINDOW_MS,
    flight_land_valid_window_ms: float = DEFAULT_FLIGHT_LAND_VALID_WINDOW_MS,
    min_takeoff_after_contact_ms: float = DEFAULT_MIN_TAKEOFF_AFTER_CONTACT_MS,
    takeoff_max_force_in_window_pct_bw: float = DEFAULT_TAKEOFF_MAX_FORCE_IN_WINDOW_PCT_BW,
    peak1_fraction_of_contact: float = DEFAULT_PEAK1_FRACTION_OF_CONTACT,
    peak2_start_fraction_of_contact: float = DEFAULT_PEAK2_START_FRACTION_OF_CONTACT,
    peak2_min_fraction_of_segment_max: float = DEFAULT_PEAK2_MIN_FRACTION_OF_SEGMENT_MAX,
    concentric_slope_sustain_ms: float = DEFAULT_CONCENTRIC_SLOPE_SUSTAIN_MS,
    contact_above_bw_pct: float = DEFAULT_CONTACT_ABOVE_BW_PCT,
    min_valid_force_pct_bw: float = DEFAULT_MIN_VALID_FORCE_PCT_BW,
    peak_impact_validation_window_ms: float = DEFAULT_PEAK_IMPACT_VALIDATION_WINDOW_MS,
    ctp_min_force_pct_bw: float = DEFAULT_CTP_MIN_FORCE_PCT_BW,
    ctp_min_trough_depth_pct_bw: float = DEFAULT_CTP_MIN_TROUGH_DEPTH_PCT_BW,
    ctp_slope_window_ms: float = DEFAULT_CTP_SLOPE_WINDOW_MS,
    ctp_validation_window_ms: float = DEFAULT_CTP_VALIDATION_WINDOW_MS,
) -> Tuple[DropJumpPoints, DropJumpPhases]:
    """
    Detect all DJ key points and phase boundaries from raw vertical GRF.
    Uses two-phase logic: find contact episodes first so pre-jump is never contact.
    Peaks (impact, drive-off, landing) are required to be >= bodyweight to avoid pre-jump noise.
    Optional light smoothing is applied for peak/valley detection only.
    Returns (points, phases).
    """
    force = np.asarray(force, dtype=float)
    n = len(force)
    dt = 1.0 / sample_rate if sample_rate > 0 else 0.0
    points = DropJumpPoints()
    phases = DropJumpPhases()
    if n < 10 or sample_rate <= 0 or bodyweight <= 0:
        return points, phases

    sustain = _ms_to_samples(contact_sustain_ms, sample_rate)
    ep_min = _ms_to_samples(episode_min_duration_ms, sample_rate)
    peak1_win = _ms_to_samples(peak1_window_ms, sample_rate)
    land_win = _ms_to_samples(landing_peak_window_ms, sample_rate)
    min_sep = max(1, _ms_to_samples(min_peak_separation_ms, sample_rate))
    takeoff_thresh = max(takeoff_floor_n, takeoff_pct_bw * bodyweight)
    min_peak_force = bodyweight * min_peak_above_bw_pct
    if min_peak_force <= 0:
        min_peak_force = bodyweight

    force_smooth = _smooth_for_peaks(force, sample_rate, peak_smooth_window_ms)

    episodes = _find_contact_episodes(
        force, sample_rate, bodyweight,
        episode_threshold_n=episode_threshold_n,
        episode_threshold_pct_bw=episode_threshold_pct_bw,
        min_duration_samples=ep_min,
        min_peak_pct_bw=episode_min_peak_pct_bw,
        flight_gap_ms=episode_flight_gap_ms,
        pre_contact_low_force_ms=pre_contact_low_force_ms,
        pre_contact_threshold_pct_bw=pre_contact_threshold_pct_bw,
    )
    if not episodes:
        return points, phases
    ep1_start, ep1_end = episodes[0]

    # Contact start: first *valid* sustained crossing. Valid = force trajectory after candidate
    # rises (positive slope) and builds to a peak >= min_peak_pct_bw * BW (real landing, not noise).
    search_back = _ms_to_samples(150.0, sample_rate)
    search_start = max(0, ep1_start - search_back)
    search_end = min(ep1_end + 1, n - 1)
    valid_window_samples = _ms_to_samples(contact_start_valid_window_ms, sample_rate)
    peak_valid_samples = _ms_to_samples(peak_valid_window_ms, sample_rate)
    valley_valid_samples = _ms_to_samples(valley_valid_window_ms, sample_rate)
    takeoff_valid_samples = _ms_to_samples(takeoff_valid_window_ms, sample_rate)
    flight_land_valid_samples = _ms_to_samples(flight_land_valid_window_ms, sample_rate)

    candidates: List[int] = []
    pos = search_start
    while pos <= search_end:
        c = first_crossing_above(force, drop_landing_threshold_n, pos, search_end, sustain)
        if c is None:
            break
        candidates.append(c)
        pos = c + 1

    contact_start: Optional[int] = None
    for c in candidates:
        if _contact_start_valid(
            force, c, valid_window_samples, bodyweight,
            min_mean_slope=contact_start_min_mean_slope,
            min_peak_pct_bw=contact_start_min_peak_in_window_pct_bw,
        ):
            contact_start = c
            break
    if contact_start is None:
        contact_start = candidates[0] if candidates else ep1_start
    points.drop_landing = contact_start
    phases.contact_start = contact_start

    # Take-off: first *valid* sustained below threshold after a minimum delay from contact start
    # (avoids impact-phase dips). After candidate, force must stay low (true flight).
    min_takeoff_after_samples = _ms_to_samples(min_takeoff_after_contact_ms, sample_rate)
    takeoff_candidates: List[int] = []
    pos = contact_start + 1
    while pos < n - 1:
        c = first_crossing_below(force, takeoff_thresh, pos, n - 1, sustain)
        if c is None:
            break
        takeoff_candidates.append(c)
        pos = c + 1
    # Ignore candidates too close to contact start (must be past impact phase)
    takeoff_candidates = [c for c in takeoff_candidates if c >= contact_start + min_takeoff_after_samples]
    take_off = None
    takeoff_max_mean = takeoff_thresh * 2.0
    takeoff_max_in_window = bodyweight * takeoff_max_force_in_window_pct_bw  # flight: no spike
    for c in takeoff_candidates:
        if _takeoff_valid_after(
            force, c, takeoff_valid_samples, takeoff_max_mean, max_force_in_window=takeoff_max_in_window
        ):
            take_off = c
            break
    if take_off is None and takeoff_candidates:
        # Fallback: use last crossing below in the episode (real take-off is last time leaving ground)
        take_off = max(takeoff_candidates)
    if take_off is None:
        # No candidate past min delay: use last crossing below in first episode (real take-off)
        all_below = []
        pos = contact_start + 1
        while pos < n - 1:
            c = first_crossing_below(force, takeoff_thresh, pos, n - 1, sustain)
            if c is None:
                break
            all_below.append(c)
            pos = c + 1
        # Prefer last crossing within first episode so we don't take landing as take-off
        in_ep1 = [c for c in all_below if c <= ep1_end]
        take_off = max(in_ep1) if in_ep1 else (max(all_below) if all_below else None)
    # Do NOT fabricate take-off. If none found, return early (no peak impact / CTP / peak drive-off).
    points.take_off = take_off
    phases.contact_end = take_off
    phases.flight_start = take_off
    if take_off is None:
        return points, phases

    contact_end = take_off  # type: int

    # Detect peak impact, CTP, start of concentric, peak drive-off: three-peak + one-valley model.
    peak_impact_idx, ctp, start_of_conc, peak_drive_off_idx = _detect_contact_phase_three_peaks(
        force,
        contact_start,
        contact_end,
        bodyweight,
        sample_rate,
        force_smooth=force_smooth,
        min_valid_force_pct_bw=min_valid_force_pct_bw,
        min_peak_separation_ms=min_peak_separation_ms,
        ctp_min_force_pct_bw=ctp_min_force_pct_bw,
    )
    points.peak_impact_force = peak_impact_idx
    points.contact_through_point = ctp
    points.start_of_concentric = start_of_conc
    points.peak_drive_off_force = peak_drive_off_idx

    # Landing peak: must be local maximum with negative slope after, force >= BW, within window of second contact
    def _landing_peak_local_max(start: int, end: int) -> Optional[int]:
        if end <= start + 2:
            return None
        seg = force[start : end + 1].astype(float)
        peaks, _ = find_peaks(seg, prominence=(0.05 * bodyweight), width=1)
        candidates = [start + int(idx) for idx in peaks if force[start + int(idx)] >= min_peak_force]
        valid = [i for i in candidates if _peak_valid_after(force, i, peak_valid_samples, max_mean_slope=0.0)]
        if not valid:
            return None
        return max(valid, key=lambda i: force[i])

    if len(episodes) >= 2:
        ep2_start, _ = episodes[1]
        # Validate second landing: force should rise after contact (same as contact_start)
        if _contact_start_valid(
            force, ep2_start, flight_land_valid_samples, bodyweight,
            min_mean_slope=contact_start_min_mean_slope,
            min_peak_pct_bw=contact_start_min_peak_in_window_pct_bw,
        ):
            points.flight_land = ep2_start
        else:
            points.flight_land = ep2_start  # fallback: use episode start anyway
        phases.flight_end = points.flight_land
        phases.landing_start = points.flight_land
        phases.landing_end = n - 1
        end_land = min((points.flight_land or ep2_start) + land_win, n - 1)
        land_start = points.flight_land or ep2_start
        if end_land > land_start:
            points.peak_landing_force = _landing_peak_local_max(land_start, end_land)
    else:
        # Collect landing candidates and take first valid (force rises after contact)
        land_sustain = _ms_to_samples(landing_sustain_ms, sample_rate)
        land_candidates: List[Optional[int]] = []
        pos = take_off + 1
        while pos < n - 1:
            c = first_crossing_above(force, second_landing_threshold_n, pos, n - 1, land_sustain)
            if c is None:
                break
            land_candidates.append(c)
            pos = c + 1
        second_land = None
        for c in land_candidates:
            if c is not None and _contact_start_valid(
                force, c, flight_land_valid_samples, bodyweight,
                min_mean_slope=contact_start_min_mean_slope,
                min_peak_pct_bw=contact_start_min_peak_in_window_pct_bw,
            ):
                second_land = c
                break
        if second_land is None and land_candidates:
            second_land = land_candidates[0]
        points.flight_land = second_land
        phases.flight_end = second_land
        phases.landing_start = second_land
        phases.landing_end = n - 1
        if second_land is not None:
            end_land = min(second_land + land_win, n - 1)
            if end_land > second_land:
                points.peak_landing_force = _landing_peak_local_max(second_land, end_land)

    if points.flight_land is not None and points.peak_landing_force is not None and points.peak_landing_force < points.flight_land:
        points.peak_landing_force = None
    if points.peak_landing_force is not None and force[points.peak_landing_force] < bodyweight:
        points.peak_landing_force = None

    return points, phases


def compute_dj_metrics(
    force: np.ndarray,
    sample_rate: float,
    bodyweight: float,
    points: DropJumpPoints,
    phases: DropJumpPhases,
    *,
    high_reactive_contact_time_ms: float = DEFAULT_HIGH_REACTIVE_CONTACT_TIME_MS,
    clamped_window_ms: float = DEFAULT_CLAMPED_WINDOW_MS,
) -> Dict[str, Any]:
    """
    Compute braking/propulsive impulse, max RFD, contact time, flight time, jump height, RSI,
    peak forces, phase durations, and DJ classification.
    Returns dict with all DJ metrics; new keys: flight_time_s, jump_height_flight_m, rsi_dj,
    peak_impact_force_N, peak_drive_off_force_N, braking_duration_ms, propulsive_duration_ms.
    Classification uses three-peak structure + rolling window.
    """
    n = len(force)
    dt = 1.0 / sample_rate if sample_rate > 0 else 0.0
    G = 9.81
    out: Dict[str, Any] = {
        "braking_impulse_Ns": None,
        "propulsive_impulse_Ns": None,
        "max_rfd_braking_N_s": None,
        "max_rfd_propulsive_N_s": None,
        "contact_time_ms": None,
        "flight_time_s": None,
        "jump_height_flight_m": None,
        "rsi_dj": None,
        "peak_impact_force_N": None,
        "peak_drive_off_force_N": None,
        "braking_duration_ms": None,
        "propulsive_duration_ms": None,
        "dj_classification": "unknown",
    }
    cs = points.drop_landing
    ctp = points.contact_through_point
    to = points.take_off
    fl_land = points.flight_land
    if cs is None or to is None:
        return out
    contact_time_samples = to - cs
    contact_time_s = contact_time_samples / sample_rate
    out["contact_time_ms"] = round(1000.0 * contact_time_s, 2)

    # Flight time and jump height (from take-off to flight land)
    if to is not None and fl_land is not None and fl_land > to and sample_rate > 0:
        flight_samples = fl_land - to
        out["flight_time_s"] = round(flight_samples / sample_rate, 4)
        t_flight = out["flight_time_s"]
        out["jump_height_flight_m"] = round(G * (t_flight ** 2) / 8.0, 4)
    if out["jump_height_flight_m"] is not None and contact_time_s > 0:
        out["rsi_dj"] = round(out["jump_height_flight_m"] / contact_time_s, 4)

    # Peak impact and drive-off force (N)
    if points.peak_impact_force is not None and 0 <= points.peak_impact_force < n:
        out["peak_impact_force_N"] = round(float(force[points.peak_impact_force]), 1)
    if points.peak_drive_off_force is not None and 0 <= points.peak_drive_off_force < n:
        out["peak_drive_off_force_N"] = round(float(force[points.peak_drive_off_force]), 1)

    # Braking and propulsive phase durations (ms)
    if ctp is not None and cs is not None and ctp > cs and sample_rate > 0:
        out["braking_duration_ms"] = round(1000.0 * (ctp - cs) / sample_rate, 2)
    if ctp is not None and to is not None and to > ctp and sample_rate > 0:
        out["propulsive_duration_ms"] = round(1000.0 * (to - ctp) / sample_rate, 2)

    if ctp is not None and cs is not None and ctp > cs:
        out["braking_impulse_Ns"] = round(
            impulse_area_above_bw(force, bodyweight, cs, ctp, dt), 4
        )
    if ctp is not None and to is not None and to > ctp:
        out["propulsive_impulse_Ns"] = round(
            impulse_area_above_bw(force, bodyweight, ctp, to, dt), 4
        )

    if n < 2 or dt <= 0:
        return out
    dF = np.diff(force.astype(float)) / dt  # RFD = dF/dt (N/s)
    if cs is not None and ctp is not None and ctp > cs + 1:
        seg_rfd = dF[cs : ctp]
        if len(seg_rfd) > 0:
            out["max_rfd_braking_N_s"] = round(float(np.max(seg_rfd)), 2)
    if ctp is not None and to is not None and to > ctp + 1:
        seg_rfd = dF[ctp : to]
        if len(seg_rfd) > 0:
            out["max_rfd_propulsive_N_s"] = round(float(np.max(seg_rfd)), 2)

    # Classification: three-peak structure + rolling window (clamped = high reactive)
    p1 = points.peak_impact_force
    p2 = points.start_of_concentric
    p3 = points.peak_drive_off_force
    order_ok = (
        p1 is not None and p2 is not None and p3 is not None
        and p1 < p2 < p3
        and (ctp is None or (p1 < ctp < p2))
    )
    is_clamped = _are_contact_points_clamped(
        p1, ctp, p2, p3, sample_rate, window_ms=clamped_window_ms
    )
    if order_ok and not is_clamped:
        out["dj_classification"] = "low_reactive"
    elif p1 is not None or ctp is not None or p2 is not None or p3 is not None:
        # At least one point found but order wrong or clamped -> high reactive
        out["dj_classification"] = "high_reactive"
    return out


def detect_reactive_strength_points(
    force: np.ndarray,
    sample_rate: float,
    bodyweight: float,
    high_reactive: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Returns dict with points, phases, impulses, RFD, and dj_classification."""
    points, phases = detect_drop_jump_events(force, sample_rate, bodyweight, **kwargs)
    metrics = compute_dj_metrics(force, sample_rate, bodyweight, points, phases)
    out: Dict[str, Any] = {
        "points": points.to_dict(),
        "phases": phases.to_dict(),
        **metrics,
    }
    if high_reactive:
        out["high_reactive"] = True
    return out


def detect_drop_jump_vgrf(
    force: np.ndarray,
    fs: float,
    bw: float,
    **kwargs: Any,
) -> Dict[str, Optional[int]]:
    """
    vGRF-style output: contact_start_index, peak_impact_force_index (DJ impact peak),
    contact_trough_index (CTP), peak_drive_off_force_index (DJ drive-off peak),
    takeoff_index, landing_contact_index, landing_peak_index.
    Keys kept as peak1_index/peak2_index for compatibility; these are DJ peak impact and peak drive-off, not CMJ P1/P2.
    """
    points, phases = detect_drop_jump_events(force, fs, bw, **kwargs)
    return {
        "contact_start_index": points.drop_landing,
        "peak1_index": points.peak_impact_force,  # DJ peak impact force
        "contact_trough_index": points.contact_through_point,
        "peak2_index": points.peak_drive_off_force,  # DJ peak drive-off force
        "takeoff_index": points.take_off,
        "landing_contact_index": points.flight_land,
        "landing_peak_index": points.peak_landing_force,
    }


def plot_drop_jump_debug(
    force: np.ndarray,
    fs: float,
    events: Dict[str, Optional[int]],
    bw: Optional[float] = None,
    contact_threshold_n: float = DEFAULT_DROP_LANDING_THRESHOLD_N,
    title: str = "Drop Jump vGRF – detected events",
    ax: Any = None,
) -> Any:
    """Plot force and event markers. Returns matplotlib axes. For headless use set matplotlib.use('Agg') before importing pyplot."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("matplotlib is required for plot_drop_jump_debug")
    n = len(force)
    t = np.arange(n, dtype=float) / fs if fs > 0 else np.arange(n, dtype=float)
    if ax is None:
        _, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.plot(t, force, color="k", linewidth=1.2, label="vGRF")
    ax.axhline(contact_threshold_n, color="gray", linestyle="--", linewidth=1, label="Contact thresh")
    if bw is not None and bw > 0:
        ax.axhline(bw, color="green", linestyle=":", linewidth=1, label="Bodyweight")
    labels = [
        ("contact_start_index", "Contact start", "blue", "o"),
        ("peak1_index", "Peak impact force", "red", "v"),
        ("contact_trough_index", "CTP (valley)", "purple", "s"),
        ("peak2_index", "Peak drive-off force", "orange", "v"),
        ("takeoff_index", "Takeoff", "green", "x"),
        ("landing_contact_index", "Flight land", "teal", "o"),
        ("landing_peak_index", "Landing peak", "brown", "D"),
    ]
    for key, label, color, marker in labels:
        idx = events.get(key)
        if idx is not None and 0 <= idx < n:
            ax.plot(t[idx], force[idx], color=color, marker=marker, markersize=10, label=label, zorder=5)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)
    return ax
