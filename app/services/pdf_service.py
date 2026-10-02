"""PDF processing utilities based on PyMuPDF (pymupdf)."""
from pathlib import Path

import pymupdf  # modern import; fitz is deprecated

from app.config import Config


class PDFProcessingError(Exception):
    """Raised when PDF operations fail."""


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def open_pdf(path: str) -> pymupdf.Document:
    try:
        return pymupdf.open(path)
    except Exception as exc:
        raise PDFProcessingError(f"Cannot open PDF: {exc}") from exc


def get_page_count(path: str) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _rect_tuple(r: pymupdf.Rect) -> tuple:
    """Round a Rect to 2 decimals for readable logs."""
    return (round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))


def _normalize_rect(r: pymupdf.Rect) -> pymupdf.Rect:
    """Ensure x0 < x1 and y0 < y1."""
    x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return pymupdf.Rect(x0, y0, x1, y1)


def _get_mediabox(page: pymupdf.Page) -> pymupdf.Rect:
    """
    Return the page's MediaBox in a normalized form.

    NOTE: We use `mediabox`, NOT `rect`. `rect` returns the *CropBox*
    intersected with the rotation, which is exactly what we do NOT want
    when computing a crop to apply.
    """
    return _normalize_rect(page.mediabox)


def _crop_to_rect(crop: dict | None, mediabox: pymupdf.Rect) -> pymupdf.Rect | None:
    """
    Convert a crop dict into a Rect in absolute MediaBox coordinates.

    Supported shapes:
      {"x0","y0","x1","y1"}                  -> absolute points
      {"left","top","right","bottom"}        -> aliases for above
      {"x","y","w","h"}                      -> top-left + size
      {"l","t","r","b"} in [0,1]             -> normalized fractions
    """
    if not crop:
        return None

    keys = set(crop.keys())

    if {"l", "t", "r", "b"} <= keys and all(
        0.0 <= float(crop[k]) <= 1.0 for k in ("l", "t", "r", "b")
    ):
        x0 = mediabox.x0 + float(crop["l"]) * mediabox.width
        y0 = mediabox.y0 + float(crop["t"]) * mediabox.height
        x1 = mediabox.x0 + float(crop["r"]) * mediabox.width
        y1 = mediabox.y0 + float(crop["b"]) * mediabox.height
    elif {"x", "y", "w", "h"} <= keys:
        x0 = float(crop["x"])
        y0 = float(crop["y"])
        x1 = x0 + float(crop["w"])
        y1 = y0 + float(crop["h"])
    else:
        x0 = float(crop.get("x0", crop.get("left", mediabox.x0)))
        y0 = float(crop.get("y0", crop.get("top", mediabox.y0)))
        x1 = float(crop.get("x1", crop.get("right", mediabox.x1)))
        y1 = float(crop.get("y1", crop.get("bottom", mediabox.y1)))

    return _normalize_rect(pymupdf.Rect(x0, y0, x1, y1))


