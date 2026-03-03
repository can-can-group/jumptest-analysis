# Plan: Noise filtering and batch debug for jump test detection

## Important: database is read-only

- **Do not change any data in the database.** All work is read-only from MongoDB.
- **Workflow:** Get all jump test data locally (read from DB) → run analysis locally (with improved/filtered algorithms) → write results only to **local files** (reports, CSV, exported JSON). Use these local outputs to improve the CMJ and SJ algorithms and to compute all points and results for the data you have collected, without ever writing back to the database.

---

## Problem

~324 stored jump tests; many have points, phases, and statistics failing to detect despite time-series looking reasonable. Likely cause: high-frequency noise (“furry” curves). The API currently runs analysis on **raw** force data with **no filtering**; only the CLI supports optional `--filter`.

## Goals

1. Add configurable low-pass filtering to the analysis pipeline so future API submissions can use filtered data.
2. **Batch debug (read-only):** Fetch all stored tests from the DB locally, run analysis (with/without filter) locally, and output a report + optional exported results to local files—**no updates to MongoDB**.
3. Use the local results to **improve CMJ and SJ algorithms** and to **recalculate all points and results** for your collected data on your machine; any “corrected” or recalculated results live only in local exports (e.g. CSV, JSON files), not in the database.

---

## 1. Add noise filtering to the analysis pipeline

- **Config:** Add `FORCE_FILTER_CUTOFF_HZ` in `api/config.py` (default `0` = disabled).
- **Pipeline:** In `src/run_analysis.py`, after loading the trial, optionally apply `lowpass_filter` from `src/signal/filter.py` to force/left_force/right_force; build a filtered `CMJTrial` and use it for all detection (CMJ, SJ, DJ). Baseline (bodyweight) computed from raw trial.
- **API:** Use config (and optional request-body override) to pass filter cutoff into `run_analysis`. Document in `.env.example`.

---

## 2. Batch debug script (read-only, local output only)

**Script:** `script/debug_jump_tests_batch.py`

- **MongoDB:** **Read-only.** Only `find()` on `jump_tests` to get `raw` (and optionally existing `result`). No `insert`, `update`, `delete`, or any write operations.
- **Flow:**
  1. Connect to MongoDB (same as API); iterate over `jump_tests` (with `--limit` / `--offset`).
  2. For each document, read `raw`; if missing, record and skip.
  3. Run analysis locally (no filter and/or with filter). Catch exceptions; record status, validity, key_points count, phases count.
  4. Write all results to **local files only:** e.g. `--output debug_report.csv`, optional `--export-dir ./debug_exports/` to write per-test JSON (recalculated points and results) to disk.
- **Output:** CSV/JSON report + optional per-test exported JSON so you can inspect recalculated points and results locally and use them to improve CMJ/SJ algorithms. **Nothing is written back to the database.**

---

## 3. Optional: `run_analysis(data, filter_cutoff_hz=None)`

- Add optional `filter_cutoff_hz` to `run_analysis` so the batch script can call it with/without filter without env hacks. API can pass config/body value.

---

## 4. Summary of “no DB writes” and local improvement

| Action                    | Database        | Local |
|---------------------------|-----------------|--------|
| Fetch jump tests          | Read only       | —      |
| Run analysis (debug)      | —               | Yes    |
| Write report (CSV/JSON)    | No              | Yes    |
| Export recalculated results| No              | Yes (files) |
| Improve CMJ/SJ algorithms | No              | Yes (code + local runs) |
| Calculate points/results   | No              | Yes (output to files) |

You keep the DB unchanged and use local data + local outputs to improve the algorithms and recompute all points and results for your collected data.
