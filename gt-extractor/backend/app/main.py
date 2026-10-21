from __future__ import annotations
import io, json, os, uuid
from pathlib import Path
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from .services.archive_service import safe_zip_images, SUPPORTED
from .services.image_service import normalize_image
from .services.ocr_service import PaddleOCRService, OCRUnavailable
from .services.question_parser import parse_question_regions

DATA = Path(os.getenv("GT_DATA_DIR", "data")).resolve()
UPLOADS, PREVIEWS, RESULTS = DATA / "uploads", DATA / "previews", DATA / "results"
for folder in (UPLOADS, PREVIEWS, RESULTS):
    folder.mkdir(parents=True, exist_ok=True)
app = FastAPI(title="CORTEX GT Extractor", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
ocr = PaddleOCRService()
jobs: dict[str, dict[str, Any]] = {}

@app.get("/api/health")
def health():
    return {"status": "ok", "ocr": "lazy-loaded", "storage": str(DATA)}

@app.post("/api/jobs")
async def create_job(gt_id: str = Form(...), expected_questions: int = Form(200), files: list[UploadFile] = File(...)):
    if not gt_id.strip():
        raise HTTPException(400, "GT identifier is required")
    if not 1 <= expected_questions <= 1000:
        raise HTTPException(400, "expected_questions must be between 1 and 1000")
    if not files:
        raise HTTPException(400, "Select at least one image or ZIP")
    job_id = str(uuid.uuid4())
    job_dir = UPLOADS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    staged: list[tuple[str, bytes]] = []
    total_bytes = 0
    max_upload = int(os.getenv("GT_MAX_UPLOAD_BYTES", str(1024**3)))
    for upload in files:
        name = Path(upload.filename or "upload").name
        data = await upload.read()
        total_bytes += len(data)
        if total_bytes > max_upload:
            raise HTTPException(413, f"Total upload exceeds configured limit ({max_upload} bytes)")
        suffix = Path(name).suffix.lower()
        if suffix == ".zip":
            try:
                extracted, zip_warnings = safe_zip_images(io.BytesIO(data))
            except ValueError as exc:
                raise HTTPException(400, f"{name}: {exc}") from exc
            staged.extend((f"{name}/{inner}", blob) for inner, blob in extracted)
            warnings.extend(zip_warnings)
        elif suffix in SUPPORTED:
            staged.append((name, data))
        else:
            warnings.append(f"Ignored unsupported upload: {name}")
    if not staged:
        raise HTTPException(400, "No supported images found in upload")
    if len(staged) > int(os.getenv("GT_MAX_FILES", "500")):
        raise HTTPException(413, "Image count exceeds configured limit")
    seen: dict[str, dict[str, Any]] = {}
    image_results: list[dict[str, Any]] = []
    for source_name, data in staged:
        try:
            image, digest, preview_bytes = normalize_image(data)
            if digest in seen:
                seen[digest]["source_images"].append(source_name)
                continue
            original_path = job_dir / f"{digest}{Path(source_name).suffix.lower()}"
            original_path.write_bytes(data)
            preview_path = PREVIEWS / f"{job_id}_{digest}.jpg"
            preview_path.write_bytes(preview_bytes)
            try:
                rows = ocr.extract(image)
                candidate = parse_question_regions(rows)
                ocr_error = None
            except OCRUnavailable as exc:
                rows, candidate, ocr_error = [], None, str(exc)
            except Exception as exc:
                rows, candidate, ocr_error = [], None, f"OCR failed: {type(exc).__name__}: {exc}"
            record = {
                "source_images": [source_name], "sha256": digest, "original_path": str(original_path),
                "preview_url": f"/api/jobs/{job_id}/previews/{digest}", "width": image.width, "height": image.height,
                "ocr": rows, "question_candidate": candidate, "ocr_error": ocr_error
            }
            seen[digest] = record
            image_results.append(record)
        except ValueError as exc:
            warnings.append(f"{source_name}: {exc}")
    result = {
        "schema_version": "0.1", "job_id": job_id, "gt_id": gt_id, "expected_questions": expected_questions,
        "total_images_received": len(staged), "unique_images_processed": len(image_results),
        "warnings": warnings, "images": image_results
    }
    result_path = RESULTS / f"{job_id}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs[job_id] = {"job_id": job_id, "gt_id": gt_id, "status": "complete", "total": len(staged),
                    "processed": len(image_results), "warnings": len(warnings), "result_path": str(result_path)}
    return {"job": jobs[job_id], "result": result}

@app.get("/api/jobs")
def list_jobs():
    return list(jobs.values())

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    path = RESULTS / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/jobs/{job_id}/download")
def download_result(job_id: str):
    path = RESULTS / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    return FileResponse(path, media_type="application/json", filename=f"{job_id}_ocr.json")

@app.get("/api/jobs/{job_id}/previews/{digest}")
def get_preview(job_id: str, digest: str):
    path = PREVIEWS / f"{job_id}_{digest}.jpg"
    if not path.exists():
        raise HTTPException(404, "Preview not found")
    return FileResponse(path, media_type="image/jpeg")
