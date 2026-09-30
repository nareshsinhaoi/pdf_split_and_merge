"""PDF processing utilities based on PyMuPDF (fitz)."""
import io
from pathlib import Path

import fitz  # PyMuPDF

from app.config import Config


class PDFProcessingError(Exception):
    """Raised when PDF operations fail."""


def open_pdf(path: str) -> fitz.Document:
    try:
        return fitz.open(path)
    except Exception as exc:
        raise PDFProcessingError(f"Cannot open PDF: {exc}") from exc


def get_page_count(path: str) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _apply_crop(page: fitz.Page, crop: dict | None) -> None:
    """
    Apply a crop rectangle (in PDF points) to a page.

    The rectangle is relative to the page's *unrotated* mediabox.
    Using `set_cropbox` + `set_mediabox` preserves original content,
    resolution, and vector data — no rasterization.
    """
    if not crop:
        return
    rect = fitz.Rect(crop["x0"], crop["y0"], crop["x1"], crop["y1"])
    # Clamp to the page's mediabox to be safe
    mb = page.mediabox
    rect = rect & mb
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        raise PDFProcessingError("Invalid crop rectangle")
    page.set_cropbox(rect)
    page.set_mediabox(rect)


def render_page_thumbnail(path, page_number, rotation=0, crop=None, dpi=100):
    """Render a single page (optionally cropped) to PNG bytes."""
    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFProcessingError(f"Page {page_number} out of range")
        page = doc.load_page(page_number - 1)
        _apply_crop(page, crop)
        matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        matrix = matrix.prerotate(rotation)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def render_page_image(path, page_number, rotation=0, crop=None, dpi=150):
    return render_page_thumbnail(path, page_number, rotation=rotation,
                                 crop=crop, dpi=dpi)


def get_page_size(path: str, page_number: int) -> dict:
    """Return the natural (unrotated, uncropped) mediabox size in points."""
    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFProcessingError(f"Page {page_number} out of range")
        page = doc.load_page(page_number - 1)
        r = page.mediabox
        return {"width": r.width, "height": r.height,
                "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
    finally:
        doc.close()


def merge_pages(page_specs: list, output_path: str) -> str:
    """
    Build a merged PDF from a list of page specs.

    Each spec:
      {
        "file_path": str,
        "original_page_number": int (1-based),
        "rotation": int (0/90/180/270),
        "crop": {"x0","y0","x1","y1"} | None
      }

    Preserves original page content, size, orientation and quality.
    """
    if not page_specs:
        raise PDFProcessingError("No pages to merge")

    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out_doc = fitz.open()
    try:
        for spec in page_specs:
            src = fitz.open(spec["file_path"])
            try:
                idx = spec["original_page_number"] - 1
                if idx < 0 or idx >= src.page_count:
                    raise PDFProcessingError(
                        f"Page {spec['original_page_number']} not found in "
                        f"{spec['file_path']}"
                    )
                src_page = src.load_page(idx)
                _apply_crop(src_page, spec.get("crop"))

                out_doc.insert_pdf(
                    src,
                    from_page=idx,
                    to_page=idx,
                    rotate=spec.get("rotation", 0) % 360,
                )

                # insert_pdf does NOT carry over the cropbox/mediabox we set
                # above in all PyMuPDF versions, so reapply on the last page.
                if spec.get("crop"):
                    last = out_doc.load_page(out_doc.page_count - 1)
                    _apply_crop(last, spec["crop"])
            finally:
                src.close()

        out_doc.save(output_path, garbage=3, deflate=True)
    finally:
        out_doc.close()

    return output_path


def compute_split_crops(path: str, page_number: int, direction: str,
                        ratio: float = 0.5,
                        gutter: float = 0.0) -> list[dict]:
    """
    Return two crop rectangles representing a page split.

    `direction`:
      - "vertical"   → split into LEFT and RIGHT halves (side-by-side)
      - "horizontal" → split into TOP and BOTTOM halves

    `ratio`  — where the split occurs (0.0–1.0). 0.5 = middle.
    `gutter` — optional inner margin (in points) to trim from the split edge
               on each resulting half. Useful for scanned book spreads.

    Returns: [ {"x0","y0","x1","y1"}, {...} ]  — first half, second half.
    """
    if direction not in ("vertical", "horizontal"):
        raise PDFProcessingError("direction must be 'vertical' or 'horizontal'")
    if not (0.05 <= ratio <= 0.95):
        raise PDFProcessingError("ratio must be between 0.05 and 0.95")

    size = get_page_size(path, page_number)
    x0, y0, x1, y1 = size["x0"], size["y0"], size["x1"], size["y1"]
    w = x1 - x0
    h = y1 - y0

    if direction == "vertical":
        split = x0 + w * ratio
        left  = {"x0": x0,             "y0": y0, "x1": split - gutter, "y1": y1}
        right = {"x0": split + gutter, "y0": y0, "x1": x1,            "y1": y1}
        return [left, right]
    else:  # horizontal
        split = y0 + h * ratio
        top    = {"x0": x0, "y0": y0,            "x1": x1, "y1": split - gutter}
        bottom = {"x0": x0, "y0": split + gutter, "x1": x1, "y1": y1}
        return [top, bottom]