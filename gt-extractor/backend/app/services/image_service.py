from __future__ import annotations
import hashlib, io
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

def normalize_image(data: bytes) -> tuple[Image.Image, str, bytes]:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Could not decode image; verify it is valid HEIC/HEIF/JPEG/PNG") from exc
    digest = hashlib.sha256(data).hexdigest()
    preview = io.BytesIO()
    thumb = image.copy()
    thumb.thumbnail((1800, 1800))
    thumb.save(preview, format="JPEG", quality=88, optimize=True)
    return image, digest, preview.getvalue()
