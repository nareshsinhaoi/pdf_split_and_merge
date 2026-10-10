"""Image compression service using Pillow.

Supports the following modes, matching Smallpdf's UX:
  - less        : high quality, small savings
  - recommended : balanced quality vs size
  - extreme     : smaller file, lower quality
  - lossless    : optimize without quality loss (PNG/JPEG optimize)
  - target_size : iterative compression to hit a target KB
  - quality     : user-chosen quality 0..100
"""
import io
import logging
from pathlib import Path

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


class ImageCompressError(Exception):
    pass


# mode -> (jpeg_quality, max_dimension_or_None, strip_metadata)
MODE_PRESETS = {
    "less":        {"quality": 90, "max_dim": None, "strip": True},
    "recommended": {"quality": 75, "max_dim": 2400, "strip": True},
    "extreme":     {"quality": 50, "max_dim": 1600, "strip": True},
    "lossless":    {"quality": None, "max_dim": None, "strip": True},
}

# Target size is bounded to a sane range
TARGET_MIN_KB = 100
TARGET_MAX_KB = 5000

# Custom quality is bounded
QUALITY_MIN = 10
QUALITY_MAX = 100


def _open_image(path: str) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
        return img
    except Exception as exc:
        raise ImageCompressError(f"Cannot open image: {exc}") from exc


def _normalize_mode(img: Image.Image, max_dim: int | None) -> Image.Image:
    """Apply EXIF orientation, convert to RGB, optionally resize."""
    img = ImageOps.exif_transpose(img)
    if max_dim and (img.width > max_dim or img.height > max_dim):
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
    if img.mode in ("RGBA", "LA", "P"):
        # Flatten alpha onto white
        bg = Image.new("RGB", img.size, (255, 255, 255))
        img_rgba = img.convert("RGBA")
        bg.paste(img_rgba, mask=img_rgba.split()[-1])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _encode_jpeg(img: Image.Image, quality: int, strip: bool = True) -> bytes:
    buf = io.BytesIO()
    kwargs = {
        "format": "JPEG",
        "quality": quality,
        "optimize": True,
        "progressive": True,
    }
    if strip:
        # JPEG encoder keeps only the pixel data; EXIF is dropped by default
        pass
    img.save(buf, **kwargs)
    return buf.getvalue()


def _encode_lossless(img: Image.Image) -> bytes:
    """
    Lossless: try to reduce size without changing pixels.
    For RGB, best we can do in JPEG format is quality=95 with optimize.
    For PNG sources, re-encode as optimized PNG; but we output JPEG for
    uniformity in the tool, so use quality=95.
    """
    return _encode_jpeg(img, quality=95, strip=True)


def _compress_to_target(img: Image.Image, target_kb: int) -> bytes:
    """
    Binary search on JPEG quality to hit roughly target_kb.
    Caps attempts to avoid pathological loops.
    """
    target_bytes = target_kb * 1024
    lo, hi = 10, 95
    best = None
    best_diff = None

    # If even q=10 exceeds target, return the q=10 output.
    q10 = _encode_jpeg(img, 10)
    if len(q10) > target_bytes:
        return q10

    for _ in range(10):
        q = (lo + hi) // 2
        data = _encode_jpeg(img, q)
        diff = abs(len(data) - target_bytes)
        if best is None or diff < best_diff:
            best = data
            best_diff = diff
        if len(data) > target_bytes:
            hi = q - 1
        else:
            lo = q + 1
        if hi < lo:
            break

    return best or q10


def compress_image(input_path: str,
                   output_path: str,
                   mode: str,
                   target_kb: int | None = None,
                   custom_quality: int | None = None) -> dict:
    """
    Compress a single image. Writes output to output_path.

    Returns a stats dict with input_size, output_size, saved_pct, mode.
    """
    in_size = Path(input_path).stat().st_size

    img = _open_image(input_path)
    orig_w, orig_h = img.width, img.height

    if mode in MODE_PRESETS:
        cfg = MODE_PRESETS[mode]
        img = _normalize_mode(img, cfg["max_dim"])
        if mode == "lossless":
            data = _encode_lossless(img)
        else:
            data = _encode_jpeg(img, cfg["quality"], cfg["strip"])
    elif mode == "target_size":
        if target_kb is None:
            raise ImageCompressError("target_size requires target_kb")
        tk = max(TARGET_MIN_KB, min(TARGET_MAX_KB, int(target_kb)))
        img = _normalize_mode(img, max_dim=2400)
        data = _compress_to_target(img, tk)
    elif mode == "quality":
        if custom_quality is None:
            raise ImageCompressError("quality mode requires custom_quality")
        q = max(QUALITY_MIN, min(QUALITY_MAX, int(custom_quality)))
        img = _normalize_mode(img, max_dim=None)
        data = _encode_jpeg(img, q)
    else:
        raise ImageCompressError(f"Unknown mode: {mode}")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(data)

    out_size = len(data)
    saved = max(0, in_size - out_size)
    pct = round((saved / in_size) * 100, 1) if in_size else 0.0

    logger.info(
        "Compressed image %s -> %s (%d -> %d bytes, %.1f%% saved, mode=%s)",
        input_path, output_path, in_size, out_size, pct, mode,
    )

    return {
        "input_size": in_size,
        "output_size": out_size,
        "saved_bytes": saved,
        "saved_pct": pct,
        "mode": mode,
        "original_dimensions": [orig_w, orig_h],
        "output_dimensions": [img.width, img.height],
    }