"""
Squat Jump (SJ) detection and classification from vertical ground reaction force (vGRF).

Supports single or dual force plate. Events: quiet phase → contraction start →
countermovement check → peak force → takeoff → landing → peak landing.
Classification: optimal_squat_jump vs injured_or_fatigued_squat_jump.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.integrate import trapezoid
from scipy.signal import savgol_filter, find_peaks

from ..data.types import CMJTrial

# ---------------------------------------------------------------------------
# Configurable constants (spec-aligned)
# ---------------------------------------------------------------------------
DEFAULT_QUIET_WINDOW_S = 1.5
DEFAULT_QUIET_SIGMA_THRESHOLD_N = 50.0  # flag trial if std(quiet) > this
# Contraction start = when force first leaves bodyweight (detect close to BW, not far into curve)
# Use a small rise so we catch the actual movement start, not 2–3% above BW
DEFAULT_CONTRACTION_RISE_N = 15.0  # absolute floor (N)
DEFAULT_CONTRACTION_RISE_PCT_BW = 0.005  # 0.5% BW above baseline (~38 N at 7540 N BW)
DEFAULT_CONTRACTION_ONSET_N_SIGMA = 3.0  # or BW + 3*sigma; use min with pct so we pick the closer threshold
# Fixed window (ms): force must stay above threshold for this long = real contraction, not noise
DEFAULT_CONTRACTION_SUSTAIN_MS = 40.0
# Countermovement = real dip before rise (injured SJ). Require clear drop below BW so noise is not counted.
DEFAULT_COUNTERMOVEMENT_DIP_N = 50.0  # absolute: force must go at least this far below baseline (N)
DEFAULT_COUNTERMOVEMENT_DIP_PCT_BW = 0.03  # or 3% of BW below baseline (e.g. 97% BW)
DEFAULT_COUNTERMOVEMENT_SUSTAIN_MS = 60.0  # dip sustained this long = real countermovement
# Use same as CMJ (events.py): threshold max(20, 0.05*BW), K consecutive samples
DEFAULT_TAKEOFF_THRESHOLD_N = 20.0
DEFAULT_TAKEOFF_CONSECUTIVE_SAMPLES = 4  # same as CMJ
DEFAULT_LANDING_THRESHOLD_N = 200.0  # CMJ uses this for landing "close" tolerance
DEFAULT_LANDING_CLOSE_TOLERANCE_PCT_BW = 0.03  # landing force within this of takeoff force
DEFAULT_PEAK_LANDING_WINDOW_MS = 200.0
DEFAULT_SAVGOL_WINDOW_MS = 25.0
DEFAULT_SAVGOL_POLY = 3
DEFAULT_RFD_WINDOW_MS = 20.0
DEFAULT_FLIGHT_TIME_MIN_S = 0.1
DEFAULT_ASYMMETRY_OPTIMAL_PCT = 15.0  # above this => injured/fatigued
DEFAULT_ASYMMETRY_STRICT_PCT = 10.0   # optional stricter for "optimal"
# Bimodality / bimodal takeoff: two distinct peaks in concentric phase
DEFAULT_BIMODAL_MIN_PEAK_RATIO = 0.50  # second peak at least 50% of first (catch more bimodal curves)
DEFAULT_BIMODAL_PROMINENCE_PCT_BW = 0.015  # 1.5% BW prominence so smaller second peak is found
DEFAULT_BIMODAL_MIN_SEPARATION_MS = 25.0  # min time between P1 and P2 (ms)
# Contraction time (s): typical range for "optimal" (research: ~0.3–0.5 s common for SJ)
DEFAULT_CONTRACTION_TIME_MIN_S = 0.15
DEFAULT_CONTRACTION_TIME_MAX_S = 1.4
# RFD: optimal if above this multiple of BW/s (e.g. 15 = 15 * BW per second)
DEFAULT_MIN_RFD_BW_PER_S = 8.0


def _ms_to_samples(ms: float, fs: float) -> int:
    return max(1, int(round(fs * ms / 1000.0)))


@dataclass
class SquatJumpPoints:
    """SJ event indices (sample indices). Bimodal takeoff: first_peak, trough, second_peak when applicable."""

    contraction_start: Optional[int] = None
    peak_force_index: Optional[int] = None
    takeoff_index: Optional[int] = None
    landing_index: Optional[int] = None
    peak_landing_index: Optional[int] = None
    # Bimodal takeoff strategy (when two peaks in concentric phase)
    first_peak_index: Optional[int] = None
    trough_between_peaks_index: Optional[int] = None
    second_peak_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Optional[int]]:
        d = {
            "contraction_start": self.contraction_start,
            "peak_force_index": self.peak_force_index,
            "takeoff_index": self.takeoff_index,
            "landing_index": self.landing_index,
            "peak_landing_index": self.peak_landing_index,
        }
        if self.first_peak_index is not None:
            d["first_peak_index"] = self.first_peak_index
        if self.trough_between_peaks_index is not None:
            d["trough_between_peaks_index"] = self.trough_between_peaks_index
        if self.second_peak_index is not None:
            d["second_peak_index"] = self.second_peak_index
        return d


@dataclass
class SquatJumpConfig:
    """Configurable thresholds for SJ detection and classification.

    Fixed windows (contraction_sustain_ms, countermovement_sustain_ms) are used so that
    contraction start and the countermovement dip/bottom must be sustained for that
    duration, rejecting brief noise and confirming a real rise or real bottom (e.g. injured SJ).
    """

    quiet_window_s: float = DEFAULT_QUIET_WINDOW_S
    quiet_sigma_threshold_n: float = DEFAULT_QUIET_SIGMA_THRESHOLD_N
    contraction_rise_n: float = DEFAULT_CONTRACTION_RISE_N
    contraction_rise_pct_bw: float = DEFAULT_CONTRACTION_RISE_PCT_BW
    contraction_onset_n_sigma: float = DEFAULT_CONTRACTION_ONSET_N_SIGMA
    contraction_sustain_ms: float = DEFAULT_CONTRACTION_SUSTAIN_MS  # fixed window: reject noise
    countermovement_dip_n: float = DEFAULT_COUNTERMOVEMENT_DIP_N
    countermovement_dip_pct_bw: float = DEFAULT_COUNTERMOVEMENT_DIP_PCT_BW
    countermovement_sustain_ms: float = DEFAULT_COUNTERMOVEMENT_SUSTAIN_MS
    takeoff_threshold_n: float = DEFAULT_TAKEOFF_THRESHOLD_N
    takeoff_consecutive_samples: int = DEFAULT_TAKEOFF_CONSECUTIVE_SAMPLES
    landing_threshold_n: float = DEFAULT_LANDING_THRESHOLD_N
    landing_close_tolerance_pct_bw: float = DEFAULT_LANDING_CLOSE_TOLERANCE_PCT_BW
    peak_landing_window_ms: float = DEFAULT_PEAK_LANDING_WINDOW_MS
    savgol_window_ms: float = DEFAULT_SAVGOL_WINDOW_MS
    savgol_poly: int = DEFAULT_SAVGOL_POLY
    rfd_window_ms: float = DEFAULT_RFD_WINDOW_MS
    flight_time_min_s: float = DEFAULT_FLIGHT_TIME_MIN_S
    asymmetry_optimal_pct: float = DEFAULT_ASYMMETRY_OPTIMAL_PCT
    asymmetry_strict_pct: float = DEFAULT_ASYMMETRY_STRICT_PCT
    bimodal_min_peak_ratio: float = DEFAULT_BIMODAL_MIN_PEAK_RATIO
    bimodal_prominence_pct_bw: float = DEFAULT_BIMODAL_PROMINENCE_PCT_BW
    bimodal_min_separation_ms: float = DEFAULT_BIMODAL_MIN_SEPARATION_MS
    contraction_time_min_s: float = DEFAULT_CONTRACTION_TIME_MIN_S
    contraction_time_max_s: float = DEFAULT_CONTRACTION_TIME_MAX_S
    min_rfd_bw_per_s: float = DEFAULT_MIN_RFD_BW_PER_S


DEFAULT_SJ_CONFIG = SquatJumpConfig()


def _smooth_force(force: np.ndarray, sr: float, window_ms: float, poly: int) -> np.ndarray:
    """Savitzky-Golay smoothing; preserve peak timing."""
    n = len(force)
    if n < 10:
        return np.asarray(force, dtype=float)
    w = _ms_to_samples(window_ms, sr)
    w = min(n - 1 if (n % 2 == 0) else n, max(5, w | 1))
    if poly >= w:
        poly = max(1, w - 1)
    return savgol_filter(force.astype(float), window_length=w, polyorder=poly, mode="nearest")


def _compute_baseline_sj(
    force: np.ndarray,
    sr: float,
    quiet_window_s: float = DEFAULT_QUIET_WINDOW_S,
) -> Tuple[float, float]:
    """Baseline (bodyweight) and sigma from first quiet_window_s. Returns (bodyweight_N, sigma_N)."""
    n_quiet = min(int(sr * quiet_window_s), len(force))
    if n_quiet <= 0:
        n_quiet = min(int(sr * 0.5), len(force))
    seg = force[:n_quiet]
    bw = float(np.mean(seg))
    sigma = float(np.std(seg)) if len(seg) > 1 else 0.0
    return bw, sigma


def _first_above_sustained(
    force: np.ndarray,
    threshold: float,
    start: int,
    end: int,
    min_samples: int,
) -> Optional[int]:
    """First index where force > threshold and stays above for min_samples."""
    n = len(force)
    i = max(0, start)
    end = min(end, n - 1)
    while i <= end - min_samples + 1:
        if force[i] > threshold:
            ok = True
            for j in range(i, min(i + min_samples, n)):
                if force[j] <= threshold:
                    ok = False
                    break
            if ok:
                return i
        i += 1
    return None


def _first_below_sustained(
    force: np.ndarray,
    threshold: float,
    start: int,
    end: int,
    min_samples: int,
) -> Optional[int]:
    """First index where force < threshold and stays below for min_samples."""
    n = len(force)
    i = max(0, start)
    end = min(end, n - 1)
    while i <= end - min_samples + 1:
        if force[i] < threshold:
            ok = True
            for j in range(i, min(i + min_samples, n)):
                if force[j] >= threshold:
                    ok = False
                    break
            if ok:
                return i
        i += 1
    return None


def _first_above_after(
    force: np.ndarray,
    threshold: float,
    after_index: int,
) -> Optional[int]:
    """First index after after_index where force > threshold."""
    n = len(force)
    for i in range(after_index + 1, n):
        if force[i] > threshold:
            return i
    return None


def _takeoff_landing_cmj_style(
    force: np.ndarray,
    bodyweight: float,
    search_start: int,
    takeoff_threshold: Optional[float] = None,
    takeoff_consecutive: int = 4,
    landing_close_tolerance: Optional[float] = None,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Same algorithm as CMJ (events.py): takeoff = first descending crossing with
    K consecutive samples below threshold; landing = after takeoff, find peak
    force then scan backward to first point where force is close to force[takeoff].

    Uses raw force. search_start: only consider takeoff after this index (e.g. after peak force).
    """
    n = len(force)
    if takeoff_threshold is None:
        takeoff_threshold = max(DEFAULT_TAKEOFF_THRESHOLD_N, 0.05 * bodyweight)
    if landing_close_tolerance is None:
        landing_close_tolerance = max(30.0, 0.03 * bodyweight)

    K = min(takeoff_consecutive, n - 1)
    take_off: Optional[int] = None
    i = max(1, search_start + 1)
    while i < n:
        if force[i - 1] >= takeoff_threshold and force[i] < takeoff_threshold:
            end = min(i + 1 + K, n)
            if end - (i + 1) < K:
                i = end
                continue
            ok = True
            for j in range(i + 1, i + 1 + K):
                if force[j] >= takeoff_threshold:
                    ok = False
                    i = j
                    break
            if ok:
                take_off = i
                break
        i += 1

    landing: Optional[int] = None
    if take_off is not None and take_off + 1 < n:
        f_to = float(force[take_off])
        post_to = force[take_off + 1 :]
        if len(post_to) > 0:
            peak_offset = int(np.argmax(post_to))
            peak_idx = take_off + 1 + peak_offset
            for idx in range(peak_idx, take_off, -1):
                if abs(float(force[idx]) - f_to) <= landing_close_tolerance:
                    landing = idx
                    break
            if landing is None:
                landing = peak_idx

    return take_off, landing


