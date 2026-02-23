"""MongoDB connection and collection access."""
from typing import Optional

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from api.config import MONGODB_DB, MONGODB_URI

_client: Optional[MongoClient] = None
_db: Optional[Database] = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGODB_URI)
    return _client


def get_db() -> Database:
    global _db
    if _db is None:
        _db = get_client()[MONGODB_DB]
    return _db


def users_collection() -> Collection:
    return get_db()["users"]


def jump_tests_collection() -> Collection:
    return get_db()["jump_tests"]


def admin_users_collection() -> Collection:
    return get_db()["admin_users"]


COLLECTION_NAMES = ("users", "jump_tests", "admin_users")


def ensure_database_and_collections() -> None:
    """Create the database and collections if they do not exist."""
    db = get_db()
    existing = db.list_collection_names()
    for name in COLLECTION_NAMES:
        if name not in existing:
            db.create_collection(name)


def ensure_indexes() -> None:
    """Create indexes for users, jump_tests, and admin_users."""
    users = users_collection()
    users.create_index("email", unique=True)

    admins = admin_users_collection()
    admins.create_index("email", unique=True)

    tests = jump_tests_collection()
    tests.create_index("user_id")
    tests.create_index("athlete_id")
    tests.create_index("test_type")
    tests.create_index("created_at")
    tests.create_index([("user_id", 1), ("created_at", -1)])
    tests.create_index([("athlete_id", 1), ("created_at", -1)])


def init_db() -> None:
    """On startup: create database and collections if needed, then ensure indexes."""
    ensure_database_and_collections()
    ensure_indexes()
