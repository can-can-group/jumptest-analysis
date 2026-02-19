# Drop Jump (DJ) Detection: Plan and Algorithms

This document describes **how each key point and phase is found** in the vertical ground reaction force (vGRF) signal for a drop jump test. Use it to review what is correct and what may be missing or wrong.

---

## 1. High-level plan

- **Input:** Raw vGRF time series `force[]`, `sample_rate`, and **bodyweight (N)**.
- **Output:** Eight **key points** (sample indices) and **phase boundaries** (contact, flight, landing).
- **Force-level rules (DJ, not CMJ):**  
  - **Below bodyweight:** **drop_landing**, **take_off**, **flight_land** (contact/flight boundaries).  
  - **At bodyweight:** **start_of_concentric** is the first frame where force > BW with sustained positive slope.  
  - **Above bodyweight:** **CTP (contact through point)**, **peak impact force**, **peak drive-off force**, and **peak landing force**. CTP is the lowest point in the trough region that is still **≥ bodyweight** (transition through BW). A final check nulls CTP or any of the three peaks if force at that index is < BW.
- **Strategy:** Two-phase approach: (1) find **contact episodes** (high-force regions) so pre-jump is never treated as contact; (2) within the first episode, find contact start, then take-off, then **three peaks + one valley** in the contact phase (see below). Second episode (or first crossing above threshold after flight) gives second landing.
- **Contact-phase model (three peaks + one valley):** Over the full contact segment we find **three local maxima** (peaks) with force ≥ 1.30× BW and minimum separation (e.g. 15 ms). By time order: **Peak 1** = peak impact force, **Peak 2** = start of concentric, **Peak 3** = peak drive-off force. The **contact through point (CTP)** is the **lowest point** (valley) **strictly between** Peak 1 and Peak 2 with force ≥ 1.10× BW. If fewer than three peaks are found, or no valid valley between P1 and P2, the structure is "not aligned" and is used for classification (high reactive).
- **Smoothing:** Light Savitzky–Golay smoothing (e.g. 15 ms) is applied **only** for peak/valley detection (scipy `find_peaks`); **thresholds and crossings use raw force**.
- **DJ classification** is based on **structure + rolling window**, not contact time alone: see section 12.

---

## 2. Bodyweight

- **Source:** `compute_baseline_drop_jump(trial)` in `src/detect/baseline.py`.
- **Method:** Use the **trailing** portion of the trial (e.g. last 0.8 s) where the subject is standing still after landing. Only samples with force ≥ 100 N are used; mean of those = bodyweight. Fallback if too few samples: 700 N.
- **Used for:** Thresholds (e.g. take-off % BW, min peak above BW), validation windows (e.g. max force in window as % BW), prominence (e.g. peak1 prominence = 10% BW).

---

## 3. Contact episodes (two-phase logic)

- **Goal:** Get the first two “contact” intervals for **grouping only** (not biomechanical contact definition). Contact start is defined by 20–30 N threshold with sustain.
- **Algorithm:** `_find_contact_episodes(force, fs, bw, ...)`:
  - **Threshold:** Force > max(**30 N**, **0.10× BW**) (low so light athletes / soft landings still get episodes).
  - **Episode:** Consecutive samples above threshold; **gap** = at least 50 ms of force ≤ threshold to split episodes.
  - **Minimum duration:** 40 ms; **minimum peak** in episode: 0.35× BW.
  - **First episode only:** Must be preceded by **pre-contact low force**: at least 50 ms of force < 0.5× BW immediately before the episode start.
- **Result:** `episodes = [(ep1_start, ep1_end), (ep2_start, ep2_end)]` (up to two episodes). If only one episode, second landing is found later by crossing above a threshold.

---

## 4. Key point 1: Drop landing (contact start)

