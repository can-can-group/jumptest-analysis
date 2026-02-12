# CMJ Force Plate Analysis: Point Detection, Phases, and Metrics

**Purpose of this document**  
This describes exactly which **points** (events) and **phases** (areas) are detected from vertical force data, which **algorithms** are used, and how all **metrics** are calculated. It is intended for review by a biomechanics or sports science expert so they can confirm correctness, suggest additions, or identify gaps.

**Scope**  
- Counter-movement jump (CMJ) only.  
- Input: vertical ground reaction force (GRF) time series from a force plate (total, and optionally left/right), in newtons, with known sample count and trial duration.  
- Output: event sample indices, phase boundaries, and derived metrics (jump height, power, RFD, phase impulses, etc.).

---

## 1. Input data and assumptions

- **Force**: Vertical component of ground reaction force (GRF), in **newtons (N)**. Positive = upward reaction force (compression into the plate).
- **Time**: Derived as `t[i] = i / sample_rate`, with `sample_rate = sample_count / test_duration` (Hz).
- **Gravity**: \( g = 9.81\,\text{m/s}^2 \) used for all calculations.
- **Body mass**: Inferred from the weighing phase (see below), not given as input.  
- **Coordinate convention**: Vertical acceleration/velocity are positive **upward** (so that at take-off the COM has positive upward velocity).

---

## 2. Baseline: bodyweight and mass

**Purpose**  
Establish the force corresponding to standing (bodyweight) so we can normalize thresholds and compute mass for kinematics.

**Algorithm**

1. **Weighing window**: First \( N_{\text{weigh}} \) samples of the trial, where  
   \( N_{\text{weigh}} = \min\bigl(\lfloor \text{sample\_rate} \times 1.0 \rfloor,\ \text{sample\_count}\bigr) \).  
   So we use the first **1 second** of data (or all samples if the trial is shorter).
2. **Bodyweight (BW)**:  
   \( \text{BW} = \frac{1}{N_{\text{weigh}}} \sum_{i=0}^{N_{\text{weigh}}-1} F(i) \), in N.
3. **Mass**:  
   \( m = \text{BW} / g \), in kg.

**Output**  
- `bodyweight` (N)  
- `mass` (kg)  
- `sigma_quiet` (N): standard deviation of force over the weighing window (used for statistical movement-onset detection).

These are used for all subsequent event detection and metrics. Bodyweight is always computed from the **raw** force signal (before any optional filtering).

---

## 3. Detected points (events)

All events are reported as **sample indices** into the force/time arrays. Detection is performed on the **total** vertical force (left/right are used only for visualization or future asymmetry metrics).

**Definitions (biomechanical)**  
- **Peak eccentric velocity**: index where COM vertical velocity is minimum (most negative); stored as `eccentric_end`.  
- **Bottom of dip**: first sample after that where velocity crosses zero (upward); stored as `velocity_zero`.  
- **Minimum force**: index of minimum force in [onset, take_off]; end of unweighting phase; stored as `min_force`.

**Order of detection in code**  
1. Take-off (with consecutive samples below threshold)  
2. Landing (relative threshold + sustained contact)  
3. Movement onset (statistical or fallback + sustained)  
4. Min force (argmin F in contact)  
5. Eccentric end and velocity zero (from COM velocity; see Section 5)

### 3.1 Take-off

**Definition**  
The first instant at which vertical force drops below a low threshold, indicating the feet are leaving the plate.

**Algorithm**

- **Threshold**:  
  \( F_{\text{TO}} = \max(20\,\text{N},\ 0.05 \times \text{BW}) \).  
  So at least 20 N, or 5% of bodyweight, whichever is larger. (Configurable in code/CLI.)
- **Rule**: First descending crossing such that force **remains** below threshold for the next **K** consecutive samples (default K=4, ~3–5 ms at 1000 Hz). If any of those samples is above threshold, search continues for the next crossing.
- **Search**: From the start of the trial to the end.

**Output**  
- `take_off`: sample index \( i \) at take-off.

**Note**  
If the force signal is noisy, an optional low-pass filter (e.g. 50–100 Hz) can be applied to the force **before** this detection; in that case, the same filtered force is used for all contact-phase event detection and for COM velocity integration.

---

### 3.2 Landing

