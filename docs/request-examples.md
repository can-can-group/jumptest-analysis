# Request examples: user, jump test, history, SMTP, viewer

Base URL: `http://localhost:8000` (or your API host). Replace `YOUR_ADMIN_SECRET` and tokens where needed.

---

## 1. Create an admin (once)

```bash
curl -X POST http://localhost:8000/admin/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: YOUR_ADMIN_SECRET" \
  -d '{"email":"admin@example.com","password":"your-secure-password"}'
```

**Response:** `{"email":"admin@example.com","created":true}`

---

## 2. Login and get JWT

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"your-secure-password"}'
```

**Response:** `{"access_token":"eyJ...","token_type":"bearer"}`

Save the token for the next steps:

```bash
export TOKEN="<paste access_token here>"
```

---

## 3. Create a user (admin only)

```bash
curl -X POST http://localhost:8000/users \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "email": "athlete@example.com",
    "name": "Jane",
    "last_name": "Doe",
    "phone_number": "+1 555 123 4567",
    "student_number": "S12345",
    "gender": "female"
  }'
```

**Response (example):**

```json
{
  "id": "674a1b2c3d4e5f678901234",
  "email": "athlete@example.com",
  "name": "Jane",
  "last_name": "Doe",
  "phone_number": "+1 555 123 4567",
  "student_number": "S12345",
  "gender": "female",
  "created_at": "2026-02-23T12:00:00.000Z",
  "updated_at": "2026-02-23T12:00:00.000Z"
}
```

Save the user `id` for linking jump tests and for history:

```bash
export USER_ID="<paste id from response>"
```

---

## 4. Submit a jump test and get the analysis response

**Option A – use an existing JSON file** (e.g. from `saved_raw_data/cmj-data/`) and add `user_id` with `jq`:

```bash
curl -X POST http://localhost:8000/jump-tests \
  -H "Content-Type: application/json" \
  -d "$(jq --arg uid "$USER_ID" '. + {user_id: $uid}' saved_raw_data/cmj-data/saved1.json)"
```

**Option B – minimal inline payload** (short arrays; replace `$USER_ID`):

```bash
curl -X POST http://localhost:8000/jump-tests \
  -H "Content-Type: application/json" \
  -d '{
    "athlete_id": "'"$USER_ID"'",
    "test_type": "CMJ",
    "test_duration": 3.0,
    "force": [1020,1020,1018,1010,1000,990,980,970,960,950,940,930,920,910,900,890,880,870,860,850,840,830,820,810,800,790,780,770,760,750,740,730,720,710,700,690,680,670,660,650,640,630,620,610,600,590,580,570,560,550,540,530,520,510,500,0,0,0,0,0,0,0,0,0,0,200,400,600,800,1000,1020,1020],
    "left_force": [510,510,509,505,500,495,490,485,480,475,470,465,460,455,450,445,440,435,430,425,420,415,410,405,400,395,390,385,380,375,370,365,360,355,350,345,340,335,330,325,320,315,310,305,300,295,290,285,280,275,270,265,260,255,250,0,0,0,0,0,0,0,0,0,0,100,200,300,400,510,510,510],
    "right_force": [510,510,509,505,500,495,490,485,480,475,470,465,460,455,450,445,440,435,430,425,420,415,410,405,400,395,390,385,380,375,370,365,360,355,350,345,340,335,330,325,320,315,310,305,300,295,290,285,280,275,270,265,260,255,250,0,0,0,0,0,0,0,0,0,0,100,200,300,400,510,510,510],
    "user_id": "'"$USER_ID"'"
  }'
```

**Response:** JSON with `id` (stored jump test id) plus the full analysis (`time_s`, `force_N`, `phases`, `key_points`, `metrics`, `analysis`, `validity`, etc.). Example shape:

```json
{
  "id": "674a1b2c3d4e5f678901235",
  "time_s": [...],
  "force_N": [...],
  "phases": [...],
  "key_points": [...],
  "metrics": { "jump_height_impulse_m": 0.35, ... },
  "analysis": { ... },
  "validity": { ... }
}
```

Save the jump test id for the next steps:

```bash
export TEST_ID="<paste id from response>"
```

---

## 5. Get one jump test (full document)

```bash
curl -s "http://localhost:8000/jump-tests/$TEST_ID" | jq .
```

Optional: include raw request body:

```bash
curl -s "http://localhost:8000/jump-tests/$TEST_ID?include_raw=true" | jq .
```

---

## 6. Retrieve historical data for that user

```bash
curl -s "http://localhost:8000/jump-tests?user_id=$USER_ID&limit=10" | jq .
```

**Response (example):**

```json
{
  "items": [
    {
      "id": "674a1b2c3d4e5f678901235",
      "athlete_id": "674a1b2c3d4e5f678901234",
      "test_type": "CMJ",
      "created_at": "2026-02-23T12:05:00.000Z",
      "metrics": { "jump_height_impulse_m": 0.35, ... }
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

Optional filters: `athlete_id`, `test_type`, `from_date`, `to_date`, `offset`.

---

## 7. Test the SMTP server (send result link by email)

Requires SMTP env vars set (e.g. `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `EMAIL_BASE_URL`).

**Use the linked user’s email** (from `user_id` on the jump test):

```bash
curl -X POST "http://localhost:8000/jump-tests/$TEST_ID/send-link" \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Override recipient:**

```bash
curl -X POST "http://localhost:8000/jump-tests/$TEST_ID/send-link" \
  -H "Content-Type: application/json" \
  -d '{"email":"athlete@example.com"}'
```

**Response:** `{"sent":true}` or `503` with detail if email is not configured or send fails.

---

## 8. Web viewing

**Single test (shareable link):** open in a browser:

```
http://localhost:8000/viewer?test_id=<TEST_ID>
```

Example:

```
http://localhost:8000/viewer?test_id=674a1b2c3d4e5f678901235
```

**User’s test history (my tests):** list all tests for a user with “View” links:

```
http://localhost:8000/my-tests?user_id=<USER_ID>
```

Example:

```
http://localhost:8000/my-tests?user_id=674a1b2c3d4e5f678901234
```

---

## Quick copy-paste flow (after TOKEN and USER_ID are set)

```bash
# 1) Submit jump test (using a file)
curl -s -X POST http://localhost:8000/jump-tests \
  -H "Content-Type: application/json" \
  -d "$(jq --arg uid "$USER_ID" '. + {user_id: $uid}' saved_raw_data/cmj-data/saved1.json)" | jq '.id'

# 2) Set TEST_ID from the response (or from list)
export TEST_ID="<id from above>"

# 3) Historical list for user
curl -s "http://localhost:8000/jump-tests?user_id=$USER_ID" | jq .

# 4) Send email with viewer link (if SMTP configured)
curl -s -X POST "http://localhost:8000/jump-tests/$TEST_ID/send-link" -H "Content-Type: application/json" -d '{}' | jq .

# 5) Open in browser
echo "Viewer: http://localhost:8000/viewer?test_id=$TEST_ID"
echo "My tests: http://localhost:8000/my-tests?user_id=$USER_ID"
```
