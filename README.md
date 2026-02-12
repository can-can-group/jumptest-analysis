# CMJ Force Plate Analysis

Analyze counter-movement jump (CMJ) force plate exports: visualize total/left/right force, detect events (movement onset, take-off, landing, eccentric end), and compute physics-based metrics (jump height, peak power, RFD, phase impulses).

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
- **src/detect**: bodyweight/mass (`baseline.py`), take-off/landing/onset (`events.py`), eccentric end and v=0 (`phases.py`).
- **src/physics**: COM acceleration/velocity from force (`kinematics.py`), jump height, power, RFD, phase impulses (`metrics.py`).
- **src/signal**: optional low-pass filter (`filter.py`) for robustness.
- **src/viz**: single chart of force traces and event lines (`chart.py`).
- **script/main.py**: entry point that ties load → baseline → events → phases → metrics → plot.
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