**Definition**  
The first instant after take-off at which vertical force rises above a contact threshold, indicating foot contact on the plate again.

**Algorithm**

- **Threshold**: \( F_{\text{land}} = \max(200\,\text{N},\ 0.05 \times \text{BW}) \). (Configurable.)
- **Rule**: First ascending crossing **after** take_off such that force **remains** above threshold for at least **20 ms** (configurable). If any sample in that window drops below threshold, search continues.
- **Search**: From the sample after `take_off` to the end of the trial.

**Output**  
- `landing`: sample index \( i \) at landing.

**Rationale**  
200 N is a common choice in force-plate event definitions (e.g. Qualisys drop-jump/landing) to avoid noise and ensure clear contact.

---

### 3.3 Movement onset

**Definition**  
The start of the countermovement (unweighting): when force first drops meaningfully below bodyweight.

**Algorithm**

- **Threshold**: \( F_{\text{onset}} = \text{BW} - 5\,\sigma_{\text{quiet}} \) (configurable multiplier `onset_n_sigma`). If \( \sigma_{\text{quiet}} \) is zero or very small, fallback: \( F_{\text{onset}} = (1 - \alpha)\,\text{BW} \) with \( \alpha = 0.05 \).
- **Rule**: First sample index \( i \) such that force **remains** below the threshold for at least **30 ms** (configurable `onset_sustain_ms`). Onset = first sample of that sustained run.
- **Search window**: From \( i_{\text{start}} = \lfloor 0.5 \times \text{sample\_rate} \rfloor \) up to (but not including) `take_off`.  
  So we **ignore the first 0.5 s** (to avoid early noise or small fluctuations) and **only search before take-off** (to avoid confusing landing with onset).

**Output**  
- `movement_onset`: sample index \( i \) at movement onset.

**Note**  
If no sample in that window has \( F < F_{\text{onset}} \), `movement_onset` remains unset (None). Downstream kinematics and phase-based metrics then depend on having a valid onset.

---

### 3.4 Minimum force

**Definition**  
The index at which vertical force is **minimum** during the contact phase (onset to take-off). This marks the **end of the unweighting phase** (force has dropped to its lowest point before rising again).

**Algorithm**  
- **min_force** = `onset + argmin(force[onset : take_off+1])` when onset and take_off exist.

---

### 3.5 Eccentric end (peak eccentric velocity)

**Definition**  
The instant when the center of mass (COM) has its **most negative** vertical velocity during the contact phase—i.e. **peak eccentric (downward) velocity**. This is *not* the bottom of the dip; the bottom of the dip is when velocity = 0 (see velocity_zero).

**Algorithm**

- **Requires**: COM vertical velocity \( v(t) \) from onset to take-off (see Section 5).
- **Rule**: Among indices from `movement_onset` to `take_off` (inclusive),  
  **eccentric_end** = index at which \( v \) is **minimum** (most negative).

**Output**  
- `eccentric_end`: sample index.

**Note**  
This is the same as “Eccentric_end” in Qualisys CMJ definitions (time of peak/minimum body COM vertical velocity).

---

### 3.6 Velocity zero (bottom of dip / start of concentric)

**Definition**  
The first instant **after** eccentric end at which COM vertical velocity crosses from **≤ 0** to **> 0**—i.e. the transition from braking to concentric (push-off) phase.

**Algorithm**

- **Requires**: COM vertical velocity \( v(t) \) from onset to take-off.
- **Rule**: First index \( i \) after `eccentric_end` (within the contact phase) such that  
  \( v(i-1) \leq 0 \) and \( v(i) > 0 \).
- **Fallback**: If no such crossing exists (e.g. very short or noisy segment), we set velocity_zero to `eccentric_end + 1` so that concentric phase duration remains defined.

**Output**  
- `velocity_zero`: sample index.

---

## 4. Detected phases (areas)

Phases are **time intervals** between the points defined above. All boundaries are **sample indices**; duration in seconds is \( \Delta t = \Delta i / \text{sample\_rate} \).