def _detect_countermovement(
    force: np.ndarray,
    contraction_start: int,
    baseline: float,
    dip_n: float,
    dip_pct_bw: float = 0.03,
    sustain_samples: int = 5,
    min_lookback_samples: int = 100,
) -> bool:
    """
    True if before contraction_start there is a sustained force dip below baseline.
    Uses threshold = baseline - max(dip_n, dip_pct_bw * baseline) so only a clear
    countermovement dip (chart goes down then up) is detected, not noise.
    """
    start = max(0, contraction_start - min_lookback_samples)
    drop = max(dip_n, dip_pct_bw * baseline)
    threshold = baseline - drop
    n = contraction_start - start
    if n < sustain_samples:
        return False
    for i in range(start, contraction_start - sustain_samples + 1):
        ok = True
        for j in range(i, i + sustain_samples):
            if force[j] >= threshold:
                ok = False
                break
        if ok:
            return True
    return False


def _detect_bimodal(
    force: np.ndarray,
    start_idx: int,
    end_idx: int,
    min_peak_ratio: float = DEFAULT_BIMODAL_MIN_PEAK_RATIO,
    prominence_pct_bw: float = 0.05,
    min_separation_ms: float = 50.0,
    sr: float = 1000.0,
) -> Tuple[bool, Optional[float]]:
    """
    Detect two significant local peaks in [start_idx, end_idx].
    Returns (bimodal_flag, bimodality_index = |peak1 - peak2| or None).
    """
    seg = force[start_idx : end_idx + 1]
    if len(seg) < 20:
        return False, None
    bw_est = float(np.mean(force[:max(1, start_idx)]))
    prominence = max(50.0, prominence_pct_bw * bw_est)
    min_sep = max(5, _ms_to_samples(min_separation_ms, sr))
    peaks, props = find_peaks(seg, prominence=prominence, distance=min_sep)
    if len(peaks) < 2:
        return False, None
    vals = seg[peaks]
    order = np.argsort(vals)[::-1]
    p1_val = float(vals[order[0]])
    p2_val = float(vals[order[1]])
    if p2_val < min_peak_ratio * p1_val:
        return False, None
    return True, float(abs(p1_val - p2_val))


