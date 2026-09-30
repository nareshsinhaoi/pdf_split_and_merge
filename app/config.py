"""Application configuration (PyInstaller-aware)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _app_root() -> Path:
    """
    Return the base directory for app resources.
    - When running normally: the project root (parent of `app/`).
    - When frozen by PyInstaller: sys._MEIPASS (the temp extraction dir).
    """
    if _is_frozen():
        return Path(sys._MEIPASS)          # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _writable_root() -> Path:
    """
    Return a writable directory for uploads/outputs/.env.
    - When frozen: next to the .exe (so users can find their files).
    - When running normally: the project root.
    """
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()
WRITABLE_ROOT = _writable_root()

# Load .env from beside the exe first, then from the project root
load_dotenv(WRITABLE_ROOT / ".env")
load_dotenv(APP_ROOT / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

    MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/")
    MONGODB_DATABASE = os.environ.get("MONGODB_DATABASE", "pdf_merger")

    UPLOAD_FOLDER = str(WRITABLE_ROOT / os.environ.get("UPLOAD_FOLDER", "uploads"))
    OUTPUT_FOLDER = str(WRITABLE_ROOT / os.environ.get("OUTPUT_FOLDER", "outputs"))

    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 100 * 1024 * 1024))

    ALLOWED_EXTENSIONS = {"pdf"}
    ALLOWED_MIMETYPES = {"application/pdf", "application/x-pdf"}
    PDF_SIGNATURE = b"%PDF-"

    # Where Flask should look for templates/static when frozen
    TEMPLATE_FOLDER = str(APP_ROOT / "app" / "templates")
    STATIC_FOLDER = str(APP_ROOT / "app" / "static")