| Phase          | Start index       | End index         | Description |
|----------------|-------------------|-------------------|-------------|
| **Weighing**   | 0                 | ~1 s              | Standing still; used only for BW (first 1 s). |
| **Unweighting**| `movement_onset`  | `min_force`       | Force drops below BW until minimum force. |
| **Braking**    | `min_force`       | `velocity_zero`   | From min force to bottom of dip (v = 0). |
| **Propulsion (concentric)** | `velocity_zero` | `take_off` | Push-off; v > 0 until take-off. |
| **Flight**     | `take_off`        | `landing`         | No contact; force near zero. |
| **Landing**    | `landing`         | End of trial      | Impact and stabilization. |

**Notes**

- **Weighing** is fixed as the first 1 s for baseline only; we do not output a separate “weighing end” event.
- **Unweighting** and **braking** together correspond to the eccentric part of the CMJ (force below BW, then force rising through BW until v = 0).
- **Propulsion** is the concentric phase (force above BW, COM moving upward until take-off).
- We do **not** currently output a dedicated `CMJPhases` structure in the main pipeline; all phase boundaries are implied by the five events above. The codebase defines a `CMJPhases` dataclass for possible future use.

---

## 5. Kinematics: acceleration and velocity from force

**Purpose**  
Compute vertical COM acceleration and velocity so we can define eccentric end and velocity zero, and later power and impulse-based metrics.

**Assumptions**

- Only vertical GRF is used; horizontal forces are ignored.
- COM motion obeys \( F_{\text{GRF}}(t) - m g = m a(t) \), with positive upward.

**Formulas**

1. **Acceleration** (full-length array):  
   \( a(t) = \dfrac{F(t) - \text{BW}}{m} \),  
   with \( m = \text{BW}/g \). Units: m/s².

2. **Velocity** (from movement onset to take-off):  
   - \( v(\text{onset}) = 0 \).  
   - \( v(t) = \int_{\text{onset}}^{t} a(\tau)\,d\tau \) for \( t \in [\text{onset}, \text{take\_off}] \).  
   Integration is done numerically with the **trapezoidal rule** (`scipy.integrate.cumtrapz`).  
   **Drift correction**: After integration, a linear correction is applied so that \( v(\text{take\_off}) = J/m \) (impulse/mass). The correction is a ramp from 0 at onset to \( (v_{\text{expected}} - v_{\text{integrated}}) \) at take-off, removing integration drift.  
   Outside the contact interval, velocity is set to 0. Units: m/s.

**Implementation detail**  
Integration is over the segment `[onset_idx, take_off_idx + 1]` so that the velocity at the take-off sample is included. All downstream uses (eccentric end, velocity zero, power, impulse) use this same velocity series.

---

## 6. Metrics (formulas)

All metrics are computed from the **total** vertical force, bodyweight/mass, and the detected events/velocity. If optional low-pass filtering is used, the **same filtered force** used for event detection is used for kinematics and these metrics.

### 6.1 Jump height

**6.1.1 Impulse–momentum method (primary)**

- **Impulse** (contact phase):  
  \( J = \int_{t_{\text{onset}}}^{t_{\text{TO}}} \bigl( F(t) - \text{BW} \bigr)\,dt \).  
  Implemented as trapezoidal integration over samples `[onset, take_off]` (inclusive).
- **Take-off velocity**:  
  \( v_{\text{TO}} = J / m \).
- **Jump height** (from take-off to apex, under constant \(-g\)):  
  \( H_{\text{impulse}} = \dfrac{v_{\text{TO}}^2}{2g} \).  
  Units: m.

**6.1.2 Flight-time method (cross-check)**

- **Flight time**:  
  \( t_{\text{flight}} = (\text{landing\_index} - \text{take\_off\_index}) / \text{sample\_rate} \).  
  Units: s.
- **Jump height**:  
  \( H_{\text{flight}} = \dfrac{g\,t_{\text{flight}}^2}{8} \).  
  Derivation: time to apex = \( t_{\text{flight}}/2 \), \( v_{\text{TO}} = g\cdot(t_{\text{flight}}/2) \), so \( H = v_{\text{TO}}^2/(2g) = g\,t_{\text{flight}}^2/8 \).  
  Units: m.

**Output**  
- `take_off_velocity_m_s`, `jump_height_impulse_m`, `flight_time_s`, `jump_height_flight_m`.

---

### 6.2 Peak power

**Definition**  
Maximum instantaneous vertical power during the contact phase (onset → take-off).

**Formula**  
\( P(t) = F(t)\,v(t) \).  
**Peak power** = \( \max_{t \in [\text{onset}, \text{take\_off}]} P(t) \).  
Units: W.

