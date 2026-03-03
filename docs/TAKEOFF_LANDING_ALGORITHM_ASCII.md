# Takeoff & Landing Detection — ASCII Visualization

## Intended behavior (what we want)

```
Force
  ^
  |     CONCENTRIC PUSH          FLIGHT DIP              LANDING SPIKE
  |          ___                    ~~~
  |         /   \                  /   \                    /\
  |        /     \                /     \                  /  \
  |   ____/       \______________/       \________________/    \____
  |       |                    |     |     |                    |
  |       |                    |     |     |                    |
  |       |              --------+---+---+--------  <- FLIGHT LINE (mean + 50%)
  |       |                    |     |     |                    |
  |       |                    ^     ^     ^                    ^
  |       |                    |     |     |                    |
  |       |                 takeoff  mid  landing            (spike - NOT landing)
  |       |                    |     |     |
  |       |                    |     valley
  |       |                    |     (lowest point)
  |       |                    |
  |       |              "waterfall"  "rising wall"
  |       |              (descent     (ascent back
  |       |               into dip)   to line)
  |
  +---------------------------------------------------------------------> time
        concentric peak    expanded segment [take_off ......... landing]
                          (after expand_flight_to_dip)
```

**Goal:**
- **Takeoff** = **first** point where force is **on the flight line** (within a small band) on the **way down** (waterfall).
- **Landing** = **first** point where force is **on the flight line** on the **way up** (rising wall), after the valley — so takeoff and landing have almost the same force and are not in the middle of the slopes.

---

## Preprocessing: Tare (force ≥ 0)

Before analysis, force is **tared** so all values are ≥ 0: subtract `min(force)` from the total (and left/right) force. That keeps the flight line and band on the positive side and avoids negative values.

## Implementation (band-based, same force for takeoff & landing)

Takeoff and landing are forced to lie **on the flight line** (within a tolerance band) so they have almost the same force value, and we avoid picking points in the middle of the waterfall or rising wall. A **rolling-window** smooths the force when finding band crossings so takeoff/landing sit at the bottom of the free fall and rising wall; a **minimum gap** (e.g. 50 ms) keeps them from being clamped next to each other.

```
Step 1: Get initial flight segment [take_off, landing] (after expansion)
        |<---------------- segment ------------------>|
        take_off ............................... landing

Step 2: Flight line = mean(force in segment) * 1.50   (capped at 50% BW and ≥ 0)
        Band: line_lo = line * 0.92, line_hi = line * 1.08  (±8% = "on the line", robust to noise)
        Optional: smooth force with rolling mean (e.g. 30 ms window) for band checks so points are at bottom of free fall / rising wall.
        Min gap: takeoff and landing must be at least 150 ms apart (configurable) so they are not clamped; search is constrained so each point respects this gap.

Step 3: Valley = index of MIN(force) within segment
        take_off ......... mid ......... landing
                    ^
                    valley (lowest point)

Step 4: Takeoff
        First index i in [take_off .. mid] where force in band (first on line, descent).
        Fallback 1: first i where force[i] <= line_hi (at or below line). Fallback 2: closest to line in left half;
        if that picks valley (mid), use first at-or-below line or keep segment start (never put takeoff at valley).

Step 5: Landing
        First index i in [mid .. landing] where force[i] > valley AND force in band (rising wall).
        Fallbacks: first after mid with force > valley AND in band; else closest to line on ascending part only.
```

So both points are in the same force band (almost the same value) and sit on the line, not in the middle of the slopes.

---

## Why the old “closest in half” logic went wrong (ASCII)

If the flight line sits **above** the valley, then in the **right half** the curve looks like:

```
        RIGHT HALF:  [mid -------- landing]
        Force
          ^
          |                    *  <- spike (far above line)
          |                   /
          |                  /
          |  ---line--------+--------  FLIGHT LINE
          |                 \
          |                  \__
          |                    ^
          |                    mid (valley) — CLOSEST to line in right half!
          |
          +---------------------------------> index
                mid                      landing
```

So **landing** is chosen as the point in the right half **closest to the line**. That can be **at or near `mid`** (the valley), because the valley is closer to the line than the spike. So we mark **landing = valley** instead of **landing = where the curve crosses the line on the way up** (the rising wall).

---

## What we want (ASCII)

```
        RIGHT HALF:  we want the point on the RISING part that is ON the line
        Force
          ^
          |                    *  <- spike (ignore)
          |                   /
          |                  /
          |  ---line--------X--------  FLIGHT LINE  <- LANDING = here (first/last on line going up)
          |                 /
          |                /
          |               *
          |               
          |                mid (valley)
          |
          +---------------------------------> index
                mid         ^
                         landing (on rising wall, on the line)
```

So we want **landing** = the point on the **ascent** (after the valley) where the curve **crosses or is closest to** the flight line, not the global closest in the right half (which can be the valley).

---

## Summary

| Item        | Implementation |
|------------|-----------------|
| Tare       | force = force - min(force) so all values ≥ 0 (before baseline) |
| Flight line| mean(segment) × 1.50, capped at 50% BW and ≥ 0 |
| Band       | line ± 8% (takeoff & landing same force; 8% tolerates noise) |
| Rolling window | 30 ms (config: `FLIGHT_LINE_ROLLING_WINDOW_MS`) for smoothed band checks |
| Min gap    | 150 ms (config: `MIN_FLIGHT_GAP_MS`); search constrained so takeoff/landing cannot be chosen within this window |
| Takeoff    | First in [take_off..mid] where force in band. Fallbacks: first at or below line; else closest to line in left half (never valley). |
| Landing    | First index in [mid..landing] where force > valley and force in band (first on line, rising wall). Fallbacks: first in band after mid; else closest to line on ascending part. |
