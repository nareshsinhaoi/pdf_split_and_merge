"""Image compression endpoints."""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from app.config import Config
from app.models import get_db, serialize_doc, to_object_id
from app.services import compress_image_service

logger = logging.getLogger(__name__)

image_bp = Blueprint("image", __name__, url_prefix="/api/images")

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}


def _images_folder() -> Path:
    p = Path(Config.OUTPUT_FOLDER).parent / "images"
    p.mkdir(parents=True, exist_ok=True)
    return p


@image_bp.route("/upload", methods=["POST"])
def upload_image():
    """
    Upload an image for compression. Returns a job_id and file metadata.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    fs = request.files["file"]
    if not fs or not fs.filename:
        return jsonify({"error": "Empty file"}), 400

    ext = Path(fs.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return jsonify({"error": f"Unsupported format: {ext}"}), 400

    job_id = uuid.uuid4().hex
    stored_name = f"{job_id}{ext}"
    target = _images_folder() / stored_name

    try:
        fs.save(str(target))
    except Exception as exc:
        logger.exception("Failed to save uploaded image")
        return jsonify({"error": f"Save failed: {exc}"}), 500

    size = target.stat().st_size

    db = get_db()
    db.image_jobs.insert_one({
        "_id": job_id,
        "original_filename": fs.filename,
        "stored_filename": stored_name,
        "file_path": str(target),
        "file_size": size,
        "uploaded_at": datetime.utcnow(),
        "status": "uploaded",
        "result": None,
    })

    return jsonify({
        "job_id": job_id,
        "original_filename": fs.filename,
        "file_size": size,
        "file_size_kb": round(size / 1024, 1),
    }), 201


@image_bp.route("/<job_id>/compress", methods=["POST"])
def compress(job_id):
    """
    Compress the uploaded image using the requested mode.

    Body:
      {
        "mode": "less" | "recommended" | "extreme" | "lossless"
                | "target_size" | "quality",
        "target_kb": 500,          # when mode == target_size
        "custom_quality": 80       # when mode == quality (0..100)
      }
    """
    db = get_db()
    job = db.image_jobs.find_one({"_id": job_id})
    if not job:
        return jsonify({"error": "Job not found"}), 404

    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "recommended").lower()

    target_kb = body.get("target_kb")
    if target_kb is not None:
        try:
            target_kb = int(target_kb)
        except (TypeError, ValueError):
            return jsonify({"error": "target_kb must be an integer"}), 400

    custom_quality = body.get("custom_quality")
    if custom_quality is not None:
        try:
            custom_quality = int(custom_quality)
        except (TypeError, ValueError):
            return jsonify({"error": "custom_quality must be an integer"}), 400

    output_name = f"compressed_{job_id}.jpg"
    output_path = _images_folder() / output_name

    try:
        stats = compress_image_service.compress_image(
            input_path=job["file_path"],
            output_path=str(output_path),
            mode=mode,
            target_kb=target_kb,
            custom_quality=custom_quality,
        )
    except compress_image_service.ImageCompressError as exc:
        logger.exception("Image compression failed")
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Unexpected image compression error")
        return jsonify({"error": f"Compression failed: {exc}"}), 500

    db.image_jobs.update_one(
        {"_id": job_id},
        {"$set": {
            "status": "compressed",
            "result": {
                **stats,
                "output_filename": output_name,
                "output_path": str(output_path),
            },
            "compressed_at": datetime.utcnow(),
        }},
    )

    return jsonify({
        "job_id": job_id,
        "message": "Image compressed",
        "output_filename": output_name,
        "download_url": f"/api/images/{job_id}/download",
        "input_size": stats["input_size"],
        "output_size": stats["output_size"],
        "input_size_kb": round(stats["input_size"] / 1024, 1),
        "output_size_kb": round(stats["output_size"] / 1024, 1),
        "saved_bytes": stats["saved_bytes"],
        "saved_pct": stats["saved_pct"],
        "mode": stats["mode"],
        "original_dimensions": stats["original_dimensions"],
        "output_dimensions": stats["output_dimensions"],
    }), 200


@image_bp.route("/<job_id>/download", methods=["GET"])
def download(job_id):
    db = get_db()
    job = db.image_jobs.find_one({"_id": job_id})
    if not job or not job.get("result"):
        return jsonify({"error": "No compressed image available"}), 404

    path = Path(job["result"]["output_path"])
    if not path.exists():
        return jsonify({"error": "File missing on disk"}), 404

    download_name = f"compressed_{Path(job['original_filename']).stem}.jpg"

    return send_file(
        str(path),
        mimetype="image/jpeg",
        as_attachment=True,
        download_name=download_name,
    )


@image_bp.route("/<job_id>/preview", methods=["GET"])
def preview(job_id):
    """Inline preview of the compressed image (no Content-Disposition)."""
    db = get_db()
    job = db.image_jobs.find_one({"_id": job_id})
    if not job or not job.get("result"):
        return jsonify({"error": "No compressed image available"}), 404

    path = Path(job["result"]["output_path"])
    if not path.exists():
        return jsonify({"error": "File missing on disk"}), 404

    return send_file(str(path), mimetype="image/jpeg")