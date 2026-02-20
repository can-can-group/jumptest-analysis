# Squat Jump (SJ) Test — Metrics and Statistics Reference

This document lists all **events**, **metrics**, **flags**, and **classification** outputs provided by the squat jump detection and analysis pipeline.

---

## 1. Detected events (time points)

All times are in **seconds** from trial start. Indices are sample numbers.

| Key | Description | Unit |
|-----|-------------|------|
| **contraction_start** | When force first sustains above bodyweight (start of concentric push) | s |
| **peak_force_time** | Time of peak vertical force in the concentric phase | s |
| **takeoff** | Last instant of contact before flight (force sustained below threshold) | s |
| **landing** | First instant of contact after flight (CMJ-style: force matches takeoff level) | s |
| **first_peak_time** | (Bimodal) Time of first peak in two-peak concentric pattern | s |
| **trough_between_peaks_time** | (Bimodal) Time of minimum force between the two peaks | s |
| **second_peak_time** | (Bimodal) Time of second peak in two-peak concentric pattern | s |

Corresponding **sample indices** (for plotting or low-level use):  
`contraction_start`, `peak_force_index`, `takeoff_index`, `landing_index`, `peak_landing_index`,  
`first_peak_index`, `trough_between_peaks_index`, `second_peak_index` (when bimodal).

---

## 2. Temporal metrics

| Metric | Description | Unit |
|--------|-------------|------|
| **contraction_time_s** | Duration from contraction start to take-off (concentric duration) | s |
| **flight_time_s** | Time airborne from take-off to landing | s |
| **time_to_peak_s** | Time from contraction start to peak force | s |
| **time_to_max_rfd_s** | Time from contraction start to peak RFD | s |

---

## 3. Outcome / performance metrics

| Metric | Description | Unit |
|--------|-------------|------|
| **jump_height_m** | Jump height from **flight time**: \( h = g \cdot T^2 / 8 \) | m |
| **jump_height_impulse_m** | Jump height from **impulse–momentum**: \( v = \text{impulse}/m \), \( h = v^2/(2g) \) | m |
| **takeoff_velocity_m_s** | Vertical take-off velocity: \( v = \text{impulse} / \text{mass} \) | m/s |
| **rsi_mod** | Modified reactive strength index: jump height (flight) / contraction time | m/s |

---

## 4. Force metrics

| Metric | Description | Unit |
|--------|-------------|------|
| **peak_force_N** | Peak vertical force during the concentric phase | N |
| **peak_force_pct_bw** | Peak concentric force as percentage of bodyweight | % |
| **mean_force_N** | Mean vertical force during the concentric phase | N |
| **mean_force_pct_bw** | Mean concentric force as percentage of bodyweight | % |
| **impulse_Ns** | Net impulse (integral of \( F - \text{BW} \)) from contraction start to take-off | N·s |

---

## 5. Rate of force development (RFD)

| Metric | Description | Unit |
|--------|-------------|------|
| **max_rfd_N_s** | Peak rate of force development in the concentric phase (Smoothed derivative) | N/s |
| **time_to_max_rfd_s** | Time from contraction start to peak RFD | s |

---

## 6. Bimodal takeoff strategy (when two peaks detected)

| Metric | Description | Unit |
|--------|-------------|------|
| **bimodality_index** | Absolute difference between the two peak force values | N |
| **trough_depth_N** | Force drop from the higher peak to the trough between the two peaks | N |

When bimodal, the events **first_peak_time**, **trough_between_peaks_time**, and **second_peak_time** are also provided.

---

## 7. Bilateral asymmetry (dual force plate only)

| Metric | Description | Unit |
|--------|-------------|------|
| **peak_force_asymmetry_pct** | Left–right asymmetry in peak concentric force: \( 100 \cdot |L-R|/(L+R) \) | % |
| **impulse_asymmetry_pct** | Left–right asymmetry in concentric impulse | % |
| **rfd_asymmetry_pct** | Left–right asymmetry in peak RFD | % |

---

## 8. Flags (boolean indicators)

| Flag | Meaning |
|------|--------|
| **countermovement** | A sustained dip below bodyweight was detected before the concentric rise (injured-type pattern). |
| **bimodal** | Two distinct peaks (and trough) were detected in the concentric phase (bimodal takeoff strategy). |
| **asymmetry_flag** | At least one asymmetry metric exceeds the configured threshold (e.g. > 15%). |

---

## 9. Classification

| Value | Meaning |
|-------|--------|
| **optimal_squat_jump** | No countermovement; force rises from bodyweight without a prior dip. Valid take-off and landing. |
| **injured_or_fatigued_squat_jump** | Countermovement dip present, and/or invalid trial (e.g. no take-off/landing). |

Classification is based **only** on the presence of a countermovement dip and basic validity (take-off, landing, flight time).

---

## 10. Validity

| Field | Description |
|-------|-------------|
| **is_valid** | `true` if the trial passed all validity checks. |
| **flags** | List of issues, e.g. `no_takeoff`, `no_landing`, `no_contraction_start`, `event_order_invalid`, `short_flight`. |

---

## 11. Trial-level inputs used

- **bodyweight_N** (or estimated from quiet phase)
- **sample_rate** (Hz)
- **force** (total vGRF); optionally **left_force** and **right_force** for asymmetry

---

## 12. Output locations

- **Per-trial JSON (viz):** `output/<stem>_viz.json` — full payload for the chart viewer (phases, key points, metrics, events, classification).
- **Summary:** `output/sj_detection_results.json` — one object per file with `points_index`, `points_time_s`, `metrics`, `flags`, `classification`, `validity`.

All metrics above appear in the **metrics** object of each result; events appear in **events** (times) and **points_index** / **points_time_s** (indices and times). Bimodal indices (`first_peak_index`, `trough_between_peaks_index`, `second_peak_index`) are included when bimodal takeoff is detected.
