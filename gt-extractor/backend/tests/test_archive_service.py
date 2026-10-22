import io, zipfile
import pytest
from app.services.archive_service import safe_zip_images

def test_extracts_supported_image_and_warns_on_unsupported():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("GT1/IMG_0001.heic", b"fake-image")
        z.writestr("notes.txt", "ignore")
    stream.seek(0)
    images, warnings = safe_zip_images(stream)
    assert images == [("GT1/IMG_0001.heic", b"fake-image")]
    assert any("unsupported" in w.lower() for w in warnings)

def test_rejects_path_traversal_member():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("../outside.png", b"x")
    stream.seek(0)
    images, warnings = safe_zip_images(stream)
    assert images == []
    assert any("unsafe" in w.lower() for w in warnings)

def test_invalid_zip_fails_clearly():
    with pytest.raises(ValueError, match="valid ZIP"):
        safe_zip_images(io.BytesIO(b"not a zip"))
