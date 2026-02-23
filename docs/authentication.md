# Authentication

## Creating an admin account

Admin accounts **cannot** be created from the admin panel. Use **curl** or **Postman** with the shared secret.

1. Set `ADMIN_SECRET` in your environment (e.g. in `.env`).
2. Call the register endpoint with the secret in the header:

```bash
curl -X POST https://your-api.example.com/admin/register \
  -H "Content-Type: application/json" \
  -H "X-Admin-Secret: YOUR_ADMIN_SECRET" \
  -d '{"email": "admin@example.com", "password": "your-secure-password"}'
```

Response: `{"email": "admin@example.com", "created": true}`. If the secret is wrong: `403 Forbidden`.

## Logging in

To get a JWT for the admin panel or for calling user endpoints:

```bash
curl -X POST https://your-api.example.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@example.com", "password": "your-secure-password"}'
```

Response: `{"access_token": "<JWT>", "token_type": "bearer"}`.

## Using the token

- **Admin panel**: Log in on the `/admin` page; the page stores the token and sends it with every request to `/users`.
- **API calls**: For any `POST/GET/PUT/DELETE /users` or `GET /users`, add the header:
  - `Authorization: Bearer <access_token>`

If the token is missing or invalid, the API returns `401 Unauthorized`.