def _detect_bimodal_takeoff_points(
    force: np.ndarray,
    start_idx: int,
    end_idx: int,
    min_peak_ratio: float = DEFAULT_BIMODAL_MIN_PEAK_RATIO,
    prominence_pct_bw: float = DEFAULT_BIMODAL_PROMINENCE_PCT_BW,
    min_separation_ms: float = DEFAULT_BIMODAL_MIN_SEPARATION_MS,
    sr: float = 1000.0,
) -> Tuple[bool, Optional[int], Optional[int], Optional[int], Optional[float], Optional[float]]:
    """
    Bimodal takeoff strategy: two peaks (P1, P2) and trough between them in concentric phase.
    Returns (bimodal, first_peak_idx, trough_idx, second_peak_idx, bimodality_index, trough_depth_N).
    Indices are absolute (into force). first_peak is earlier in time, second_peak later.
    Uses prominence relative to segment so smaller second peaks are detected.
    """
    seg = force[start_idx : end_idx + 1]
    if len(seg) < 25:
        return False, None, None, None, None, None
    bw_est = float(np.mean(force[:max(1, start_idx)]))
    seg_max = float(np.max(seg))
    # Prominence: use % of BW or % of segment max (whichever is smaller) so we catch bimodal curves
    prominence_bw = prominence_pct_bw * bw_est
    prominence_seg = 0.012 * seg_max  # 1.2% of segment max
    prominence = max(25.0, min(prominence_bw, prominence_seg))
    min_sep = max(3, _ms_to_samples(min_separation_ms, sr))
    peaks, props = find_peaks(seg, prominence=prominence, distance=min_sep)
    if len(peaks) < 2:
        return False, None, None, None, None, None
    # Order peaks by time (index in segment): P1 = first, P2 = second
    peaks_sorted = sorted(peaks)
    p1_rel, p2_rel = peaks_sorted[0], peaks_sorted[1]
    v1 = float(seg[p1_rel])
    v2 = float(seg[p2_rel])
    # Both peaks must be significant relative to each other (min 5% drop research)
    if v2 < min_peak_ratio * v1 or v1 < min_peak_ratio * v2:
        return False, None, None, None, None, None
    # Trough = minimum force strictly between P1 and P2
    trough_rel = int(np.argmin(seg[p1_rel : p2_rel + 1])) + p1_rel
    trough_val = float(seg[trough_rel])
    trough_depth = max(v1, v2) - trough_val
    bimodality_index = abs(v1 - v2)
    first_peak_idx = start_idx + p1_rel
    second_peak_idx = start_idx + p2_rel
    trough_idx = start_idx + trough_rel
    return True, first_peak_idx, trough_idx, second_peak_idx, bimodality_index, trough_depth


