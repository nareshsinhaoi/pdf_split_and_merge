"""PDF processing utilities based on PyMuPDF (pymupdf)."""
import logging
from pathlib import Path

import pymupdf  # modern import; fitz is deprecated

from app.config import Config

logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """Raised when PDF operations fail."""


# ---------------------------------------------------------------------------
# Target canvas for merged output: A4 portrait, in PDF points
# ---------------------------------------------------------------------------
A4_WIDTH_PT = 595.276
A4_HEIGHT_PT = 841.89
TARGET_PORTRAIT = pymupdf.Rect(0, 0, A4_WIDTH_PT, A4_HEIGHT_PT)
A4_PORTRAIT  = pymupdf.Rect(0, 0, 595.276, 841.89)   # 210 × 297 mm
A4_LANDSCAPE = pymupdf.Rect(0, 0, 841.89, 595.276)   # 297 × 210 mm

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

    We use `mediabox`, NOT `rect`. `rect` returns the CropBox (intersected
    with rotation), which for magazine PDFs is often much smaller than the
    visible printed page, causing content to shrink inside the merge.
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

    We only ever call `set_cropbox`, never `set_mediabox`, because changing
    the MediaBox corrupts PDFs and causes downstream CropBox errors.
    """
    if not crop:
        return

    mb = _get_mediabox(page)
    if mb.is_empty or mb.width <= 0 or mb.height <= 0:
        return

    requested = _crop_to_rect(crop, mb)
    if requested is None:
        return

    clamped = requested & mb

    # Shrink inward by epsilon; PyMuPDF rejects a CropBox that touches
    # the MediaBox boundary on some builds due to float error.
    EPS = 0.5
    cx0 = max(mb.x0 + EPS, clamped.x0)
    cy0 = max(mb.y0 + EPS, clamped.y0)
    cx1 = min(mb.x1 - EPS, clamped.x1)
    cy1 = min(mb.y1 - EPS, clamped.y1)

    if cx1 - cx0 < 1 or cy1 - cy0 < 1:
        logger.warning(
            "Crop skipped (too small after clamp). %s requested=%s mediabox=%s",
            context, _rect_tuple(requested), _rect_tuple(mb),
        )
        return

    safe = pymupdf.Rect(cx0, cy0, cx1, cy1)

    if not (safe.x0 >= mb.x0 and safe.y0 >= mb.y0
            and safe.x1 <= mb.x1 and safe.y1 <= mb.y1):
        logger.warning(
            "Crop skipped (would not be inside MediaBox). %s "
            "safe=%s mediabox=%s",
            context, _rect_tuple(safe), _rect_tuple(mb),
        )
        return

    try:
        page.set_cropbox(safe)
    except ValueError as exc:
        logger.warning(
            "set_cropbox failed for %s: %s. requested=%s safe=%s mediabox=%s",
            context, exc, _rect_tuple(requested), _rect_tuple(safe),
            _rect_tuple(mb),
        )


# ---------------------------------------------------------------------------
# Blank / junk page detection
# ---------------------------------------------------------------------------

def is_blank_or_junk_page(doc: pymupdf.Document,
                          page_index: int,
                          dpi: int = 36,
                          ink_threshold: float = 0.008) -> bool:
    """
    Return True if the page is essentially blank or contains only a tiny
    amount of ink (a page number, a stray 'CMYK', repeating digit noise).

    `ink_threshold` is the fraction of non-white pixels below which we
    classify the page as junk. Default 0.008 = 0.8%.
    """
    try:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csGRAY)
    except Exception:
        return False

    samples = pix.samples
    total = len(samples)
    if total == 0:
        return True

    # Count pixels darker than 200 (out of 255). Anything below is "ink".
    ink = 0
    for v in samples:
        if v < 200:
            ink += 1
            # Early exit once we're clearly above threshold
            if ink > total * ink_threshold:
                return False

    return (ink / total) < ink_threshold


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
# Merge  (cover: fill the entire A4 canvas, no white margins)
# ---------------------------------------------------------------------------
def _detect_content_bbox(page: pymupdf.Page, dpi: int = 48,
                         white_cutoff: int = 240) -> pymupdf.Rect:
    """
    Render the page at low DPI, find the bbox of non-white pixels,
    convert back to PDF points. Returns the mediabox if nothing found.
    """
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    s = pix.samples
    stride = pix.stride

    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        off = y * stride
        row = s[off:off + w]
        first = -1
        last = -1
        for x in range(w):
            if row[x] < white_cutoff:
                first = x
                break
        if first == -1:
            continue
        for x in range(w - 1, -1, -1):
            if row[x] < white_cutoff:
                last = x
                break
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y
        if first < min_x:
            min_x = first
        if last > max_x:
            max_x = last

    mb = page.mediabox
    if max_x < 0 or max_y < 0:
        return _normalize_rect(mb)

    sx = mb.width / w
    sy = mb.height / h
    return _normalize_rect(pymupdf.Rect(
        mb.x0 + min_x * sx,
        mb.y0 + min_y * sy,
        mb.x0 + (max_x + 1) * sx,
        mb.y0 + (max_y + 1) * sy,
    ))

def _build_normalized_page(src: pymupdf.Document,
                           idx: int,
                           crop: dict | None,
                           user_rotation: int,
                           context: str = "") -> pymupdf.Document:
    """
    Render one source page onto a canvas that matches the *content's*
    orientation (not the page box's orientation).

    This handles the common magazine case where the physical page is A4
    portrait but the printed content inside is a landscape spread rotated
    90° to sit on the page.
    """
    src_page = src.load_page(idx)

    if crop:
        _apply_crop(src_page, crop, context=context + " [source]")

    # --- Decide orientation from the RENDERED CONTENT, not the mediabox ---
    content_box = _detect_content_bbox(src_page)
    # Fall back to mediabox if detection failed
    if content_box.is_empty or content_box.width < 10 or content_box.height < 10:
        content_box = _normalize_rect(src_page.mediabox)

    cw, ch = content_box.width, content_box.height
    is_landscape = cw > ch
    canvas = A4_LANDSCAPE if is_landscape else A4_PORTRAIT

    # Apply user rotation on top of content orientation
    total_rotation = user_rotation % 360
    if total_rotation in (90, 270):
        disp_w, disp_h = ch, cw
        # user rotated it - swap canvas accordingly
        canvas = A4_PORTRAIT if is_landscape else A4_LANDSCAPE
    else:
        disp_w, disp_h = cw, ch

    # COVER: fill the canvas, crop overflow
    scale = max(canvas.width / disp_w, canvas.height / disp_h)
    placed_w = disp_w * scale
    placed_h = disp_h * scale
    tx = (canvas.width - placed_w) / 2.0
    ty = (canvas.height - placed_h) / 2.0
    target_rect = pymupdf.Rect(tx, ty, tx + placed_w, ty + placed_h)

    # Set CropBox on the source so show_pdf_page renders only the content
    # (not the scanner's white border).
    try:
        src_page.set_cropbox(content_box)
    except Exception as exc:
        logger.warning("Could not set CropBox on %s: %s", context, exc)

    temp = pymupdf.open()
    out_page = temp.new_page(width=canvas.width, height=canvas.height)
    out_page.show_pdf_page(target_rect, src, idx, rotate=total_rotation)
    return temp


def merge_pages(page_specs: list, output_path: str) -> str:
    """
    Merge page specs into a single PDF where every page is A4 portrait
    and content fills the canvas (cover).

    If a spec has `skip_if_junk=True`, the corresponding source page is
    checked for blank/junk content and skipped if it looks empty.
    """
    if not page_specs:
        raise PDFProcessingError("No pages to merge")

    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out_doc = pymupdf.open()
    pages_written = 0
    pages_skipped = 0
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

                # Optional junk filter at merge time
                if spec.get("skip_if_junk") and is_blank_or_junk_page(src, idx):
                    logger.info(
                        "Skipping junk page %s (file=%s idx=%d)",
                        spec.get("page_id", "?"), spec["file_path"], idx,
                    )
                    pages_skipped += 1
                    continue

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

                normalized = _build_normalized_page(
                    src, idx, crop, rotation, context=ctx
                )
                try:
                    out_doc.insert_pdf(normalized)
                    pages_written += 1
                finally:
                    normalized.close()
            finally:
                src.close()

        if pages_written == 0:
            raise PDFProcessingError(
                "No valid pages to merge (all were skipped as junk)."
            )

        out_doc.save(output_path, garbage=3, deflate=True)
    finally:
        out_doc.close()

    logger.info(
        "Merged %d page(s), skipped %d junk page(s) -> %s",
        pages_written, pages_skipped, output_path,
    )
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