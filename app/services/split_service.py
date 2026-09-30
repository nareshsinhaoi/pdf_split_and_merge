"""Page-splitting logic."""
from app.models import file as file_repo
from app.models import page as page_repo
from app.services import pdf_service


class SplitError(Exception):
    pass


def split_page(project_id: str, page_id: str, direction: str,
               ratio: float = 0.5, gutter: float = 0.0) -> dict:
    """
    Split an existing page into two, replacing the original in the UI.

    - The original page is soft-deleted (kept for undo).
    - Two new pages are inserted at the original's position with the
      computed crop rectangles.
    - Returns {"page1": <doc>, "page2": <doc>, "original": <doc>}
    """
    original = page_repo.get_page(page_id)
    if not original:
        raise SplitError("Page not found")
    if str(original["project_id"]) != str(project_id):
        raise SplitError("Page does not belong to this project")

    fdoc = file_repo.get_file(str(original["file_id"]))
    if not fdoc:
        raise SplitError("Source file not found")

    # If the page already has a crop, apply it first so we split the visible area.
    base_crop = original.get("crop")

    try:
        crops = pdf_service.compute_split_crops(
            fdoc["file_path"],
            original["original_page_number"],
            direction=direction,
            ratio=ratio,
            gutter=gutter,
        )
    except pdf_service.PDFProcessingError as exc:
        raise SplitError(str(exc)) from exc

    # Intersect with existing crop if present (split a sub-region)
    if base_crop:
        crops = [_intersect(base_crop, c) for c in crops]

    position = original["position"]

    # Make room for one extra page after the original's position
    page_repo.shift_positions_from(project_id, position + 1, delta=1)

    rotation = original.get("rotation", 0)

    page1 = page_repo.create_page(
        project_id=project_id,
        file_id=str(original["file_id"]),
        original_page_number=original["original_page_number"],
        position=position,
        rotation=rotation,
        crop=crops[0],
        parent_page_id=page_id,
    )
    page2 = page_repo.create_page(
        project_id=project_id,
        file_id=str(original["file_id"]),
        original_page_number=original["original_page_number"],
        position=position + 1,
        rotation=rotation,
        crop=crops[1],
        parent_page_id=page_id,
    )

    # Soft-delete the original so it disappears from the UI but can be undone
    page_repo.soft_delete_page(page_id)

    return {"page1": page1, "page2": page2, "original": original}


def _intersect(a: dict, b: dict) -> dict:
    """Intersection of two crop rectangles."""
    return {
        "x0": max(a["x0"], b["x0"]),
        "y0": max(a["y0"], b["y0"]),
        "x1": min(a["x1"], b["x1"]),
        "y1": min(a["y1"], b["y1"]),
    }

def undo_split(project_id: str, original_page_id: str) -> dict:
    """
    Undo a previous split:
      - Remove the two child pages (hard delete).
      - Restore the original page.
      - Re-normalize positions.
    """
    original = page_repo.get_page(original_page_id)
    if not original:
        raise SplitError("Original page not found")

    db = page_repo.get_db()
    children = list(db.pages.find({
        "parent_page_id": to_object_id(original_page_id),
    }))
    child_ids = [c["_id"] for c in children]

    if child_ids:
        db.pages.delete_many({"_id": {"$in": child_ids}})

    page_repo.restore_page(original_page_id)

    # Recompute positions for the whole project (stable order by old position)
    remaining = list(db.pages.find(
        {"project_id": to_object_id(project_id), "deleted": False}
    ).sort("position", 1))
    for i, p in enumerate(remaining):
        db.pages.update_one({"_id": p["_id"]}, {"$set": {"position": i}})

    return {"restored_page_id": original_page_id,
            "removed_children": [str(c) for c in child_ids]}