def detect_squat_jump_events(
    trial: CMJTrial,
    config: Optional[SquatJumpConfig] = None,
    bodyweight: Optional[float] = None,
    use_smoothing: bool = True,
) -> Tuple[SquatJumpPoints, float, float, Dict[str, Any]]:
    """
    Detect SJ events in order: contraction start → (countermovement check) →
    peak force → takeoff → landing → peak landing.

    Returns:
        (points, bodyweight_N, sigma_quiet, extra) where extra has keys
        countermovement (bool), bimodal (bool), bimodality_index, quiet_noisy (bool).
    """
    cfg = config or DEFAULT_SJ_CONFIG
    force = trial.force
    n = len(force)
    sr = trial.sample_rate
    dt = 1.0 / sr

    if use_smoothing:
        force_work = _smooth_force(force, sr, cfg.savgol_window_ms, cfg.savgol_poly)
    else:
        force_work = np.asarray(force, dtype=float)

    if bodyweight is None:
        bw, sigma_quiet = _compute_baseline_sj(force_work, sr, cfg.quiet_window_s)
    else:
        bw = bodyweight
        sigma_quiet, _ = _compute_baseline_sj(force_work, sr, cfg.quiet_window_s)

    quiet_noisy = sigma_quiet > cfg.quiet_sigma_threshold_n

    # Contraction start: detect when force first leaves bodyweight (small rise, not far into curve).
    # Use the smaller of (pct_bw*BW, n_sigma*sigma) so we pick the threshold closest to BW.
    rise_pct = cfg.contraction_rise_pct_bw * bw
    rise_sigma = cfg.contraction_onset_n_sigma * sigma_quiet
    rise_from_baseline = max(cfg.contraction_rise_n, min(rise_pct, rise_sigma) if sigma_quiet > 0 else rise_pct)
    contraction_threshold = bw + rise_from_baseline
    quiet_samples = min(int(sr * cfg.quiet_window_s), n)
    sustain = _ms_to_samples(cfg.contraction_sustain_ms, sr)

    contraction_start: Optional[int] = _first_above_sustained(
        force_work, contraction_threshold, quiet_samples, n - 1, sustain
    )
    if contraction_start is None:
        return (
            SquatJumpPoints(contraction_start=None),
            bw,
            sigma_quiet,
            {"countermovement": False, "bimodal": False, "bimodality_index": None, "trough_depth_N": None, "quiet_noisy": quiet_noisy},
        )

    # Countermovement: sustained dip below baseline (clear drop, not noise) before contraction_start
    cm_sustain = _ms_to_samples(cfg.countermovement_sustain_ms, sr)
    countermovement = _detect_countermovement(
        force_work,
        contraction_start,
        bw,
        cfg.countermovement_dip_n,
        dip_pct_bw=cfg.countermovement_dip_pct_bw,
        sustain_samples=cm_sustain,
        min_lookback_samples=max(100, int(sr * 0.4)),
    )

    # Takeoff and landing: same algorithm as CMJ (events.py) on raw force
    # Search for takeoff only after contraction start
    takeoff_threshold = max(cfg.takeoff_threshold_n, 0.05 * bw)
    landing_tolerance = max(30.0, cfg.landing_close_tolerance_pct_bw * bw)
    takeoff_idx, landing_idx = _takeoff_landing_cmj_style(
        force,  # use raw force to match CMJ
        bw,
        search_start=contraction_start,
        takeoff_threshold=takeoff_threshold,
        takeoff_consecutive=cfg.takeoff_consecutive_samples,
        landing_close_tolerance=landing_tolerance,
    )

    # Peak force between contraction_start and takeoff (or end if no takeoff)
    search_end = takeoff_idx if takeoff_idx is not None else (n - 1)
    window_conc = force_work[contraction_start : search_end + 1]
    if len(window_conc) == 0:
        peak_force_index = contraction_start
        peak_force_value = float(force_work[contraction_start])
    else:
        rel_peak = int(np.argmax(window_conc))
        peak_force_index = contraction_start + rel_peak
        peak_force_value = float(force_work[peak_force_index])

    peak_landing_idx: Optional[int] = None
    if landing_idx is not None:
        window_land = _ms_to_samples(cfg.peak_landing_window_ms, sr)
        end_land = min(landing_idx + window_land, n - 1)
        seg_land = force_work[landing_idx : end_land + 1]
        if len(seg_land) > 0:
            peak_landing_idx = landing_idx + int(np.argmax(seg_land))

    # Bimodal takeoff strategy: two peaks + trough between contraction_start and takeoff
    bimodal = False
    bimodality_index: Optional[float] = None
    trough_depth_n: Optional[float] = None
    first_peak_idx: Optional[int] = None
    trough_idx: Optional[int] = None
    second_peak_idx: Optional[int] = None
    if contraction_start is not None and takeoff_idx is not None and takeoff_idx > contraction_start + 25:
        bimodal, first_peak_idx, trough_idx, second_peak_idx, bimodality_index, trough_depth_n = _detect_bimodal_takeoff_points(
            force_work,
            contraction_start,
            takeoff_idx,
            min_peak_ratio=cfg.bimodal_min_peak_ratio,
            prominence_pct_bw=cfg.bimodal_prominence_pct_bw,
            min_separation_ms=cfg.bimodal_min_separation_ms,
            sr=sr,
        )

    points = SquatJumpPoints(
        contraction_start=contraction_start,
        peak_force_index=peak_force_index if contraction_start is not None else None,
        takeoff_index=takeoff_idx,
        landing_index=landing_idx,
        peak_landing_index=peak_landing_idx,
        first_peak_index=first_peak_idx,
        trough_between_peaks_index=trough_idx,
        second_peak_index=second_peak_idx,
    )

    extra = {
        "countermovement": countermovement,
        "bimodal": bimodal,
        "bimodality_index": bimodality_index,
        "trough_depth_N": trough_depth_n,
        "quiet_noisy": quiet_noisy,
    }
    return points, bw, sigma_quiet, extra


