"""Load raw CMJ/DJ JSON exports and build typed trial data."""
import json
from pathlib import Path
from typing import Any, Dict, Union

import numpy as np

from .types import CMJTrial


def _resolve_force(data: Dict[str, Any]) -> np.ndarray:
    """Return total force array, accepting 'force' or 'total_force' key."""
    if "force" in data:
        return np.asarray(data["force"], dtype=float)
    if "total_force" in data:
        return np.asarray(data["total_force"], dtype=float)
    raise ValueError("Missing required key: 'force' (or 'total_force')")


def load_trial_from_dict(data: Dict[str, Any]) -> CMJTrial:
    """Build a CMJTrial from an in-memory dict (e.g. from an API request).

    Tolerant of missing optional fields:
      - athlete_id: falls back to 'name' key, then 'unknown'.
      - sample_count: derived from force array length if absent.
      - force key: accepts 'force' or 'total_force'.
    """
    force = _resolve_force(data)

    if "left_force" not in data or "right_force" not in data:
        raise ValueError("Missing required keys: left_force and/or right_force")
    if "test_duration" not in data:
        raise ValueError("Missing required key: test_duration")

    left_force = np.asarray(data["left_force"], dtype=float)
    right_force = np.asarray(data["right_force"], dtype=float)
    sample_count = int(data.get("sample_count", len(force)))
    test_duration = float(data["test_duration"])
    athlete_id = str(data.get("athlete_id") or data.get("name") or "unknown")
    test_type = str(data.get("test_type", "CMJ"))

    if len(force) != sample_count:
        sample_count = len(force)
    if len(left_force) != sample_count or len(right_force) != sample_count:
        min_len = min(len(force), len(left_force), len(right_force))
        force = force[:min_len]
        left_force = left_force[:min_len]
        right_force = right_force[:min_len]
        sample_count = min_len

    sample_rate = sample_count / test_duration
    t = np.arange(sample_count, dtype=float) / sample_rate

    return CMJTrial(
        athlete_id=athlete_id,
        test_type=test_type,
        test_duration=test_duration,
        sample_count=sample_count,
        force=force,
        left_force=left_force,
        right_force=right_force,
        sample_rate=sample_rate,
        t=t,
    )


def load_trial(path: Union[str, Path]) -> CMJTrial:
    """Load a single CMJ/DJ export JSON and return a validated CMJTrial.

    Tolerant of missing optional fields:
      - athlete_id: falls back to 'name' key, then 'unknown'.
      - sample_count: derived from force array length if absent.
      - force key: accepts 'force' or 'total_force'.

    Args:
        path: Path to the JSON file.

    Returns:
        CMJTrial with force arrays and time vector.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If critical keys are missing or array lengths are inconsistent.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    return load_trial_from_dict(data)
