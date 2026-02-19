"""
Robust biomechanical event detection for Drop Jump vertical GRF (vGRF) time-series.

Two-phase approach:
  1. Find the two main "contact episodes" (sustained high force) using a BW-based
     threshold so pre-jump noise is never confused with contact.
  2. Refine contact_start, takeoff, Peak 1, trough, Peak 2 within the first episode,
     and landing_contact / landing_peak from the second episode.

Peak identity is by temporal position (impact window vs drive-off), not amplitude.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import find_peaks


# ---------------------------------------------------------------------------
# Default configurable thresholds (with rationale)
# ---------------------------------------------------------------------------
DEFAULT_CONTACT_THRESHOLD_N = 20.0
"""Force above this (N) indicates contact; below indicates flight (for takeoff/landing edges)."""

DEFAULT_CONTACT_SUSTAIN_MS = 10.0
"""Contact/takeoff must persist this long (ms) to avoid noise."""

# Episode detection: only consider "contact" when force is clearly above pre-jump noise.
DEFAULT_EPISODE_THRESHOLD_PCT_BW = 0.25
"""Contact episode = force > max(episode_threshold_n, this * BW). Default 25% BW."""
DEFAULT_EPISODE_THRESHOLD_N = 200.0
"""Minimum force (N) to count as in-episode; avoids pre-jump noise < 200 N."""
DEFAULT_EPISODE_MIN_DURATION_MS = 40.0
"""Episode must last at least this long (ms)."""
DEFAULT_EPISODE_MIN_PEAK_PCT_BW = 0.35
"""Episode must contain at least one sample >= this * BW (reject tiny bumps)."""

DEFAULT_PEAK1_WINDOW_MS = 120.0
"""Impact peak (Peak 1) is searched only within this window after contact start."""

DEFAULT_PEAK1_PROMINENCE_PCT_BW = 10.0
"""Peak 1 minimum prominence as % of bodyweight."""

DEFAULT_PEAK2_PROMINENCE_PCT_BW_MIN = 5.0
DEFAULT_PEAK2_PROMINENCE_PCT_BW_MAX = 10.0
"""Peak 2 (drive-off) prominence as % BW."""

DEFAULT_LANDING_SEARCH_MS = 150.0
"""After second contact, landing peak is the max in this window (ms)."""

# Legacy (kept for API compatibility; episode logic overrides pre-contact)
DEFAULT_PRE_CONTACT_THRESHOLD_N = 100.0
DEFAULT_PRE_CONTACT_MIN_DURATION_MS = 50.0

_SLOPE_MARGIN = 2


def _ms_to_samples(ms: float, fs: float) -> int:
    """Convert time in milliseconds to number of samples."""
    return max(1, int(round(fs * ms / 1000.0)))


def _first_crossing_above_sustained(
    force: np.ndarray,
    threshold: float,
    start: int,
    end: int,
    min_samples: int,
) -> Optional[int]:
    """
    First index in [start, end] where force rises above threshold and stays
    above for at least min_samples. Returns the index of the first sample above.
    """
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


def _first_segment_below_sustained(
    force: np.ndarray,
    threshold: float,
    start: int,
    end: int,
    min_samples: int,
) -> Optional[int]:
    """
    First index in [start, end] where force is below threshold and stays below
    for at least min_samples. Returns that start index.
    """
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


def _find_contact_episodes(
    force: np.ndarray,
    fs: float,
    bw: float,
    episode_threshold_n: float,
    episode_threshold_pct_bw: float,
    min_duration_samples: int,
    min_peak_pct_bw: float,
    flight_gap_ms: float = 50.0,
) -> List[Tuple[int, int]]:
    """
    Find the first two "contact episodes": sustained high-force regions separated
    by at least flight_gap_ms of low force. Short dips within contact are merged.
    """
    n = len(force)
    thresh = max(episode_threshold_n, episode_threshold_pct_bw * bw)
    min_peak = min_peak_pct_bw * bw
    flight_gap_samples = max(1, int(round(fs * flight_gap_ms / 1000.0)))
    episodes: List[Tuple[int, int]] = []
    i = 0
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    while i < n and len(episodes) < 2:
        if force[i] > thresh:
            if current_start is None:
                current_start = i
            current_end = i
            i += 1
            continue
        if current_start is not None and current_end is not None:
            gap_len = 0
            j = i
            while j < n and force[j] <= thresh and gap_len < flight_gap_samples:
                gap_len += 1
                j += 1
            if gap_len >= flight_gap_samples:
                duration = current_end - current_start + 1
                if duration >= min_duration_samples:
                    peak_in = float(np.max(force[current_start : current_end + 1]))
                    if peak_in >= min_peak:
                        episodes.append((current_start, current_end))
                current_start = None
                current_end = None
                i = j
            else:
                i = j
        else:
            i += 1
    if len(episodes) < 2 and current_start is not None and current_end is not None:
        duration = current_end - current_start + 1
        if duration >= min_duration_samples:
            peak_in = float(np.max(force[current_start : current_end + 1]))
            if peak_in >= min_peak and (not episodes or (current_start, current_end) != episodes[-1]):
                episodes.append((current_start, current_end))
    return episodes


def _first_crossing_below_sustained(
    force: np.ndarray,
    threshold: float,
    start: int,
    end: int,
    min_samples: int,
) -> Optional[int]:
    """
    First index in [start, end] where force drops below threshold and stays
    below for at least min_samples. Returns the index of the first sample below.
    """
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


def _slope_before_positive(force: np.ndarray, idx: int, margin: int = _SLOPE_MARGIN) -> bool:
    """True if there is positive slope (force rising) before idx."""
    if idx < margin:
        return True
    return force[idx] > force[idx - margin]


def _slope_after_negative(force: np.ndarray, idx: int, margin: int = _SLOPE_MARGIN) -> bool:
    """True if there is negative slope (force falling) after idx."""
    n = len(force)
    if idx + margin >= n:
        return True
    return force[idx] > force[idx + margin]


def _slope_before_negative(force: np.ndarray, idx: int, margin: int = _SLOPE_MARGIN) -> bool:
    """True if force is decreasing into idx (trough)."""
    if idx < margin:
        return True
    return force[idx] < force[idx - margin]


def _slope_after_positive(force: np.ndarray, idx: int, margin: int = _SLOPE_MARGIN) -> bool:
    """True if force is increasing after idx (trough)."""
    n = len(force)
    if idx + margin >= n:
        return True
    return force[idx] < force[idx + margin]


def detect_drop_jump_vgrf(
    force: np.ndarray,
    fs: float,
    bw: float,
    *,
    contact_threshold_n: float = DEFAULT_CONTACT_THRESHOLD_N,
    contact_sustain_ms: float = DEFAULT_CONTACT_SUSTAIN_MS,
    pre_contact_threshold_n: float = DEFAULT_PRE_CONTACT_THRESHOLD_N,
    pre_contact_min_duration_ms: float = DEFAULT_PRE_CONTACT_MIN_DURATION_MS,
    episode_threshold_n: float = DEFAULT_EPISODE_THRESHOLD_N,
    episode_threshold_pct_bw: float = DEFAULT_EPISODE_THRESHOLD_PCT_BW,
    episode_min_duration_ms: float = DEFAULT_EPISODE_MIN_DURATION_MS,
    episode_min_peak_pct_bw: float = DEFAULT_EPISODE_MIN_PEAK_PCT_BW,
    peak1_window_ms: float = DEFAULT_PEAK1_WINDOW_MS,
    peak1_prominence_pct_bw: float = DEFAULT_PEAK1_PROMINENCE_PCT_BW,
    peak2_prominence_pct_bw_min: float = DEFAULT_PEAK2_PROMINENCE_PCT_BW_MIN,
    peak2_prominence_pct_bw_max: float = DEFAULT_PEAK2_PROMINENCE_PCT_BW_MAX,
    landing_search_ms: float = DEFAULT_LANDING_SEARCH_MS,
) -> Dict[str, Optional[int]]:
    """
    Detect biomechanical events in drop jump vGRF using a two-phase approach.

    Phase 1: Find the two main contact episodes (sustained force above 25% BW / 200 N)
    so pre-jump noise is never confused with contact.
    Phase 2: Refine contact_start, takeoff, Peak 1, trough, Peak 2 within the first
    episode; landing_contact and landing_peak from the second episode.

    Returns
    -------
    dict
        Keys: contact_start_index, peak1_index, contact_trough_index, peak2_index,
        takeoff_index, landing_contact_index, landing_peak_index. Values are sample indices or None.
    """
    force = np.asarray(force, dtype=float)
    n = len(force)
    out: Dict[str, Optional[int]] = {
        "contact_start_index": None,
        "peak1_index": None,
        "contact_trough_index": None,
        "peak2_index": None,
        "takeoff_index": None,
        "landing_contact_index": None,
        "landing_peak_index": None,
    }
    if n < 10 or fs <= 0 or bw <= 0:
        return out

    sustain_samples = _ms_to_samples(contact_sustain_ms, fs)
    episode_min_samples = _ms_to_samples(episode_min_duration_ms, fs)
    peak1_window_samples = _ms_to_samples(peak1_window_ms, fs)
    landing_window_samples = _ms_to_samples(landing_search_ms, fs)

    # ----- Phase 1: Find the two contact episodes (high-force regions) -----
    episodes = _find_contact_episodes(
        force, fs, bw,
        episode_threshold_n=episode_threshold_n,
        episode_threshold_pct_bw=episode_threshold_pct_bw,
        min_duration_samples=episode_min_samples,
        min_peak_pct_bw=episode_min_peak_pct_bw,
    )
    if len(episodes) < 1:
        return out
    ep1_start, ep1_end = episodes[0]

    # Contact start: leading edge of first episode (first sustained rise to contact_threshold before/during episode)
    search_back = _ms_to_samples(150.0, fs)
    contact_search_start = max(0, ep1_start - search_back)
    contact_start = _first_crossing_above_sustained(
        force, contact_threshold_n, contact_search_start, min(ep1_start + 1, n - 1), sustain_samples
    )
    if contact_start is None:
        contact_start = ep1_start
    out["contact_start_index"] = contact_start

    # Takeoff: first sustained drop below contact_threshold after first episode
    takeoff = _first_crossing_below_sustained(
        force, contact_threshold_n, contact_start + 1, n - 1, sustain_samples
    )
    out["takeoff_index"] = takeoff
    if takeoff is None or takeoff <= contact_start + 1:
        return out

    contact_end = takeoff
    if contact_end - contact_start < 3:
        return out

    # ----- Phase 2: Peak 1 (Impact) in first 120 ms of contact -----
    peak1_search_end = min(contact_start + peak1_window_samples, contact_end - 1)
    if peak1_search_end <= contact_start + 1:
        peak1_search_end = contact_start + 1
    segment = force[contact_start : peak1_search_end + 1]
    prominence_min = (peak1_prominence_pct_bw / 100.0) * bw
    peaks1, _ = find_peaks(segment, prominence=prominence_min, width=1)
    peak1_index = None
    for idx in peaks1:
        global_idx = contact_start + int(idx)
        if _slope_before_positive(force, global_idx) and _slope_after_negative(force, global_idx):
            peak1_index = global_idx
            break
    if peak1_index is None and len(peaks1) > 0:
        peak1_index = contact_start + int(peaks1[0])
    out["peak1_index"] = peak1_index

    # ----- Contact trough: deepest local min between Peak 1 and takeoff -----
    trough_start = (peak1_index if peak1_index is not None else contact_start) + 1
    trough_end = contact_end - 1
    contact_trough_index = None
    if trough_end > trough_start:
        neg_force = -force[trough_start : trough_end + 1]
        prominence_trough = (2.0 / 100.0) * bw
        peaks_neg, _ = find_peaks(neg_force, prominence=prominence_trough, width=1)
        candidates = [(trough_start + int(i), force[trough_start + int(i)]) for i in peaks_neg]
        for idx, _ in candidates:
            if _slope_before_negative(force, idx) and _slope_after_positive(force, idx):
                if contact_trough_index is None or force[idx] < force[contact_trough_index]:
                    contact_trough_index = idx
        if contact_trough_index is None and candidates:
            contact_trough_index = min(candidates, key=lambda x: x[1])[0]
    out["contact_trough_index"] = contact_trough_index

    # ----- Peak 2 (Drive-off): last prominent local max before takeoff -----
    drive_start = (contact_trough_index if contact_trough_index is not None else trough_start)
    if drive_start >= contact_end - 1:
        drive_start = (peak1_index if peak1_index is not None else contact_start) + 1
    drive_end = contact_end - 1
    peak2_index = None
    if drive_end > drive_start:
        prom_min = (peak2_prominence_pct_bw_min / 100.0) * bw
        peaks2, _ = find_peaks(force[drive_start : drive_end + 1], prominence=prom_min, width=1)
        valid = [
            drive_start + int(idx) for idx in peaks2
            if _slope_before_positive(force, drive_start + int(idx))
            and _slope_after_negative(force, drive_start + int(idx))
        ]
        if valid:
            peak2_index = max(valid, key=lambda i: i)
        elif len(peaks2) > 0:
            peak2_index = drive_start + int(peaks2[-1])
    out["peak2_index"] = peak2_index

    # ----- Landing: from second episode or first sustained contact after takeoff -----
    if len(episodes) >= 2:
        ep2_start, ep2_end = episodes[1]
        out["landing_contact_index"] = ep2_start
        search_end = min(ep2_start + landing_window_samples, n - 1)
        if search_end > ep2_start:
            segment_land = force[ep2_start : search_end + 1]
            out["landing_peak_index"] = ep2_start + int(np.argmax(segment_land))
    else:
        second_contact = _first_crossing_above_sustained(
            force, contact_threshold_n, takeoff + 1, n - 1, sustain_samples
        )
        out["landing_contact_index"] = second_contact
        if second_contact is not None:
            search_end = min(second_contact + landing_window_samples, n - 1)
            if search_end > second_contact:
                segment_land = force[second_contact : search_end + 1]
                out["landing_peak_index"] = second_contact + int(np.argmax(segment_land))

    return out


def plot_drop_jump_vgrf_debug(
    force: np.ndarray,
    fs: float,
    events: Dict[str, Optional[int]],
    bw: Optional[float] = None,
    contact_threshold_n: float = DEFAULT_CONTACT_THRESHOLD_N,
    title: str = "Drop Jump vGRF – detected events",
    ax=None,
) -> Any:
    """
    Plot force trace and detected event indices for debugging.

    Parameters
    ----------
    force : np.ndarray
        1D force (N).
    fs : float
        Sampling frequency (Hz).
    events : dict
        Output of detect_drop_jump_vgrf (sample indices).
    bw : float, optional
        Bodyweight for horizontal line; if None, not drawn.
    contact_threshold_n : float
        Threshold line (N).
    title : str
        Plot title.
    ax : matplotlib axes, optional
        If provided, draw on this axes; otherwise create new figure.

    Returns
    -------
    matplotlib axes (or figure if ax was None and figure was created).
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("matplotlib is required for plot_drop_jump_vgrf_debug")

    n = len(force)
    t = np.arange(n, dtype=float) / fs if fs > 0 else np.arange(n, dtype=float)
    if ax is None:
        fig, ax = plt.subplots(1, 1, figsize=(12, 5))
    ax.plot(t, force, color="k", linewidth=1.2, label="vGRF")
    ax.axhline(contact_threshold_n, color="gray", linestyle="--", linewidth=1, label=f"Contact thresh ({contact_threshold_n} N)")
    if bw is not None and bw > 0:
        ax.axhline(bw, color="green", linestyle=":", linewidth=1, label=f"Bodyweight ({bw:.0f} N)")

    labels = [
        ("contact_start_index", "Contact start", "blue", "o"),
        ("peak1_index", "Peak 1 (Impact)", "red", "v"),
        ("contact_trough_index", "Contact trough", "purple", "s"),
        ("peak2_index", "Peak 2 (Drive-off)", "orange", "v"),
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
