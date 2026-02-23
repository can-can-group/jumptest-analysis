# Historical data

**Endpoint:** `GET /jump-tests`

Returns a **paginated list** of jump test summaries with optional filters. No authentication required.

## Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `user_id` | string | Filter by linked user id. |
| `athlete_id` | string | Filter by athlete id. |
| `test_type` | string | Filter by `CMJ`, `SJ`, or `DJ`. |
| `from_date` | ISO datetime | Tests on or after this time. |
| `to_date` | ISO datetime | Tests on or before this time. |
| `limit` | number | Page size (default 20, max 100). |
| `offset` | number | Skip (default 0). |

## Response

```json
{
  "items": [
    {
      "id": "...",
      "athlete_id": "...",
      "test_type": "CMJ",
      "created_at": "2026-02-23T12:00:00",
      "metrics": { "jump_height_impulse_m": 0.35, ... }
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

Each item includes key **metrics** from the analysis (e.g. jump height, RSI for DJ). Use the **`id`** to open the full result with `GET /jump-tests/{id}` or the viewer with `/viewer?test_id={id}`.
