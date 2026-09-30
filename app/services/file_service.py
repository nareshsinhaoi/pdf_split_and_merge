"""File upload, validation and storage helpers."""
import os
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from app.config import Config


class FileValidationError(Exception):
    """Raised when an uploaded file fails validation."""


def allowed_extension(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in Config.ALLOWED_EXTENSIONS


def validate_pdf(file_storage) -> None:
    """
    Validate that the uploaded file is a PDF.
    Checks extension, mimetype and magic signature.
    """
    filename = file_storage.filename or ""
    if not allowed_extension(filename):
        raise FileValidationError("Only .pdf files are allowed")

    content_type = (file_storage.mimetype or "").lower()
    if content_type and content_type not in Config.ALLOWED_MIMETYPES:
        # Some browsers send application/octet-stream; we still check signature.
        if content_type != "application/octet-stream":
            raise FileValidationError(f"Invalid MIME type: {content_type}")

    # Read signature (first 5 bytes) without consuming the whole stream
    head = file_storage.stream.read(5)
    file_storage.stream.seek(0)
    if not head.startswith(Config.PDF_SIGNATURE):
        raise FileValidationError("File is not a valid PDF (bad signature)")


def generate_stored_filename(original_filename: str) -> str:
    """Create a unique, safe filename; never trust the client name."""
    safe = secure_filename(original_filename) or "document.pdf"
    stem = Path(safe).stem[:50] or "document"
    return f"{uuid.uuid4().hex}_{stem}.pdf"


def save_upload(file_storage, stored_filename: str) -> str:
    """Persist the uploaded file to the upload folder. Returns absolute path."""
    upload_dir = Path(Config.UPLOAD_FOLDER).resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Prevent path traversal: stored_filename should be a plain filename.
    safe_name = os.path.basename(stored_filename)
    target = (upload_dir / safe_name).resolve()
    if not str(target).startswith(str(upload_dir)):
        raise FileValidationError("Invalid target path")

    file_storage.save(str(target))
    return str(target)


def delete_stored_file(file_path: str) -> None:
    try:
        p = Path(file_path).resolve()
        upload_dir = Path(Config.UPLOAD_FOLDER).resolve()
        if str(p).startswith(str(upload_dir)) and p.exists():
            p.unlink()
    except OSError:
        pass


def file_size_bytes(path: str) -> int:
    return os.path.getsize(path)