def compute_sj_metrics(
    trial: CMJTrial,
    points: SquatJumpPoints,
    bodyweight: float,
    flags: Dict[str, Any],
    config: Optional[SquatJumpConfig] = None,
) -> Dict[str, Any]:
    """Compute SJ metrics: contraction time, flight time, jump height, peak force, RFD, impulse, etc."""
    cfg = config or DEFAULT_SJ_CONFIG
    force = trial.force
    left_f = trial.left_force
    right_f = trial.right_force
    n = len(force)
    sr = trial.sample_rate
    dt = 1.0 / sr

    cs = points.contraction_start
    pf_idx = points.peak_force_index
    to_idx = points.takeoff_index
    land_idx = points.landing_index

    out: Dict[str, Any] = {
        "contraction_time_s": None,
        "flight_time_s": None,
        "jump_height_m": None,
        "peak_force_N": None,
        "max_rfd_N_s": None,
        "time_to_max_rfd_s": None,
        "impulse_Ns": None,
        "mean_force_N": None,
        "time_to_peak_s": None,
        "bimodality_index": flags.get("bimodality_index"),
        "trough_depth_N": flags.get("trough_depth_N"),
        "peak_force_asymmetry_pct": None,
        "impulse_asymmetry_pct": None,
        "rfd_asymmetry_pct": None,
    }

    if cs is None or to_idx is None:
        return out

    # Contraction time
    out["contraction_time_s"] = float((to_idx - cs) * dt)

    # Flight time and jump height (flight time method: h = g*T^2/8)
    if land_idx is not None:
        t_flight = (land_idx - to_idx) * dt
        out["flight_time_s"] = float(t_flight)
        out["jump_height_m"] = float(9.81 * (t_flight ** 2) / 8.0)

    # Peak force (concentric)
    if pf_idx is not None and cs <= pf_idx <= to_idx:
        out["peak_force_N"] = float(force[pf_idx])

    # RFD: derivative over window, max between contraction_start and peak_force
    rfd_window = _ms_to_samples(cfg.rfd_window_ms, sr)
    rfd = np.gradient(
        _smooth_force(force, sr, cfg.rfd_window_ms, 3),
        dt,
    )
    search_end = pf_idx if pf_idx is not None else to_idx
    if search_end is not None and cs < search_end:
        rfd_seg = rfd[cs : search_end + 1]
        if len(rfd_seg) > 0:
            max_rfd_val = float(np.max(rfd_seg))
            max_rfd_rel = int(np.argmax(rfd_seg))
            out["max_rfd_N_s"] = max_rfd_val
            out["time_to_max_rfd_s"] = float(max_rfd_rel * dt)

    # Impulse (concentric): integral of (force - baseline) from contraction_start to takeoff
    t_seg = np.arange(cs, to_idx + 1, dtype=float) * dt
    if len(t_seg) > 1:
        impulse = trapezoid(force[cs : to_idx + 1] - bodyweight, t_seg)
        out["impulse_Ns"] = float(impulse)
    f_conc = force[cs : to_idx + 1]
    out["mean_force_N"] = float(np.mean(f_conc))

    # Time to peak
    if pf_idx is not None:
        out["time_to_peak_s"] = float((pf_idx - cs) * dt)

    # Bilateral asymmetry (if dual plate)
    if (
        len(left_f) == n and len(right_f) == n
        and cs is not None and to_idx is not None
    ):
        sl = slice(cs, to_idx + 1)
        L_peak = float(np.max(left_f[sl]))
        R_peak = float(np.max(right_f[sl]))
        if (L_peak + R_peak) > 0:
            out["peak_force_asymmetry_pct"] = float(
                100.0 * abs(L_peak - R_peak) / (L_peak + R_peak)
            )
        J_L = trapezoid(left_f[sl], np.arange(cs, to_idx + 1, dtype=float) * dt)
        J_R = trapezoid(right_f[sl], np.arange(cs, to_idx + 1, dtype=float) * dt)
        if (J_L + J_R) != 0:
            out["impulse_asymmetry_pct"] = float(
                100.0 * abs(J_L - J_R) / (J_L + J_R)
            )
        rfd_L = np.gradient(_smooth_force(left_f, sr, cfg.rfd_window_ms, 3), dt)
        rfd_R = np.gradient(_smooth_force(right_f, sr, cfg.rfd_window_ms, 3), dt)
        peak_rfd_L = float(np.max(rfd_L[sl]))
        peak_rfd_R = float(np.max(rfd_R[sl]))
        if (peak_rfd_L + peak_rfd_R) > 0:
            out["rfd_asymmetry_pct"] = float(
                100.0 * abs(peak_rfd_L - peak_rfd_R) / (peak_rfd_L + peak_rfd_R)
            )

    return out


