from __future__ import annotations
from typing import Any

class OCRUnavailable(RuntimeError):
    pass

class PaddleOCRService:
    """Lazy OCR wrapper preserving text, confidence, and polygon boxes."""
    def __init__(self) -> None:
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise OCRUnavailable("PaddleOCR is not installed. Install with: pip install paddleocr paddlepaddle") from exc
            self._engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        return self._engine

    def extract(self, image) -> list[dict[str, Any]]:
        result = self._get_engine().ocr(image, cls=True)
        rows: list[dict[str, Any]] = []
        for page in result or []:
            for item in page or []:
                if not item or len(item) < 2:
                    continue
                box, payload = item[0], item[1]
                rows.append({
                    "text": str(payload[0]) if payload else "",
                    "bbox": [[float(p[0]), float(p[1])] for p in box],
                    "confidence": float(payload[1]) if payload and len(payload) > 1 else None,
                })
        return rows
