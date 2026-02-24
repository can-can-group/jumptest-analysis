# CMJ Force Plate Analysis

Analyze counter-movement jump (CMJ) force plate exports: detect events (movement onset, take-off, landing), phases, key points (P1/P2), and compute physics-based metrics (jump height, peak power, RFD, phase impulses). This codebase is designed to be used **as a service** from your API: you send raw force data (or a path to a JSON file), and get back a structured analysis payload suitable for your frontend or other consumers.

---

## Connecting your frontend to the API

This section documents everything needed to integrate a web or mobile frontend with the Jump Test API (auth, users, jump tests, viewer links, and email).

### Base URL and CORS

- **Base URL:** Your API root, e.g. `http://localhost:8000` in development or `https://your-api.example.com` in production.
- **CORS:** The API allows all origins (`allow_origins=["*"]`). For production you may want to restrict this in `api/main.py` (e.g. `allow_origins=["https://your-frontend.com"]`).
- **OpenAPI (Swagger):** `GET {base}/docs` — interactive docs and “Try it out” for all endpoints.
- **Health:** `GET {base}/health` → `{ "status": "ok" }`.

### Authentication (admin only)

Only **admin** users are authenticated. There is no end-user login; athletes view their tests via shareable links (`/my-tests?user_id=...`, `/viewer?test_id=...`). In production, the API is served behind a reverse proxy and email links route through the main website; see **Reverse proxy and gateway routing** below.

**1. Create an admin (one-time, e.g. from backend or script)**  
- **Endpoint:** `POST /admin/register`  
- **Header:** `X-Admin-Secret: <ADMIN_SECRET>` (from `.env`)  
- **Body (JSON):** `{ "email": "admin@example.com", "password": "your-password" }`  
- **Response:** `201` → `{ "email": "admin@example.com", "created": true }`  
- **Errors:** `403` missing/wrong secret; `409` email already exists.

**2. Log in (get JWT)**  
- **Endpoint:** `POST /auth/login`  
- **Body (JSON):** `{ "email": "admin@example.com", "password": "your-password" }`  
- **Response:** `200` → `{ "access_token": "<JWT>", "token_type": "bearer" }`  
- **Errors:** `401` invalid email or password.

**3. Call protected endpoints**  
- **Header:** `Authorization: Bearer <access_token>`  
- Required for: all **User** endpoints (`POST/GET/PUT/DELETE /users`, `GET /users`).  
- **Jump test** endpoints (`POST/GET /jump-tests`, `GET /jump-tests/{id}`, etc.) do **not** require auth.

**Example (fetch):**

```javascript
// Login
const loginRes = await fetch(`${API_BASE}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "admin@example.com", password: "secret" }),
});
const { access_token } = await loginRes.json();

// List users (protected)
const usersRes = await fetch(`${API_BASE}/users?limit=10`, {
  headers: { "Authorization": `Bearer ${access_token}` },
});
const users = await usersRes.json();
```

---

### Users (admin only)

All `/users` routes require `Authorization: Bearer <token>`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/users` | Create user (sends welcome email with “View my jump tests” link) |
| `GET`  | `/users` | List users (paginated) |
| `GET`  | `/users/{user_id}` | Get one user |
| `PUT`  | `/users/{user_id}` | Update user |
| `DELETE` | `/users/{user_id}` | Delete user |

**Create user — request body:**

```json
{
  "email": "athlete@example.com",
  "name": "Jane",
  "last_name": "Doe",
  "phone_number": "+1234567890",
  "student_number": "S12345",
  "gender": "F"
}
```

All fields except `email` are optional. Response: same shape as **User response** below. On success, a welcome email is sent (if SMTP is configured) with a link to `{EMAIL_BASE_URL}/my-tests?user_id=<id>`.

**List users — query params:**

- `limit` (default 20, max 100)  
- `offset` (default 0)

**User response (single or list item):**

```json
{
  "id": "507f1f77bcf86cd799439011",
  "email": "athlete@example.com",
  "name": "Jane",
  "last_name": "Doe",
  "phone_number": "+1234567890",
  "student_number": "S12345",
  "gender": "F",
  "created_at": "2026-02-20T12:00:00Z",
  "updated_at": "2026-02-20T12:00:00Z"
}
```

**Update user — request body:** same fields as create, all optional; only sent fields are updated.

---

