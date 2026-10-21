from __future__ import annotations
from typing import Any
import numpy as np

class OCRUnavailable(RuntimeError):
    pass

class TesseractOCRService:
    """Low-memory OCR adapter using the system Tesseract binary and pytesseract."""
    def __init__(self) -> None:
        self._pytesseract = None

    def _get_engine(self):
        if self._pytesseract is None:
            try:
                import pytesseract
                from shutil import which
                if not which("tesseract"):
                    raise OCRUnavailable(
                        "Tesseract binary is missing. Render build command must install tesseract-ocr."
                    )
                self._pytesseract = pytesseract
            except ImportError as exc:
                raise OCRUnavailable("pytesseract is not installed.") from exc
        return self._pytesseract

    @staticmethod
    def _option_marker(image, text: str, box) -> str | None:
        """Conservatively classify green/red pixels near an OCR A-D option label."""
        import cv2
        import re
        match = re.match(r"^\s*([A-D])(?:\s*[).:]|\s+)", text, re.I)
        if not match:
            return None
        arr = np.asarray(image.convert("RGB"))
        h, w = arr.shape[:2]
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        left = max(0, int(x0 - max(12, (y1-y0) * 1.4)))
        right = min(w, int(x0 + max(10, (y1-y0) * 0.65)))
        top = max(0, int(y0 - (y1-y0) * 0.25))
        bottom = min(h, int(y1 + (y1-y0) * 0.25))
        if right <= left or bottom <= top:
            return None
        hsv = cv2.cvtColor(arr[top:bottom, left:right], cv2.COLOR_RGB2HSV)
        red = (((hsv[:,:,0] <= 10) | (hsv[:,:,0] >= 170)) & (hsv[:,:,1] >= 75) & (hsv[:,:,2] >= 65))
        green = ((hsv[:,:,0] >= 32) & (hsv[:,:,0] <= 95) & (hsv[:,:,1] >= 55) & (hsv[:,:,2] >= 55))
        total = max(1, hsv.shape[0] * hsv.shape[1])
        rr, gr = float(red.sum()) / total, float(green.sum()) / total
        if rr >= 0.12 and rr > gr * 1.35:
            return "red"
        if gr >= 0.12 and gr > rr * 1.35:
            return "green"
        return None

    def extract(self, image) -> list[dict[str, Any]]:
        pytesseract = self._get_engine()
        # Tesseract is a separate native process and uses substantially less RAM
        # than loading a deep-learning OCR model into the 512 MB Render instance.
        rgb = np.asarray(image.convert("RGB"))
        h, w = rgb.shape[:2]
        scale = min(1.0, 1800.0 / max(h, w))
        if scale < 1.0:
            import cv2
            rgb = cv2.resize(rgb, (max(1, int(w*scale)), max(1, int(h*scale))), interpolation=cv2.INTER_AREA)
        data = pytesseract.image_to_data(
            rgb, lang="eng", config="--oem 1 --psm 6",
            output_type=pytesseract.Output.DICT
        )
        rows: list[dict[str, Any]] = []
        for i, value in enumerate(data.get("text", [])):
            text = str(value or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
                confidence = conf / 100.0 if conf >= 0 else None
            except (ValueError, TypeError, KeyError):
                confidence = None
            x, y = int(data["left"][i]), int(data["top"][i])
            bw, bh = int(data["width"][i]), int(data["height"][i])
            box = [[x, y], [x+bw, y], [x+bw, y+bh], [x, y+bh]]
            row = {"text": text, "bbox": [[float(a), float(b)] for a,b in box], "confidence": confidence, "block_num": int(data["block_num"][i]), "par_num": int(data["par_num"][i]), "line_num": int(data["line_num"][i])}
            marker = self._option_marker(image, text, [[a/scale, b/scale] for a,b in box])
            if marker:
                row["option_marker"] = marker
            rows.append(row)
        return rows
