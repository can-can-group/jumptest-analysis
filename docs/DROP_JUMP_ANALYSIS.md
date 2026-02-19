# Drop Jump Analysis: Overview and Pipeline

This document describes **what the drop jump (DJ) analysis does**, **how points are detected**, and **how the analysis is run**. For low-level algorithm details (thresholds, validation windows), see [DROP_JUMP_DETECTION_ALGORITHM.md](DROP_JUMP_DETECTION_ALGORITHM.md).

---

## 1. What the analysis does

The pipeline takes **raw vertical ground reaction force (vGRF)** from a drop jump trial and:

1. **Detects key events** – drop landing, peak impact, contact through point (CTP), start of concentric, peak drive-off, take-off, flight land, peak landing force.
2. **Defines phases** – Pre-jump, Contact, Flight, Landing.
3. **Classifies the jump** – high reactive (fast SSC) vs low reactive (slow SSC) using the **shape** of the force curve (three-peak structure + whether points are “clamped” in time).
4. **Computes metrics** – contact time, flight time, jump height, RSI, braking/propulsive impulse and duration, peak forces, max RFD, and classification.

Output is a **structured payload** (phases, key points, metrics) suitable for the web viewer, export JSON, or your API.

---

## 2. Inputs and outputs

**Inputs**

- **Force** – 1D array of vertical force (N) at constant sample rate.
- **Sample rate** – Hz (samples per second).
- **Bodyweight** – N, from baseline (trailing portion of the trial where the subject is standing) or provided.

**Outputs**

- **Key points** (sample indices and times): `drop_landing`, `peak_impact_force`, `contact_through_point`, `start_of_concentric`, `peak_drive_off_force`, `take_off`, `flight_land`, `peak_landing_force`. Any can be `null` if not found.
- **Phases**: Pre-jump, Contact, Flight, Landing (each with start/end time and duration).
- **Metrics**: contact_time_ms, flight_time_s, jump_height_flight_m, rsi_dj, braking_impulse_Ns, propulsive_impulse_Ns, max_rfd_braking_N_s, max_rfd_propulsive_N_s, peak_impact_force_N, peak_drive_off_force_N, braking_duration_ms, propulsive_duration_ms, dj_classification.
- **Analysis block** – same data with human-readable explanations for the UI.

---

## 3. How points are detected (pipeline order)

Detection is implemented in **`src/detect/drop_jump.py`**. The order of operations is fixed so that later steps use only already-found indices.

### Step 1: Contact episodes (grouping only)

- **Function:** `_find_contact_episodes(force, fs, bw, ...)`
- **Purpose:** Find the first two “high-force” intervals (first = drop + push-off contact, second = landing after the jump). This avoids treating pre-jump noise as contact.
- **Logic:** Force above a low threshold (e.g. 30 N or 0.10× BW) for a minimum duration; episodes separated by at least 50 ms of low force. First episode must be preceded by ~50 ms of low force (pre-jump).
- **Result:** `[(ep1_start, ep1_end), (ep2_start, ep2_end)]`.

### Step 2: Drop landing (contact start)

- **Output:** `drop_landing` = first **sustained** crossing above a contact threshold (e.g. 20 N) such that the next 60 ms looks like a real landing (force rising, max force ≥ 0.5× BW).
- **Rationale:** Rejects brief spikes; only a sustained rise is accepted as contact start.

### Step 3: Take-off

- **Output:** `take_off` = first **sustained** crossing **below** a take-off threshold (e.g. 20 N or 0.05× BW) **after** a minimum delay from contact start (e.g. 80 ms), with the next 30 ms looking like flight (force stays low).
- **Important:** If no valid take-off is found, the function returns early and does **not** compute contact-phase peaks, CTP, or second landing. All contact-phase points and many metrics stay `null`.

### Step 4: Contact-phase points (three-peak + one-valley model)

- **Function:** `_detect_contact_phase_three_peaks(force, contact_start, contact_end, bodyweight, sample_rate, ...)`
- **Range:** From `contact_start` (drop_landing) to `contact_end` (take_off).

