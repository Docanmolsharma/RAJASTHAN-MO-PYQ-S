FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GT_DATA_DIR=/app/data \
    GT_DB_PATH=/app/data/cortex_extractor.sqlite3

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# The OCR adapter uses PaddleOCR 2.x's .ocr(image, cls=True) API.
# PaddleOCR 3.x has a different prediction API; do not silently upgrade it.
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install "paddleocr>=2.7,<3" "paddlepaddle>=2.6,<3"

COPY app ./app
RUN mkdir -p /app/data/uploads /app/data/previews /app/data/results

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
