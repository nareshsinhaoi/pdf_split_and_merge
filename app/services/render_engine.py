"""Enterprise-grade page rendering engine.

Rasterizes scanned pages to strip OCR/annotation noise and scanner borders,
detects content bounding box per page, and renders to a uniform canvas.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)


class RenderError(Exception):
    pass


# ---- Target canvases (PDF points) ----
CANVASES = {
    "a4":      (595.276, 841.89),
    "letter":  (612.0,   792.0),
    "a3":      (841.89,  1190.55),
    "fit":     None,   # use source page size
}

# ---- Quality profiles ----
QUALITY = {
    "screen":   {"dpi": 96,  "jpeg_q": 72, "grayscale": False},
    "ebook":    {"dpi": 150, "jpeg_q": 82, "grayscale": False},
    "print":    {"dpi": 220, "jpeg_q": 88, "grayscale": False},
    "archive":  {"dpi": 300, "jpeg_q": 92, "grayscale": False},
    "text":     {"dpi": 200, "jpeg_q": 85, "grayscale": True},
}


@dataclass
class PageSpec:
    """One source page + the user's intent for it."""
    file_path: str
    source_page: int            # 1-based
    rotation: int = 0           # user rotation, degrees
    crop: dict | None = None    # absolute pts {x0,y0,x1,y1}
    kind_hint: str = "auto"     # auto | digital | scanned
    page_id: str = ""
    project_id: str = ""


@dataclass
class RenderOptions:
    canvas: str = "a4"                 # a4 | letter | a3 | fit
    orientation: str = "portrait"      # portrait | landscape | auto
    fit_mode: str = "cover"            # cover | contain
    quality: str = "ebook"             # screen | ebook | print | archive | text
    trim_scanner_border: bool = True   # detect content bbox and crop
    drop_near_blank: bool = True       # skip blank / page-number-only pages
    blank_threshold: float = 0.01      # ink fraction below which page is blank


# ---------------------------------------------------------------------------
# Content detection
# ---------------------------------------------------------------------------

def detect_content_bbox(page: pymupdf.Page, dpi: int = 48,
                        white_cutoff: int = 245) -> pymupdf.Rect:
    """
    Find the bbox of actual content on the page. Renders at low DPI,
    scans for non-white rows/cols, converts back to PDF points.

    Returns the page's mediabox if nothing detected.
    """
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csGRAY)
    w, h = pix.width, pix.height
    samples = pix.samples
    stride = pix.stride

    # Vectorised-ish scan: find min/max row and col with ink
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row_off = y * stride
        row = samples[row_off:row_off + w]
        # Find first/last ink pixel in this row
        first = -1
        last = -1
        for x, v in enumerate(row):
            if v < white_cutoff:
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

    if max_x < 0 or max_y < 0:
        return _normalize_rect(page.mediabox)

    # Convert pixel coords -> PDF points
    mb = page.mediabox
    sx = mb.width / w
    sy = mb.height / h
    bbox = pymupdf.Rect(
        mb.x0 + min_x * sx,
        mb.y0 + min_y * sy,
        mb.x0 + (max_x + 1) * sx,
        mb.y0 + (max_y + 1) * sy,
    )
    return _normalize_rect(bbox)


def measure_ink_ratio(page: pymupdf.Page, dpi: int = 36,
                      cutoff: int = 200) -> float:
    """Fraction of non-white pixels on the page (0..1)."""
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csGRAY)
    s = pix.samples
    if not s:
        return 0.0
    ink = 0
    threshold = len(s) * 0.5   # early-out
    for v in s:
        if v < cutoff:
            ink += 1
            if ink > threshold:
                return 1.0
    return ink / len(s)


def is_page_digital(page: pymupdf.Page, text_chars_threshold: int = 200) -> bool:
    """
    Heuristic: a page is 'digital' if it has a lot of real selectable text
    AND few images, i.e. it wasn't scanned.
    """
    try:
        text = page.get_text("text") or ""
    except Exception:
        return False
    chars = len(text.strip())
    images = len(page.get_images(full=True))
    return chars > text_chars_threshold and images <= 1


def _normalize_rect(r: pymupdf.Rect) -> pymupdf.Rect:
    x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    return pymupdf.Rect(x0, y0, x1, y1)


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

