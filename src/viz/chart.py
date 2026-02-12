"""Single chart: total, left, and right force vs time; optional event lines."""
from pathlib import Path
from typing import Optional

import numpy as np

from ..data.types import CMJTrial, CMJEvents, TrialValidity


def plot_force(
    trial: CMJTrial,
    events: Optional[CMJEvents] = None,
    bodyweight: Optional[float] = None,
    output_path: Optional[Path] = None,
    validity: Optional[TrialValidity] = None,
) -> None:
    """Plot total, left, and right force on one chart. Optionally add event lines and bodyweight.

    Args:
        trial: Loaded CMJ trial.
        events: If provided, vertical lines at movement_onset, take_off, landing, min_force, etc.
        bodyweight: If provided, horizontal line at this value (N).
        output_path: If provided, save figure here; otherwise display.
        validity: If provided and not valid, title includes flags.
    """
    try:
        import matplotlib
        if output_path is not None:
            matplotlib.use("Agg")  # no display when saving to file
        import matplotlib.pyplot as plt
    except ImportError:
        raise ImportError("matplotlib is required for plot_force. Install with: pip install matplotlib") from None

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(trial.t, trial.force, color="black", linewidth=1.5, label="Total force")
    ax.plot(trial.t, trial.left_force, color="blue", linewidth=1, linestyle="--", alpha=0.8, label="Left force")
    ax.plot(trial.t, trial.right_force, color="red", linewidth=1, linestyle="--", alpha=0.8, label="Right force")

    if bodyweight is not None:
        ax.axhline(y=bodyweight, color="gray", linewidth=1, linestyle=":", label=f"Bodyweight ({bodyweight:.0f} N)")

    if events is not None:
        colors = {"Movement onset": "green", "Take-off": "orange", "Landing": "brown"}
        if events.movement_onset is not None:
            t_onset = trial.t[events.movement_onset]
            ax.axvline(x=t_onset, color=colors["Movement onset"], linewidth=1, linestyle="-", alpha=0.8)
            ax.text(t_onset, ax.get_ylim()[1] * 0.98, "onset", fontsize=8, color=colors["Movement onset"], ha="left")
        if events.take_off is not None:
            t_to = trial.t[events.take_off]
            ax.axvline(x=t_to, color=colors["Take-off"], linewidth=1, linestyle="-", alpha=0.8)
            ax.text(t_to, ax.get_ylim()[1] * 0.98, "take-off", fontsize=8, color=colors["Take-off"], ha="left")
        if events.landing is not None:
            t_land = trial.t[events.landing]
            ax.axvline(x=t_land, color=colors["Landing"], linewidth=1, linestyle="-", alpha=0.8)
            ax.text(t_land, ax.get_ylim()[1] * 0.98, "landing", fontsize=8, color=colors["Landing"], ha="left")
        if events.eccentric_end is not None:
            t_ecc = trial.t[events.eccentric_end]
            ax.axvline(x=t_ecc, color="purple", linewidth=0.8, linestyle="--", alpha=0.7)
            ax.text(t_ecc, ax.get_ylim()[1] * 0.98, "ecc end", fontsize=8, color="purple", ha="left")
        if events.velocity_zero is not None:
            t_v0 = trial.t[events.velocity_zero]
            ax.axvline(x=t_v0, color="teal", linewidth=0.8, linestyle="--", alpha=0.7)
            ax.text(t_v0, ax.get_ylim()[1] * 0.98, "v=0", fontsize=8, color="teal", ha="left")
        if events.min_force is not None:
            t_mf = trial.t[events.min_force]
            ax.axvline(x=t_mf, color="darkorange", linewidth=0.8, linestyle="-.", alpha=0.8)
            ax.text(t_mf, ax.get_ylim()[1] * 0.98, "min F", fontsize=8, color="darkorange", ha="left")

    title = f"CMJ Force — {trial.athlete_id} ({trial.test_type})"
    if validity is not None and not validity.is_valid and validity.flags:
        title += f"  [Flags: {', '.join(validity.flags)}]"
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Force (N)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
    else:
        plt.show()