- **Output name:** `drop_landing` (point); `contact_start` (phase).
- **Idea:** First time force **sustainably** goes above a low contact threshold, and the **trajectory after** looks like a real landing (force rises and builds), not a noise spike.
- **Steps:**
  1. **Search range:** From `ep1_start - 150 ms` to `ep1_end + 1` (samples).
  2. **Candidates:** All “first crossing above” events: `first_crossing_above(force, 20 N, start, end, sustain)` where **sustain** = 10 ms (force must stay above threshold for 10 ms). Collect every such crossing by re-searching from `crossing + 1`.
  3. **Validation:** For each candidate, in the next **60 ms** after the candidate:
     - **Mean slope** of force ≥ 0 (force rising).
     - **Max force** in that window ≥ 0.5× BW (some loading).
   (Function: `_contact_start_valid(force, candidate, 60 ms, bodyweight, ...)`.)
  4. **Choice:** First candidate that passes; if none, use the first candidate or `ep1_start`.
- **Rationale:** Brief spikes that then drop are rejected; only a sustained rise to a meaningful load is accepted as contact start.

---

## 5. Key point 2: Take-off

- **Output name:** `take_off`; also `contact_end` and `flight_start`.
- **Idea:** First time force **sustainably** goes **below** a take-off threshold **after** the impact phase, and the **following window** looks like flight (force stays low), not a brief dip during contact. **No fabrication:** if no valid take-off is found, return `None` and do not invent a take-off time.
- **Steps:**
  1. **Threshold:** Take-off = max(20 N, 0.05× BW).
  2. **Candidates:** All “first crossing below” from `contact_start + 1` to end of signal; collect all by advancing `pos`.
  3. **Minimum delay:** Discard any candidate with index < `contact_start + 80 ms` (avoids impact-phase dips).
  4. **Validation:** For each remaining candidate, in the next **30 ms**: mean force ≤ 2× take-off threshold; **max force** in window ≤ 0.45× BW (true flight).
  5. **Choice:** First valid candidate; if none, use the **last** crossing below in the filtered list; if still none, use last crossing below **within first episode** only. **Do not** force take-off to `contact_start + 80 ms`; if take-off is still missing, return with `take_off = None`.
- **Early return:** If `take_off` is `None`, the function returns immediately and does **not** compute peak1, CTP, peak2, flight_land, or peak_landing.

---

## 6. Contact-phase points: three-peak + one-valley model

Contact-phase key points are found in one pass using a **three-peak + one-valley** model (`_detect_contact_phase_three_peaks`).

### 6.1 Peak impact force (Peak 1)

- **Output name:** `peak_impact_force`.
- **Idea:** First of three local maxima (by time) in the contact segment with force ≥ 1.30× BW.
- **Steps:** Run `find_peaks` on **smoothed** force over the full contact segment with prominence (e.g. 10% BW) and minimum peak separation (e.g. 15 ms). Keep only peaks with force ≥ min_valid (1.30× BW). Sort by index; **first** peak = peak impact force.
- **Rationale:** Impact produces the first clear peak; using the first peak by time avoids confusion with drive-off or intermediate bumps.

---

### 6.2 Contact through point (CTP) — valley between Peak 1 and Peak 2

- **Output name:** `contact_through_point`.
- **Idea:** **Lowest point** (valley) **strictly between** Peak 1 and Peak 2 with force ≥ 1.10× BW (transition through bodyweight).
- **Steps:** In the range `(peak_impact + 1)` to `(start_of_concentric - 1)`, take the index with **minimum force** among samples with force ≥ min_ctp_force (1.10× BW). If no sample ≥ min_ctp_force, optionally use global min in range if force there ≥ BW; otherwise CTP = None.
- **Rationale:** CTP marks the trough between impact and the start of the concentric (push) phase. If there is no clear trough (e.g. stiff landing), CTP is null and the jump is classified as high reactive.

---

### 6.3 Start of concentric (Peak 2)

- **Output name:** `start_of_concentric`.
- **Idea:** **Second** of the three peaks by time (redefined as the **time/index of the second peak**, not the first sustained rise after CTP).
- **Steps:** From the same peak list as above, **second** peak by index = start_of_concentric.
- **Rationale:** In the three-peak model, the second peak corresponds to the onset of the concentric/push phase. Braking/propulsive impulse split still uses CTP.

---