**4a. Three peaks**

- Run **`find_peaks`** on **smoothed** force over the full contact segment (prominence ≈ 10% BW, min separation ≈ 15 ms).
- Keep only peaks with force ≥ 1.30× BW. Sort by time (index).
- **Peak 1** → `peak_impact_force`
- **Peak 2** → `start_of_concentric`
- **Peak 3** → `peak_drive_off_force`

If fewer than three peaks are found, only the available ones are set; the rest are `null`.

**4b. Contact through point (CTP)**

- **Valley** strictly **between Peak 1 and Peak 2**.
- Choose the index with **minimum force** among samples with force ≥ 1.10× BW (so CTP stays “through” bodyweight).
- If there is no such point (e.g. stiff landing, no trough), CTP = `null`.

### Step 5: Second landing and peak landing force

- **flight_land** = start of the second contact (second episode if two episodes, else first sustained crossing above a threshold after take-off). Validated so force rises after contact.
- **peak_landing_force** = local maximum in a window (e.g. 150 ms) after `flight_land`, force ≥ BW.

---

## 4. How classification works (high vs low reactive)

Classification does **not** use contact time alone. It uses **structure** and **time spacing** of the four contact-phase points (peak impact, CTP, start of concentric, peak drive-off).

**Rules (in `compute_dj_metrics`):**

1. **Order check:** Require  
   `peak_impact < (CTP if present) < start_of_concentric < peak_drive_off`.
2. **Clamped check:** In **time** (ms), if any two **consecutive** points (in that order) are closer than **50 ms**, or if any **50 ms sliding window** contains **2 or more** of the four points, the trial is considered **clamped** (user reacted so fast that the phases are not visually separable).

**Result:**

- **low_reactive** – All four points in the correct order **and** not clamped (clearly separated in time).
- **high_reactive** – Order wrong, or clamped, or we could not find three distinct peaks / valid CTP (structure not aligned).
- **unknown** – No valid contact start or take-off, or no contact-phase points to evaluate.

Clamped detection uses **time in milliseconds** (not sample indices) so the 50 ms rule is consistent across sample rates.

---

## 5. How metrics are computed

**Function:** `compute_dj_metrics(force, sample_rate, bodyweight, points, phases)` in `src/detect/drop_jump.py`.

| Metric | Formula / source |
|--------|-------------------|
| **contact_time_ms** | (take_off − drop_landing) / sample_rate × 1000 |
| **flight_time_s** | (flight_land − take_off) / sample_rate when both set |
| **jump_height_flight_m** | g × flight_time_s² / 8 (g = 9.81) |
| **rsi_dj** | jump_height_flight_m / contact_time_s (Reactive Strength Index, m/s) |
| **braking_impulse_Ns** | ∫(F − BW) from drop_landing to CTP (requires CTP) |
| **propulsive_impulse_Ns** | ∫(F − BW) from CTP to take_off (requires CTP) |
| **max_rfd_braking_N_s** | max(dF/dt) over [drop_landing, CTP] (requires CTP) |
| **max_rfd_propulsive_N_s** | max(dF/dt) over [CTP, take_off] (requires CTP) |
| **peak_impact_force_N** | force[peak_impact_force] at the peak impact index |
| **peak_drive_off_force_N** | force[peak_drive_off_force] at the peak drive-off index |
| **braking_duration_ms** | (CTP − drop_landing) / sample_rate × 1000 (requires CTP) |
| **propulsive_duration_ms** | (take_off − CTP) / sample_rate × 1000 (requires CTP) |
| **dj_classification** | From order + clamped check (see above) |

Braking/propulsive impulse, RFD, and phase durations are `null` when CTP is missing. Flight time and jump height are `null` when `flight_land` or `take_off` is missing.

---

## 6. How to run the analysis

### Option A: Export script (batch, writes files)

From the project root, with dependencies installed:

```bash
PYTHONPATH=. python3 script/export_dj_viz.py [path_to_dj_json_dir]
```