def _apply_crop(page: pymupdf.Page, crop: dict | None, context: str = "") -> None:
    """
    Apply a crop rectangle to `page`.

    IMPORTANT RULES (do not violate these):
      * We only ever call `set_cropbox`, never `set_mediabox`.
        Changing the MediaBox corrupts PDFs and causes the
        'CropBox not in MediaBox' error to appear later after insert_pdf.
      * The requested rect is clamped strictly *inside* the MediaBox with
        a small epsilon, because PyMuPDF rejects a CropBox that equals the
        MediaBox boundary on some builds and rejects any overshoot at all.
      * If the requested rect does not meaningfully intersect the MediaBox,
        we skip it silently (with a warning) rather than crashing the merge.
    """
    if not crop:
        return

    mb = _get_mediabox(page)
    if mb.is_empty or mb.width <= 0 or mb.height <= 0:
        return

    requested = _crop_to_rect(crop, mb)
    if requested is None:
        return

    # Intersect with MediaBox first, so we never pass an out-of-bounds rect
    clamped = requested & mb

    # Shrink inward by epsilon. PyMuPDF validates `CropBox in MediaBox`
    # with strict inequality on some builds (or with float error), so a
    # CropBox that touches the MediaBox border can still fail.
    EPS = 0.5
    cx0 = max(mb.x0 + EPS, clamped.x0)
    cy0 = max(mb.y0 + EPS, clamped.y0)
    cx1 = min(mb.x1 - EPS, clamped.x1)
    cy1 = min(mb.y1 - EPS, clamped.y1)

    if cx1 - cx0 < 1 or cy1 - cy0 < 1:
        import logging
        logging.getLogger(__name__).warning(
            "Crop skipped (too small after clamp). %s "
            "requested=%s mediabox=%s",
            context, _rect_tuple(requested), _rect_tuple(mb),
        )
        return

    safe = pymupdf.Rect(cx0, cy0, cx1, cy1)

    # Sanity check: safe MUST be strictly inside mb
    if not (safe.x0 >= mb.x0 and safe.y0 >= mb.y0
            and safe.x1 <= mb.x1 and safe.y1 <= mb.y1):
        import logging
        logging.getLogger(__name__).warning(
            "Crop skipped (would not be inside MediaBox). %s "
            "safe=%s mediabox=%s",
            context, _rect_tuple(safe), _rect_tuple(mb),
        )
        return

    try:
        page.set_cropbox(safe)
    except ValueError as exc:
        # Last resort: give up on this crop but don't kill the whole merge
        import logging
        logging.getLogger(__name__).warning(
            "set_cropbox failed for %s: %s. requested=%s safe=%s mediabox=%s",
            context, exc, _rect_tuple(requested), _rect_tuple(safe),
            _rect_tuple(mb),
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_page_thumbnail(path, page_number, rotation=0, crop=None, dpi=100):
    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFProcessingError(f"Page {page_number} out of range")
        page = doc.load_page(page_number - 1)
        ctx = f"[thumbnail] file={path} page={page_number}"
        _apply_crop(page, crop, context=ctx)
        matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0).prerotate(rotation)
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
        r = _get_mediabox(page)
        return {"width": r.width, "height": r.height,
                "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_pages(page_specs: list, output_path: str) -> str:
    if not page_specs:
        raise PDFProcessingError("No pages to merge")

    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out_doc = pymupdf.open()
    try:
        for i, spec in enumerate(page_specs):
            src = pymupdf.open(spec["file_path"])
            try:
                idx = spec["original_page_number"] - 1
                if idx < 0 or idx >= src.page_count:
                    raise PDFProcessingError(
                        f"Page {spec['original_page_number']} not found in "
                        f"{spec['file_path']}"
                    )

                rotation = spec.get("rotation", 0) % 360
                crop = spec.get("crop")

                ctx = (
                    f"[merge spec #{i}] file={spec['file_path']} "
                    f"page={spec['original_page_number']} "
                    f"project={spec.get('project_id', '?')} "
                    f"page_id={spec.get('page_id', '?')} "
                    f"rotation={rotation} "
                    f"crop={crop}"
                )

                # ---------------------------------------------------------
                # KEY FIX: apply crop to the SOURCE page (unrotated space)
                # BEFORE insert_pdf, so that when insert_pdf(rotate=N)
                # rotates the page, the crop rotates with it.
                #
                # We also must NOT call set_mediabox() — that breaks
                # downstream CropBox validation. Only set_cropbox().
                # ---------------------------------------------------------
                if crop:
                    src_page = src.load_page(idx)
                    _apply_crop(src_page, crop, context=ctx + " [source]")

                # Insert the (now-cropped) source page with rotation applied
                out_doc.insert_pdf(
                    src,
                    from_page=idx,
                    to_page=idx,
                    rotate=rotation,
                )
            finally:
                src.close()

        out_doc.save(output_path, garbage=3, deflate=True)
    finally:
        out_doc.close()

    return output_path


# ---------------------------------------------------------------------------
# Split helpers
# ---------------------------------------------------------------------------

def compute_split_crops(path, page_number, direction, ratio=0.5, gutter=0.0):
    if direction not in ("vertical", "horizontal"):
        raise PDFProcessingError("direction must be 'vertical' or 'horizontal'")
    if not (0.05 <= ratio <= 0.95):
        raise PDFProcessingError("ratio must be between 0.05 and 0.95")

    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFProcessingError(f"Page {page_number} out of range")

        page = doc.load_page(page_number - 1)
        mb = _get_mediabox(page)
        x0, y0, x1, y1 = mb.x0, mb.y0, mb.x1, mb.y1
        w, h = x1 - x0, y1 - y0

        if w <= 0 or h <= 0:
            raise PDFProcessingError(
                f"Invalid mediabox on page {page_number}: "
                f"({x0}, {y0}, {x1}, {y1})"
            )

        if direction == "vertical":
            split = x0 + w * ratio
            left = pymupdf.Rect(x0, y0, split - gutter, y1) & mb
            right = pymupdf.Rect(split + gutter, y0, x1, y1) & mb
            halves = [left, right]
        else:
            split = y0 + h * ratio
            top = pymupdf.Rect(x0, y0, x1, split - gutter) & mb
            bottom = pymupdf.Rect(x0, split + gutter, x1, y1) & mb
            halves = [top, bottom]

        for i, r in enumerate(halves):
            if r.is_empty or r.width <= 0.01 or r.height <= 0.01:
                raise PDFProcessingError(
                    f"Split produced empty half #{i + 1}. "
                    f"file={path} page={page_number} "
                    f"direction={direction} ratio={ratio} gutter={gutter} "
                    f"mediabox=({x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f})"
                )

        return [{"x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1}
                for r in halves]
    finally:
        doc.close()