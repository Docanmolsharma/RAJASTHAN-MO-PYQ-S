from __future__ import annotations

import io
import zipfile

import pytest

from app.services import archive_service


def _zip_with_images() -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one.png", b"123456")
        archive.writestr("two.png", b"abcdef")
    buffer.seek(0)
    return buffer


def test_zip_rejects_aggregate_expanded_size_over_limit(monkeypatch):
    monkeypatch.setattr(archive_service, "MAX_TOTAL_EXTRACTED_BYTES", 10)
    monkeypatch.setattr(archive_service, "MAX_MEMBER_BYTES", 100)

    with pytest.raises(ValueError, match="total limit"):
        archive_service.safe_zip_images(_zip_with_images())


def test_zip_accepts_images_within_aggregate_expanded_size(monkeypatch):
    monkeypatch.setattr(archive_service, "MAX_TOTAL_EXTRACTED_BYTES", 12)
    monkeypatch.setattr(archive_service, "MAX_MEMBER_BYTES", 100)

    images, warnings = archive_service.safe_zip_images(_zip_with_images())

    assert [name for name, _ in images] == ["one.png", "two.png"]
    assert [len(data) for _, data in images] == [6, 6]
    assert warnings == []