- **Default input:** `saved_raw_data/dj-data/` (all `*.json` with `test_type` DJ).
- **Outputs:**
  - `output/<stem>_viz.json` – full payload for the web viewer (force, phases, key_points, metrics, analysis).
  - `output/dj_detection_results.json` – one entry per file: file name, sample_rate, bodyweight, points (indices), points_time_s, phases, metrics.

The script loads each trial, runs `detect_drop_jump_events` and `compute_dj_metrics`, then builds the visualization payload via `build_dj_visualization_payload`.

### Option B: In code (single trial, no file write)

```python
from src.data import load_trial
from src.detect import compute_baseline_drop_jump, detect_drop_jump_events
from src.detect.drop_jump import compute_dj_metrics
from src.export_viz import build_dj_visualization_payload

# Load raw DJ JSON (path or dict with force, sample_count, test_type, etc.)
trial = load_trial(Path("path/to/dj_raw.json"))

bodyweight, _, _ = compute_baseline_drop_jump(trial)
points, phases = detect_drop_jump_events(
    trial.force, trial.sample_rate, bodyweight
)
metrics = compute_dj_metrics(
    trial.force, trial.sample_rate, bodyweight, points, phases
)

# Optional: build full payload for viewer/API (includes analysis block with explanations)
from src.data.types import TrialValidity
payload = build_dj_visualization_payload(
    trial, bodyweight, points, phases,
    TrialValidity(is_valid=True, flags=[]), metrics
)
# payload["metrics"], payload["analysis"]["metrics"], etc.
```

### Option C: Reactive-strength API-style entry point

```python
from src.detect import detect_reactive_strength_points

result = detect_reactive_strength_points(
    force, sample_rate, bodyweight
)
# result = { "points": {...}, "phases": {...}, "braking_impulse_Ns": ..., "contact_time_ms": ..., "dj_classification": ..., ... }
```

---

## 7. Where the code lives

| Responsibility | Module / function |
|----------------|-------------------|
| Load DJ trial (JSON) | `src.data.load_trial` |
| Bodyweight from trial | `src.detect.baseline.compute_baseline_drop_jump` |
| Contact episodes | `src.detect.drop_jump._find_contact_episodes` |
| Drop landing, take-off, flight land, landing peak | `src.detect.drop_jump.detect_drop_jump_events` |
| Contact-phase points (3 peaks + CTP) | `src.detect.drop_jump._detect_contact_phase_three_peaks` |
| Clamped check (time-based) | `src.detect.drop_jump._are_contact_points_clamped` |
| All DJ metrics + classification | `src.detect.drop_jump.compute_dj_metrics` |
| Build viz payload + analysis block | `src.export_viz.build_dj_visualization_payload`, `src.analysis_response.build_analysis_response` |
| Metric explanations (UI) | `src.analysis_response.METRIC_EXPLANATIONS` |
| Batch export | `script/export_dj_viz.py` |
| Web viewer | `web/viewer.html` (loads `*_viz.json`) |

---

## 8. Summary diagram

```
Raw vGRF + sample_rate + bodyweight
        │
        ▼
┌───────────────────────────────────┐
│ Contact episodes (grouping)       │  → ep1, ep2
└───────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────┐
│ Drop landing (contact start)      │  → drop_landing
└───────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────┐
│ Take-off (sustained below thresh) │  → take_off  [early return if null]
└───────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────┐
│ Three peaks + CTP in contact      │  → peak_impact, CTP, start_conc, peak_drive_off
└───────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────┐
│ Second landing + landing peak     │  → flight_land, peak_landing_force
└───────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────┐
│ compute_dj_metrics                │  → impulses, RFD, times, RSI, forces, classification
└───────────────────────────────────┘
        │
        ▼
Phases, key points, metrics → payload → viewer / export / API
```

For full algorithm detail (thresholds, validation windows, constants), see [DROP_JUMP_DETECTION_ALGORITHM.md](DROP_JUMP_DETECTION_ALGORITHM.md).
