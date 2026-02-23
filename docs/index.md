# Jump Test API

This service provides a **lightweight API** for:

- **Users** — Create and manage users (name, last name, email, phone, student number, gender). Admin only.
- **Jump tests** — Submit force-plate data (CMJ, SJ, or DJ), get analysis results, and store them in MongoDB.
- **Historical data** — List jump tests by user, athlete, test type, and date range.
- **Viewer** — Shareable links so users can view their jump test results in a browser; optional email delivery of the link.

Use the **API usage** section in the sidebar for how to authenticate, send jump test data, get user info, and link users to their jump tests.

For algorithm and metric details (detection, phases, physics), see **Algorithm and metrics**.

**OpenAPI (Swagger)** is available at `/docs` when the API is running.
