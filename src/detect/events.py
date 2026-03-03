"""Take-off, landing, movement onset, and min-force detection."""
from typing import List, Optional, Tuple

import numpy as np

from ..data.types import CMJTrial, CMJEvents

DEFAULT_TAKE_OFF_THRESHOLD_N = 20.0
DEFAULT_LANDING_THRESHOLD_N = 200.0
FLIGHT_THRESHOLD_PCT_BW = 0.04   # 4% BW = flight; plates that don't read zero still work
MIN_FLIGHT_DURATION_MS = 25.0
ONSET_BELOW_BW = 0.05
ONSET_N_SIGMA = 5.0
ONSET_SUSTAIN_MS = 30.0
# Onset/min_force: anchor to the real unweighting dip (before concentric push), not the dip right before take_off
# Prefer: concentric_peak = max(force) in last CONCENTRIC_SEARCH_BEFORE_TAKEOFF_S before take_off; if > BW then
#   min_force = argmin(force) in [window_start, concentric_peak] (eccentric dip before push)
CONCENTRIC_SEARCH_BEFORE_TAKEOFF_S = 0.5  # find concentric peak in this window before take_off
ONSET_WINDOW_BEFORE_TAKEOFF_S = 5.0       # large window before take_off for search
ONSET_MIN_DIP_DEPTH_PCT_BW = 0.02         # dip must drop at least this below BW to count as real (reject tiny wobbles)
LANDING_SUSTAIN_MS = 20.0
TAKE_OFF_CONSECUTIVE_SAMPLES = 4
TAKE_OFF_SEARCH_WINDOW_MS = 25.0
FLIGHT_SEARCH_START_S = 0.6
# Plausible CMJ flight duration (s) – used to score and accept candidates
FLIGHT_DURATION_MIN_S = 0.01   # 10 ms; accept very short flights from noisy plates
FLIGHT_DURATION_MAX_S = 1.5
FLIGHT_DURATION_TYPICAL_MIN_S = 0.05
FLIGHT_DURATION_TYPICAL_MAX_S = 0.95
# Landing: adaptive – first contact when force rises. Use lower % for uncalibrated plates.
LANDING_CONTACT_PCT_BW = 0.10
LANDING_CONTACT_PCT_BW_STRICT = 0.18  # fallback if 10% would be too early
# Don't set landing closer than this (ms) to take_off; keep run_end if refinement would be too early
LANDING_MIN_AFTER_TAKEOFF_MS = 20.0
# Max mean force in flight segment to accept (relaxed for uncalibrated/noisy data)
FLIGHT_MEAN_F_MAX_PCT_BW = 0.70
# Preferred: takeoff/landing from segment with lowest values (closest to zero)
FLIGHT_MEAN_F_PREFERRED_PCT_BW = 0.30  # prefer mean < 30% BW
FLIGHT_MEAN_F_ABSOLUTE_MAX_PCT_BW = 0.40  # never accept mean > 40% BW (not flight)
# Expand flight segment to full dip: left to waterfall, right to rising wall (below this % BW)
FLIGHT_DIP_EXPAND_PCT_BW = 0.45
# Flight line: mean of flight segment, moved up; takeoff/landing = points ON the line (same force band)
FLIGHT_LINE_PCT_ABOVE = 0.50  # move line up 50% above mean
FLIGHT_LINE_MAX_PCT_BW = 0.50  # cap line at 50% bodyweight so we stay in the dip region
# Band around line: only indices where force is within this % of line_value count as "on the line"
FLIGHT_LINE_TOLERANCE_PCT = 0.08  # ±8% so takeoff and landing have almost the same force; 5% was too strict for noisy data
# Rolling window (ms) for smoothing when finding band crossings — avoids noise clamping takeoff/landing
FLIGHT_LINE_ROLLING_WINDOW_MS = 30.0
# Minimum time (ms) between takeoff and landing so they are not clamped next to each other (robust for real CMJ flight)
MIN_FLIGHT_GAP_MS = 150.0


