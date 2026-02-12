"""Low-pass filter for force signal (e.g. before event detection)."""
import numpy as np
from scipy.signal import butter, filtfilt


def lowpass_filter(signal: np.ndarray, sample_rate: float, cutoff_hz: float, order: int = 4) -> np.ndarray:
    """Zero-phase low-pass Butterworth filter.

    Args:
        signal: 1D force (or other) signal.
        sample_rate: Sampling frequency in Hz.
        cutoff_hz: Cutoff frequency in Hz (e.g. 50 or 100).
        order: Butterworth order (default 4).

    Returns:
        Filtered signal, same shape as input.
    """
    nyq = 0.5 * sample_rate
    normal_cutoff = cutoff_hz / nyq
    if normal_cutoff >= 1.0:
        return signal.copy()
    b, a = butter(order, normal_cutoff, btype="low", analog=False)
    return filtfilt(b, a, signal.astype(float))
