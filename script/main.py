"""Entry point: load CMJ JSON, detect events/phases, validate, compute metrics, plot."""
import argparse
from pathlib import Path

from src.data import load_trial, CMJTrial, CMJEvents
from src.detect import compute_baseline, detect_events, compute_phases, validate_trial
from src.physics import compute_kinematics, compute_metrics, compute_asymmetry
from src.viz import plot_force
from src.export_viz import build_visualization_payload, export_visualization_json


def main() -> None:
    parser = argparse.ArgumentParser(description="CMJ Force Plate Analysis")
    parser.add_argument(
        "file",
        nargs="?",
        default=None,
        help="Path to raw CMJ JSON (default: first file in saved_raw_data)",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip opening/saving plot",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        help="Save plot to this path",
    )
    parser.add_argument(
        "--filter",
        type=float,
        default=None,
        metavar="HZ",
        help="Low-pass filter cutoff in Hz before detection (e.g. 50 or 100)",
    )
    parser.add_argument(
        "--take-off-threshold",
        type=float,
        default=None,
        metavar="N",
        help="Take-off force threshold in N (default: max(20, 5%% BW))",
    )
    parser.add_argument(
        "--take-off-consecutive",
        type=int,
        default=4,
        metavar="N",
        help="Samples force must stay below threshold for take-off (default: 4)",
    )
    parser.add_argument(
        "--landing-threshold",
        type=float,
        default=None,
        metavar="N",
        help="Landing force threshold in N (default: max(200, 5%% BW))",
    )
    parser.add_argument(
        "--landing-sustain-ms",
        type=float,
        default=20.0,
        metavar="MS",
        help="Landing sustained contact duration in ms (default: 20)",
    )
    parser.add_argument(
        "--onset-below-bw",
        type=float,
        default=0.05,
        metavar="FRAC",
        help="Movement onset fallback: force below (1-FRAC)*BW (default: 0.05)",
    )
    parser.add_argument(
        "--onset-n-sigma",
        type=float,
        default=5.0,
        metavar="N",
        help="Movement onset: force below BW - N*sigma_quiet (default: 5)",
    )
    parser.add_argument(
        "--onset-sustain-ms",
        type=float,
        default=30.0,
        metavar="MS",
        help="Movement onset sustained duration in ms (default: 30)",
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        metavar="PATH",
        help="Export visualization JSON to PATH for the web chart viewer",
    )
    args = parser.parse_args()

    if args.file:
        path = Path(args.file)
    else:
        data_dir = Path(__file__).resolve().parent.parent / "saved_raw_data"
        files = sorted(data_dir.glob("*.json"))
        if not files:
            raise SystemExit("No JSON files in saved_raw_data and no file given.")
        path = files[0]
        print(f"Using: {path}")

    trial = load_trial(path)
    bw, mass, sigma_quiet = compute_baseline(trial)

    if args.filter is not None:
        from src.signal import lowpass_filter
        force_filtered = lowpass_filter(trial.force, trial.sample_rate, args.filter)
        trial_analysis = CMJTrial(
            athlete_id=trial.athlete_id,
            test_type=trial.test_type,
            test_duration=trial.test_duration,
            sample_count=trial.sample_count,
            force=force_filtered,
            left_force=trial.left_force,
            right_force=trial.right_force,
            sample_rate=trial.sample_rate,
            t=trial.t,
        )
    else:
        trial_analysis = trial

    events = detect_events(
        trial_analysis,
        bodyweight=bw,
        sigma_quiet=sigma_quiet,
        take_off_threshold=args.take_off_threshold,
        take_off_consecutive_samples=args.take_off_consecutive,
        landing_threshold=args.landing_threshold,
        landing_sustain_ms=args.landing_sustain_ms,
        onset_below_bw=args.onset_below_bw,
        onset_n_sigma=args.onset_n_sigma,
        onset_sustain_ms=args.onset_sustain_ms,
    )
    v, a = compute_kinematics(
        trial_analysis,
        bodyweight=bw,
        onset_idx=events.movement_onset,
        take_off_idx=events.take_off,
    )
    events = compute_phases(trial_analysis, events, v)

    validity = validate_trial(trial_analysis, events, bodyweight=bw, take_off_threshold=args.take_off_threshold)
    if not validity.is_valid:
        print(f"Validity flags: {validity.flags}")

    metrics = compute_metrics(trial_analysis, events, bodyweight=bw, velocity=v)
    asym = compute_asymmetry(trial_analysis, events)
    for k, val in asym.items():
        metrics[k] = val

    print(f"Athlete: {trial.athlete_id}  Test: {trial.test_type}")
    print(f"Bodyweight: {bw:.1f} N  Mass: {mass:.2f} kg")
    print(f"Movement onset: {events.movement_onset}  Take-off: {events.take_off}  Landing: {events.landing}")
    print(f"Min force: {events.min_force}  Ecc end (peak ecc v): {events.eccentric_end}  Velocity zero: {events.velocity_zero}")
    payload = None
    if args.export:
        payload = build_visualization_payload(trial_analysis, events, bw, metrics, validity)
        print("Phases:")
        for p in payload["phases"]:
            print(f"  {p['name']}: {p['start_time_s']:.3f} s -> {p['end_time_s']:.3f} s")
        print("Key points:")
        for kp in payload["key_points"]:
            v = kp.get("value_N") or kp.get("value_N_per_s")
            print(f"  {kp['name']}: t={kp['time_s']:.3f} s" + (f"  value={v}" if v is not None else ""))
    print("Metrics:")
    for k, val in sorted(metrics.items()):
        if isinstance(val, float):
            print(f"  {k}: {val:.4f}")
        else:
            print(f"  {k}: {val}")

    if not args.no_plot:
        out = Path(args.save) if args.save else None
        plot_force(trial, events=events, bodyweight=bw, output_path=out, validity=validity)

    if args.export and payload is not None:
        export_visualization_json(payload, Path(args.export))
        print(f"Exported visualization JSON to {args.export}")


if __name__ == "__main__":
    main()
