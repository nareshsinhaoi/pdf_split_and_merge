"""Page model / repository."""
from bson import ObjectId

from app.models import get_db, to_object_id

def create_page(project_id, file_id, original_page_number, position,
                rotation=0, crop=None, parent_page_id=None):
    db = get_db()
    doc = {
        "project_id": to_object_id(project_id),
        "file_id": to_object_id(file_id),
        "original_page_number": original_page_number,
        "position": position,
        "rotation": rotation,
        "deleted": False,
        "crop": crop,                     # {"x0","y0","x1","y1"} or None
        "parent_page_id": to_object_id(parent_page_id) if parent_page_id else None,
    }
    result = db.pages.insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


def get_page(page_id: str) -> dict | None:
    db = get_db()
    return db.pages.find_one({"_id": to_object_id(page_id)})


def list_pages(project_id: str) -> list:
    """Return all non-deleted pages ordered by position."""
    db = get_db()
    return list(db.pages.find({
        "project_id": to_object_id(project_id),
        "deleted": False,
    }).sort("position", 1))


def list_all_pages(project_id: str) -> list:
    db = get_db()
    return list(db.pages.find({"project_id": to_object_id(project_id)}))


def update_page(page_id: str, fields: dict) -> None:
    db = get_db()
    db.pages.update_one({"_id": to_object_id(page_id)}, {"$set": fields})


def soft_delete_page(page_id: str) -> None:
    update_page(page_id, {"deleted": True})


def restore_page(page_id: str) -> None:
    update_page(page_id, {"deleted": False})


def next_position(project_id: str) -> int:
    """Next position value (max+1) for new pages."""
    db = get_db()
    last = db.pages.find_one(
        {"project_id": to_object_id(project_id)},
        sort=[("position", -1)],
    )
    return (last["position"] + 1) if last else 0


def reorder_pages(project_id: str, ordered_page_ids: list) -> None:
    """Set positions according to given order list of page IDs."""
    db = get_db()
    oid = to_object_id(project_id)
    for index, page_id in enumerate(ordered_page_ids):
        db.pages.update_one(
            {"_id": to_object_id(page_id), "project_id": oid},
            {"$set": {"position": index}},
        )


def delete_pages_for_file(file_id: str) -> None:
    db = get_db()
    db.pages.delete_many({"file_id": to_object_id(file_id)})

def shift_positions_from(project_id: str, from_position: int, delta: int = 1) -> None:
    """Shift all pages at or after `from_position` by `delta`."""
    db = get_db()
    db.pages.update_many(
        {
            "project_id": to_object_id(project_id),
            "position": {"$gte": from_position},
        },
        {"$inc": {"position": delta}},
    )