"""Web-optimize uploaded images before shipping to blob storage.

Goals:
  - Cap the largest dimension (MAX_EDGE_PX) so we never serve 8000px photos.
  - Re-encode to WebP where possible (smallest for photo + alpha), fall back
    to JPEG for opaque images, preserve PNG only when alpha is present.
  - Strip EXIF/location metadata (camera bodies leak GPS).
  - Leave SVG and GIF untouched — SVG is already text-compressible, and
    re-encoding animated GIFs would silently drop frames.
"""
from __future__ import annotations

import io
import logging
from typing import Literal

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

# Tune for "big enough to look crisp on 2x displays, small enough to serve fast".
MAX_EDGE_PX = 2200
WEBP_QUALITY = 82
JPEG_QUALITY = 82
# Refuse to decode anything with more than ~100 megapixels — that's a
# decompression-bomb warning sign and would cost ~400 MB of RAM to decode.
# Matches the ballpark of Pillow's own MAX_IMAGE_PIXELS default.
MAX_DECODE_PIXELS = 100_000_000
# Formats we refuse to re-encode (pass through as-is).
PASSTHROUGH_TYPES = {"image/svg+xml", "image/gif"}


def optimize(
    data: bytes,
    content_type: str,
) -> tuple[bytes, str]:
    """Return (optimized_bytes, new_content_type).

    If optimization can't meaningfully help (SVG, GIF, already-tiny files,
    Pillow can't decode), returns the original bytes/type unchanged.
    """
    if content_type in PASSTHROUGH_TYPES:
        return data, content_type
    # Cheap short-circuit: tiny files don't benefit from a re-encode round trip.
    if len(data) < 50 * 1024:
        return data, content_type

    try:
        img = Image.open(io.BytesIO(data))
        # Dimension check before full decode — cheap and guards against bombs.
        w, h = img.size
        if w * h > MAX_DECODE_PIXELS:
            log.warning(
                "image too large to decode safely (%dx%d = %d px); passing through",
                w, h, w * h,
            )
            return data, content_type
        img.load()
    except Exception as exc:  # noqa: BLE001
        log.warning("image decode failed (%s); passing through", exc)
        return data, content_type

    # Honor EXIF rotation, then drop all EXIF on save.
    img = ImageOps.exif_transpose(img)

    # Downscale in place if needed. Pillow's thumbnail() preserves aspect ratio
    # and mutates only when the source is larger than the target.
    img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.Resampling.LANCZOS)

    has_alpha = _has_alpha(img)
    target: Literal["webp", "jpeg", "png"]
    if has_alpha:
        # WebP handles alpha well and usually beats PNG on size.
        target = "webp"
    else:
        # JPEG for opaque photos is universally cached/supported; WebP saves
        # more bytes but JPEG is the safer default for a personal CMS. If the
        # caller explicitly uploaded WebP, keep WebP.
        target = "webp" if content_type == "image/webp" else "jpeg"

    buf = io.BytesIO()
    if target == "webp":
        # RGBA okay for WebP.
        save_img = img if has_alpha else img.convert("RGB")
        save_img.save(buf, format="WEBP", quality=WEBP_QUALITY, method=6)
        new_type = "image/webp"
    elif target == "jpeg":
        save_img = img.convert("RGB")
        save_img.save(
            buf,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )
        new_type = "image/jpeg"
    else:  # png (unused currently but left for completeness)
        img.save(buf, format="PNG", optimize=True)
        new_type = "image/png"

    optimized = buf.getvalue()
    # If we somehow made it bigger (rare: tiny PNGs re-encoded to JPEG), keep
    # the original.
    if len(optimized) >= len(data):
        log.info(
            "optimize produced larger output (%d vs %d); keeping original",
            len(optimized), len(data),
        )
        return data, content_type
    return optimized, new_type


def _has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA"):
        # Check if alpha is actually used.
        alpha = img.getchannel("A")
        return alpha.getextrema()[0] < 255
    if img.mode == "P" and "transparency" in img.info:
        return True
    return False
