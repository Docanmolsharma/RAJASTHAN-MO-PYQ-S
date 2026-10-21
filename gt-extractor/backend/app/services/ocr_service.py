from __future__ import annotations
from typing import Any

import numpy as np

class OCRUnavailable(RuntimeError):
    pass

class PaddleOCRService:
    """Lazy OCR wrapper preserving text, confidence, polygon boxes and option badge colours."""
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

    @staticmethod
    def _option_marker(image, text: str, box) -> str | None:
        """Classify red/green option badge pixels near an OCR A-D label.

        Conservative HSV detection: only emits a marker when a substantial
        fraction of the small badge-area crop is clearly red or green.
        """
        import cv2
        import re
        match = re.match(r"^\\s*([A-D])(?:\\s*[).:]|\\s+)", text, re.I)
        if not match:
            return None
        arr = np.asarray(image.convert("RGB"))
        h, w = arr.shape[:2]
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        # PaddleOCR's text box often starts on the option badge itself. Include
        # a small area to the left and around the first label, excluding most text.
        left = max(0, int(x0 - max(12, (y1-y0) * 1.4)))
        right = min(w, int(x0 + max(10, (y1-y0) * 0.65)))
        top = max(0, int(y0 - (y1-y0) * 0.25))
        bottom = min(h, int(y1 + (y1-y0) * 0.25))
        if right <= left or bottom <= top:
            return None
        crop = arr[top:bottom, left:right]
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
        # Ignore low-saturation white/grey background and dark text.
        red = (((hsv[:,:,0] <= 10) | (hsv[:,:,0] >= 170)) & (hsv[:,:,1] >= 75) & (hsv[:,:,2] >= 65))
        green = ((hsv[:,:,0] >= 32) & (hsv[:,:,0] <= 95) & (hsv[:,:,1] >= 55) & (hsv[:,:,2] >= 55))
        total = max(1, crop.shape[0] * crop.shape[1])
        red_ratio, green_ratio = float(red.sum())/total, float(green.sum())/total
        if red_ratio >= 0.12 and red_ratio > green_ratio * 1.35:
            return "red"
        if green_ratio >= 0.12 and green_ratio > red_ratio * 1.35:
            return "green"
        return None

    def extract(self, image) -> list[dict[str, Any]]:
        result = self._get_engine().ocr(image, cls=True)
        rows: list[dict[str, Any]] = []
        for page in result or []:
            for item in page or []:
                if not item or len(item) < 2:
                    continue
                box, payload = item[0], item[1]
                text = str(payload[0]) if payload else ""
                row = {
                    "text": text,
                    "bbox": [[float(p[0]), float(p[1])] for p in box],
                    "confidence": float(payload[1]) if payload and len(payload) > 1 else None,
                }
                marker = self._option_marker(image, text, box)
                if marker:
                    row["option_marker"] = marker
                rows.append(row)
        return rows
