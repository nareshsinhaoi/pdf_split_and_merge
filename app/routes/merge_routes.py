"""PDF merge and download endpoints."""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from app.config import Config
from app.models import serialize_doc
from app.models import file as file_repo
from app.models import page as page_repo
from app.models import project as project_repo
from app.services import render_engine
from app.services import compress_service

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

    files = {str(f["_id"]): f for f in file_repo.list_files(project_id)}

    # Build specs
    specs = []
    for p in pages:
        f = files.get(str(p["file_id"]))
        if not f:
            logger.warning("Skipping page %s: source file missing", p["_id"])
            continue
        specs.append(render_engine.PageSpec(
            file_path=f["file_path"],
            source_page=p["original_page_number"],
            rotation=p.get("rotation", 0),
            crop=p.get("crop"),
            kind_hint="auto",
            page_id=str(p["_id"]),
            project_id=project_id,
        ))

    if not specs:
        return jsonify({"error": "No valid pages to merge"}), 400

    # Read render options from the request body
    body = request.get_json(silent=True) or {}
    try:
        options = render_engine.RenderOptions(
            canvas=body.get("canvas", "a4"),
            orientation=body.get("orientation", "portrait"),
            fit_mode=body.get("fit_mode", "cover"),
            quality=body.get("quality", "ebook"),
            trim_scanner_border=bool(body.get("trim_scanner_border", True)),
            drop_near_blank=bool(body.get("drop_near_blank", True)),
            blank_threshold=float(body.get("blank_threshold", 0.01)),
        )
        # Validate
        if options.canvas not in render_engine.CANVASES:
            return jsonify({"error": f"Unknown canvas: {options.canvas}"}), 400
        if options.quality not in render_engine.QUALITY:
            return jsonify({"error": f"Unknown quality: {options.quality}"}), 400
        if options.fit_mode not in ("cover", "contain"):
            return jsonify({"error": "fit_mode must be cover or contain"}), 400
    except (TypeError, ValueError) as exc:
        return jsonify({"error": f"Invalid options: {exc}"}), 400

    output_name = f"merged_{project_id}_{uuid.uuid4().hex[:8]}.pdf"
    output_path = str(Path(Config.OUTPUT_FOLDER) / output_name)

    try:
        stats = render_engine.merge_specs(specs, options, output_path)
    except render_engine.RenderError as exc:
        logger.exception("Merge failed")
        return jsonify({"error": str(exc)}), 500

    project_repo.update_project(project_id, {
        "status": "merged",
        "output_filename": output_name,
        "output_path": output_path,
        "merged_at": datetime.utcnow(),
        "merge_stats": stats,
    })

    return jsonify({
        "message": "PDF created successfully",
        "output_filename": output_name,
        "download_url": f"/api/projects/{project_id}/download",
        "page_count": stats["written"],
        "skipped_count": stats["skipped"],
        "canvas": stats["canvas"],
        "quality": stats["quality"],
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


@merge_bp.route("/<project_id>/compress", methods=["POST"])
def compress_project(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    output_path = project.get("output_path")
    if not output_path or not Path(output_path).exists():
        return jsonify({"error": "Merge the project first"}), 400

    data = request.get_json(silent=True) or {}
    preset = (data.get("preset") or "medium").lower()
    if preset not in compress_service.PRESETS:
        return jsonify({
            "error": f"preset must be one of {list(compress_service.PRESETS)}"
        }), 400

    compressed_name = f"compressed_{project_id}_{preset}_{uuid.uuid4().hex[:8]}.pdf"
    compressed_path = str(Path(Config.OUTPUT_FOLDER) / compressed_name)

    try:
        stats = compress_service.compress_pdf(output_path, compressed_path, preset=preset)
    except compress_service.CompressError as exc:
        logger.exception("Compression failed")
        return jsonify({"error": str(exc)}), 500

    project_repo.update_project(project_id, {
        "compressed_filename": compressed_name,
        "compressed_path": compressed_path,
    })

    return jsonify({
        "message": "PDF compressed",
        "output_filename": compressed_name,
        "download_url": f"/api/projects/{project_id}/download-compressed",
        "input_size": stats["input_size"],
        "output_size": stats["output_size"],
        "saved_bytes": stats["saved_bytes"],
        "saved_pct": stats["saved_pct"],
        "preset": preset,
    }), 200


@merge_bp.route("/<project_id>/download-compressed", methods=["GET"])
def download_compressed(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    path = project.get("compressed_path")
    name = project.get("compressed_filename")
    if not path or not Path(path).exists():
        return jsonify({"error": "No compressed PDF available"}), 404

    resolved = Path(path).resolve()
    out_dir = Path(Config.OUTPUT_FOLDER).resolve()
    if not str(resolved).startswith(str(out_dir)):
        return jsonify({"error": "Invalid path"}), 400

    return send_file(
        str(resolved),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=name or "compressed.pdf",
    )