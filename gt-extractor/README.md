# CORTEX GT Extractor (MVP scaffold)

Apple-first web interface with a Python/FastAPI processing backend. It accepts multiple image files or ZIPs, normalizes HEIC/HEIF/JPEG/PNG images, produces OCR JSON with bounding boxes, and stores two independent records in SQLite:

1. **Module bank** — reusable question stem, four options, source, image path, answer key (only when reliably extracted/verified), module label and verification state. Intended for later CORTEX quiz modules.
2. **Attempt history** — selected option, correct option, outcome (correct/incorrect/unattempted/unknown), source and evidence. Unknown is preserved when visual indicators cannot yet be decoded.

Supported source labels: PrepLadder, Marrow, Cerebellum, Book, Other. These are source labels, not official integrations.

## Run backend
```bash
cd gt-extractor/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# OCR extra: pip install paddleocr paddlepaddle
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `capture-studio.html` from the same deployed CORTEX origin so it can reuse the signed-in Supabase session. Configure the deployed OCR backend URL in the page. The backend validates the bearer token against Supabase Auth on every non-health API route, and scopes in-memory job access plus local SQLite records to the authenticated user. The older `frontend/index.html` is a developer preview; production capture should use `capture-studio.html`. For iPhone/iPad use, the browser must be able to reach the backend; mobile Safari itself is not expected to run large OCR batches.

## Container build

`backend/Dockerfile` builds a CPU OCR image with PaddleOCR/PaddlePaddle included. Configure `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` in the host environment. Use a persistent mounted disk for `GT_DATA_DIR`; without it, local previews/results/SQLite records may be lost on redeploy. Job ownership and recent job summaries are recovered from SQLite after process restart. Result JSON and preview files still require a persistent mounted disk; horizontal scaling and cloud object storage are not implemented.

## API
- `POST /api/jobs`: multi-image/ZIP capture; form fields `gt_id`, `expected_questions`, `source_app`, `files`.
- `GET /api/questions?source_app=PrepLadder&outcome=incorrect`: module bank with latest attempt summary.
- `GET /api/attempts?source_app=Marrow&outcome=correct`: attempt history.
- `PATCH /api/questions/{id}`: manually verify/correct question, options, answer key and module.
- `PATCH /api/attempts/{id}`: correct selected/correct answer and outcome.
- `GET /api/jobs/{id}/download`: per-batch JSON export.

## Run tests
```bash
cd gt-extractor/backend
pip install pytest
pytest
```

## Important limitations
This is an initial prototype, not a validated GT dataset. PaddleOCR is optional and loaded lazily. Explanation exclusion and correct/incorrect color mapping must be calibrated on actual review screenshots. It deliberately does not infer answers from medical knowledge. If visual status cannot be read confidently, the record remains `unknown` pending verification. The private Supabase capture tables and owner-based RLS policies are provisioned. The local SQLite prototype now also stores a user id on each record and scopes reads/updates to that user. OCR previews currently reference the configured backend; durable original-image storage in a private Supabase Storage bucket, verified screenshot colour mapping, resumable uploads, persistent job tracking, and end-to-end tests on real PrepLadder/Marrow/Cerebellum/book examples are still required before production use.
