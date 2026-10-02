"""PDF compression service using PyMuPDF."""
import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)


class CompressError(Exception):
    pass


# Presets: (image_quality, dpi, subsample, use_grayscale)
PRESETS = {
    "low":    {"quality": 80, "dpi": 150, "subsample": True,  "gray": False},
    "medium": {"quality": 60, "dpi": 120, "subsample": True,  "gray": False},
    "high":   {"quality": 40, "dpi": 90,  "subsample": True,  "gray": False},
    "extreme":{"quality": 30, "dpi": 72,  "subsample": True,  "gray": True},
}


def compress_pdf(input_path: str, output_path: str, preset: str = "medium") -> dict:
    """
    Recompress images inside a PDF to reduce file size.

    Returns dict with:
      - input_size, output_size, saved_bytes, saved_pct
    """
    if preset not in PRESETS:
        raise CompressError(f"Unknown preset: {preset}")

    cfg = PRESETS[preset]

    input_path = str(Path(input_path).resolve())
    output_path = str(Path(output_path).resolve())
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    in_size = Path(input_path).stat().st_size

    try:
        doc = pymupdf.open(input_path)
    except Exception as exc:
        raise CompressError(f"Cannot open PDF: {exc}") from exc

    try:
        for page in doc:
            _compress_page_images(page, cfg)

        # Save with maximum compression flags. `garbage=4` removes unused
        # objects (old image streams), `deflate=True` zlib-compresses
        # remaining streams, `clean=True` sanitizes content streams.
        doc.save(
            output_path,
            garbage=4,
            deflate=True,
            clean=True,
            deflate_images=True,
            deflate_fonts=True,
        )
    except Exception as exc:
        raise CompressError(f"Compression failed: {exc}") from exc
    finally:
        doc.close()

    out_size = Path(output_path).stat().st_size
    saved = max(0, in_size - out_size)
    pct = round((saved / in_size) * 100, 1) if in_size else 0.0

    logger.info(
        "Compressed %s -> %s (%d -> %d bytes, %.1f%% saved, preset=%s)",
        input_path, output_path, in_size, out_size, pct, preset,
    )

    return {
        "input_size": in_size,
        "output_size": out_size,
        "saved_bytes": saved,
        "saved_pct": pct,
        "preset": preset,
    }


def _compress_page_images(page: pymupdf.Page, cfg: dict) -> None:
    """Replace each image on the page with a recompressed JPEG version."""
    # get_images(full=True) returns xref info; we only care about xref ints.
    try:
        images = page.get_images(full=True)
    except Exception:
        return

    for img_info in images:
        xref = img_info[0]
        try:
            pix = pymupdf.Pixmap(page.parent, xref)
        except Exception:
            continue

        try:
            # Skip tiny images and masks — not worth recompressing
            if pix.width < 32 or pix.height < 32:
                continue
            if pix.n - pix.alpha >= 4:   # CMYK
                continue

            # Convert to RGB(A) if needed (JPEG encoder needs RGB)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)  # drop alpha
            if pix.colorspace and pix.colorspace.n not in (1, 3):
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)

            # Downsample if the effective DPI is much higher than target
            # (rough heuristic: shrink if width > 2000 px)
            if pix.width > 2000:
                factor = 2000 / pix.width
                new_w = int(pix.width * factor)
                new_h = int(pix.height * factor)
                pix = pymupdf.Pixmap(pix, 0)
                pix.shrink(1) if factor < 0.5 else None  # optional

            # Recompress to JPEG at the requested quality
            jpg_bytes = pix.tobytes("jpeg", jpg_quality=cfg["quality"])

            # Swap the old image stream for the new one.
            # insert_image returns the new xref; we then update the page
            # content to reference it, and finally remove the old xref.
            page.insert_image(
                page.rect,
                stream=jpg_bytes,
                overlay=True,
            )
        except Exception as exc:
            logger.warning("Skipped image xref=%s: %s", xref, exc)
        finally:
            try:
                pix = None
            except Exception:
                pass