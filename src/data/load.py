"""Load raw CMJ JSON exports and build typed trial data."""
import json
from pathlib import Path
from typing import Any, Dict, Union

import numpy as np

from .types import CMJTrial

REQUIRED_KEYS = {"athlete_id", "test_type", "test_duration", "sample_count", "force", "left_force", "right_force"}


def load_trial_from_dict(data: Dict[str, Any]) -> CMJTrial:
    """Build a CMJTrial from an in-memory dict (e.g. from an API request).

    Accepts the same logical fields as file-based JSON. For "force", either
    "force" or "total_force" is accepted; sample_count is derived from the
    force array length if not provided.

    Args:
        data: Dict with athlete_id, test_type, test_duration, force (or
              total_force), left_force, right_force. Optional: sample_count.

    Returns:
        CMJTrial with force arrays and time vector.

    Raises:
        ValueError: If required keys are missing or array lengths mismatch.
    """
    force_key = "force" if "force" in data else "total_force"
    required = {"athlete_id", "test_type", "test_duration", "left_force", "right_force"}
    if force_key not in data:
        required = required | {"force"}  # mention "force" in error
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    force = np.asarray(data[force_key], dtype=float)
    left_force = np.asarray(data["left_force"], dtype=float)
    right_force = np.asarray(data["right_force"], dtype=float)
    sample_count = int(data.get("sample_count", len(force)))
    test_duration = float(data["test_duration"])

    if len(force) != sample_count:
        raise ValueError(f"force length {len(force)} != sample_count {sample_count}")
    if len(left_force) != sample_count:
        raise ValueError(f"left_force length {len(left_force)} != sample_count {sample_count}")
    if len(right_force) != sample_count:
        raise ValueError(f"right_force length {len(right_force)} != sample_count {sample_count}")

    sample_rate = sample_count / test_duration
    t = np.arange(sample_count, dtype=float) / sample_rate

    return CMJTrial(
        athlete_id=str(data["athlete_id"]),
        test_type=str(data["test_type"]),
        test_duration=test_duration,
        sample_count=sample_count,
        force=force,
        left_force=left_force,
        right_force=right_force,
        sample_rate=sample_rate,
        t=t,
    )


def load_trial(path: Union[str, Path]) -> CMJTrial:
    """Load a single CMJ export JSON and return a validated CMJTrial.

    Args:
        path: Path to the JSON file.

    Returns:
        CMJTrial with force arrays and time vector.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If required keys are missing or array lengths mismatch.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        raise ValueError(f"Missing required keys: {missing}")

    sample_count = int(data["sample_count"])
    test_duration = float(data["test_duration"])
    force = np.asarray(data["force"], dtype=float)
    left_force = np.asarray(data["left_force"], dtype=float)
    right_force = np.asarray(data["right_force"], dtype=float)

    if len(force) != sample_count:
        raise ValueError(f"force length {len(force)} != sample_count {sample_count}")
    if len(left_force) != sample_count:
        raise ValueError(f"left_force length {len(left_force)} != sample_count {sample_count}")
    if len(right_force) != sample_count:
        raise ValueError(f"right_force length {len(right_force)} != sample_count {sample_count}")

    sample_rate = sample_count / test_duration
    t = np.arange(sample_count, dtype=float) / sample_rate

    return CMJTrial(
        athlete_id=str(data["athlete_id"]),
        test_type=str(data["test_type"]),
        test_duration=test_duration,
        sample_count=sample_count,
        force=force,
        left_force=left_force,
        right_force=right_force,
        sample_rate=sample_rate,
        t=t,
    )