def classify_squat_jump(
    points: SquatJumpPoints,
    metrics: Dict[str, Any],
    flags: Dict[str, Any],
    bodyweight: float,
    config: Optional[SquatJumpConfig] = None,
) -> str:
    """
    Classify as optimal_squat_jump or injured_or_fatigued_squat_jump.

    Rule: countermovement dip is the only classifier for this distinction.
    - Optimal: chart goes up without countermovement (no sustained dip below BW before the rise).
    - Injured: chart has a countermovement dip (sustained force drop below baseline before the rise).

    Invalid trials (no takeoff/landing) are classified as injured for consistency.
    """
    # Countermovement dip present => injured squat jump
    if flags.get("countermovement"):
        return "injured_or_fatigued_squat_jump"

    # No countermovement + valid jump => optimal squat jump (force went up without a dip)
    if points.takeoff_index is not None and points.landing_index is not None:
        flight_time = metrics.get("flight_time_s")
        if flight_time is not None and flight_time >= (config or DEFAULT_SJ_CONFIG).flight_time_min_s:
            return "optimal_squat_jump"

    # Invalid or no flight => injured for consistency
    return "injured_or_fatigued_squat_jump"


def validate_squat_jump_trial(
    points: SquatJumpPoints,
    metrics: Dict[str, Any],
    flight_time_min_s: float = DEFAULT_FLIGHT_TIME_MIN_S,
) -> Tuple[bool, List[str]]:
    """Validity: clear takeoff, flight >= 100 ms, event order."""
    flags: List[str] = []
    if points.takeoff_index is None:
        flags.append("no_takeoff")
    if points.landing_index is None and points.takeoff_index is not None:
        flags.append("no_landing")
    if points.contraction_start is None:
        flags.append("no_contraction_start")
    # Event order
    if points.contraction_start is not None and points.peak_force_index is not None:
        if points.peak_force_index < points.contraction_start:
            flags.append("event_order_invalid")
    if points.peak_force_index is not None and points.takeoff_index is not None:
        if points.takeoff_index < points.peak_force_index:
            flags.append("event_order_invalid")
    if points.takeoff_index is not None and points.landing_index is not None:
        if points.landing_index <= points.takeoff_index:
            flags.append("event_order_invalid")
    flight_time = metrics.get("flight_time_s")
    if flight_time is not None and flight_time < flight_time_min_s:
        flags.append("short_flight")
    is_valid = len(flags) == 0
    return is_valid, flags


