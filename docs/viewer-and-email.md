# Viewer and shareable links

## Shareable link for one test

Open in a browser:

```
{base}/viewer?test_id=<jump_test_id>
```

The viewer loads the analysis from the API (`/jump-tests/{id}/viz`) and shows the force curve, phases, key points, and metrics. No login required; anyone with the link can view.

## My tests page

To let a user see all their jump tests and open any one:

```
{base}/my-tests?user_id=<user_id>
```

The page lists tests (date, type, optional jump height) with a **View** button that goes to the viewer.

## Reverse proxy support (`BASE_PATH`)

When the API is served behind a reverse proxy at a sub-path (e.g. `wellbodytech.com/arge/`), set `BASE_PATH` in `.env` to match the Nginx location:

```env
BASE_PATH=/arge
```

This ensures all internal links and API calls from the viewer and my-tests pages use the correct prefix (e.g. `/arge/jump-tests/{id}/viz` instead of `/jump-tests/{id}/viz`).

For standalone deployments or local development, leave `BASE_PATH` empty (default).

## Gateway routing (production)

In production, email links route through the main website (`wellbodytech.com`) instead of pointing directly to the API. The website has gateway pages (`/viewer`, `/my-tests`) that embed the API pages in an iframe within the site layout (header, footer, CTAs).

| Email type | Link in email | Website embeds via iframe |
|-----------|--------------|--------------------------|
| Result email | `wellbodytech.com/viewer?test_id=<id>` | `wellbodytech.com/arge/viewer?test_id=<id>` |
| Welcome email | `wellbodytech.com/my-tests?user_id=<id>` | `wellbodytech.com/arge/my-tests?user_id=<id>` |

Configuration:

- `EMAIL_BASE_URL=https://wellbodytech.com` (email links go to website gateway)
- `BASE_PATH=/arge` (API served at `wellbodytech.com/arge/` via Nginx proxy)

For self-hosted deployments without a separate website, set `EMAIL_BASE_URL` to the public API URL (e.g. `https://customer.com/jump-test`). Email links go directly to the API viewer.

## Sending the link by email

**Endpoint:** `POST /jump-tests/{id}/send-link`

Sends an email containing the viewer link for that test.

- **Body (optional):** `{ "email": "override@example.com" }`. If omitted, the email is taken from the jump test's **user_id** (user document's email).
- **Requirements:** SMTP configured via env (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `EMAIL_BASE_URL`). If not configured, the API returns `503`.
- **Response:** `200 { "sent": true }` or `503` on failure.

Example:

```bash
curl -X POST https://wellbodytech.com/arge/jump-tests/TEST_ID/send-link \
  -H "Content-Type: application/json" \
  -d '{}'
```

To override the recipient:

```bash
curl -X POST https://wellbodytech.com/arge/jump-tests/TEST_ID/send-link \
  -H "Content-Type: application/json" \
  -d '{"email": "athlete@example.com"}'
```
