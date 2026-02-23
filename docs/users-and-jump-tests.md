# Users and their jump tests

## Linking tests to users

When you submit a jump test (`POST /jump-tests`), you can set **`user_id`** to the id of a user document. That links the test to that user for:

- **Historical listing** — `GET /jump-tests?user_id=<user_id>` returns all tests for that user.
- **Email** — `POST /jump-tests/{id}/send-link` can resolve the recipient from the test’s `user_id` (user’s email) if you don’t pass an override email.
- **My-tests page** — `/my-tests?user_id=<user_id>` shows a list of that user’s tests with “View” links.

**`athlete_id`** is a separate field (e.g. an external athlete id or the same as user id). You can set `athlete_id` to the user’s id when submitting so that filtering by `athlete_id` also works for that user.

## Summary

| Use case | How |
|----------|-----|
| Store who the test belongs to | Set `user_id` in `POST /jump-tests` to the user document id. |
| List all tests for a user | `GET /jump-tests?user_id=<user_id>`. |
| Show “my tests” page to a user | Send them `/my-tests?user_id=<user_id>`. |
| Email the result link | `POST /jump-tests/{id}/send-link` (no body to use the user’s email from `user_id`). |