### Jump tests (no auth required)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jump-tests` | Submit jump test; returns analysis + stored `id` |
| `GET`  | `/jump-tests` | List tests (filter by user, athlete, type, date range) |
| `GET`  | `/jump-tests/{id}` | Get one test (result + metadata; optional raw) |
| `GET`  | `/jump-tests/{id}/viz` | Viz JSON for the web viewer |
| `POST` | `/jump-tests/{id}/send-link` | Email result link (optional override email) |

**Submit jump test — request body:**

```json
{
  "test_type": "CMJ",
  "test_duration": 2.5,
  "total_force": [ 0, 100, 200, ... ],
  "left_force": [ 0, 50, 100, ... ],
  "right_force": [ 0, 50, 100, ... ],
  "user_id": "507f1f77bcf86cd799439011",
  "athlete_id": "optional-override"
}
```

- **Required:** `test_type` (e.g. `"CMJ"`, `"DJ"`, `"SJ"`), `test_duration` (seconds), **either** `force` or `total_force`, `left_force`, `right_force`.  
- **Optional:** `user_id` (links test to a user), `athlete_id` (defaults to `user_id` or `"unknown"`), `sample_count`, `name`, `started_at`.  
- **Response:** `200` → `{ "id": "<test_id>", ...analysis payload }` (same structure as the `result` object below).  
- **Errors:** `400` if validation or analysis fails (e.g. invalid force data).

**List jump tests — query params:**

- `user_id` — filter by user  
- `athlete_id` — filter by athlete  
- `test_type` — e.g. `CMJ`, `DJ`  
- `from_date`, `to_date` — ISO datetime  
- `limit` (default 20, max 100), `offset` (default 0)

**List response:**