### 6.4 Peak drive-off force (Peak 3)

- **Output name:** `peak_drive_off_force`.
- **Idea:** **Third** of the three peaks by time.
- **Steps:**
  From the same peak list, **third** peak by index = peak drive-off force. 
- **Rationale:** The last peak before take-off is the peak drive-off. If fewer than three peaks are found, peak_drive_off_force (and/or start_of_concentric) may be null; classification then uses "structure not aligned" → high reactive.

---

## 10. Key point 7: Flight land (second landing contact)

- **Output name:** `flight_land`; phases `flight_end`, `landing_start`.
- **Two cases:**
  - **Two episodes:** `flight_land = ep2_start`. Optionally validate with same rule as contact start: in next **50 ms**, mean slope ≥ 0 and max force ≥ 0.5× BW; if fail, still use `ep2_start` as fallback.
  - **One episode:** Collect all “first crossing above” (threshold 200 N, sustain 20 ms) from `take_off + 1` to end. First candidate that passes **contact-start-style validation** (50 ms window, slope ≥ 0, max ≥ 0.5× BW) is chosen; if none, first candidate.
- **Rationale:** Second landing should show force rising and building, like drop landing.

---

## 11. Key point 8: Peak landing force

- **Output name:** `peak_landing_force`.
- **Idea:** **Local maximum** in the 150 ms window after second landing, with force ≥ bodyweight and **negative slope after** (real peak, not raw argmax).
- **Steps:**
  1. **Window:** From `flight_land` to `flight_land + 150 ms` (capped at signal end).
  2. **Candidates:** `find_peaks(seg, prominence=5% BW, width=1)` in that window; filter by force ≥ bodyweight.
  3. **Validation:** `_peak_valid_after` (next 40 ms mean slope ≤ 0).
  4. **Choice:** Among valid candidates, the one with **maximum force**. If none valid, return `None`.
- **Note:** Landing peak is a true local maximum with decaying force after, not just the highest sample in the window.

---

## 12. DJ metrics (statistics and results)

All of the following are returned by `compute_dj_metrics()` and included in `detect_reactive_strength_points()` output and in the visualization payload.

### 12.1 Full metrics list and definitions

| Metric | Definition | Unit |
|--------|------------|------|
| **contact_time_ms** | (take_off − contact_start) / sample_rate × 1000 | ms |
| **flight_time_s** | (flight_land − take_off) / sample_rate when both are set | s |
| **jump_height_flight_m** | g × flight_time_s² / 8 (same formula as CMJ flight-time height) | m |
| **rsi_dj** | jump_height_flight_m / contact_time_s (Reactive Strength Index) | m/s |
| **braking_impulse_Ns** | ∫(F − BW) from contact_start to CTP | N·s |
| **propulsive_impulse_Ns** | ∫(F − BW) from CTP to take_off | N·s |
| **max_rfd_braking_N_s** | max(dF/dt) over [contact_start, CTP] | N/s |
| **max_rfd_propulsive_N_s** | max(dF/dt) over [CTP, take_off] | N/s |
| **peak_impact_force_N** | Force at the peak impact key point | N |
| **peak_drive_off_force_N** | Force at the peak drive-off key point | N |
| **braking_duration_ms** | (CTP − contact_start) / sample_rate × 1000 | ms |
| **propulsive_duration_ms** | (take_off − CTP) / sample_rate × 1000 | ms |
| **dj_classification** | high_reactive \| low_reactive \| unknown (see below) | — |

Braking/propulsive impulse, RFD, and phase durations are `null` when CTP is missing. Flight time and jump height are `null` when flight_land or take_off is missing; RSI is `null` when jump height or contact time is unavailable or zero.

### 12.2 DJ classification (structure + rolling window)

- **low_reactive:** The four contact-phase points (peak impact, CTP, start of concentric, peak drive-off) are in the required order (P1 < CTP < P2 < P3, with CTP optional) **and** they are **not clamped** (see below).
- **high_reactive:** If the four points are **not** in the required order, or if **any** sliding window of **50 ms** contains **2 or more** of the four points ("clamped"), or if we could not find three distinct peaks or a valid CTP between P1 and P2 (structure not aligned).
- **unknown:** If take_off or contact_start is missing or no contact-phase points were found.
- **Rolling-window clamped check:** If any 50 ms window contains ≥ 2 of the four key points, the trial is classified as high reactive.

