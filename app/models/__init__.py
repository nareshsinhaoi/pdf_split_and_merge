"""Database access layer."""
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

from app.config import Config

_client = None
_db = None


def get_db():
    """Get MongoDB database instance (singleton)."""
    global _client, _db
    if _db is None:
        try:
            _client = MongoClient(Config.MONGODB_URI, serverSelectionTimeoutMS=5000)
            _client.admin.command("ping")
            _db = _client[Config.MONGODB_DATABASE]
            _ensure_indexes(_db)
        except ConnectionFailure as exc:
            raise RuntimeError(f"Cannot connect to MongoDB: {exc}") from exc
    return _db


def _ensure_indexes(db):
    """Create indexes for frequently queried fields."""
    db.projects.create_index("created_at")
    db.files.create_index("project_id")
    db.pages.create_index([("project_id", 1), ("position", 1)])
    db.pages.create_index("file_id")


def to_object_id(value):
    """Convert a string to ObjectId, raising ValueError if invalid."""
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise ValueError(f"Invalid ObjectId: {value}")
    return ObjectId(value)


def serialize_doc(doc):
    """Recursively convert ObjectIds and datetimes to JSON-safe types."""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(d) for d in doc]
    if isinstance(doc, dict):
        return {k: serialize_doc(v) for k, v in doc.items()}
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc