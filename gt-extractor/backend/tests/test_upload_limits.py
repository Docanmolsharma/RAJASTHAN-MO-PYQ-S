from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.main import _read_upload_bounded


class FakeUpload:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.closed = False
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self.chunks.pop(0) if self.chunks else b""

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_bounded_upload_reads_in_chunks_and_returns_aggregate_count():
    upload = FakeUpload([b"abc", b"def"])

    data, total = await _read_upload_bounded(upload, total_bytes=2, max_bytes=8)

    assert data == b"abcdef"
    assert total == 8
    assert upload.read_sizes == [1024 * 1024] * 3
    assert upload.closed


@pytest.mark.asyncio
async def test_bounded_upload_rejects_aggregate_overflow_and_closes_file():
    upload = FakeUpload([b"1234"])

    with pytest.raises(HTTPException) as error:
        await _read_upload_bounded(upload, total_bytes=3, max_bytes=6)

    assert error.value.status_code == 413
    assert upload.closed