def run_squat_jump_analysis(
    trial: CMJTrial,
    config: Optional[SquatJumpConfig] = None,
    bodyweight: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Full SJ pipeline: detect events, compute metrics, classify, validate.

    Returns the spec output format:
      events (times in s), metrics, flags (countermovement, bimodal, asymmetry_flag),
      classification, validity.
    """
    cfg = config or DEFAULT_SJ_CONFIG
    points, bw, sigma_quiet, extra = detect_squat_jump_events(
        trial, config=cfg, bodyweight=bodyweight
    )
    flags: Dict[str, bool] = {
        "countermovement": extra["countermovement"],
        "bimodal": extra["bimodal"],
        "asymmetry_flag": False,
    }
    metrics = compute_sj_metrics(trial, points, bw, extra, config=cfg)
    asym = metrics.get("peak_force_asymmetry_pct")
    if asym is not None and asym > cfg.asymmetry_optimal_pct:
        flags["asymmetry_flag"] = True

    classification = classify_squat_jump(points, metrics, extra, bw, config=cfg)
    is_valid, validity_flags = validate_squat_jump_trial(
        points, metrics, flight_time_min_s=cfg.flight_time_min_s
    )

    # Event times in seconds
    sr = trial.sample_rate
    t = trial.t
    n = len(trial.force)

    def _time(idx: Optional[int]) -> Optional[float]:
        if idx is None or idx < 0 or idx >= n:
            return None
        return float(t[idx])

    events_t = {
        "contraction_start": _time(points.contraction_start),
        "peak_force_time": _time(points.peak_force_index),
        "takeoff": _time(points.takeoff_index),
        "landing": _time(points.landing_index),
    }
    if points.first_peak_index is not None:
        events_t["first_peak_time"] = _time(points.first_peak_index)
    if points.trough_between_peaks_index is not None:
        events_t["trough_between_peaks_time"] = _time(points.trough_between_peaks_index)
    if points.second_peak_index is not None:
        events_t["second_peak_time"] = _time(points.second_peak_index)

    # Spec: metrics dict with all keys (value or None)
    metrics_out = {k: metrics.get(k) for k in [
        "contraction_time_s", "flight_time_s", "jump_height_m", "peak_force_N",
        "max_rfd_N_s", "time_to_max_rfd_s", "impulse_Ns", "mean_force_N",
        "time_to_peak_s", "bimodality_index", "trough_depth_N", "peak_force_asymmetry_pct",
        "impulse_asymmetry_pct", "rfd_asymmetry_pct",
    ]}
    for k, v in metrics.items():
        if k in metrics_out:
            metrics_out[k] = v

    return {
        "events": events_t,
        "metrics": metrics_out,
        "flags": flags,
        "classification": classification,
        "validity": {"is_valid": is_valid, "flags": validity_flags},
        # Extra for export/viz (non-serialized)
        "_points": points,
        "_bodyweight": bw,
        "_metrics_full": metrics,
    }
