FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GT_DATA_DIR=/app/data \
    GT_DB_PATH=/app/data/cortex_extractor.sqlite3

# Install Tesseract in the image layer; native Render build commands cannot use apt-get.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-render.txt ./requirements-render.txt
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-render.txt

COPY app ./app
COPY capture-studio.html ./capture-studio.html
RUN mkdir -p /app/data/uploads /app/data/previews /app/data/results

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
