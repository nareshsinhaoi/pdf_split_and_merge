"""File (uploaded PDF) model / repository."""
from datetime import datetime

from app.models import get_db, to_object_id


def create_file(project_id: str, original_filename: str, stored_filename: str,
                file_path: str, page_count: int, file_size: int) -> dict:
    db = get_db()
    doc = {
        "project_id": to_object_id(project_id),
        "original_filename": original_filename,
        "stored_filename": stored_filename,
        "file_path": file_path,
        "page_count": page_count,
        "file_size": file_size,
        "uploaded_at": datetime.utcnow(),
    }
    result = db.files.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def list_files(project_id: str) -> list:
    db = get_db()
    return list(db.files.find({"project_id": to_object_id(project_id)}))


def get_file(file_id: str) -> dict | None:
    db = get_db()
    return db.files.find_one({"_id": to_object_id(file_id)})


def delete_file(file_id: str) -> None:
    db = get_db()
    db.files.delete_one({"_id": to_object_id(file_id)})