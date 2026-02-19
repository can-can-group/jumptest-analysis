"""Bodyweight, mass, and quiet-phase std from weighing phase."""
from typing import Union

import numpy as np

from ..data.types import CMJTrial

G = 9.81


def compute_baseline(
    trial: CMJTrial, weighing_seconds: float = 1.0
) -> tuple[float, float, float]:
    """Compute bodyweight (N), mass (kg), and sigma_quiet from the first weighing_seconds.

    Uses mean and std of vertical force over the weighing phase; mass = BW / g.
    sigma_quiet is used for statistical movement-onset detection.

    Returns:
        (bodyweight_N, mass_kg, sigma_quiet_N).
    """
    n_weighing = min(int(trial.sample_rate * weighing_seconds), trial.sample_count)
    if n_weighing <= 0:
        n_weighing = min(int(trial.sample_rate * 0.1), trial.sample_count)
    seg = trial.force[:n_weighing]
    bodyweight = float(np.mean(seg))
    mass = bodyweight / G
    sigma_quiet = float(np.std(seg)) if len(seg) > 1 else 0.0
    return bodyweight, mass, sigma_quiet


def compute_baseline_drop_jump(
    trial_or_force: Union[CMJTrial, np.ndarray],
    trailing_seconds: float = 0.8,
    min_force_threshold_n: float = 100.0,
    sample_rate: float = 0.0,
) -> tuple[float, float, float]:
    """Compute bodyweight for a drop jump trial from post-landing stabilization.

    DJ trials start with near-zero force (athlete on box), so the initial weighing
    window used for CMJ is not applicable. Instead, bodyweight is estimated from the
    final *trailing_seconds* of the trial where force >= *min_force_threshold_n*
    (post-landing stabilization, where the athlete stands still on the plate).

    Falls back to the global mean of samples above the threshold if the trailing
    window has insufficient data.

    Args:
        trial_or_force: A CMJTrial object or raw force array.
        trailing_seconds: Duration (s) from end of trial used for BW estimation.
        min_force_threshold_n: Only samples with force >= this value are used.
        sample_rate: Required when *trial_or_force* is a raw array.

    Returns:
        (bodyweight_N, mass_kg, sigma_quiet_N).
    """
    if isinstance(trial_or_force, CMJTrial):
        force = trial_or_force.force
        fs = trial_or_force.sample_rate
    else:
        force = np.asarray(trial_or_force, dtype=float)
        fs = sample_rate

    n = len(force)
    if n == 0 or fs <= 0:
        return 0.0, 0.0, 0.0

    trailing_samples = min(int(fs * trailing_seconds), n)
    seg = force[n - trailing_samples :]
    above = seg[seg >= min_force_threshold_n]

    if len(above) >= max(10, int(fs * 0.05)):
        bodyweight = float(np.mean(above))
        sigma = float(np.std(above)) if len(above) > 1 else 0.0
    else:
        all_above = force[force >= min_force_threshold_n]
        if len(all_above) > 0:
            bodyweight = float(np.mean(all_above))
            sigma = float(np.std(all_above)) if len(all_above) > 1 else 0.0
        else:
            bodyweight = float(np.mean(force))
            sigma = float(np.std(force)) if n > 1 else 0.0

    mass = bodyweight / G
    return bodyweight, mass, sigma