```json
{
  "items": [
    {
      "id": "507f1f77bcf86cd799439012",
      "athlete_id": "507f1f77bcf86cd799439011",
      "test_type": "CMJ",
      "created_at": "2026-02-20T12:00:00Z",
      "metrics": { "jump_height_impulse_m": 0.32, "flight_time_s": 0.45, ... }
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

**Get one test —** `GET /jump-tests/{id}`  
- Optional query: `include_raw=true` to include the raw request body.  
- Response includes `id`, `user_id`, `athlete_id`, `test_type`, `result` (full analysis), `created_at`, and optionally `raw`.

**Viz for viewer —** `GET /jump-tests/{id}/viz`  
Returns only the `result` payload (time series, phases, key_points, metrics, analysis) used by the built-in viewer. Your frontend can use this to drive a custom chart or reuse the same JSON shape.

**Send result link by email —** `POST /jump-tests/{id}/send-link`  
- **Body (optional):** `{ "email": "override@example.com" }`. If omitted, the API uses the email of the user linked to the test (`user_id`).  
- **Response:** `200` → `{ "sent": true }`.  
- **Errors:** `400` no email available; `404` test not found; `503` SMTP not configured or send failed (see `.env.example` for SMTP).

---

### Viewer and “My tests” pages (shareable links)

The API serves two HTML pages:

- **Viewer (single test):** `{base}/viewer?test_id=<id>`  
  Loads the test from `GET /jump-tests/{id}/viz` and shows the force chart, phases, and key points.

- **My tests (user’s list):** `{base}/my-tests?user_id=<user_id>`  
  Lists that user’s jump tests with “View” links to the viewer.

Both work without authentication.

### Reverse proxy and gateway routing (production)

When deployed behind a reverse proxy (e.g. Nginx at `wellbodytech.com/arge/`), set `BASE_PATH` in `.env` to match the proxy location:

```env
BASE_PATH=/arge
EMAIL_BASE_URL=https://wellbodytech.com
```

**How it works:**

1. Nginx proxies `wellbodytech.com/arge/*` to `localhost:8765/*` (path stripping)
2. `BASE_PATH=/arge` makes all internal links and API calls use the `/arge/` prefix
3. `EMAIL_BASE_URL=https://wellbodytech.com` makes email links point to the website gateway
4. The website has gateway pages (`/viewer`, `/my-tests`) that embed the API in an iframe via `/arge/viewer?test_id=<id>`
5. All traffic stays on `wellbodytech.com` — no separate subdomain needed

For self-hosted deployments without a website gateway, set `EMAIL_BASE_URL` to the public API URL (e.g. `https://customer.com/jump-test`). Email links go directly to the API viewer.

For local development, leave both `BASE_PATH` and `EMAIL_BASE_URL` empty (defaults to root path and `localhost:8000`).

---

### Response shapes your frontend can rely on (analysis result)

After submit or from `GET /jump-tests/{id}` / `GET /jump-tests/{id}/viz`, the `result` object includes:

- **`phases`** — array of `{ name, start_time_s, end_time_s, duration_s, ... }`  
- **`key_points`** — array of `{ name, index, time_s, value_N, ... }`  
- **`metrics`** — flat dict of metric name → number (e.g. `jump_height_impulse_m`, `flight_time_s`, `peak_power_W`)  
- **`analysis`** — `{ phases, key_points, metrics }` with per-key `{ value, explanation }` for tooltips/UI; use `analysis.phase_order` and `analysis.key_point_order` for display order.

Use these for custom dashboards, tables, or charts alongside or instead of the built-in viewer.

---

### Error handling

- **401 Unauthorized:** Missing or invalid/expired Bearer token on protected routes. Redirect to login or refresh token.  
- **403 Forbidden:** Wrong or missing `X-Admin-Secret` on `POST /admin/register`.  
- **404 Not Found:** Invalid `user_id` or `test_id` (e.g. not in DB).  
- **409 Conflict:** Duplicate email (user or admin).  
- **503 Service Unavailable:** Email send failed (e.g. SMTP not configured). Response `detail` explains the reason.

All error responses follow the FastAPI default: `{ "detail": "message" }` (string or list of validation errors).

---

### Quick reference: env and URLs

| Env / URL | Purpose |
|-----------|--------|
| `MONGODB_URI`, `MONGODB_DB` | Database (required for API) |
| `ADMIN_SECRET` | Create admins via `POST /admin/register` |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | Admin JWT |
| `SMTP_*`, `EMAIL_BASE_URL` | Welcome + result emails |
| `BASE_PATH` | Reverse proxy prefix (e.g. `/arge`); empty for standalone |
| `{base}/docs` | OpenAPI UI |
| `{base}/health` | Health check |
| `{base}/viewer?test_id=` | Viewer for one test |
| `{base}/my-tests?user_id=` | User’s test list |
| `{base}/admin` | Admin panel (login + user CRUD) |

---

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

## Run the Jump Test API (lightweight server)

From the project root, with MongoDB running (e.g. `mongodb://localhost:27017`):

```bash
export MONGODB_URI=mongodb://localhost:27017   # optional; default
export MONGODB_DB=jumptest                     # optional; default
PYTHONPATH=. .venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

- **OpenAPI docs:** http://localhost:8000/docs  
- **Documentation (MkDocs):** Run `mkdocs build` in the project root, then open http://localhost:8000/documentation/  
- **Admin panel:** http://localhost:8000/admin — log in with an admin account (create admins via `POST /admin/register` with header `X-Admin-Secret`; see `.env.example`).  
- **Users:** `POST/GET/PUT/DELETE /users`, `GET /users` (admin JWT required). User fields: name, last_name, email, phone_number, student_number, gender.  
- **Jump tests:** `POST /jump-tests` (body: `test_type`, `test_duration`, `force` or `total_force`, `left_force`, `right_force`; optional `user_id`, optional `athlete_id`) → returns analysis and stores raw + result in MongoDB.  
- **History:** `GET /jump-tests?user_id=...&athlete_id=...&test_type=...&from_date=...&to_date=...&limit=...&offset=...`  
- **One result:** `GET /jump-tests/{id}`; **viz JSON for viewer:** `GET /jump-tests/{id}/viz`  
- **Viewer:** http://localhost:8000/viewer?test_id=ID — shareable link to view a jump test. You must include `?test_id=<id>` in the URL; the viewer is served by the API so it can load data from `/jump-tests/{id}/viz`.  
- **My tests:** http://localhost:8000/my-tests?user_id=ID — list tests for a user with “View” links.  
- **Email result link:** `POST /jump-tests/{id}/send-link` (optional body `{ "email": "..." }`). Configure SMTP in `.env` (see below).

### Configuring email (Gmail)

To send jump test result links by email, set in `.env`:

- `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`
- `SMTP_USER` = your Gmail address
- `SMTP_PASSWORD` = [App Password](https://myaccount.google.com/apppasswords) (not your normal password)
- `SMTP_FROM` = same as SMTP_USER (or your sender address)
- `EMAIL_BASE_URL` = base URL for email links. Set to `https://wellbodytech.com` in production (gateway routing) or `http://localhost:8000` for local development

If SMTP is missing or wrong, `POST /jump-tests/{id}/send-link` returns **503** with a message (e.g. "SMTP not configured..." or "SMTP authentication failed. For Gmail use an App Password...").

### Create a user and send them a link

To create a user (e.g. `sinasevda12389@gmail.com`) and send them a jump test result link:

```bash
export ADMIN_SECRET=your-secret
PYTHONPATH=. python script/create_user_and_send_link.py sinasevda12389@gmail.com --test-id YOUR_TEST_ID
```

Or create the user, submit a jump test from a JSON file, then send the link in one go:

```bash
PYTHONPATH=. python script/create_user_and_send_link.py sinasevda12389@gmail.com --jump-test-json saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json
```

SMTP must be configured in `.env` for the email to be sent.

### Test all endpoints (script)

With the API running and `ADMIN_SECRET` set in `.env`, run (requires `requests`):

```bash
pip install requests
export ADMIN_SECRET=your-secret
PYTHONPATH=. python script/test_api_endpoints.py saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json
```

Or use a CMJ file: `saved_raw_data/cmj-data/saved3.json`. The script creates an admin (if needed), logs in, creates a user, submits the jump test from the JSON file, fetches the test and history, tries send-link, and prints the viewer and my-tests URLs.

### Run with Docker

Only the **API** runs in Docker. MongoDB is not included—use your cloud database by setting `MONGODB_URI` (and optionally `MONGODB_DB`) in `.env`.

**Prerequisites:** Docker and Docker Compose.

1. **Create `.env`** (copy from `.env.example`). Set at least:
   - `MONGODB_URI` — your cloud MongoDB connection string (e.g. Atlas `mongodb+srv://...`)
   - `MONGODB_DB` — database name (default `jumptest`)
   - `ADMIN_SECRET`, `JWT_SECRET` — for admin auth

2. **Build and start:**

   ```bash
   docker compose up -d
   ```

   - API: http://localhost:8000  
   - OpenAPI: http://localhost:8000/docs  

3. **Create an admin** (first time):

   ```bash
   curl -X POST http://localhost:8000/admin/register \
     -H "Content-Type: application/json" \
     -H "X-Admin-Secret: YOUR_ADMIN_SECRET" \
     -d '{"email":"admin@example.com","password":"your-password"}'
   ```

4. **Logs:** `docker compose logs -f api`

5. **Stop:** `docker compose down`

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

## Drop jump analysis

The same viewer can display **drop jump (DJ)** trials. DJ analysis detects **eight key points** (drop landing, peak impact, contact through point, start of concentric, peak drive-off, take-off, flight land, peak landing force) using a **three-peak + one-valley** model over the contact phase, then computes **metrics** (contact time, flight time, jump height, RSI, braking/propulsive impulse and RFD, peak forces, phase durations) and **classification** (high reactive vs low reactive) from the curve shape and time spacing of the points.

**Run DJ export (batch):**

```bash
PYTHONPATH=. python3 script/export_dj_viz.py [path_to_dj_json_dir]
```

- Default input: `saved_raw_data/dj-data/` (all `*.json` with `test_type` DJ).
- Output: `output/<stem>_viz.json` per file and `output/dj_detection_results.json` (summary of all trials).

Open `web/viewer.html` and load any `*_viz.json` to see phases, key points, and metrics.

**Documentation:**

- **[docs/DROP_JUMP_ANALYSIS.md](docs/DROP_JUMP_ANALYSIS.md)** – Overview: what the pipeline does, how points are detected (episodes → contact start → take-off → three peaks + CTP → second landing), how classification and metrics work, how to run the analysis (export script vs in code), and where the code lives.
- **[docs/DROP_JUMP_DETECTION_ALGORITHM.md](docs/DROP_JUMP_DETECTION_ALGORITHM.md)** – Detailed algorithm: thresholds, validation windows, and constants for each key point and phase.

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
- **src/detect**: bodyweight/mass (`baseline.py`), take-off/landing/onset (`events.py`), eccentric end and v=0 (`phases.py`), P1/P2 detection (`structural_peaks.py`), trial validity (`validity.py`). **Drop jump:** `drop_jump.py` (contact episodes, drop landing, take-off, three-peak + CTP detection, metrics, high/low reactive classification).
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