def render_page_to_canvas(
    spec: PageSpec,
    options: RenderOptions,
    target_size: tuple[float, float],
) -> tuple[bytes, bool]:
    """
    Render one source page into a clean single-page PDF whose page is
    exactly `target_size` (w, h) in points.

    Returns (pdf_bytes, was_skipped).
    """
    src = pymupdf.open(spec.file_path)
    try:
        idx = spec.source_page - 1
        if idx < 0 or idx >= src.page_count:
            raise RenderError(
                f"Page {spec.source_page} out of range in {spec.file_path}"
            )
        page = src.load_page(idx)

        # --- 1. Blank / junk detection ---
        if options.drop_near_blank:
            ratio = measure_ink_ratio(page)
            if ratio < options.blank_threshold:
                logger.info(
                    "Skipping near-blank page %s (ink=%.4f)",
                    spec.page_id or f"{spec.file_path}#{spec.source_page}",
                    ratio,
                )
                return b"", True

        # --- 2. Determine source content box ---
        # Start from user crop if any; else mediabox.
        if spec.crop:
            content_box = pymupdf.Rect(
                spec.crop["x0"], spec.crop["y0"],
                spec.crop["x1"], spec.crop["y1"],
            )
        else:
            content_box = _normalize_rect(page.mediabox)

        # --- 3. Trim scanner border (optional) ---
        if options.trim_scanner_border and not spec.crop:
            detected = detect_content_bbox(page)
            # Only accept detected box if it's meaningfully smaller AND
            # still contains most of the original page.
            if (detected.width > 0.3 * content_box.width
                    and detected.height > 0.3 * content_box.height
                    and detected.width < 0.98 * content_box.width):
                content_box = detected

        # --- 4. Decide page kind ---
        kind = spec.kind_hint
        if kind == "auto":
            kind = "digital" if is_page_digital(page) else "scanned"

        # --- 5. Compute rotation & final displayed size ---
        rot = spec.rotation % 360
        is_landscape = content_box.width > content_box.height
        if options.orientation == "auto" and is_landscape:
            rot = (rot + 90) % 360

        if rot in (90, 270):
            disp_w = content_box.height
            disp_h = content_box.width
        else:
            disp_w = content_box.width
            disp_h = content_box.height

        # --- 6. Compute placement rect on the target canvas ---
        tw, th = target_size
        if options.fit_mode == "cover":
            scale = max(tw / disp_w, th / disp_h)
        else:
            scale = min(tw / disp_w, th / disp_h)

        placed_w = disp_w * scale
        placed_h = disp_h * scale
        tx = (tw - placed_w) / 2.0
        ty = (th - placed_h) / 2.0

        # --- 7. Build output PDF ---
        out = pymupdf.open()
        out_page = out.new_page(width=tw, height=th)

        if kind == "digital":
            # Vector path: keep text crisp, no rasterization.
            # Clone the source page's content into a temp doc so we can
            # set CropBox without touching the caller's page.
            tmp = pymupdf.open()
            tmp.insert_pdf(src, from_page=idx, to_page=idx)
            tmp_page = tmp.load_page(0)
            try:
                tmp_page.set_cropbox(content_box)
            except Exception:
                pass
            # Place it on the canvas
            out_page.show_pdf_page(
                pymupdf.Rect(tx, ty, tx + placed_w, ty + placed_h),
                tmp, 0, rotate=rot,
            )
            tmp.close()
        else:
            # Scanned path: rasterize the content bbox only, at quality DPI.
            q = QUALITY[options.quality]
            dpi = q["dpi"]
            # Apply a temporary cropbox so get_pixmap renders only content.
            tmp = pymupdf.open()
            tmp.insert_pdf(src, from_page=idx, to_page=idx)
            tmp_page = tmp.load_page(0)
            try:
                tmp_page.set_cropbox(content_box)
            except Exception:
                pass

            zoom = dpi / 72.0
            mat = pymupdf.Matrix(zoom, zoom).prerotate(rot)
            pix = tmp_page.get_pixmap(matrix=mat, alpha=False)
            tmp.close()

            if q["grayscale"] and pix.n >= 3:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)

            img_bytes = pix.tobytes("jpeg", jpg_quality=q["jpeg_q"])
            out_page.insert_image(
                pymupdf.Rect(tx, ty, tx + placed_w, ty + placed_h),
                stream=img_bytes,
                keep_proportion=True,
            )

        pdf_bytes = out.tobytes(garbage=4, deflate=True, clean=True)
        out.close()
        return pdf_bytes, False
    finally:
        src.close()


# ---------------------------------------------------------------------------
# Merge orchestrator
# ---------------------------------------------------------------------------

def merge_specs(
    specs: list[PageSpec],
    options: RenderOptions,
    output_path: str,
    progress_cb=None,
) -> dict:
    """
    Merge a list of PageSpec into a single PDF at output_path.

    Returns a stats dict:
      { "written": N, "skipped": M, "pages": K, "output": path }
    """
    if not specs:
        raise RenderError("No pages to merge")

    # Determine canvas size
    if options.canvas == "fit":
        # Use the first spec's source size
        first = pymupdf.open(specs[0].file_path)
        try:
            p0 = first.load_page(specs[0].source_page - 1)
            mb = p0.mediabox
            tw, th = mb.width, mb.height
            if options.orientation == "portrait" and tw > th:
                tw, th = th, tw
            elif options.orientation == "landscape" and th > tw:
                tw, th = th, tw
        finally:
            first.close()
    else:
        tw, th = CANVASES[options.canvas]
        if options.orientation == "landscape":
            tw, th = th, tw

    target_size = (tw, th)

    out_doc = pymupdf.open()
    written = 0
    skipped = 0
    total = len(specs)

    try:
        for i, spec in enumerate(specs):
            try:
                pdf_bytes, was_skipped = render_page_to_canvas(
                    spec, options, target_size
                )
            except RenderError:
                raise
            except Exception as exc:
                logger.exception("Render failed for spec %d: %s", i, exc)
                raise RenderError(f"Render failed on page {i + 1}: {exc}") from exc

            if was_skipped:
                skipped += 1
            else:
                tmp = pymupdf.open("pdf", pdf_bytes)
                try:
                    out_doc.insert_pdf(tmp)
                    written += 1
                finally:
                    tmp.close()

            if progress_cb:
                progress_cb(int((i + 1) / total * 100))

        if written == 0:
            raise RenderError("All pages were skipped as blank/junk")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        out_doc.save(output_path, garbage=4, deflate=True, clean=True)
    finally:
        out_doc.close()

    return {
        "written": written,
        "skipped": skipped,
        "total_input": total,
        "output": str(output_path),
        "canvas": [tw, th],
        "quality": options.quality,
    }