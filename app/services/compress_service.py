"""PDF compression service using PyMuPDF.

Re-encodes embedded images in place to shrink PDFs while preserving
text, vectors and document structure. Uses `Document.update_stream()`
to replace each image XObject's stream, so the original images are
truly removed and `garbage=4` at save time can drop them from the file.
"""
import io
import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)


class CompressError(Exception):
    pass


# Presets.
#   quality  — JPEG quality for re-encoded images (1..95; >95 bloats)
#   max_dim  — longest edge in pixels; images larger are downscaled.
#              Set to 0 to disable resizing entirely.
#   gray     — convert to grayscale (big win for scanned B/W pages).
PRESETS = {
    "low":     {"quality": 80, "max_dim": 2400, "gray": False},
    "medium":  {"quality": 65, "max_dim": 1800, "gray": False},
    "high":    {"quality": 50, "max_dim": 1400, "gray": False},
    "extreme": {"quality": 35, "max_dim": 1100, "gray": True},
}

# Never re-encode images smaller than this — the win is negligible and
# quality can visibly suffer on tiny icons.
_MIN_SIDE = 32

# Only replace a stream if the new one is at least this much smaller.
# Prevents the file from growing for already-optimised JPEGs.
_MIN_SAVING_RATIO = 0.90   # new_len < old_len * 0.90

