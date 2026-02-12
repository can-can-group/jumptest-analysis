"""Left/right asymmetry metrics for CMJ (peak force, impulses, RFD)."""
from typing import Dict, Any, Optional

import numpy as np
from scipy.integrate import trapz
from scipy.signal import savgol_filter

from ..data.types import CMJTrial, CMJEvents

RFD_SAVGOL_WINDOW_MS = 20.0
RFD_SAVGOL_POLY = 3


def _asymmetry_index(left: float, right: float) -> Optional[float]:
    """Signed asymmetry: 2*(L-R)/(L+R)*100. Positive = left dominant."""
    s = left + right
    if s <= 0:
        return None
    return float(2.0 * (left - right) / s * 100.0)


def _rfd_signal(force: np.ndarray, sr: float, window_ms: float, poly: int) -> np.ndarray:
    dt = 1.0 / sr
    w = max(3, int(sr * window_ms / 1000.0) | 1)
    if w > len(force):
        w = len(force) if len(force) % 2 else max(1, len(force) - 1)
    if poly >= w:
        poly = max(1, w - 1)
    f_smooth = savgol_filter(force.astype(float), window_length=w, polyorder=poly, mode="nearest")
    return np.gradient(f_smooth, dt)


def compute_asymmetry(
    trial: CMJTrial,
    events: CMJEvents,
    rfd_savgol_window_ms: float = RFD_SAVGOL_WINDOW_MS,
    rfd_savgol_poly: int = RFD_SAVGOL_POLY,
) -> Dict[str, Any]:
    """Compute left/right asymmetry metrics. Returns empty dict if L/R not usable."""
    out: Dict[str, Any] = {}
    left_f = trial.left_force
    right_f = trial.right_force
    if len(left_f) != len(trial.force) or len(right_f) != len(trial.force):
        return out

    onset = events.movement_onset
    take_off = events.take_off
    v_zero = events.velocity_zero
    min_force = events.min_force
    t = trial.t
    sr = trial.sample_rate

    if onset is None or take_off is None:
        return out

    # Peak force asymmetry (concentric phase)
    if v_zero is not None:
        sl = slice(v_zero, take_off + 1)
        L_peak = float(np.max(left_f[sl]))
        R_peak = float(np.max(right_f[sl]))
        out["peak_force_asymmetry_pct"] = _asymmetry_index(L_peak, R_peak)
    else:
        out["peak_force_asymmetry_pct"] = None

    # Concentric impulse asymmetry
    if v_zero is not None:
        sl = slice(v_zero, take_off + 1)
        J_L = trapz(left_f[sl], t[sl])
        J_R = trapz(right_f[sl], t[sl])
        out["concentric_impulse_asymmetry_pct"] = _asymmetry_index(J_L, J_R)
    else:
        out["concentric_impulse_asymmetry_pct"] = None

    # Eccentric impulse asymmetry (onset to min_force)
    if min_force is not None:
        sl = slice(onset, min_force + 1)
        J_L = trapz(left_f[sl], t[sl])
        J_R = trapz(right_f[sl], t[sl])
        out["eccentric_impulse_asymmetry_pct"] = _asymmetry_index(J_L, J_R)
    else:
        out["eccentric_impulse_asymmetry_pct"] = None

    # RFD asymmetry: peak RFD left vs right over contact
    rfd_L = _rfd_signal(left_f, sr, rfd_savgol_window_ms, rfd_savgol_poly)
    rfd_R = _rfd_signal(right_f, sr, rfd_savgol_window_ms, rfd_savgol_poly)
    sl = slice(onset, take_off + 1)
    peak_rfd_L = float(np.max(rfd_L[sl]))
    peak_rfd_R = float(np.max(rfd_R[sl]))
    out["rfd_asymmetry_pct"] = _asymmetry_index(peak_rfd_L, peak_rfd_R)

    return out
