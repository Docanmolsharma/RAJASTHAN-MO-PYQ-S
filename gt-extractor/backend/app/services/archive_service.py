from __future__ import annotations
import io, os, zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

SUPPORTED = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
MAX_FILES = int(os.getenv("GT_MAX_FILES", "500"))
MAX_ARCHIVE_BYTES = int(os.getenv("GT_MAX_ARCHIVE_BYTES", str(2 * 1024**3)))
MAX_MEMBER_BYTES = int(os.getenv("GT_MAX_MEMBER_BYTES", str(40 * 1024**2)))
MAX_TOTAL_EXTRACTED_BYTES = int(os.getenv("GT_MAX_TOTAL_EXTRACTED_BYTES", str(256 * 1024**2)))

def safe_zip_images(stream: BinaryIO) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Read supported images from ZIP, rejecting traversal and suspicious sizes."""
    images: list[tuple[str, bytes]] = []
    warnings: list[str] = []
    total_extracted_bytes = 0
    stream.seek(0, io.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size > MAX_ARCHIVE_BYTES:
        raise ValueError(f"ZIP exceeds configured limit ({MAX_ARCHIVE_BYTES} bytes)")
    try:
        with zipfile.ZipFile(stream) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) > MAX_FILES:
                raise ValueError(f"ZIP has {len(members)} files; limit is {MAX_FILES}")
            for member in members:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    warnings.append(f"Rejected unsafe archive path: {member.filename}")
                    continue
                if path.suffix.lower() not in SUPPORTED:
                    warnings.append(f"Ignored unsupported file: {member.filename}")
                    continue
                if total_extracted_bytes + member.file_size > MAX_TOTAL_EXTRACTED_BYTES:
                    raise ValueError(f"ZIP extracted image data exceeds configured total limit ({MAX_TOTAL_EXTRACTED_BYTES} bytes)")
                if member.file_size > MAX_MEMBER_BYTES:
                    warnings.append(f"Ignored oversized image: {member.filename}")
                    continue
                if member.file_size and member.compress_size == 0:
                    warnings.append(f"Ignored suspicious archive member: {member.filename}")
                    continue
                if member.compress_size and member.file_size / member.compress_size > 250:
                    warnings.append(f"Ignored high-ratio archive member: {member.filename}")
                    continue
                with zf.open(member) as src:
                    data = src.read(MAX_MEMBER_BYTES + 1)
                if len(data) > MAX_MEMBER_BYTES:
                    warnings.append(f"Ignored oversized image: {member.filename}")
                    continue
                total_extracted_bytes += len(data)
                images.append((str(path), data))
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive") from exc
    return images, warnings
