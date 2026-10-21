# CORTEX GT Extractor (MVP scaffold)

Apple-first web interface with a Python/FastAPI processing backend. This first milestone accepts multiple image files or ZIPs, safely unpacks supported image formats, normalizes HEIC/HEIF/JPEG/PNG images, and writes per-image OCR JSON with bounding boxes and preview images.

## Run backend
```bash
cd gt-extractor/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# OCR extra: pip install paddleocr paddlepaddle
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `frontend/index.html` using a local web server. Configure the backend address in the UI. For iPhone/iPad use, the browser must be able to reach the backend; mobile Safari itself is not expected to run large OCR batches.

## Important
- This is an initial prototype, not a validated GT1 dataset.
- PaddleOCR is optional and loaded lazily.
- Explanation exclusion and answer-highlight detection must be calibrated on actual PrepLadder review screenshots.
- Never infer selected answers or change source-designated answers using medical knowledge.
- Current batch upload is single-request; resumable/chunked uploads and persistent SQLite job state are planned next.
