"""Render the CMJ video + synced force chart to a single MP4 file.

Composites the source video with a force-vs-time chart; a playhead moves
in sync with the video. Output is a video file (e.g. MP4) with audio preserved.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import load_trial
from src.data.types import CMJTrial
from src.detect import compute_baseline, detect_events


def render_chart_frame(
    trial: CMJTrial,
    playhead_time: float,
    width: int,
    height: int,
    dpi: int = 100,
) -> np.ndarray:
    """Draw force chart with playhead at playhead_time; return RGB array (H, W, 3)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_w = width / dpi
    fig_h = height / dpi
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor("#252525")
    ax.set_facecolor("#252525")

    ax.plot(trial.t, trial.force, color="white", linewidth=1.5, label="Total force")
    ax.plot(trial.t, trial.left_force, color="#64b5f6", linewidth=1, linestyle="--", alpha=0.8, label="Left force")
    ax.plot(trial.t, trial.right_force, color="#e57373", linewidth=1, linestyle="--", alpha=0.8, label="Right force")

    ax.axvline(x=playhead_time, color=(1.0, 0.65, 0.0, 0.9), linewidth=2, linestyle="--")

    ax.set_xlabel("Time (s)", color="#aaa")
    ax.set_ylabel("Force (N)", color="#aaa")
    ax.set_title(f"CMJ Force — {trial.athlete_id} ({trial.test_type})", color="#e0e0e0")
    ax.tick_params(colors="#888")
    ax.legend(loc="upper right", fontsize=8, labelcolor="#ccc")
    ax.grid(True, alpha=0.3, color="#444")
    ax.set_xlim(0, trial.test_duration)
    for spine in ax.spines.values():
        spine.set_color("#444")

    fig.tight_layout()
    fig.canvas.draw()

    try:
        buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
        buf = buf.reshape((*fig.canvas.get_width_height()[::-1], 4))
        buf = buf[:, :, :3]
    except AttributeError:
        buf = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
        buf = buf.reshape((*fig.canvas.get_width_height()[::-1], 3))
    plt.close(fig)

    # Resize to exact (height, width) if canvas size differed
    if buf.shape[0] != height or buf.shape[1] != width:
        from scipy.ndimage import zoom
        zoom_factors = (height / buf.shape[0], width / buf.shape[1], 1)
        buf = zoom(buf, zoom_factors, order=1).astype(np.uint8)
    return buf


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render CMJ video + synced force chart to an MP4 file."
    )
    parser.add_argument(
        "--video",
        "-v",
        type=str,
        required=True,
        metavar="PATH",
        help="Path to jump test video",
    )
    parser.add_argument(
        "--data",
        "-d",
        type=str,
        required=True,
        metavar="PATH",
        help="Path to CMJ JSON data",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        metavar="PATH",
        help="Output video path (default: input video name with _synced suffix)",
    )
    parser.add_argument(
        "--offset",
        type=float,
        default=None,
        metavar="SEC",
        help="Video time offset: data t=0 at this video time (used when onset/landing not set)",
    )
    parser.add_argument(
        "--onset-video",
        type=float,
        default=None,
        metavar="SEC",
        help="Video time (seconds) when movement onset happens; use with --landing-video for two-point sync",
    )
    parser.add_argument(
        "--landing-video",
        type=float,
        default=None,
        metavar="SEC",
        help="Video time (seconds) when landing happens; use with --onset-video for two-point sync",
    )
    parser.add_argument(
        "--chart-height",
        type=int,
        default=280,
        metavar="PX",
        help="Height of the chart panel in pixels (default: 280)",
    )
    args = parser.parse_args()

    video_path = Path(args.video)
    data_path = Path(args.data)
    if not video_path.is_absolute():
        video_path = ROOT / video_path
    if not data_path.is_absolute():
        data_path = ROOT / data_path

    if not video_path.exists():
        raise SystemExit(f"Video not found: {video_path}")
    if not data_path.exists():
        raise SystemExit(f"Data file not found: {data_path}")

    if args.output is None:
        out_path = video_path.parent / (video_path.stem + "_synced" + video_path.suffix)
    else:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = ROOT / out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("Loading data...")
    trial = load_trial(data_path)

    use_two_point = args.onset_video is not None and args.landing_video is not None
    if use_two_point:
        if args.onset_video >= args.landing_video:
            raise SystemExit("--onset-video must be less than --landing-video")
        bw, _ = compute_baseline(trial)
        events = detect_events(trial, bodyweight=bw)
        if events.movement_onset is None or events.landing is None:
            raise SystemExit(
                "Could not detect onset and/or landing in data. "
                "Use --offset for simple sync, or check the data file."
            )
        t_onset_data = float(trial.t[events.movement_onset])
        t_landing_data = float(trial.t[events.landing])
        # data_time = a * video_time + b
        a = (t_landing_data - t_onset_data) / (args.landing_video - args.onset_video)
        b = t_onset_data - a * args.onset_video
        print(
            f"Two-point sync: video onset {args.onset_video:.2f}s -> data {t_onset_data:.2f}s, "
            f"video landing {args.landing_video:.2f}s -> data {t_landing_data:.2f}s"
        )

        def video_to_data_time(t_sec: float) -> float:
            return float(np.clip(a * t_sec + b, 0, trial.test_duration))
    else:
        offset = args.offset if args.offset is not None else 0.0
        print(f"Offset sync: data t=0 at video t={offset:.2f}s")

        def video_to_data_time(t_sec: float) -> float:
            return float(np.clip(t_sec - offset, 0, trial.test_duration))

    try:
        from moviepy import VideoFileClip, VideoClip
    except ImportError:
        try:
            from moviepy.editor import VideoFileClip, VideoClip
        except ImportError:
            raise SystemExit("moviepy is required. Install with: pip install moviepy") from None

    print("Loading video...")
    video = VideoFileClip(str(video_path))
    w, h = video.size
    chart_h = args.chart_height

    def make_frame(t_sec: float):
        data_time = video_to_data_time(t_sec)
        vid_frame = video.get_frame(t_sec)
        chart_img = render_chart_frame(trial, data_time, width=w, height=chart_h)
        return np.vstack([vid_frame, chart_img])

    print("Rendering composite video (this may take a while)...")
    out_clip = VideoClip(make_frame, duration=video.duration)
    if video.audio is not None:
        try:
            out_clip = out_clip.with_audio(video.audio)
        except AttributeError:
            out_clip = out_clip.set_audio(video.audio)
    out_clip.write_videofile(
        str(out_path),
        codec="libx264",
        audio_codec="aac",
        fps=video.fps,
        preset="medium",
        logger=None,
    )
    video.close()
    out_clip.close()
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