**Output**  
- `peak_power_W`.

---

### 6.3 Rate of force development (RFD)

**Definition**  
Rate of change of force (dF/dt) after Savitzky–Golay smoothing to reduce noise while preserving peaks.

**Algorithm**

1. **Smoothing**: Savitzky–Golay filter on \( F(t) \), window ~20 ms, polynomial order 3 (`scipy.signal.savgol_filter`).
2. **RFD**: \( \text{RFD}(t) = d(\text{smoothed } F)/dt \) (numpy gradient).
3. **Peak RFD** (global): Maximum over contact phase (onset → take_off).
4. **Peak RFD eccentric**: Maximum over [onset, velocity_zero].
5. **Peak RFD concentric**: Maximum over [velocity_zero, take_off].
6. **RFD 0–100 ms / 0–200 ms**: Maximum RFD in the first 100 ms or 200 ms after onset.

**Output**  
- `peak_rfd_N_per_s`, `peak_rfd_eccentric_N_per_s`, `peak_rfd_concentric_N_per_s`, `rfd_0_100ms_N_per_s`, `rfd_0_200ms_N_per_s`.

---

### 6.4 Phase impulses and phase durations

**Unweighting phase** (onset → min_force)

- **Unweighting impulse**:  
  \( J_{\text{unweight}} = \int_{t_{\text{onset}}}^{t_{\text{min\_force}}} \bigl( F(t) - \text{BW} \bigr)\,dt \).  
  Expected to be **negative**. Units: N·s.
- **Unweighting time**: \( (\text{min\_force} - \text{onset}) / \text{sample\_rate} \).  
- **Eccentric time** (onset to peak eccentric velocity): \( (\text{eccentric\_end} - \text{onset}) / \text{sample\_rate} \).

**Braking phase** (min_force → velocity_zero)

- **Braking impulse**:  
  \( J_{\text{braking}} = \int_{t_{\text{min\_force}}}^{t_{v=0}} \bigl( F(t) - \text{BW} \bigr)\,dt \).  
  Units: N·s.

**Propulsion phase** (velocity_zero → take_off)

- **Propulsion impulse**: \( J_{\text{prop}} = \int_{t_{v=0}}^{t_{\text{TO}}} \bigl( F(t) - \text{BW} \bigr)\,dt \).  
  Should equal \( m\,v_{\text{TO}} \). Units: N·s.
- **Concentric time**: \( (\text{take\_off} - \text{velocity\_zero}) / \text{sample\_rate} \).

**Output**  
- `unweighting_impulse_Ns`, `unweighting_time_s`, `eccentric_time_s`, `braking_impulse_Ns`, `propulsion_impulse_Ns`, `concentric_time_s`.

---

### 6.5 Additional metrics

- **Time to take-off**: \( (\text{take\_off} - \text{onset}) / \text{sample\_rate} \). Output: `time_to_takeoff_s`.
- **RSImod**: \( \text{jump\_height\_impulse\_m} / \text{time\_to\_takeoff\_s} \). Output: `rsi_mod`.
- **Peak eccentric velocity**: \( \max(0, -\min(v)) \) over contact (magnitude, downward). Output: `peak_eccentric_velocity_m_s`.
- **Peak / mean concentric force**: max and mean of F over [velocity_zero, take_off]. Output: `peak_concentric_force_N`, `mean_concentric_force_N`.
- **Minimum force value**: \( F(\text{min\_force}) \). Output: `min_force_N`.
- **COM displacement**: \( s(t) = \int_{\text{onset}}^t v(\tau)\,d\tau \).  
  - **Countermovement depth**: \( \min(s) \) over contact (negative = downward). Output: `countermovement_depth_m`.  
  - **COM displacement at take-off**: \( s(\text{take\_off}) \). Output: `com_displacement_at_takeoff_m`.

---

### 6.6 Left/right asymmetry

When left_force and right_force are present, asymmetry index (signed) is computed as  
\( \text{AI} = 2\,(L - R)/(L + R) \times 100 \). Positive = left dominant.

**Output**  
- `peak_force_asymmetry_pct` (concentric peak force L vs R),  
- `concentric_impulse_asymmetry_pct`,  
- `eccentric_impulse_asymmetry_pct` (onset → min_force),  
- `rfd_asymmetry_pct`.

