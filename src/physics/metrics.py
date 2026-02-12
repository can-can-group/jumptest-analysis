"""CMJ metrics: jump height, power, RFD, phase impulses, COM displacement, etc."""
from typing import Dict, Any, Optional

import numpy as np
from scipy.integrate import trapz, cumtrapz
from scipy.signal import savgol_filter

from ..config import DEFAULT_CONFIG
from ..data.types import CMJTrial, CMJEvents
from ..detect.structural_peaks import detect_peaks_smoothed_then_match

G = 9.81
RFD_SAVGOL_WINDOW_MS = 20.0
RFD_SAVGOL_POLY = 3


def _smooth_rfd(force: np.ndarray, t: np.ndarray, window_ms: float, poly: int, sr: float):
    """Savitzky-Golay smoothed force and its derivative (RFD)."""
    dt = 1.0 / sr
    w = max(3, int(sr * window_ms / 1000.0) | 1)
    if w > len(force):
        w = len(force) if len(force) % 2 else max(1, len(force) - 1)
    if poly >= w:
        poly = max(1, w - 1)
    f_smooth = savgol_filter(force.astype(float), window_length=w, polyorder=poly, mode="nearest")
    rfd = np.gradient(f_smooth, dt)
    return rfd


def compute_metrics(
    trial: CMJTrial,
    events: CMJEvents,
    bodyweight: float,
    velocity: np.ndarray,
    rfd_savgol_window_ms: float = RFD_SAVGOL_WINDOW_MS,
    rfd_savgol_poly: int = RFD_SAVGOL_POLY,
) -> Dict[str, Any]:
    """Compute all CMJ metrics including phase impulses, displacement, RSImod, RFD.

    Phase boundaries: unweighting = onset -> min_force; braking = min_force -> P1 (or v_zero);
    propulsion = P1 (or v_zero) -> take_off.
    """
    mass = bodyweight / G
    force = trial.force
    t = trial.t
    sr = trial.sample_rate
    dt = 1.0 / sr

    onset = events.movement_onset
    take_off = events.take_off
    landing = events.landing
    ecc_end = events.eccentric_end
    v_zero = events.velocity_zero
    min_force = events.min_force

    out: Dict[str, Any] = {}

    # Take-off velocity and jump height (impulse-momentum)
    if onset is not None and take_off is not None:
        impulse = trapz(force[onset : take_off + 1] - bodyweight, t[onset : take_off + 1])
        v_to = impulse / mass
        out["take_off_velocity_m_s"] = float(v_to)
        out["jump_height_impulse_m"] = float((v_to ** 2) / (2 * G))
        out["time_to_takeoff_s"] = float((take_off - onset) * dt)
        out["rsi_mod"] = float(out["jump_height_impulse_m"] / out["time_to_takeoff_s"]) if out["time_to_takeoff_s"] > 0 else None
    else:
        out["take_off_velocity_m_s"] = None
        out["jump_height_impulse_m"] = None
        out["time_to_takeoff_s"] = None
        out["rsi_mod"] = None

    # Flight time and jump height (flight time method)
    if take_off is not None and landing is not None:
        t_flight = (landing - take_off) * dt
        out["flight_time_s"] = float(t_flight)
        out["jump_height_flight_m"] = float(G * (t_flight ** 2) / 8.0)
    else:
        out["flight_time_s"] = None
        out["jump_height_flight_m"] = None

    # Peak power (P = F * v)
    if onset is not None and take_off is not None:
        contact_slice = slice(onset, take_off + 1)
        power = force[contact_slice] * velocity[contact_slice]
        out["peak_power_W"] = float(np.max(power))
    else:
        out["peak_power_W"] = None

    # RFD: Savitzky-Golay
    rfd = _smooth_rfd(force, t, rfd_savgol_window_ms, rfd_savgol_poly, sr)
    if onset is not None and take_off is not None:
        rfd_contact = rfd[onset : take_off + 1]
        out["peak_rfd_N_per_s"] = float(np.max(rfd_contact))
        max_rfd_idx_rel = int(np.argmax(rfd_contact))
        out["max_rfd_index"] = onset + max_rfd_idx_rel
        out["max_rfd_time_s"] = float(t[out["max_rfd_index"]])
        # 0-100 ms and 0-200 ms from onset
        n_100 = min(int(sr * 0.1), len(rfd_contact))
        n_200 = min(int(sr * 0.2), len(rfd_contact))
        out["rfd_0_100ms_N_per_s"] = float(np.max(rfd_contact[:n_100])) if n_100 > 0 else None
        out["rfd_0_200ms_N_per_s"] = float(np.max(rfd_contact[:n_200])) if n_200 > 0 else None
    else:
        out["peak_rfd_N_per_s"] = None
        out["max_rfd_index"] = None
        out["max_rfd_time_s"] = None
        out["rfd_0_100ms_N_per_s"] = None
        out["rfd_0_200ms_N_per_s"] = None
    if v_zero is not None and onset is not None:
        rfd_ecc = rfd[onset : v_zero + 1]
        out["peak_rfd_eccentric_N_per_s"] = float(np.max(rfd_ecc)) if len(rfd_ecc) > 0 else None
    else:
        out["peak_rfd_eccentric_N_per_s"] = None
    if take_off is not None and v_zero is not None:
        rfd_conc = rfd[v_zero : take_off + 1]
        out["peak_rfd_concentric_N_per_s"] = float(np.max(rfd_conc)) if len(rfd_conc) > 0 else None
    else:
        out["peak_rfd_concentric_N_per_s"] = None

    # Phase impulses and times: unweighting = onset -> min_force; braking/propulsion use P1 when available
    if min_force is not None and onset is not None:
        unweighting_impulse = trapz(force[onset : min_force + 1] - bodyweight, t[onset : min_force + 1])
        out["unweighting_impulse_Ns"] = float(unweighting_impulse)
        out["unweighting_time_s"] = float((min_force - onset) * dt)
    else:
        out["unweighting_impulse_Ns"] = None
        out["unweighting_time_s"] = None
    if ecc_end is not None and onset is not None:
        out["eccentric_time_s"] = float((ecc_end - onset) * dt)
    else:
        out["eccentric_time_s"] = None

    # Peak eccentric velocity (magnitude, positive = downward)
    if onset is not None and take_off is not None:
        v_contact = velocity[onset : take_off + 1]
        out["peak_eccentric_velocity_m_s"] = float(-np.min(v_contact)) if len(v_contact) > 0 else None
    else:
        out["peak_eccentric_velocity_m_s"] = None

    # Peak/mean concentric force (window: velocity_zero to take_off)
    if v_zero is not None and take_off is not None:
        f_conc = force[v_zero : take_off + 1]
        out["peak_concentric_force_N"] = float(np.max(f_conc))
        out["mean_concentric_force_N"] = float(np.mean(f_conc))
    else:
        out["peak_concentric_force_N"] = None
        out["mean_concentric_force_N"] = None

    # P1/P2 from min_force to take_off: smooth for detection, then match indices to original force
    if min_force is not None and take_off is not None and min_force < take_off:
        cfg = DEFAULT_CONFIG
        result = detect_peaks_smoothed_then_match(
            force,
            min_force,
            take_off,
            sample_rate=sr,
            min_p1_p2_separation_ms=cfg.min_p1_p2_separation_ms,
            min_peak2_force_ratio=cfg.min_peak2_force_ratio,
        )
        p1_idx = result.get("P1_index")
        p2_idx = result.get("P2_index")
        out["p1_peak_index"] = p1_idx
        out["p2_peak_index"] = p2_idx
        out["p1_peak_N"] = float(force[p1_idx]) if p1_idx is not None else None
        out["p2_peak_N"] = float(force[p2_idx]) if p2_idx is not None else None
    else:
        out["p1_peak_index"] = None
        out["p2_peak_index"] = None
        out["p1_peak_N"] = None
        out["p2_peak_N"] = None
    if min_force is not None:
        out["min_force_N"] = float(force[min_force])
    else:
        out["min_force_N"] = None

    # Braking = min_force -> P1 (or v_zero if no P1); propulsion = P1 (or v_zero) -> take_off
    p1_idx = out.get("p1_peak_index")
    braking_end = p1_idx if p1_idx is not None else v_zero
    if min_force is not None and braking_end is not None and braking_end >= min_force:
        braking_impulse = trapz(force[min_force : braking_end + 1] - bodyweight, t[min_force : braking_end + 1])
        out["braking_impulse_Ns"] = float(braking_impulse)
    else:
        out["braking_impulse_Ns"] = None
    if take_off is not None and braking_end is not None and braking_end <= take_off:
        propulsion_impulse = trapz(force[braking_end : take_off + 1] - bodyweight, t[braking_end : take_off + 1])
        out["propulsion_impulse_Ns"] = float(propulsion_impulse)
        out["concentric_time_s"] = float((take_off - braking_end) * dt)
    else:
        out["propulsion_impulse_Ns"] = None
        out["concentric_time_s"] = None

    # COM displacement from onset: s = cumtrapz(v, t)
    if onset is not None and take_off is not None and take_off >= onset:
        v_seg = velocity[onset : take_off + 1]
        t_seg = t[onset : take_off + 1]
        if len(v_seg) > 1:
            s_seg = cumtrapz(v_seg, t_seg, initial=0)
            out["countermovement_depth_m"] = float(np.min(s_seg))
            out["com_displacement_at_takeoff_m"] = float(s_seg[-1])
        else:
            out["countermovement_depth_m"] = None
            out["com_displacement_at_takeoff_m"] = None
    else:
        out["countermovement_depth_m"] = None
        out["com_displacement_at_takeoff_m"] = None

    return out
