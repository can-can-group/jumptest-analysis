# Viewer and shareable links

## Shareable link for one test

Open in a browser:

```
https://your-api.example.com/viewer?test_id=<jump_test_id>
```

The viewer loads the analysis from the API (`/jump-tests/{id}/viz`) and shows the force curve, phases, key points, and metrics. No login required; anyone with the link can view.

## My tests page

To let a user see all their jump tests and open any one:

```
https://your-api.example.com/my-tests?user_id=<user_id>
```

The page lists tests (date, type, optional jump height) with a **View** button that goes to `/viewer?test_id=<id>`.

## Sending the link by email

**Endpoint:** `POST /jump-tests/{id}/send-link`

Sends an email containing the viewer link for that test.

- **Body (optional):** `{ "email": "override@example.com" }`. If omitted, the email is taken from the jump test’s **user_id** (user document’s email).
- **Requirements:** SMTP configured via env (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `EMAIL_BASE_URL` for the link). If not configured, the API returns `503`.
- **Response:** `200 { "sent": true }` or `503` on failure.

Example:

```bash
curl -X POST https://your-api.example.com/jump-tests/TEST_ID/send-link \
  -H "Content-Type: application/json" \
  -d '{}'
```

To override the recipient:

```bash
curl -X POST https://your-api.example.com/jump-tests/TEST_ID/send-link \
  -H "Content-Type: application/json" \
  -d '{"email": "athlete@example.com"}'
```

`EMAIL_BASE_URL` should be the public base URL of your API (e.g. `https://your-api.example.com`) so the link in the email is correct.