---

### 6.7 Trial validity

Checks performed (no exception; flags only):

- **Single take-off**: Count descending crossings of take-off threshold; if > 1, flag `multiple_takeoff`.
- **Flight duration**: If \( t_{\text{flight}} \) &lt; 0.1 s or &gt; 2.0 s, flag `short_flight` or `long_flight`.

**Output**  
- `TrialValidity(is_valid, flags)`; if not valid, flags are printed and optionally shown in the plot title.

---

## 7. Optional processing: low-pass filter

**Purpose**  
Reduce high-frequency noise before event detection and kinematics, to make threshold crossings and integration more stable.

**Algorithm**

- **Filter**: 4th-order Butterworth low-pass, zero-phase (forward–backward) via `scipy.signal.filtfilt`.
- **Cutoff**: User-defined (e.g. 50 Hz or 100 Hz). If cutoff ≥ Nyquist, the signal is returned unchanged.
- **Usage**: When enabled (e.g. CLI `--filter 80`), a **copy** of the trial is made where the **force** channel is replaced by the filtered force. This copy is used for:
  - Take-off, landing, and movement onset detection  
  - COM acceleration/velocity integration  
  - All metrics above  
  Bodyweight is still computed from the **raw** force (first 1 s). Visualization can show either raw or filtered; currently the plot shows **raw** force with events that were detected from the filtered signal (if used).

---

## 8. Summary: what is detected and what is not

**Points (events) detected**

| Point            | Symbol / name   | How it is detected |
|------------------|-----------------|---------------------|
| Take-off         | `take_off`      | First descending crossing with K consecutive samples below \( F_{\text{TO}} \). |
| Landing          | `landing`       | First ascending crossing of \( \max(200\,\text{N},\,0.05\,\text{BW}) \) after take-off, sustained 20 ms. |
| Movement onset   | `movement_onset`| First sustained run (30 ms) of \( F < \text{BW} - 5\sigma_{\text{quiet}} \) (or \( < 0.95\,\text{BW} \) fallback). |
| Min force        | `min_force`     | argmin(F) in [onset, take_off]; end of unweighting. |
| Eccentric end    | `eccentric_end` | Index of peak eccentric (min) COM velocity. |
| Velocity zero    | `velocity_zero` | First v > 0 after eccentric_end (bottom of dip). |

**Phases (areas) derived**

- Unweighting: onset → min_force  
- Braking: min_force → velocity_zero  
- Propulsion: velocity_zero → take_off  
- Flight: take_off → landing  
- Landing: landing → end of trial  

**Metrics computed**

- Bodyweight, mass, sigma_quiet  
- Jump height (impulse–momentum and flight-time), time to take-off, RSImod  
- Take-off velocity, flight time, peak power  
- Peak RFD (global, eccentric, concentric), RFD 0–100 ms, 0–200 ms  
- Unweighting, braking, propulsion impulses; unweighting/eccentric/concentric times  
- Peak eccentric velocity, peak/mean concentric force, min_force_N  
- Countermovement depth, COM displacement at take-off  
- Left/right asymmetry (peak force, concentric impulse, eccentric impulse, RFD)  
- Trial validity (single take-off, flight duration flags)  

**Not implemented / left for review**

- Explicit **weighing end** as an event (we use a fixed 1 s window).  
- **Double-integration** jump height (COM displacement from standing to apex).  
- **Filtering of velocity** before finding eccentric end / velocity zero (only force can be optionally filtered).

---

## 9. Glossary and references

- **BW**: bodyweight (N).  
- **COM**: center of mass.  
- **GRF**: ground reaction force.  
- **RFD**: rate of force development (N/s).  
- **Sample index**: integer index into the force/time arrays (0-based).

**References (cited in design)**

- Qualisys Appendix C – Event definitions (force-based take-off/landing thresholds).  
- BMC Vertical Jump notebook – impulse–momentum and flight-time jump height, COM from GRF.  
- Systematic review on CMJ jump height methods (e.g. Springer 2023).  
- CMJ force–time curve phases (e.g. Strength & Conditioning Journal; Salford/Bohrium phase descriptions).

---

*End of documentation. This document describes the implementation as of the current codebase and is intended for expert review and feedback.*