def compress_pdf(input_path: str, output_path: str, preset: str = "medium") -> dict:
    """
    Recompress embedded images inside a PDF.

    Returns a stats dict:
      {
        "input_size": int,
        "output_size": int,
        "saved_bytes": int,
        "saved_pct": float,
        "preset": str,
        "images_processed": int,
        "images_skipped": int,
      }
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

    processed = 0
    skipped = 0
    seen: set[int] = set()

    try:
        for page in doc:
            try:
                images = page.get_images(full=True)
            except Exception:
                continue
            for img_info in images:
                xref = img_info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    if _recompress_xref(doc, xref, cfg):
                        processed += 1
                    else:
                        skipped += 1
                except Exception as exc:
                    logger.warning("xref=%s could not be recompressed: %s",
                                   xref, exc)
                    skipped += 1

        # Save with all supported compression flags.
        # NOTE: do NOT pass `linear=True` — the parameter was removed
        # from PyMuPDF 1.24+ and raises code=4 if supplied.
        doc.save(
            output_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    except Exception as exc:
        raise CompressError(f"Compression failed: {exc}") from exc
    finally:
        doc.close()

    out_size = Path(output_path).stat().st_size
    saved = max(0, in_size - out_size)
    pct = round((saved / in_size) * 100, 1) if in_size else 0.0

    logger.info(
        "Compressed %s -> %s (%d -> %d bytes, %.1f%% saved, preset=%s, "
        "images: %d processed, %d skipped)",
        input_path, output_path, in_size, out_size, pct, preset,
        processed, skipped,
    )

    return {
        "input_size": in_size,
        "output_size": out_size,
        "saved_bytes": saved,
        "saved_pct": pct,
        "preset": preset,
        "images_processed": processed,
        "images_skipped": skipped,
    }
# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _recompress_xref(doc: pymupdf.Document, xref: int, cfg: dict) -> bool:
    """
    Re-encode the image at `xref` and replace its stream in place.

    Returns True if the stream was replaced, False if the image was
    skipped (too small, has an SMask, unsupported colorspace, or the
    recompressed version wasn't smaller).
    """
    # Skip images that carry a separate transparency mask — recompressing
    # the base image without its mask corrupts the alpha channel.
    if _has_smask(doc, xref):
        logger.debug("xref=%s skipped (has SMask)", xref)
        return False

    try:
        pix = pymupdf.Pixmap(doc, xref)
    except Exception:
        return False

    if pix.width < _MIN_SIDE or pix.height < _MIN_SIDE:
        return False

    # Only handle Gray and RGB sources. CMYK, Lab, Indexed and ICC-based
    # images need colorspace conversion that risks visible shifts, so
    # we leave them alone.
    n = pix.n - pix.alpha
    if n not in (1, 3):
        logger.debug("xref=%s skipped (colorspace n=%d)", xref, n)
        return False

    # Drop alpha (JPEG can't carry it, and SMask-carrying images were
    # already excluded above).
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)

    # Optional grayscale conversion.
    if cfg["gray"] and pix.colorspace.n != 1:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)

    # Downscale if the longest side exceeds the target.
    max_dim = cfg["max_dim"]
    if max_dim and max(pix.width, pix.height) > max_dim:
        # PyMuPDF only offers integer halving via shrink(); loop until
        # we're within 2× of the target, then accept the nearest step.
        while max(pix.width, pix.height) > max_dim * 2:
            pix.shrink(1)

    # Re-encode as JPEG.
    jpg_bytes = pix.tobytes("jpeg", jpg_quality=cfg["quality"])

    # Compare against the raw stored stream so we only replace when
    # there's a real win.
    try:
        old_stream = doc.xref_stream_raw(xref)
    except Exception:
        old_stream = None
    old_len = len(old_stream) if old_stream else 0
    new_len = len(jpg_bytes)

    if old_len and new_len >= old_len * _MIN_SAVING_RATIO:
        logger.debug("xref=%s skipped (no win: %d -> %d)", xref, old_len, new_len)
        return False

    # Replace the stream and normalise its dictionary so PDF readers
    # decode it as an 8-bit JPEG in the correct colorspace.
    doc.update_stream(xref, jpg_bytes, compress=False)

    # Clear keys that no longer apply and set the JPEG ones.
    for key in ("Decode", "DecodeParms", "SMask", "Mask", "ColorTransform"):
        try:
            doc.xref_set_key(xref, key, "null")
        except Exception:
            pass

    try:
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
        doc.xref_set_key(xref, "BitsPerComponent", "8")
        doc.xref_set_key(
            xref, "ColorSpace",
            "/DeviceGray" if pix.colorspace.n == 1 else "/DeviceRGB",
        )
        # Make sure the object declares itself as an image XObject.
        doc.xref_set_key(xref, "Subtype", "/Image")
        doc.xref_set_key(xref, "Type", "/XObject")
        doc.xref_set_key(
            xref, "Width", str(pix.width)
        )
        doc.xref_set_key(
            xref, "Height", str(pix.height)
        )
    except Exception as exc:
        logger.warning("Could not fully rewrite xref=%s dict: %s", xref, exc)

    return True


def _has_smask(doc: pymupdf.Document, xref: int) -> bool:
    """Return True if the image at `xref` declares an /SMask."""
    try:
        smask = doc.xref_get_key(xref, "SMask")
    except Exception:
        return False
    if not smask:
        return False
    value = smask[1] if isinstance(smask, tuple) else smask
    return value not in (None, "", "null")


# def compress_pdf(input_path: str, output_path: str, preset: str = "medium") -> dict:
#     """
#     Recompress images inside a PDF to reduce file size.

#     Returns dict with:
#       - input_size, output_size, saved_bytes, saved_pct
#     """
#     if preset not in PRESETS:
#         raise CompressError(f"Unknown preset: {preset}")

#     cfg = PRESETS[preset]

#     input_path = str(Path(input_path).resolve())
#     output_path = str(Path(output_path).resolve())
#     Path(output_path).parent.mkdir(parents=True, exist_ok=True)

#     in_size = Path(input_path).stat().st_size

#     try:
#         doc = pymupdf.open(input_path)
#     except Exception as exc:
#         raise CompressError(f"Cannot open PDF: {exc}") from exc

#     try:
#         for page in doc:
#             _compress_page_images(page, cfg)

#         # Save with maximum compression flags. `garbage=4` removes unused
#         # objects (old image streams), `deflate=True` zlib-compresses
#         # remaining streams, `clean=True` sanitizes content streams.
#         doc.save(
#             output_path,
#             garbage=4,
#             deflate=True,
#             clean=True,
#             deflate_images=True,
#             deflate_fonts=True,
#         )
#     except Exception as exc:
#         raise CompressError(f"Compression failed: {exc}") from exc
#     finally:
#         doc.close()

#     out_size = Path(output_path).stat().st_size
#     saved = max(0, in_size - out_size)
#     pct = round((saved / in_size) * 100, 1) if in_size else 0.0

#     logger.info(
#         "Compressed %s -> %s (%d -> %d bytes, %.1f%% saved, preset=%s)",
#         input_path, output_path, in_size, out_size, pct, preset,
#     )

#     return {
#         "input_size": in_size,
#         "output_size": out_size,
#         "saved_bytes": saved,
#         "saved_pct": pct,
#         "preset": preset,
#     }


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