def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean with same length as arr; edges use partial windows."""
    if window <= 1 or len(arr) == 0:
        return arr.copy()
    pad = window // 2
    padded = np.pad(arr.astype(float), (pad, window - pad - 1), mode="edge")
    out = np.convolve(padded, np.ones(window) / window, mode="valid")
    return out[: len(arr)]


def _refine_takeoff_landing_to_mean_line_crossings(
    force: np.ndarray,
    take_off: int,
    landing: int,
    concentric_peak_idx: int,
    bodyweight: float,
    sample_rate: Optional[float] = None,
) -> Tuple[int, int, Optional[float]]:
    """Set takeoff and landing to points ON the flight line (same force band), not in the middle of
    waterfall or rising wall. Uses optional rolling-window smoothing so values are not clamped.
    Flight line = mean(segment) + 50%, capped at 50% BW and >= 0. Returns (take_off, landing, line_value or None).
    """
    n = len(force)
    if take_off >= landing or landing >= n:
        return take_off, landing, None
    mean_flight = float(np.mean(force[take_off : landing + 1]))
    line_value = mean_flight * (1.0 + FLIGHT_LINE_PCT_ABOVE)
    max_line = FLIGHT_LINE_MAX_PCT_BW * bodyweight
    if line_value > max_line:
        line_value = max_line
    line_value = max(0.0, line_value)  # never negative (e.g. after tare)

    # Band: points "on the line" have force in [line_lo, line_hi] so takeoff/landing same force
    tol = FLIGHT_LINE_TOLERANCE_PCT
    line_lo = line_value * (1.0 - tol)
    line_hi = line_value * (1.0 + tol)

    # Optional rolling-window smoothing so takeoff/landing are at bottom of free fall / rising wall, not clamped by noise
    if sample_rate is not None and sample_rate > 0 and FLIGHT_LINE_ROLLING_WINDOW_MS > 0:
        window = max(3, int(round(sample_rate * FLIGHT_LINE_ROLLING_WINDOW_MS / 1000.0)))
        force_use = _rolling_mean(force, window)
    else:
        force_use = force

    # Valley: lowest point in segment (do not pick landing in the valley)
    seg = force_use[take_off : landing + 1]
    mid_offset = int(np.argmin(seg))
    mid = take_off + mid_offset
    valley_force = float(force_use[mid])

    # Min gap (samples) so takeoff and landing are not clamped next to each other
    min_gap_samples = 1
    if sample_rate is not None and sample_rate > 0 and MIN_FLIGHT_GAP_MS > 0:
        min_gap_samples = max(1, int(round(sample_rate * MIN_FLIGHT_GAP_MS / 1000.0)))

    # Require segment long enough to place both points with min_gap between them
    if landing - take_off < min_gap_samples:
        return take_off, landing, line_value

    # Takeoff: first index in [take_off, mid] where force is IN the band, but not within min_gap of segment end
    take_off_new = take_off
    take_off_max = landing - min_gap_samples  # takeoff must be at least min_gap before landing
    end_left = min(mid + 1, take_off_max + 1, landing + 1)
    for i in range(take_off, end_left):
        if line_lo <= force_use[i] <= line_hi:
            take_off_new = i
            break
    # Fallback 1: first index at or below line on descent (so we don't put takeoff at the valley)
    if take_off_new == take_off and take_off < min(mid, take_off_max + 1):
        for i in range(take_off, min(mid, take_off_max + 1)):
            if force_use[i] <= line_hi:
                take_off_new = i
                break
    # Fallback 2: closest to line in left half; avoid choosing valley (mid) as takeoff; stay left of take_off_max
    if take_off_new == take_off and take_off <= mid:
        left_end = min(mid + 1, take_off_max + 1)
        left_slice = force_use[take_off : left_end]
        if len(left_slice) > 0:
            closest_offset = int(np.argmin(np.abs(left_slice - line_value)))
            take_off_new = take_off + closest_offset
            if take_off_new == mid and take_off < mid:
                for i in range(take_off, min(mid, take_off_max + 1)):
                    if force_use[i] <= line_hi:
                        take_off_new = i
                        break
                if take_off_new == mid:
                    take_off_new = take_off
        if take_off_new > take_off_max:
            take_off_new = take_off

    # Landing: first index AFTER valley where force is IN the band on the ASCENDING leg, and at least min_gap after takeoff
    landing_min_idx = take_off_new + min_gap_samples  # landing must be at least min_gap after takeoff
    landing_new = landing
    for i in range(max(mid, landing_min_idx), landing + 1):
        if force_use[i] > valley_force and line_lo <= force_use[i] <= line_hi:
            landing_new = i
            break
    # Fallback: no point in band on ascent — first point after valley in band (must be above valley), or closest on ascending part
    if landing_new == landing and mid < landing:
        for i in range(max(mid + 1, landing_min_idx), landing + 1):
            if force_use[i] > valley_force and line_lo <= force_use[i] <= line_hi:
                landing_new = i
                break
        if landing_new == landing and landing_min_idx <= landing:
            right_slice = force_use[mid : landing + 1]
            above = np.where(right_slice > valley_force)[0]
            if len(above) > 0:
                first_above = int(above[0])
                # Search ascending part but only from landing_min_idx onward (so gap is satisfied)
                start_idx = max(mid + first_above, landing_min_idx)
                sub = force_use[start_idx : landing + 1]
                if len(sub) > 0:
                    landing_new = start_idx + int(np.argmin(np.abs(sub - line_value)))
                else:
                    landing_new = max(landing_min_idx, landing)
            else:
                start_idx = max(mid, landing_min_idx)
                sub = force_use[start_idx : landing + 1]
                if len(sub) > 0:
                    landing_new = start_idx + int(np.argmin(np.abs(sub - line_value)))
                else:
                    landing_new = max(landing_min_idx, landing)

    # Enforce minimum gap so takeoff and landing are not clamped next to each other
    if landing_new - take_off_new < min_gap_samples:
        landing_new = min(take_off_new + min_gap_samples, landing)
    if take_off_new >= landing_new:
        landing_new = min(take_off_new + min_gap_samples, landing)
    return take_off_new, landing_new, line_value


def _expand_flight_to_dip(
    force: np.ndarray,
    start: int,
    end: int,
    bodyweight: float,
    concentric_peak_idx: int,
) -> Tuple[int, int]:
    """Expand (start, end) to full dip: left to waterfall, right to rising wall.
    Uses FLIGHT_DIP_EXPAND_PCT_BW so takeoff/landing are not clamped close together.
    """
    n = len(force)
    thr = FLIGHT_DIP_EXPAND_PCT_BW * bodyweight
    # Expand left (waterfall): include all samples below thr back to concentric
    new_start = start
    for i in range(start - 1, concentric_peak_idx - 1, -1):
        if force[i] < thr:
            new_start = i
        else:
            break
    # Expand right (rising wall): include all samples below thr until force rises
    new_end = end
    for i in range(end + 1, n):
        if force[i] < thr:
            new_end = i
        else:
            break
    return new_start, new_end


def _refine_landing(
    force: np.ndarray,
    take_off: int,
    landing_run_end: int,
    bodyweight: float,
    sample_rate: float,
) -> int:
    """Set landing to first contact: first sample after take_off where force rises above threshold.
    Uses adaptive threshold (min of 10% BW or run_mean + 0.1*BW) for uncalibrated plates.
    """
    n = len(force)
    min_gap = max(2, int(sample_rate * LANDING_MIN_AFTER_TAKEOFF_MS / 1000.0))
    run_mean = float(np.mean(force[take_off : landing_run_end + 1])) if landing_run_end >= take_off else 0.0
    # Adaptive: contact when force exceeds run mean by a margin, or 10% BW (whichever is lower for early detection)
    contact_adaptive = run_mean + 0.12 * bodyweight
    contact_pct = max(40.0, LANDING_CONTACT_PCT_BW * bodyweight)
    contact_threshold = min(contact_pct, contact_adaptive)
    if contact_threshold < 30.0:
        contact_threshold = max(30.0, LANDING_CONTACT_PCT_BW_STRICT * bodyweight)
    for i in range(take_off + 1, min(landing_run_end + 1, n)):
        if force[i] >= contact_threshold:
            if i - take_off >= min_gap:
                return i
            break
    return landing_run_end


def _refine_takeoff(
    force: np.ndarray,
    run_start: int,
    threshold: float,
) -> int:
    """Exact take-off = first sample where force drops below threshold (crossing). Walk backward from run_start."""
    for i in range(run_start - 1, -1, -1):
        if force[i] >= threshold:
            return i + 1
    return run_start


def _find_runs_below(force: np.ndarray, threshold: float, start: int, end: int) -> List[Tuple[int, int]]:
    """Contiguous runs where force < threshold. Returns [(start, end), ...]."""
    runs: List[Tuple[int, int]] = []
    i = start
    while i < end:
        if force[i] >= threshold:
            i += 1
            continue
        j = i
        while j < end and force[j] < threshold:
            j += 1
        runs.append((i, j - 1))
        i = j
    return runs


def _concentric_peak_index(force: np.ndarray, sr: float) -> int:
    """Index of concentric push (max force before flight). Flight must be after this.
    If global max is after global min and the min is late (>2s in), the 'max' is likely landing peak;
    then use max force before the dip as concentric.
    """
    n = len(force)
    start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    seg = force[start:]
    if len(seg) == 0:
        return start
    gmin_idx = start + int(np.argmin(seg))
    gmax_idx = start + int(np.argmax(seg))
    # Only use "max before dip" when the dip is late (likely flight), not unweighting (~1–1.5s)
    gmin_time_s = (gmin_idx - start) / sr
    if gmax_idx > gmin_idx and gmin_time_s > 1.8:
        seg_before = force[start : gmin_idx + 1]
        if len(seg_before) > 0:
            return start + int(np.argmax(seg_before))
    return gmax_idx


def _detect_flight_longest_run(
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    take_off_threshold: float,
    flight_search_start: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Take-off/landing = run below threshold (min 25ms) after concentric peak. Prefer run containing global min."""
    n = len(force)
    min_flight_samples = max(4, int(sr * MIN_FLIGHT_DURATION_MS / 1000.0))
    if flight_search_start is None:
        flight_search_start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    search_start = flight_search_start
    runs = _find_runs_below(force, take_off_threshold, search_start, n)
    candidates = [(s, e) for s, e in runs if (e - s + 1) >= min_flight_samples]
    if not candidates:
        return None, None
    seg = force[search_start:]
    gmin_idx = search_start + int(np.argmin(seg))
    # Prefer run that contains the global min (anchors to real flight; reduces wrong take-off/landing)
    containing = [(s, e) for s, e in candidates if s <= gmin_idx <= e]
    use = containing if containing else candidates
    # Among those, prefer flight-like (mean < 20% BW) then lowest mean
    flight_like = [(s, e) for s, e in use if float(np.mean(force[s : e + 1])) < 0.20 * bodyweight]
    use = flight_like if flight_like else use
    best = min(use, key=lambda se: float(np.mean(force[se[0] : se[1] + 1])))
    return best[0], best[1]


