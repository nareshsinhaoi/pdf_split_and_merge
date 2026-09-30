"""Project model / repository."""
from datetime import datetime

from bson import ObjectId

from app.models import get_db, to_object_id


def create_project(name: str) -> dict:
    db = get_db()
    now = datetime.utcnow()
    doc = {
        "project_name": name or "Untitled Project",
        "created_at": now,
        "updated_at": now,
        "status": "active",
        "output_filename": None,
        "output_path": None,
    }
    result = db.projects.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_projects() -> list:
    db = get_db()
    return list(db.projects.find().sort("created_at", -1))


def get_project(project_id: str) -> dict | None:
    db = get_db()
    return db.projects.find_one({"_id": to_object_id(project_id)})


def update_project(project_id: str, fields: dict) -> None:
    db = get_db()
    fields["updated_at"] = datetime.utcnow()
    db.projects.update_one({"_id": to_object_id(project_id)}, {"$set": fields})


def delete_project(project_id: str) -> None:
    """Delete a project and all related files/pages records."""
    db = get_db()
    oid = to_object_id(project_id)
    db.files.delete_many({"project_id": oid})
    db.pages.delete_many({"project_id": oid})
    db.projects.delete_one({"_id": oid})