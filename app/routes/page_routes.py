"""Page management endpoints."""
from io import BytesIO

from flask import Blueprint, abort, jsonify, request, send_file

from app.models import serialize_doc, to_object_id
from app.models import file as file_repo
from app.models import page as page_repo
from app.models import project as project_repo
from app.services import pdf_service
from app.services.split_service import SplitError, split_page


page_bp = Blueprint("pages", __name__, url_prefix="/api")


def _get_page_and_file(page_id):
    page = page_repo.get_page(page_id)
    if not page:
        abort(404)
    fdoc = file_repo.get_file(str(page["file_id"]))
    if not fdoc:
        abort(404)
    return page, fdoc


@page_bp.route("/projects/<project_id>/pages", methods=["GET"])
def list_pages(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    files = {str(f["_id"]): f for f in file_repo.list_files(project_id)}
    pages = page_repo.list_pages(project_id)

    result = []
    for p in pages:
        f = files.get(str(p["file_id"]))
        result.append({
            **p,
            "file_name": f["original_filename"] if f else None,
            "thumbnail_url": f"/api/pages/{p['_id']}/thumbnail",
        })

    return jsonify(serialize_doc(result)), 200


@page_bp.route("/pages/<page_id>", methods=["PUT"])
def update_page(page_id):
    """Update rotation or deleted flag."""
    data = request.get_json(silent=True) or {}
    update = {}

    if "rotation" in data:
        try:
            rot = int(data["rotation"]) % 360
        except (TypeError, ValueError):
            return jsonify({"error": "rotation must be an integer"}), 400
        if rot not in (0, 90, 180, 270):
            return jsonify({"error": "rotation must be 0, 90, 180 or 270"}), 400
        update["rotation"] = rot

    if "deleted" in data:
        update["deleted"] = bool(data["deleted"])

    if not update:
        return jsonify({"error": "No valid fields provided"}), 400

    page = page_repo.get_page(page_id)
    if not page:
        return jsonify({"error": "Page not found"}), 404

    page_repo.update_page(page_id, update)
    updated = page_repo.get_page(page_id)
    return jsonify(serialize_doc(updated)), 200


@page_bp.route("/pages/<page_id>", methods=["DELETE"])
def delete_page(page_id):
    """Soft-delete a page (can be undone via PUT with deleted=false)."""
    page = page_repo.get_page(page_id)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    page_repo.soft_delete_page(page_id)
    return jsonify({"message": "Page deleted", "page_id": page_id}), 200


@page_bp.route("/pages/<page_id>/duplicate", methods=["POST"])
def duplicate_page(page_id):
    page = page_repo.get_page(page_id)
    if not page:
        return jsonify({"error": "Page not found"}), 404

    project_id = str(page["project_id"])
    # Place duplicate right after the original
    new_pos = page["position"] + 1

    # Shift subsequent pages by 1
    from app.models import get_db
    db = get_db()
    db.pages.update_many(
        {
            "project_id": page["project_id"],
            "position": {"$gte": new_pos},
        },
        {"$inc": {"position": 1}},
    )

    new_page = page_repo.create_page(
        project_id=project_id,
        file_id=str(page["file_id"]),
        original_page_number=page["original_page_number"],
        position=new_pos,
    )
    page_repo.update_page(str(new_page["_id"]), {"rotation": page.get("rotation", 0)})
    new_page = page_repo.get_page(str(new_page["_id"]))
    return jsonify(serialize_doc(new_page)), 201


@page_bp.route("/projects/<project_id>/pages/reorder", methods=["PUT"])
def reorder(project_id):
    data = request.get_json(silent=True) or {}
    order = data.get("order")
    if not isinstance(order, list) or not order:
        return jsonify({"error": "order must be a non-empty list of page IDs"}), 400

    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    try:
        # Validate IDs
        for pid in order:
            to_object_id(pid)
        page_repo.reorder_pages(project_id, order)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    pages = page_repo.list_pages(project_id)
    return jsonify(serialize_doc(pages)), 200


@page_bp.route("/pages/<page_id>/thumbnail", methods=["GET"])
def page_thumbnail(page_id):
    page, fdoc = _get_page_and_file(page_id)
    try:
        img = pdf_service.render_page_thumbnail(
            fdoc["file_path"],
            page["original_page_number"],
            rotation=page.get("rotation", 0),
            crop=page.get("crop"),
            dpi=90,
        )
    except pdf_service.PDFProcessingError as exc:
        return jsonify({"error": str(exc)}), 500
    return send_file(BytesIO(img), mimetype="image/png")


@page_bp.route("/pages/<page_id>/preview", methods=["GET"])
def page_preview(page_id):
    page, fdoc = _get_page_and_file(page_id)
    try:
        img = pdf_service.render_page_image(
            fdoc["file_path"],
            page["original_page_number"],
            rotation=page.get("rotation", 0),
            crop=page.get("crop"),
            dpi=150,
        )
    except pdf_service.PDFProcessingError as exc:
        return jsonify({"error": str(exc)}), 500
    return send_file(BytesIO(img), mimetype="image/png")


# ---------- NEW: split a page ----------

@page_bp.route("/pages/<page_id>/split", methods=["POST"])
def split_page_route(page_id):
    """
    Split a page into two.

    Body (JSON):
      {
        "direction": "vertical" | "horizontal",   # default "vertical"
        "ratio": 0.5,                              # 0.05–0.95
        "gutter": 0.0                              # optional inner margin in pts
      }
    """
    page = page_repo.get_page(page_id)
    if not page:
        return jsonify({"error": "Page not found"}), 404

    data = request.get_json(silent=True) or {}
    direction = (data.get("direction") or "vertical").lower()
    try:
        ratio = float(data.get("ratio", 0.5))
        gutter = float(data.get("gutter", 0.0))
    except (TypeError, ValueError):
        return jsonify({"error": "ratio and gutter must be numbers"}), 400

    project_id = str(page["project_id"])

    try:
        result = split_page(project_id, page_id, direction,
                            ratio=ratio, gutter=gutter)
    except SplitError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({
        "message": "Page split successfully",
        "page1": serialize_doc(result["page1"]),
        "page2": serialize_doc(result["page2"]),
        "original": serialize_doc(result["original"]),
    }), 201

@page_bp.route("/pages/<page_id>/size", methods=["GET"])
def page_size(page_id):
    page, fdoc = _get_page_and_file(page_id)
    try:
        size = pdf_service.get_page_size(fdoc["file_path"], page["original_page_number"])
    except pdf_service.PDFProcessingError as exc:
        return jsonify({"error": str(exc)}), 500

    # If the page already has a crop, report the crop's size instead
    crop = page.get("crop")
    if crop:
        size = {
            "width": crop["x1"] - crop["x0"],
            "height": crop["y1"] - crop["y0"],
            "x0": crop["x0"], "y0": crop["y0"],
            "x1": crop["x1"], "y1": crop["y1"],
        }
    return jsonify(size), 200
