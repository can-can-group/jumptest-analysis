"""Bodyweight, mass, and quiet-phase std from weighing phase."""
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
