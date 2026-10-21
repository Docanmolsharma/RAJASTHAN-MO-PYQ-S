from __future__ import annotations
import io, json, os, uuid
from pathlib import Path
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import httpx
from .services.archive_service import safe_zip_images, SUPPORTED
from .services.image_service import normalize_image
from .services.ocr_service import PaddleOCRService, OCRUnavailable
from .services.question_parser import parse_question_regions
from .services.data_store import init_db, save_capture, list_questions, list_attempts, update_question, update_attempt, user_owns_job, list_jobs_for_user, save_job_result, get_job_result

DATA = Path(os.getenv("GT_DATA_DIR", "data")).resolve()
UPLOADS, PREVIEWS, RESULTS = DATA / "uploads", DATA / "previews", DATA / "results"
for folder in (UPLOADS, PREVIEWS, RESULTS):
    folder.mkdir(parents=True, exist_ok=True)
init_db()
app = FastAPI(title="CORTEX GT Extractor", version="0.2.0")
# Production deployments should set GT_ALLOWED_ORIGINS to a comma-separated allowlist.
# Do not use wildcard origins for a service that accepts authenticated uploads.
_allowed_origins = [origin.strip().rstrip("/") for origin in os.getenv("GT_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
ocr = PaddleOCRService()
jobs: dict[str, dict[str, Any]] = {}
SOURCE_APPS = {"PrepLadder","Marrow","Cerebellum","Book","Other"}

async def require_cortex_session(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Validate the signed-in CORTEX user token with Supabase Auth; never trust a client-supplied user id."""
    base = os.getenv("SUPABASE_URL", "").rstrip("/")
    public_key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")
    if not base or not public_key:
        raise HTTPException(503, "Backend auth is not configured: set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "A signed-in CORTEX session is required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(base + "/auth/v1/user", headers={"apikey": public_key, "Authorization": "Bearer " + token})
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Could not validate CORTEX session with Supabase Auth") from exc
    if response.status_code != 200:
        raise HTTPException(401, "CORTEX session is invalid or expired")
    user = response.json()
    if not user.get("id"):
        raise HTTPException(401, "Supabase Auth returned no user")
    return {"user_id": user["id"], "email": user.get("email")}


async def _read_upload_bounded(upload: UploadFile, total_bytes: int, max_bytes: int) -> tuple[bytes, int]:
    """Read an upload in bounded chunks and enforce the aggregate request budget."""
    chunks: list[bytes] = []
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise HTTPException(413, f"Total upload exceeds configured limit ({max_bytes} bytes)")
            chunks.append(chunk)
        return b"".join(chunks), total_bytes
    finally:
        await upload.close()

@app.get("/api/health")
def health():
    """Deployment probe: report configuration honestly without loading the OCR model."""
    import importlib.util

    auth_configured = bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip())
    ocr_installed = importlib.util.find_spec("paddleocr") is not None
    data_writable = DATA.exists() and os.access(DATA, os.W_OK)
    return {
        "status": "ok" if data_writable else "degraded",
        "auth_configured": auth_configured,
        "ocr_runtime_installed": ocr_installed,
        "data_dir_writable": data_writable,
        "persistent_disk_required": True,
        "features": ["module-bank", "attempt-history", "multi-source", "supabase-auth-required"],
    }

@app.post("/api/jobs")
async def create_job(
    user: dict[str, Any] = Depends(require_cortex_session),
    gt_id: str = Form(...),
    expected_questions: int = Form(200),
    source_app: str = Form("PrepLadder"),
    files: list[UploadFile] = File(...)
):
    if not gt_id.strip():
        raise HTTPException(400, "GT/module identifier is required")
    if not 1 <= expected_questions <= 1000:
        raise HTTPException(400, "expected_questions must be between 1 and 1000")
    if source_app not in SOURCE_APPS:
        raise HTTPException(400, f"source_app must be one of {sorted(SOURCE_APPS)}")
    if not files:
        raise HTTPException(400, "Select at least one image or ZIP")
    job_id = str(uuid.uuid4())
    warnings: list[str] = []
    staged: list[tuple[str, bytes]] = []
    total_bytes = 0
    max_upload = int(os.getenv("GT_MAX_UPLOAD_BYTES", str(512 * 1024**2)))
    # Read in bounded chunks; reject the aggregate request before materializing
    # an oversized upload fully in memory.
    for upload in files:
        name = Path(upload.filename or "upload").name
        data, total_bytes = await _read_upload_bounded(upload, total_bytes, max_upload)
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
    # Do not create per-job disk state until the full request passes validation.
    job_dir = UPLOADS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
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
            saved = save_capture(user_id=user["user_id"], job_id=job_id, source_name=source_name, source_app=source_app,
                sha256=digest, original_path=str(original_path), preview_path=str(preview_path),
                raw_ocr=rows, candidate=candidate)
            record = {
                "source_images": [source_name], "sha256": digest, "original_path": str(original_path),
                "preview_url": f"/api/jobs/{job_id}/previews/{digest}", "width": image.width, "height": image.height,
                "ocr": rows, "question_candidate": candidate, "ocr_error": ocr_error, "saved_records": saved
            }
            seen[digest] = record
            image_results.append(record)
        except ValueError as exc:
            warnings.append(f"{source_name}: {exc}")
    result = {
        "schema_version": "0.2", "job_id": job_id, "gt_id": gt_id, "source_app": source_app,
        "expected_questions": expected_questions, "total_images_received": len(staged),
        "unique_images_processed": len(image_results), "warnings": warnings, "images": image_results
    }
    # SQLite is the durable source of truth for batch JSON; the local file is a
    # convenient download fast-path only and may disappear on ephemeral hosts.
    save_job_result(user_id=user["user_id"], result=result)
    result_path = RESULTS / f"{job_id}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    jobs[job_id] = {"job_id": job_id, "gt_id": gt_id, "source_app": source_app, "status": "complete",
                    "total": len(staged), "processed": len(image_results), "warnings": len(warnings),
                    "result_path": str(result_path), "user_id": user["user_id"]}
    return {"job": jobs[job_id], "result": result}

@app.get("/api/jobs")
async def list_jobs(user: dict[str, Any] = Depends(require_cortex_session)):
    return list_jobs_for_user(user["user_id"])

@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, user: dict[str, Any] = Depends(require_cortex_session)):
    if not user_owns_job(user["user_id"], job_id):
        raise HTTPException(404, "Job not found")
    path = RESULTS / f"{job_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    result = get_job_result(user_id=user["user_id"], job_id=job_id)
    if result is None:
        raise HTTPException(404, "Job result not found")
    return result

@app.get("/api/jobs/{job_id}/download")
async def download_result(job_id: str, user: dict[str, Any] = Depends(require_cortex_session)):
    if not user_owns_job(user["user_id"], job_id):
        raise HTTPException(404, "Job not found")
    path = RESULTS / f"{job_id}.json"
    if path.exists():
        return FileResponse(path, media_type="application/json", filename=f"{job_id}_ocr.json")
    result = get_job_result(user_id=user["user_id"], job_id=job_id)
    if result is None:
        raise HTTPException(404, "Job result not found")
    return JSONResponse(content=result, headers={"Content-Disposition": f'attachment; filename="{job_id}_ocr.json"'})

@app.get("/api/jobs/{job_id}/previews/{digest}")
async def get_preview(job_id: str, digest: str, user: dict[str, Any] = Depends(require_cortex_session)):
    if not user_owns_job(user["user_id"], job_id):
        raise HTTPException(404, "Job not found")
    path = PREVIEWS / f"{job_id}_{digest}.jpg"
    if not path.exists():
        raise HTTPException(404, "Preview not found")
    return FileResponse(path, media_type="image/jpeg")

@app.get("/api/questions")
def get_module_questions(source_app: str | None = None, outcome: str | None = None, user: dict[str, Any] = Depends(require_cortex_session)):
    if source_app and source_app not in SOURCE_APPS:
        raise HTTPException(400, "Unknown source_app")
    return list_questions(user_id=user["user_id"], source_app=source_app, outcome=outcome)

@app.get("/api/attempts")
def get_attempt_history(source_app: str | None = None, outcome: str | None = None, user: dict[str, Any] = Depends(require_cortex_session)):
    if source_app and source_app not in SOURCE_APPS:
        raise HTTPException(400, "Unknown source_app")
    if outcome and outcome not in {"correct","incorrect","unattempted","unknown"}:
        raise HTTPException(400, "Unknown outcome")
    return list_attempts(user_id=user["user_id"], source_app=source_app, outcome=outcome)

@app.patch("/api/questions/{question_id}")
def patch_module_question(question_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_cortex_session)):
    try:
        found = update_question(question_id, user["user_id"], payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not found:
        raise HTTPException(404, "Question not found")
    return {"updated": True, "question_id": question_id}

@app.patch("/api/attempts/{attempt_id}")
def patch_attempt_history(attempt_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(require_cortex_session)):
    try:
        found = update_attempt(attempt_id, user["user_id"], payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not found:
        raise HTTPException(404, "Attempt record not found")
    return {"updated": True, "attempt_id": attempt_id}


@app.get("/capture-studio.html", include_in_schema=False)
def capture_studio():
    """Serve the Capture Studio page from the sibling file in the gt-extractor project."""
    page = Path(__file__).resolve().parents[2] / "capture-studio.html"
    if not page.is_file():
        raise HTTPException(404, "Capture Studio page is not present in this deployment")
    return FileResponse(page, media_type="text/html")
