"""PDF merge and download endpoints."""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, send_file

from app.config import Config
from app.models import serialize_doc
from app.models import file as file_repo
from app.models import page as page_repo
from app.models import project as project_repo
from app.services import pdf_service

logger = logging.getLogger(__name__)

merge_bp = Blueprint("merge", __name__, url_prefix="/api/projects")


@merge_bp.route("/<project_id>/merge", methods=["POST"])
def merge_project(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    pages = page_repo.list_pages(project_id)
    if not pages:
        return jsonify({"error": "No pages to merge"}), 400

    # Build file lookup once
    files = {str(f["_id"]): f for f in file_repo.list_files(project_id)}

    specs = []
    for p in pages:
        f = files.get(str(p["file_id"]))
        if not f:
            logger.warning("Skipping page %s: source file missing", p["_id"])
            continue
        specs.append({
            "file_path": f["file_path"],
            "original_page_number": p["original_page_number"],
            "rotation": p.get("rotation", 0),
            "crop": p.get("crop"),
        })

    if not specs:
        return jsonify({"error": "No valid pages to merge"}), 400

    output_name = f"merged_{project_id}_{uuid.uuid4().hex[:8]}.pdf"
    output_path = str(Path(Config.OUTPUT_FOLDER) / output_name)

    try:
        pdf_service.merge_pages(specs, output_path)
    except pdf_service.PDFProcessingError as exc:
        logger.exception("Merge failed")
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        logger.exception("Unexpected merge error")
        return jsonify({"error": f"Merge failed: {exc}"}), 500

    project_repo.update_project(project_id, {
        "status": "merged",
        "output_filename": output_name,
        "output_path": output_path,
        "merged_at": datetime.utcnow(),
    })

    return jsonify({
        "message": "PDF created successfully",
        "output_filename": output_name,
        "download_url": f"/api/projects/{project_id}/download",
        "page_count": len(specs),
    }), 200


@merge_bp.route("/<project_id>/download", methods=["GET"])
def download(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    output_path = project.get("output_path")
    output_name = project.get("output_filename")
    if not output_path or not Path(output_path).exists():
        return jsonify({"error": "No merged PDF available"}), 404

    # Validate the path stays inside OUTPUT_FOLDER
    resolved = Path(output_path).resolve()
    out_dir = Path(Config.OUTPUT_FOLDER).resolve()
    if not str(resolved).startswith(str(out_dir)):
        return jsonify({"error": "Invalid output path"}), 400

    return send_file(
        str(resolved),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=output_name or "merged.pdf",
    )