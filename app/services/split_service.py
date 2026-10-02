"""Page-splitting logic."""
import logging

from app.models import get_db, to_object_id
from app.models import file as file_repo
from app.models import page as page_repo
from app.services import pdf_service

logger = logging.getLogger(__name__)


class SplitError(Exception):
    pass


def split_page(project_id, page_id, direction, ratio=0.5, gutter=0.0):
    original = page_repo.get_page(page_id)
    if not original:
        raise SplitError("Page not found")
    if str(original["project_id"]) != str(project_id):
        raise SplitError("Page does not belong to this project")
    if original.get("deleted"):
        raise SplitError("Cannot split a deleted page")

    fdoc = file_repo.get_file(str(original["file_id"]))
    if not fdoc:
        raise SplitError("Source file not found")

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
    except Exception as exc:
        logger.exception("compute_split_crops failed")
        raise SplitError(f"Split geometry failed: {exc}") from exc

    if base_crop:
        crops = [_intersect(base_crop, c) for c in crops]
        for i, c in enumerate(crops):
            if _is_empty(c):
                raise SplitError(
                    f"Split half #{i + 1} has no area after intersecting "
                    f"with existing crop {base_crop}"
                )

    position = original["position"]

    # Make room for one extra page after the original's position
    try:
        page_repo.shift_positions_from(project_id, position + 1, delta=1)
    except Exception as exc:
        logger.exception("shift_positions_from failed")
        raise SplitError(f"Failed to reindex pages: {exc}") from exc

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

    page_repo.soft_delete_page(page_id)

    return {"page1": page1, "page2": page2, "original": original}


def _intersect(a, b):
    return {
        "x0": max(a["x0"], b["x0"]),
        "y0": max(a["y0"], b["y0"]),
        "x1": min(a["x1"], b["x1"]),
        "y1": min(a["y1"], b["y1"]),
    }


def _is_empty(c):
    return (c["x1"] - c["x0"]) <= 0.01 or (c["y1"] - c["y0"]) <= 0.01


def undo_split(project_id, original_page_id):
    original = page_repo.get_page(original_page_id)
    if not original:
        raise SplitError("Original page not found")

    db = get_db()
    children = list(db.pages.find({
        "parent_page_id": to_object_id(original_page_id),
    }))
    child_ids = [c["_id"] for c in children]

    if child_ids:
        db.pages.delete_many({"_id": {"$in": child_ids}})

    page_repo.restore_page(original_page_id)

    remaining = list(db.pages.find(
        {"project_id": to_object_id(project_id), "deleted": False}
    ).sort("position", 1))
    for i, p in enumerate(remaining):
        db.pages.update_one({"_id": p["_id"]}, {"$set": {"position": i}})

    return {"restored_page_id": original_page_id,
            "removed_children": [str(c) for c in child_ids]}