---

## 13. Strict temporal order and classification

The three-peak model yields points in order by construction (P1 < P2 < P3; CTP between P1 and P2 when present). Classification then checks: (1) order valid (peak_impact < (CTP if present) < start_of_concentric < peak_drive_off), (2) not clamped (no 50 ms window contains 2+ of the four points). If either fails → high_reactive; if both pass → low_reactive. Also `peak_landing_force` must be ≥ `flight_land`; otherwise it is set to `None`.

---

## 14. Helper primitives (summary)

| Primitive | Role |
|-----------|------|
| `first_crossing_above(force, thresh, start, end, sustain)` | First index where force > thresh and stays above for `sustain` samples. |
| `first_crossing_below(force, thresh, start, end, sustain)` | Same but force < thresh. |
| `segment_by_slope(force)` | Segments as (start, end, is_rising) by sign of first difference. |
| `find_peaks` / `find_peaks_in_range` | Local maxima with prominence and optional slope checks. |
| `find_valleys_in_range` | Local minima via find_peaks on negated segment. |
| `_contact_start_valid` | Window after candidate: mean slope ≥ 0, max force ≥ 0.5× BW. |
| `_peak_valid_after` | Window after peak: mean slope ≤ 0. |
| `_valley_valid_after` | Window after valley: mean slope ≥ 0. |
| `_takeoff_valid_after` | Window after candidate: mean force and max force below thresholds. |
| `_slope_before_positive` / `_slope_after_negative` (etc.) | Compare force at index with force at index ± 2. |

---

## 15. Constants (defaults) quick reference

- Contact: drop_landing threshold 20 N; sustain 10 ms; contact start validation 60 ms, min peak in window 0.5× BW.
- Take-off: 5% BW (floor 20 N); sustain 10 ms; min 80 ms after contact start; validation 30 ms, max force in window 0.45× BW.
- Peak 1: window 120 ms; prominence 10% BW; peak valid window 40 ms; min peak force = BW.
- Valley/CTP: min prominence 2% BW; valley valid window 40 ms.
- Peak 2: prominence 5% BW; peak valid window 40 ms.
- Episodes: threshold 30 N / 0.10× BW (grouping only); min duration 40 ms; min peak 0.35× BW; flight gap 50 ms; pre-contact 50 ms < 0.5× BW.
- Contact-phase: three peaks (prominence 10% BW, min separation 15 ms) over full contact; min force 1.30× BW for peaks, 1.10× BW for CTP. Clamped window for classification: 50 ms (`DEFAULT_CLAMPED_WINDOW_MS`); high reactive contact time 250 ms kept for optional reporting only.
- Landing: second landing threshold 200 N, sustain 20 ms; flight land valid 50 ms; landing peak window 150 ms.

---

## 16. What to review (for the other AI)

- **Correct:** Whether the **order of operations** (episodes → contact start → take-off → peak1 → CTP → start_of_concentric → peak2 → flight_land → peak_landing) is sound and matches biomechanics.
- **Correct:** Whether **window validations** (contact start, take-off, peak, valley, flight land) use the right window length and thresholds.
- **Missing:** Whether any **additional points** (e.g. start of eccentric, end of braking) or **temporal constraints** (e.g. peak1 < CTP < peak2 < take_off) should be enforced.
- **Missing:** Whether **landing peak** should be required to be a local maximum and/or validated with `_peak_valid_after`.
- **Edge cases:** Behavior when there is **only one episode** (no clear second landing), or when **peak1** or **peak2** are null (fallbacks and effect on CTP/start_of_concentric/drive_start).
- **Robustness:** Sensitivity to **noise**, **double impacts**, **very short contacts**, or **high vs low reactive** (e.g. CTP and start_of_concentric coinciding).

End of document.
