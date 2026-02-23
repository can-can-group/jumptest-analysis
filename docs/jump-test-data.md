# Jump test data

## Submitting a jump test

`POST /jump-tests` — no authentication required. Body (JSON):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `athlete_id` | string | No | Optional; defaults to `user_id` or `"unknown"`. |
| `test_type` | string | Yes | `"CMJ"`, `"SJ"`, or `"DJ"`. |
| `test_duration` | number | Yes | Duration of the recording in seconds. |
| `force` or `total_force` | array of numbers | Yes (one of) | Total vertical force (N) per sample. |
| `left_force` | array of numbers | Yes | Left force plate (N). |
| `right_force` | array of numbers | Yes | Right force plate (N). |
| `user_id` | string | No | User document id to link this test to a user. |
| `sample_count` | number | No | Inferred from array length if omitted. |

Example (minimal):

```json
{
  "athlete_id": "user-123",
  "test_type": "CMJ",
  "test_duration": 3.5,
  "force": [1020, 1018, ...],
  "left_force": [510, 509, ...],
  "right_force": [510, 509, ...]
}
```

**Response:** The full analysis result (same shape as the visualization payload): `time_s`, `force_N`, `phases`, `key_points`, `metrics`, `analysis`, `validity`, etc. The test is also stored in MongoDB (raw body + result).

## Getting a stored result

- **Full document:** `GET /jump-tests/{id}` — returns `id`, `user_id`, `athlete_id`, `test_type`, `result`, `created_at`. Optional query `include_raw=true` to include the original request body.
- **Viz only:** `GET /jump-tests/{id}/viz` — returns only the `result` payload (for the viewer or clients that only need the chart data).
