"""API configuration from environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root and api/ so it works regardless of where .env lives
_api_dir = Path(__file__).resolve().parent
_project_root = _api_dir.parent
load_dotenv(_project_root / ".env")
load_dotenv(_api_dir / ".env")  # api/.env overrides if present

def _str(v: str) -> str:
    return (v or "").strip()

# Accept both MONGODB_URI and MONGO_URI (common .env naming)
_raw_uri = _str(os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI") or "mongodb://localhost:27017")
MONGODB_URI = _raw_uri
MONGODB_DB = _str(os.environ.get("MONGODB_DB", "jumptest"))

if MONGODB_URI and not (MONGODB_URI.startswith("mongodb://") or MONGODB_URI.startswith("mongodb+srv://")):
    raise ValueError(
        "MONGODB_URI must start with 'mongodb://' or 'mongodb+srv://'. "
        "Check your .env (no extra 'VAR=' in the value, no leading space)."
    )

# Admin and JWT (create admins via curl/Postman with ADMIN_SECRET)
ADMIN_SECRET = _str(os.environ.get("ADMIN_SECRET"))
JWT_SECRET = _str(os.environ.get("JWT_SECRET") or "change-me-in-production")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "10080"))  # default: 7 days

# Email (SMTP) for sending jump test result links
SMTP_HOST = _str(os.environ.get("SMTP_HOST"))
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = _str(os.environ.get("SMTP_USER"))
SMTP_PASSWORD = _str(os.environ.get("SMTP_PASSWORD"))
SMTP_FROM = _str(os.environ.get("SMTP_FROM") or os.environ.get("EMAIL_FROM"))
EMAIL_BASE_URL = _str(os.environ.get("EMAIL_BASE_URL") or "")

# Public URL prefix when served behind a reverse proxy (e.g. /arge, /jump-test).
# Leave empty for standalone / development (API served at root).
_raw_base_path = _str(os.environ.get("BASE_PATH") or "")
if _raw_base_path and not _raw_base_path.startswith("/"):
    _raw_base_path = "/" + _raw_base_path
BASE_PATH = _raw_base_path.rstrip("/")
