# CMJ Force Plate Analysis

Analyze counter-movement jump (CMJ) force plate exports: detect events (movement onset, take-off, landing), phases, key points (P1/P2), and compute physics-based metrics (jump height, peak power, RFD, phase impulses). This codebase is designed to be used **as a service** from your API: you send raw force data (or a path to a JSON file), and get back a structured analysis payload suitable for your frontend or other consumers.

## Using this codebase as a service in your API

You can run the full analysis pipeline in code and return the result as JSON (e.g. from a FastAPI/Flask endpoint). **No files or images are written** when using the API entry point below.

### Recommended: in-memory API entry point (no file I/O or plots)

Use `run_analysis(data)` with an in-memory dict. Input can use `"force"` or `"total_force"`; other required keys: `athlete_id`, `test_type`, `test_duration`, `left_force`, `right_force`.

```python
from src import run_analysis

# data = request.get_json()  # or build dict from your API payload
data = {
    "athlete_id": "...",
    "test_type": "CMJ",
    "test_duration": 2.5,
    "total_force": [...],   # or "force"
    "left_force": [...],
    "right_force": [...],
}
payload = run_analysis(data)
# payload is the full visualization dict (phases, key_points, metrics, analysis). Return as JSON.
```

Alternatively, load from a dict with `load_trial_from_dict(data)` then run the pipeline yourself (see below).

### Manual pipeline (file or dict)

```python
from pathlib import Path
from src.data import load_trial
from src.detect import compute_baseline, detect_events, compute_phases, validate_trial
from src.physics import compute_kinematics, compute_metrics, compute_asymmetry
from src.export_viz import build_visualization_payload

# Load raw CMJ JSON (path or dict with force, left_force, right_force, sample_count, etc.)
trial = load_trial(Path("path/to/cmj_raw.json"))

baseline = compute_baseline(trial)
bodyweight = baseline.bodyweight_N
events = detect_events(trial, bodyweight=bodyweight)
events = compute_phases(trial, events, baseline.velocity_zero_index)
validity = validate_trial(trial, events, bodyweight=bodyweight)
velocity = compute_kinematics(trial, bodyweight=bodyweight)
metrics = compute_metrics(trial, events, bodyweight=bodyweight, velocity=velocity)
metrics.update(compute_asymmetry(trial, events, bodyweight=bodyweight, metrics=metrics))

payload = build_visualization_payload(trial, events, bodyweight, metrics, validity)

# payload is a dict you can return from your API (e.g. return payload or json.dumps(payload))
# It includes:
#   - athlete_id, test_type, bodyweight_N, validity, time_s, force_N, left_force_N, right_force_N
#   - phases: list of { name, start_time_s, end_time_s, duration_s, ... }
#   - key_points: list of { name, index, time_s, value_N, ... }
#   - metrics: flat dict of metric key → value
#   - analysis: { phases, key_points, metrics } with each entry as { value, explanation } for UI/API
```

**Response shape your API can rely on:**

- **`phases`**: array of phase objects with `name`, `start_time_s`, `end_time_s`, `duration_s`, and indices.
- **`key_points`**: array of key points with `name`, `index`, `time_s`, `value_N`.
- **`metrics`**: flat dictionary of metric names to numeric values (e.g. `jump_height_impulse_m`, `flight_time_s`).
- **`analysis`**: structured block for UI and tooltips; each of `phases`, `key_points`, and `metrics` is a keyed object where each key maps to `{ "value": ..., "explanation": "..." }`. Use `analysis.phase_order` and `analysis.key_point_order` for display order.

Configurable detection (e.g. take-off/landing thresholds, P1/P2 separation) is in **`src/config.py`** and can be overridden when calling `detect_events` or the peak detector. See **Code layout** below for module roles.

If your API receives CMJ data as JSON in the request body, use `run_analysis(request_body)` or `load_trial_from_dict(request_body)` (accepts `force` or `total_force`; `sample_count` is optional and derived from the force array length).

## Data format

Raw JSON files in `saved_raw_data/` with:

- `athlete_id`, `test_type`, `test_duration` (s), `sample_count`
- `force`, `left_force`, `right_force`: arrays of vertical force in newtons

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

From the project root (so `src` is importable):

```bash
PYTHONPATH=. .venv/bin/python script/main.py [FILE]
```

- **FILE**: path to a CMJ JSON file. If omitted, uses the first file in `saved_raw_data/`.
- **--no-plot**: print metrics only, do not open or save a plot.
- **--save PATH**: save the force chart to an image file (uses non-interactive backend; no window opens).
- **--filter HZ**: low-pass filter force at HZ (e.g. 50 or 100) before event detection.
- **--take-off-threshold N**: force (N) below which take-off is detected (default: max(20, 5% BW)).
- **--landing-threshold N**: force (N) for landing detection (default: 200).
- **--onset-below-bw FRAC**: movement onset when force &lt; (1 - FRAC)×BW (default: 0.05).

Example:

```bash
PYTHONPATH=. .venv/bin/python script/main.py saved_raw_data/jump_test_export_2026-02-06T12-44-30.json --save chart.png
```

## Output

- **Console**: bodyweight, mass, event indices, and metrics (jump height impulse/flight, flight time, peak power, peak RFD, P1/P2 peaks, phase impulses and times).
- **Chart** (if not `--no-plot`): one time-series plot with total force, left force, right force, optional bodyweight line and vertical lines at detected events.

