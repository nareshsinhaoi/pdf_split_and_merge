"""File upload endpoints."""
import logging

from flask import Blueprint, jsonify, request

from app.models import serialize_doc
from app.models import file as file_repo
from app.models import page as page_repo
from app.models import project as project_repo
from app.services import file_service, pdf_service

logger = logging.getLogger(__name__)

upload_bp = Blueprint("upload", __name__, url_prefix="/api/projects")


@upload_bp.route("/<project_id>/upload", methods=["POST"])
def upload_files(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if "files" not in request.files:
        return jsonify({"error": "No files provided"}), 400

    uploaded = request.files.getlist("files")
    if not uploaded:
        return jsonify({"error": "No files provided"}), 400

    created_files = []
    created_pages = []
    skipped_pages = []  # list of {"file": name, "page": N}

    for fs in uploaded:
        if not fs or not fs.filename:
            continue
        try:
            file_service.validate_pdf(fs)
        except file_service.FileValidationError as exc:
            return jsonify({"error": f"{fs.filename}: {exc}"}), 400

        stored_name = file_service.generate_stored_filename(fs.filename)
        try:
            path = file_service.save_upload(fs, stored_name)
        except Exception as exc:
            logger.exception("Upload save failed")
            return jsonify({"error": f"Save failed: {exc}"}), 500

        try:
            page_count = pdf_service.get_page_count(path)
        except pdf_service.PDFProcessingError as exc:
            file_service.delete_stored_file(path)
            return jsonify({"error": f"Corrupted PDF: {exc}"}), 400

        # --- Detect junk pages once per uploaded PDF ---
        try:
            junk_pages = set(file_service.detect_junk_pages(path))
        except Exception:
            logger.exception("Junk page detection failed for %s", stored_name)
            junk_pages = set()

        if junk_pages:
            logger.info(
                "Detected %d junk page(s) in %s: %s",
                len(junk_pages), stored_name, sorted(junk_pages),
            )

        size = file_service.file_size_bytes(path)
        fdoc = file_repo.create_file(
            project_id=project_id,
            original_filename=fs.filename,
            stored_filename=stored_name,
            file_path=path,
            page_count=page_count,
            file_size=size,
        )

        start_pos = page_repo.next_position(project_id)
        added = 0
        for i in range(page_count):
            page_no = i + 1
            if page_no in junk_pages:
                skipped_pages.append({
                    "file": fs.filename,
                    "page": page_no,
                })
                continue
            pdoc = page_repo.create_page(
                project_id=project_id,
                file_id=str(fdoc["_id"]),
                original_page_number=page_no,
                position=start_pos + added,
            )
            created_pages.append(pdoc)
            added += 1

        created_files.append(fdoc)

    return jsonify({
        "files": serialize_doc(created_files),
        "pages": serialize_doc(created_pages),
        "skipped_pages": skipped_pages,
        "skipped_count": len(skipped_pages),
    }), 201


@upload_bp.route("/<project_id>/files", methods=["GET"])
def list_files(project_id):
    project = project_repo.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404
    files = file_repo.list_files(project_id)
    return jsonify(serialize_doc(files)), 200


@upload_bp.route("/<project_id>/pdf/add", methods=["POST"])
def add_pdf(project_id):
    """Add more PDFs to an existing project (same as upload)."""
    return upload_files(project_id)