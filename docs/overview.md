# Overview

The API runs at a base URL (e.g. `https://your-api.example.com`). Main areas:

| Area | Description |
|------|-------------|
| **Admin** | Create admin accounts via `POST /admin/register` (curl/Postman with secret). Log in with `POST /auth/login` to get a JWT. The admin panel at `/admin` uses this to manage users. |
| **Users** | All user CRUD (`POST/GET/PUT/DELETE /users`, `GET /users`) require an admin JWT in the `Authorization: Bearer <token>` header. |
| **Jump tests** | `POST /jump-tests` to submit data and get analysis; no auth. `GET /jump-tests`, `GET /jump-tests/{id}`, `GET /jump-tests/{id}/viz` for listing and viewing. |
| **Viewer** | `/viewer?test_id=<id>` — open in a browser to see the chart and metrics for that test. `/my-tests?user_id=<id>` lists tests for a user with “View” links. |
| **Email** | `POST /jump-tests/{id}/send-link` sends an email with the viewer link (optional body `{ "email": "override@example.com" }`). Requires SMTP env vars. |
| **Documentation** | This site is served at `/documentation` when the API runs (build with `mkdocs build`). |