## Web chart viewer (phases and key points)

Export a single JSON for the detailed JavaScript viewer, then open the viewer in a browser:

```bash
PYTHONPATH=. .venv/bin/python script/main.py saved_raw_data/saved1.json --no-plot --export output/cmj_viz.json
```

Open `web/viewer.html` in a browser and use **Load visualization JSON** to select `output/cmj_viz.json`. The viewer shows:

- **Phases**: Quiet, Eccentric (Unloading, Braking), Concentric, Flight, Landing — as shaded regions on the force curve.
- **Key points**: Start of movement, Minimum force (eccentric end), Max RFD, P1 peak, P2 peak, Take-off, Landing — as vertical lines with labels.
- **Bodyweight** as a horizontal dashed line.
- **Total, left, and right force** vs time.
- Side panels listing phase time ranges and key point times/values.

## Video–Data Sync Visualizer

A separate visualizer that plays a jump-test video in sync with the force chart: as the video plays, a playhead on the chart shows the current time. Click on the chart to seek the video.

From the project root:

```bash
python script/video_sync_visualizer.py --video saved_raw_data/How\ To\ Counter\ Movement\ Jump.mp4 --data saved_raw_data/saved1.json
```

- **--video, -v**: path to the jump test video.
- **--data, -d**: path to the CMJ JSON data file.
- **--offset, -o**: video time offset in seconds (data t=0 corresponds to video at this time; default 0).
- **--no-open**: start the server only; do not open the browser.

The script starts a local HTTP server and opens the visualizer in your browser. Video and chart stay in sync; you can click on the chart to jump the video to that time.

To **save the result as a video file** (MP4) instead of viewing in the browser:

```bash
python script/render_sync_video.py --video "saved_raw_data/How To Counter Movement Jump.mp4" --data saved_raw_data/saved1.json --output output/synced.mp4
```

- **--output, -o**: output video path (default: input video name with `_synced` suffix).
- **--chart-height**: height of the chart panel in pixels (default: 280).
- **--offset**: video time (s) that corresponds to data t=0 (simple sync when not using onset/landing).
- **--onset-video** and **--landing-video**: video times (s) when movement onset and landing happen; when both are given, the script uses detected onset/landing in the data to build a two-point linear sync for perfect alignment.

Example (two-point sync): if onset in the video is at 0.5 s and landing at 2.8 s:
`python script/render_sync_video.py -v video.mp4 -d data.json -o out.mp4 --onset-video 0.5 --landing-video 2.8`

The output video stacks the source video and the force chart; a playhead moves in sync with the footage. Audio from the source video is preserved.

## Code layout

- **src/data**: load JSON, validate, build time vector (`load.py`, `types.py`).
- **src/config**: default thresholds and options (`CMJConfig`); tune for your API (e.g. `min_p1_p2_separation_ms`, take-off/landing thresholds).
- **src/detect**: bodyweight/mass (`baseline.py`), take-off/landing/onset (`events.py`), eccentric end and v=0 (`phases.py`), P1/P2 detection (`structural_peaks.py`), trial validity (`validity.py`).
- **src/physics**: COM velocity from force (`kinematics.py`), jump height, power, RFD, phase impulses, P1/P2 (`metrics.py`), left/right asymmetry (`asymmetry.py`).
- **src/analysis_response**: builds the `analysis` block (phases, key_points, metrics as key → `{ value, explanation }`) for API and UI.
- **src/export_viz**: builds the full visualization payload (time, force, phases, key_points, metrics, events, analysis); used by the CLI export and by your service.
- **src/signal**: optional low-pass filter (`filter.py`) for robustness.
- **src/viz**: single chart of force traces and event lines (`chart.py`).
- **script/main.py**: CLI entry point (load → baseline → events → phases → metrics → plot/export). Use the same sequence in your API service.
- **web/viewer.html**: standalone viewer for exported JSON (phases, key points, metrics, comparison of two trials).
- **script/video_sync_visualizer.py**: launches the video–data sync visualizer (serves `visualizer/index.html` and opens in browser).
- **script/render_sync_video.py**: renders the same video+chart composite to an MP4 file (no browser).
- **visualizer/index.html**: single-page app: video player + force chart with synced playhead; chart click seeks video.

## Documentation for expert review

**[docs/DETECTION_AND_METRICS.md](docs/DETECTION_AND_METRICS.md)** describes in detail:
- Every **point** detected (take-off, landing, movement onset, eccentric end, velocity zero): definitions, algorithms, and thresholds.
- Every **phase** (unweighting, braking, propulsion, flight, landing): how boundaries are derived.
- All **physics formulas** (kinematics, jump height, power, RFD, phase impulses).
- Optional low-pass filter and what is not implemented.

Use this document when asking a biomechanics/sports science reviewer what is correct, what to add, or what is missing.

## References

- Event thresholds (e.g. 20 N take-off, 200 N landing): Qualisys Appendix C.
- Jump height: impulse–momentum and flight-time formulas (BMC Vertical Jump notebook; systematic review on CMJ height methods).
- Phases: weighing, unweighting, braking, propulsion, flight, landing (CMJ force–time curve literature).
