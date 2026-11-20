"""Pictures players upload: a group's icon (Nov 11, 2026).

An upload is never stored or served as sent. It is decoded, turned upright, cropped to a centred
square, shrunk to 256px and saved again as WebP, which leaves nothing of the original file
behind: no location or camera data, no second frame, nothing hidden after the picture. Only
PNG, JPEG and WebP are read, so an SVG (which can carry script) never gets in. The client
shrinks a picture before sending it, so the limits here are generous for an honest phone and
small enough that a hostile upload can't use much memory.
"""

from io import BytesIO

from PIL import Image, ImageOps

FORMATS = ("PNG", "JPEG", "WEBP")
UPLOAD_LIMIT = 2 * 1024 * 1024  # bytes
MAX_SIDE = 2048  # pixels, either way, in the upload
ICON_SIDE = 256
ICON_TYPE = "image/webp"
UNREADABLE = "That file isn't a picture we can read. Use a PNG, JPEG or WebP."


def square_icon(data: bytes) -> bytes:
    """An uploaded picture as a 256px square WebP, or ValueError with a reason the player can
    read."""
    if len(data) > UPLOAD_LIMIT:
        raise ValueError(f"That picture is too big. Keep it under {UPLOAD_LIMIT // (1024 * 1024)} MB.")
    try:
        with Image.open(BytesIO(data), formats=FORMATS) as picture:
            # The size comes from the file's header, before any pixels are decoded.
            if max(picture.size) > MAX_SIDE:
                raise ValueError(f"That picture is too large. Keep it within {MAX_SIDE} pixels a side.")
            picture.seek(0)  # an animation's first frame
            upright = ImageOps.exif_transpose(picture)
            clear = upright.mode in ("RGBA", "LA", "PA") or "transparency" in upright.info
            flat = upright.convert("RGBA" if clear else "RGB")
            icon = ImageOps.fit(flat, (ICON_SIDE, ICON_SIDE), Image.Resampling.LANCZOS)
            out = BytesIO()
            icon.save(out, "WEBP", quality=86, method=4)
            return out.getvalue()
    except ValueError as error:
        # Ours pass through; Pillow raises ValueError for some broken files too.
        raise error if str(error).startswith("That picture") else ValueError(UNREADABLE) from error
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError(UNREADABLE) from error
