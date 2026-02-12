"""Acceleration and velocity from force (COM kinematics), with drift correction."""
import numpy as np
from scipy.integrate import cumtrapz, trapz

from ..data.types import CMJTrial

G = 9.81


def compute_kinematics(
    trial: CMJTrial,
    bodyweight: float,
    onset_idx: int,
    take_off_idx: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute vertical COM acceleration and velocity from onset to take-off.

    a(t) = (F(t) - BW) / m. Velocity is integrated with v(onset)=0, then drift-corrected
    so that v(take_off) = J/m (impulse/mass). Correction: linear ramp from 0 at onset
    to (v_to_expected - v_integrated_at_TO) at take_off.

    Returns:
        (velocity array, acceleration array) both length sample_count. Units: m/s, m/s^2.
    """
    mass = bodyweight / G
    force = trial.force
    t = trial.t
    n = trial.sample_count

    a = (force - bodyweight) / mass

    if onset_idx is None or take_off_idx is None:
        return np.zeros(n), a
    start = max(0, onset_idx)
    end = min(take_off_idx + 1, n)
    if start >= end:
        v = np.zeros(n)
        return v, a

    t_seg = t[start:end]
    a_seg = a[start:end]
    f_seg = force[start:end]
    if len(t_seg) > 1:
        v_seg = cumtrapz(a_seg, t_seg, initial=0)
    else:
        v_seg = np.zeros_like(t_seg)

    # Drift correction: enforce v(take_off) = J/m
    J = trapz(f_seg - bodyweight, t_seg)
    v_to_expected = J / mass
    v_to_integrated = float(v_seg[-1])
    dt_seg = t_seg[-1] - t_seg[0]
    if dt_seg > 0:
        ramp = (v_to_expected - v_to_integrated) * (t_seg - t_seg[0]) / dt_seg
        v_seg = v_seg + ramp

    v = np.zeros(n)
    v[start:end] = v_seg
    return v, a
