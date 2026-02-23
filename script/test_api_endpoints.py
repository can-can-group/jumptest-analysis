#!/usr/bin/env python3
"""
Test all API endpoints in sequence. Run from project root with API server running.

Usage:
  PYTHONPATH=. python script/test_api_endpoints.py [path_to_jump_test.json]
  # Or set env: BASE_URL, ADMIN_SECRET (optional if admin exists), JUMP_TEST_JSON

Example:
  PYTHONPATH=. python script/test_api_endpoints.py saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json
"""
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin-password")
USER_EMAIL = os.environ.get("TEST_USER_EMAIL", "test-athlete@example.com")


def main():
    if not BASE_URL.endswith("/"):
        base = BASE_URL
    else:
        base = BASE_URL.rstrip("/")

    # 1) Jump test JSON path
    json_path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JUMP_TEST_JSON")
    if not json_path or not Path(json_path).is_file():
        default_cmj = "saved_raw_data/cmj-data/saved3.json"
        default_dj = "saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json"
        for p in (default_cmj, default_dj):
            if Path(p).is_file():
                json_path = p
                break
        else:
            print("Usage: python script/test_api_endpoints.py <path_to_jump_test.json>")
            print("Or set JUMP_TEST_JSON. Example files: saved_raw_data/cmj-data/saved3.json or saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json")
            sys.exit(1)
    json_path = Path(json_path).resolve()
    print(f"Using jump test file: {json_path}")

    # 2) Create admin (optional)
    print("\n--- 1. Create admin (if ADMIN_SECRET set) ---")
    if ADMIN_SECRET:
        r = requests.post(
            f"{base}/admin/register",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            headers={"X-Admin-Secret": ADMIN_SECRET},
        )
        if r.status_code == 200:
            print("OK:", r.json())
        elif r.status_code == 409:
            print("Admin already exists (OK)")
        else:
            print(f"Response {r.status_code}:", r.text)
    else:
        print("ADMIN_SECRET not set, skipping. Set it to create an admin.")

    # 3) Login
    print("\n--- 2. Login ---")
    r = requests.post(
        f"{base}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if r.status_code != 200:
        print(f"Login failed {r.status_code}:", r.text)
        sys.exit(1)
    token = r.json()["access_token"]
    print("OK, got token")

    headers = {"Authorization": f"Bearer {token}"}

    # 4) Create user
    print("\n--- 3. Create user ---")
    r = requests.post(
        f"{base}/users",
        headers=headers,
        json={
            "email": USER_EMAIL,
            "name": "Test",
            "last_name": "Athlete",
            "phone_number": "+15551234567",
            "student_number": "S001",
            "gender": "other",
        },
    )
    if r.status_code == 409:
        # get existing user id from list
        r2 = requests.get(f"{base}/users?limit=1", headers=headers)
        if r2.status_code == 200 and r2.json():
            user_id = r2.json()[0]["id"]
            print("User already exists, using id:", user_id)
        else:
            print("User exists but could not get id")
            sys.exit(1)
    elif r.status_code != 200:
        print(f"Create user failed {r.status_code}:", r.text)
        sys.exit(1)
    else:
        user_id = r.json()["id"]
        print("OK, user_id:", user_id)

    # 5) Load jump test JSON and add user_id (athlete_id optional)
    with open(json_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    payload["user_id"] = user_id
    # Remove athlete_id if you want to rely only on user_id
    if "athlete_id" not in payload:
        payload["athlete_id"] = user_id

    # 6) Submit jump test
    print("\n--- 4. Submit jump test ---")
    r = requests.post(f"{base}/jump-tests", json=payload)
    if r.status_code != 200:
        print(f"Submit failed {r.status_code}:", r.text[:500])
        sys.exit(1)
    data = r.json()
    test_id = data.get("id")
    if not test_id:
        print("Response missing 'id'. Full keys:", list(data.keys())[:15])
        sys.exit(1)
    print("OK, test_id:", test_id)
    print("  (metrics sample:", list(data.get("metrics", {}).keys())[:5], ")")

    # 7) Get one jump test
    print("\n--- 5. Get one jump test ---")
    r = requests.get(f"{base}/jump-tests/{test_id}")
    if r.status_code != 200:
        print(f"Get failed {r.status_code}:", r.text[:300])
    else:
        print("OK:", r.json().get("test_type"), "created_at:", r.json().get("created_at"))

    # 8) Historical list for user
    print("\n--- 6. Historical data for user ---")
    r = requests.get(f"{base}/jump-tests", params={"user_id": user_id, "limit": 5})
    if r.status_code != 200:
        print(f"List failed {r.status_code}:", r.text[:300])
    else:
        j = r.json()
        print("OK, total:", j.get("total"), "items:", len(j.get("items", [])))

    # 9) Send email link (optional)
    print("\n--- 7. Send result link by email ---")
    r = requests.post(f"{base}/jump-tests/{test_id}/send-link", json={})
    if r.status_code == 200:
        print("OK:", r.json())
    elif r.status_code == 503:
        print("SMTP not configured (expected):", r.json().get("detail", r.text[:200]))
    else:
        print(f"Response {r.status_code}:", r.text[:300])

    # 10) Viewer URLs
    print("\n--- 8. Web viewer URLs ---")
    viewer_url = f"{base}/viewer?test_id={test_id}"
    my_tests_url = f"{base}/my-tests?user_id={user_id}"
    print("View this test (open in browser):")
    print(" ", viewer_url)
    print("User's test list (open in browser):")
    print(" ", my_tests_url)
    print("\nDone. Open the viewer URL in a browser to see the chart.")


if __name__ == "__main__":
    main()
