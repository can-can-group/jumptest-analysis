#!/usr/bin/env python3
"""
Create a user (e.g. sinasevda12389@gmail.com) and optionally send them a jump test result link.
Requires: API running, ADMIN_SECRET set, and for send-link: SMTP configured in .env.

Usage:
  export ADMIN_SECRET=your-secret
  PYTHONPATH=. python script/create_user_and_send_link.py sinasevda12389@gmail.com

  # Create user and send a specific test link:
  PYTHONPATH=. python script/create_user_and_send_link.py sinasevda12389@gmail.com --test-id 699c2ddeb788d180d44a1903

  # Or create user, submit a jump test from JSON, then send link:
  PYTHONPATH=. python script/create_user_and_send_link.py sinasevda12389@gmail.com --jump-test-json saved_raw_data/dj-data/sina_DJ_2026-02-18-1703.json
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

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_SECRET = os.environ.get("ADMIN_SECRET")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin-password")


def main():
    if len(sys.argv) < 2:
        print("Usage: python script/create_user_and_send_link.py <email> [--test-id ID] [--jump-test-json path.json]")
        sys.exit(1)
    user_email = sys.argv[1].strip().lower()
    test_id = None
    json_path = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--test-id" and i + 1 < len(sys.argv):
            test_id = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--jump-test-json" and i + 1 < len(sys.argv):
            json_path = sys.argv[i + 1]
            i += 2
        else:
            i += 1

    if not ADMIN_SECRET:
        print("Set ADMIN_SECRET in .env or export ADMIN_SECRET=...")
        sys.exit(1)

    # Login
    r = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if r.status_code != 200:
        print("Login failed:", r.json().get("detail", r.text))
        sys.exit(1)
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create user
    r = requests.post(
        f"{BASE_URL}/users",
        headers=headers,
        json={
            "email": user_email,
            "name": "Sina",
            "last_name": "Sevda",
        },
    )
    if r.status_code == 200:
        user_id = r.json()["id"]
        print("Created user:", user_email, "id:", user_id)
    elif r.status_code == 409:
        r2 = requests.get(f"{BASE_URL}/users?limit=100", headers=headers)
        if r2.status_code != 200:
            print("User may exist but could not list users")
            sys.exit(1)
        for u in r2.json():
            if (u.get("email") or "").lower() == user_email:
                user_id = u["id"]
                print("User already exists:", user_email, "id:", user_id)
                break
        else:
            print("User exists but not found in list")
            sys.exit(1)
    else:
        print("Create user failed:", r.status_code, r.text)
        sys.exit(1)

    # Optionally submit a jump test from JSON
    if json_path and Path(json_path).is_file():
        with open(json_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        payload["user_id"] = user_id
        r = requests.post(f"{BASE_URL}/jump-tests", json=payload)
        if r.status_code != 200:
            print("Submit jump test failed:", r.status_code, r.text[:300])
            sys.exit(1)
        test_id = r.json().get("id")
        print("Submitted jump test, id:", test_id)

    if not test_id:
        if not json_path:
            print("No test to send. Use --test-id ID or --jump-test-json path.json")
        sys.exit(0)

    # Send link by email
    r = requests.post(
        f"{BASE_URL}/jump-tests/{test_id}/send-link",
        json={"email": user_email},
    )
    if r.status_code == 200:
        print("Email sent to", user_email)
    else:
        print("Send link failed:", r.status_code, r.json().get("detail", r.text))
        print("Tip: Configure SMTP in .env (see .env.example for Gmail App Password).")
        sys.exit(1)


if __name__ == "__main__":
    main()
