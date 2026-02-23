# Users

User management is **admin-only** (valid JWT with admin role required).

## User fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Unique. Used for login/lookup. |
| `name` | string | No | First/given name. |
| `last_name` | string | No | Last name. |
| `phone_number` | string | No | Phone number. |
| `student_number` | string | No | Student ID. |
| `gender` | string | No | e.g. male, female, other. |

## Endpoints

- **Create:** `POST /users` — body: `{ "email": "...", "name": "...", "last_name": "...", "phone_number": "...", "student_number": "...", "gender": "..." }`. All except `email` optional.
- **Get one:** `GET /users/{user_id}` — returns the user document.
- **Update:** `PUT /users/{user_id}` — body: any subset of the fields (only sent fields are updated).
- **Delete:** `DELETE /users/{user_id}` — deletes the user. Jump tests that referenced this user keep their `user_id`.
- **List:** `GET /users?limit=20&offset=0` — paginated list (newest first).

All require header: `Authorization: Bearer <admin_jwt>`.
