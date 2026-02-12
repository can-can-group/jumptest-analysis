"""Default configuration for CMJ detection and metrics."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class CMJConfig:
    """Default thresholds and durations for research-grade CMJ analysis."""

    weighing_seconds: float = 1.0
    take_off_threshold_n: Optional[float] = None  # None => max(20, 0.05*BW)
    take_off_consecutive_samples: int = 4
    landing_threshold_n: Optional[float] = None  # None => max(200, 0.05*BW)
    landing_sustain_ms: float = 20.0
    onset_below_bw: float = 0.05
    onset_n_sigma: float = 5.0
    onset_sustain_ms: float = 30.0
    flight_time_min_s: float = 0.1
    flight_time_max_s: float = 2.0
    rfd_savgol_window_ms: float = 20.0
    rfd_savgol_poly: int = 3
    # P1/P2: min separation (ms) so peaks are not too close; ~40–50% of typical P1–P2 distance (e.g. 200 ms)
    min_p1_p2_separation_ms: float = 80.0
    # P2 must be at least this fraction of P1 force (0 = disabled) to reject noise bumps
    min_peak2_force_ratio: float = 0.0


DEFAULT_CONFIG = CMJConfig()