# For adaptive path: accept short flight dips (5 ms) so noisy plates still get a segment
MIN_FLIGHT_DURATION_MS_ADAPTIVE = 5.0


def _detect_flight_adaptive(
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    flight_search_start: Optional[int] = None,
    take_off_threshold: Optional[float] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """
    When the plate never reaches 4% BW, use runs below 1.3 * min(force) after concentric peak.
    If min is negative (e.g. filter overshoot), use 4% BW so flight is still detected.
    Prefer the run that contains the global minimum in that region.
    """
    n = len(force)
    min_flight_samples = max(4, int(sr * MIN_FLIGHT_DURATION_MS_ADAPTIVE / 1000.0))
    if flight_search_start is None:
        flight_search_start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    search_start = flight_search_start
    seg = force[search_start:]
    if len(seg) < min_flight_samples:
        return None, None
    global_min = float(np.min(seg))
    gmin_idx = search_start + int(np.argmin(seg))
    # Filter can produce negative force; 1.3*min would be negative and no samples would be below it
    floor_threshold = max(
        DEFAULT_TAKE_OFF_THRESHOLD_N,
        FLIGHT_THRESHOLD_PCT_BW * bodyweight,
    ) if take_off_threshold is None else take_off_threshold
    adaptive_threshold = global_min * 1.30
    if adaptive_threshold < 0.05 * bodyweight or adaptive_threshold <= 0:
        adaptive_threshold = floor_threshold
    if adaptive_threshold > 0.5 * bodyweight:
        return None, None
    runs = _find_runs_below(force, adaptive_threshold, search_start, n)
    # Allow 3-sample runs when they contain global min (smoothed/filtered data can have narrow dips)
    min_for_candidate = min(min_flight_samples, max(3, min_flight_samples - 1))
    candidates = [(s, e) for s, e in runs if (e - s + 1) >= min_for_candidate]
    if not candidates:
        return None, None
    # Prefer run that contains the global min (fixes take-off/landing wrong)
    containing = [(s, e) for s, e in candidates if s <= gmin_idx <= e]
    if containing:
        best = min(containing, key=lambda se: float(np.mean(force[se[0] : se[1] + 1])))
    else:
        # Else pick run closest to global min (min distance to run)
        def dist_to_gmin(se):
            s, e = se
            if gmin_idx < s:
                return s - gmin_idx
            if gmin_idx > e:
                return gmin_idx - e
            return 0
        closest = min(candidates, key=dist_to_gmin)
        best = min(
            [c for c in candidates if dist_to_gmin(c) == dist_to_gmin(closest)],
            key=lambda se: float(np.mean(force[se[0] : se[1] + 1])),
        )
    # Reject if mean > 50% BW (not flight; prefer lowest values)
    mean_f = float(np.mean(force[best[0] : best[1] + 1]))
    if mean_f > FLIGHT_MEAN_F_ABSOLUTE_MAX_PCT_BW * bodyweight:
        return None, None
    return best[0], best[1]


def _detect_flight_valley(
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    flight_search_start: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Last resort: find global min after concentric peak, expand left/right while force below threshold.
    Uses 0.25*BW; if valley is shallow (min > 0.25*BW), uses 0.5*BW so filtered/smooth data still gets a segment.
    """
    n = len(force)
    if flight_search_start is None:
        flight_search_start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    search_start = flight_search_start
    seg = force[search_start:]
    if len(seg) < 5:
        return None, None
    gmin_idx = search_start + int(np.argmin(seg))
    gmin_val = float(force[gmin_idx])
    # Shallow valley (e.g. after low-pass filter): use higher expansion threshold
    if gmin_val >= 0.25 * bodyweight:
        threshold = 0.5 * bodyweight
    else:
        threshold = 0.25 * bodyweight
    if gmin_val >= threshold:
        return None, None
    # Expand left
    start = gmin_idx
    for i in range(gmin_idx - 1, search_start - 1, -1):
        if force[i] < threshold:
            start = i
        else:
            break
    # Expand right
    end = gmin_idx
    for i in range(gmin_idx + 1, n):
        if force[i] < threshold:
            end = i
        else:
            break
    min_dur_samples = max(4, int(sr * 0.005))  # 5 ms
    if end - start + 1 < min_dur_samples:
        return None, None
    # Reject if mean > 50% BW (not flight; prefer lowest values)
    mean_f = float(np.mean(force[start : end + 1]))
    if mean_f > FLIGHT_MEAN_F_ABSOLUTE_MAX_PCT_BW * bodyweight:
        return None, None
    return start, end


def _collect_flight_candidates(
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    take_off_threshold: float,
    concentric_peak_idx: int,
) -> List[Tuple[int, int]]:
    """Collect all plausible flight segments (start, end) from multiple strategies and search starts."""
    n = len(force)
    base_start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    search_starts = [base_start, concentric_peak_idx]
    if concentric_peak_idx != base_start:
        search_starts = list(dict.fromkeys(search_starts))  # order preserving

    candidates: List[Tuple[int, int]] = []
    min_25ms = max(4, int(sr * 0.025))
    min_5ms = max(3, int(sr * 0.005))

    for search_start in search_starts:
        seg = force[search_start:]
        if len(seg) < min_5ms:
            continue
        gmin = float(np.min(seg))
        gmin_idx = search_start + int(np.argmin(seg))

        # 4% BW runs
        runs_4 = _find_runs_below(force, take_off_threshold, search_start, n)
        for s, e in runs_4:
            if (e - s + 1) >= min_25ms:
                candidates.append((s, e))

        # 10%, 15%, 20%, 25% BW runs (uncalibrated or high-baseline plates)
        for pct in (0.10, 0.15, 0.20, 0.25):
            thresh = pct * bodyweight
            runs_pct = _find_runs_below(force, thresh, search_start, n)
            for s, e in runs_pct:
                if (e - s + 1) >= min_25ms:
                    candidates.append((s, e))

        # Adaptive: 1.4 * min in segment (or 4% BW if min negative); relax cap for noisy data
        adaptive_thr = gmin * 1.4 if gmin > 0.05 * bodyweight else take_off_threshold
        if adaptive_thr <= 0:
            adaptive_thr = take_off_threshold
        if adaptive_thr <= 0.65 * bodyweight:
            runs_adj = _find_runs_below(force, adaptive_thr, search_start, n)
            for s, e in runs_adj:
                if (e - s + 1) >= min_5ms:
                    candidates.append((s, e))

        # Valley: expand around gmin; use higher expansion for shallow valleys (uncalibrated)
        if gmin >= 0.5 * bodyweight:
            thr_valley = 0.65 * bodyweight
        elif gmin >= 0.25 * bodyweight:
            thr_valley = 0.5 * bodyweight
        else:
            thr_valley = 0.25 * bodyweight
        if gmin < thr_valley:
            start_v, end_v = gmin_idx, gmin_idx
            for i in range(gmin_idx - 1, search_start - 1, -1):
                if force[i] < thr_valley:
                    start_v = i
                else:
                    break
            for i in range(gmin_idx + 1, n):
                if force[i] < thr_valley:
                    end_v = i
                else:
                    break
            if (end_v - start_v + 1) >= min_5ms:
                candidates.append((start_v, end_v))

    # Deduplicate by (s, e)
    seen = set()
    out: List[Tuple[int, int]] = []
    for se in candidates:
        if se not in seen:
            seen.add(se)
            out.append(se)
    return out


def _score_flight_candidate(
    start: int,
    end: int,
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    gmin_idx: int,
    concentric_peak_idx: int,
) -> float:
    """Higher = better. Strongly prefer segment after concentric peak (real flight, not unweighting)."""
    dur_s = (end - start + 1) / sr
    mean_f = float(np.mean(force[start : end + 1]))
    score = 0.0
    # Must be after concentric push (avoid unweighting dip winning)
    if start >= concentric_peak_idx:
        score += 5.0
    else:
        # Allow pre-peak only if no post-peak candidate; don't give duration/gmin bonuses
        if start < concentric_peak_idx:
            score -= 2.0
    if FLIGHT_DURATION_MIN_S <= dur_s <= FLIGHT_DURATION_MAX_S:
        score += 2.0
    if FLIGHT_DURATION_TYPICAL_MIN_S <= dur_s <= FLIGHT_DURATION_TYPICAL_MAX_S:
        score += 1.0
    if start <= gmin_idx <= end:
        score += 2.0
    if mean_f < 0.20 * bodyweight:
        score += 1.0
    # Strong preference for lowest mean (closest to zero) – takeoff/landing at true flight
    score -= mean_f / (bodyweight * 2)
    return score


def _detect_flight_unified(
    force: np.ndarray,
    sr: float,
    bodyweight: float,
    take_off_threshold: float,
) -> Tuple[Optional[int], Optional[int]]:
    """Pick best flight segment from all candidates by score. More consistent than a single path."""
    n = len(force)
    base_start = min(n - 1, int(sr * FLIGHT_SEARCH_START_S))
    concentric_peak_idx = _concentric_peak_index(force, sr)
    seg = force[base_start:]
    if len(seg) < 5:
        return None, None
    gmin_idx = base_start + int(np.argmin(seg))

    candidates = _collect_flight_candidates(
        force, sr, bodyweight, take_off_threshold, concentric_peak_idx
    )
    if not candidates:
        return None, None

    # Score candidates; prefer lowest mean (closest to zero), then longer duration (full dip)
    scored = []
    for se in candidates:
        start, end = se
        mean_f = float(np.mean(force[start : end + 1]))
        sc = _score_flight_candidate(start, end, force, sr, bodyweight, gmin_idx, concentric_peak_idx)
        dur = end - start + 1
        scored.append((se, sc, mean_f, dur))
    # Sort by mean ascending, then duration descending so we don't pick a short run when a long one exists
    scored.sort(key=lambda x: (x[2], -x[3]))
    preferred_max = FLIGHT_MEAN_F_PREFERRED_PCT_BW * bodyweight
    for (start, end), _, mean_f, _ in scored:
        dur_s = (end - start + 1) / sr
        if dur_s < FLIGHT_DURATION_MIN_S or dur_s > FLIGHT_DURATION_MAX_S:
            continue
        if mean_f <= preferred_max:
            return start, end
    # Fallback: accept segment with lowest mean, but never > 40% BW (not flight)
    for (start, end), _, mean_f, _ in scored:
        dur_s = (end - start + 1) / sr
        if dur_s < FLIGHT_DURATION_MIN_S or dur_s > FLIGHT_DURATION_MAX_S:
            continue
        if mean_f <= FLIGHT_MEAN_F_ABSOLUTE_MAX_PCT_BW * bodyweight:
            return start, end
    return None, None


def _detect_flight_crossing(
    force: np.ndarray,
    n: int,
    sr: float,
    take_off_threshold: float,
    take_off_consecutive_samples: int,
    bodyweight: float,
    flight_search_start: Optional[int] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """Fallback: first crossing after concentric peak with K consecutive below in window; then landing from peak."""
    K = min(take_off_consecutive_samples, n - 1)
    window_samples = min(n, max(K + 1, int(sr * TAKE_OFF_SEARCH_WINDOW_MS / 1000.0)))
    take_off: Optional[int] = None
    i = 1 if flight_search_start is None else max(1, flight_search_start)
    while i < n:
        if force[i - 1] >= take_off_threshold and force[i] < take_off_threshold:
            search_end = min(i + window_samples, n - K)
            for start in range(i, search_end):
                run = 0
                for j in range(start, min(start + K, n)):
                    if force[j] < take_off_threshold:
                        run += 1
                    else:
                        break
                if run >= K:
                    take_off = start
                    break
            if take_off is not None:
                break
            i = min(i + window_samples, n - 1)
        i += 1
    if take_off is None:
        return None, None
    landing: Optional[int] = None
    if take_off + 1 < n:
        post_to = force[take_off + 1 :]
        peak_offset = int(np.argmax(post_to))
        peak_idx = take_off + 1 + peak_offset
        f_to = float(force[take_off])
        close_tolerance = max(30.0, 0.03 * bodyweight)
        for idx in range(peak_idx, take_off, -1):
            if abs(float(force[idx]) - f_to) <= close_tolerance:
                landing = idx
                break
        if landing is None:
            landing = peak_idx
    return take_off, landing


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

    - Take-off/landing: Primary = run below flight threshold (lowest mean). Take-off = beginning of
      dip (left edge), landing = end of dip (right edge), so they span the full flight and are not
      pulled close together. Fallback = first descending crossing with K consecutive below.
    - Movement onset and min_force: Prefer eccentric (unweighting) dip: find concentric peak (max F > BW)
      in last CONCENTRIC_SEARCH_BEFORE_TAKEOFF_S before take_off; then min_force = argmin(F) before that
      peak. Onset = start of slope to that min (walk backward until F >= threshold). Fallback = min in
      [window_start, take_off - gap]; onset = first sustained drop or slope start.
    """
    if take_off_threshold is None:
        take_off_threshold = max(DEFAULT_TAKE_OFF_THRESHOLD_N, FLIGHT_THRESHOLD_PCT_BW * bodyweight)
    if landing_threshold is None:
        landing_threshold = max(DEFAULT_LANDING_THRESHOLD_N, 0.05 * bodyweight)

    force = trial.force
    n = len(force)
    sr = trial.sample_rate
    concentric_peak_idx = _concentric_peak_index(force, sr)

    # Single consistent path: collect all flight candidates, score, pick best (avoids hit-or-miss)
    take_off, landing = _detect_flight_unified(
        force, sr, bodyweight, take_off_threshold
    )
    if take_off is None:
        # Fallback: original chain (after concentric peak only)
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
            force, n, sr, take_off_threshold, take_off_consecutive_samples, bodyweight,
            flight_search_start=concentric_peak_idx,
        )
    if take_off is not None and landing is None and take_off + 1 < n:
        f_to = float(force[take_off])
        post_to = force[take_off + 1 :]
        peak_offset = int(np.argmax(post_to))
        peak_idx = take_off + 1 + peak_offset
        close_tolerance = max(30.0, 0.03 * bodyweight)
        for idx in range(peak_idx, take_off, -1):
            if abs(float(force[idx]) - f_to) <= close_tolerance:
                landing = idx
                break
        if landing is None:
            landing = peak_idx

    flight_line_N: Optional[float] = None
    # Expand to full dip (waterfall left, rising wall right) so takeoff/landing are not clamped close
    if take_off is not None and landing is not None and landing > take_off:
        take_off, landing = _expand_flight_to_dip(
            force, take_off, landing, bodyweight, concentric_peak_idx
        )

    # Refine take-off to beginning of dip (left edge): first sample below threshold
    if take_off is not None:
        take_off = _refine_takeoff(force, take_off, take_off_threshold)
    # Landing = end of dip (right edge). Refine to first contact but never move left of run end
    if take_off is not None and landing is not None and landing > take_off:
        run_end_right = landing  # right edge of dip (run end)
        landing = _refine_landing(force, take_off, landing, bodyweight, sr)
        # Keep landing at least at run end so takeoff and landing span the full dip
        if landing < run_end_right:
            landing = run_end_right
        if landing <= take_off:
            landing = take_off + 1
        # Move line upward until time series cuts it exactly twice; those two points = takeoff & landing
        take_off, landing, flight_line_N = _refine_takeoff_landing_to_mean_line_crossings(
            force, take_off, landing, concentric_peak_idx, bodyweight, sample_rate=sr
        )

    # Min_force = eccentric (unweighting) dip, i.e. minimum *before* the concentric push, not the dip right before take_off.
    # So we need a concentric peak (force > BW) before take_off; then min_force = argmin(force) before that peak.
    onset_start = int(0.5 * sr)
    onset_end = take_off if take_off is not None else n
    min_gap_samples = max(5, int(sr * 0.05))  # exclude last 50 ms before take_off
    sustain_onset = max(1, int(np.ceil(sr * onset_sustain_ms / 1000.0)))
    movement_onset: Optional[int] = None
    min_force: Optional[int] = None

    if take_off is not None and take_off > onset_start + min_gap_samples:
        window_start = max(onset_start, int(take_off - sr * ONSET_WINDOW_BEFORE_TAKEOFF_S))
        # Concentric peak = max force in the last CONCENTRIC_SEARCH_BEFORE_TAKEOFF_S before take_off
        search_start = max(0, take_off - max(min_gap_samples, int(sr * CONCENTRIC_SEARCH_BEFORE_TAKEOFF_S)))
        seg_conc = force[search_start : take_off]
        if len(seg_conc) > 0:
            concentric_peak_idx = search_start + int(np.argmax(seg_conc))
            if float(force[concentric_peak_idx]) > bodyweight:
                # Clear concentric push: min_force = minimum *before* this peak (real unweighting dip)
                end_before_peak = min(concentric_peak_idx, take_off - min_gap_samples)
                if end_before_peak > window_start + 10:
                    seg = force[window_start : end_before_peak]
                    min_force = window_start + int(np.argmin(seg))
        # Fallback: no concentric peak above BW before take_off → min = smallest in [window_start, take_off - gap]
        if min_force is None:
            window_end = take_off - min_gap_samples
            if window_end > window_start + 10:
                seg = force[window_start : window_end]
                min_force = window_start + int(np.argmin(seg))

    if min_force is not None:
        # Onset = start of slope that connects to min_force (walk backward until force >= threshold)
        for onset_threshold in (
            bodyweight - onset_n_sigma * sigma_quiet if sigma_quiet > 0 else (1.0 - onset_below_bw) * bodyweight,
            (1.0 - 0.02) * bodyweight,
            (1.0 - 0.01) * bodyweight,
        ):
            if onset_threshold <= 0:
                continue
            for i in range(min_force - 1, onset_start - 1, -1):
                if force[i] >= onset_threshold:
                    movement_onset = i + 1
                    break
            if movement_onset is not None:
                break

    # Fallback: if no onset found from slope (e.g. force never rises above threshold), use first sustained drop
    if movement_onset is None:
        for onset_threshold in (
            bodyweight - onset_n_sigma * sigma_quiet if sigma_quiet > 0 else (1.0 - onset_below_bw) * bodyweight,
            (1.0 - 0.02) * bodyweight,
            (1.0 - 0.01) * bodyweight,
        ):
            if onset_threshold <= 0:
                continue
            for sustain in (sustain_onset, max(1, int(sr * 0.020))):
                i = onset_start
                while i < min(onset_end, n - sustain):
                    if force[i] < onset_threshold:
                        end = min(i + sustain, n)
                        if end - i < sustain:
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
                    if movement_onset is not None:
                        break
                    i += 1
                if movement_onset is not None:
                    break
            if movement_onset is not None:
                break
        # If we used first-sustained-drop and still have no min_force, set from big window or [onset, take_off - gap]
        if min_force is None and movement_onset is not None and take_off is not None and movement_onset < take_off:
            search_end = max(movement_onset + 3, take_off - min_gap_samples)
            if search_end > movement_onset:
                seg = force[movement_onset : search_end]
                if len(seg) > 0:
                    min_force = movement_onset + int(np.argmin(seg))

    if min_force is not None and take_off is not None and min_force >= take_off:
        min_force = None

    return CMJEvents(
        movement_onset=movement_onset,
        take_off=take_off,
        landing=landing,
        eccentric_end=None,
        velocity_zero=None,
        min_force=min_force,
        flight_line_N=flight_line_N,
    )
