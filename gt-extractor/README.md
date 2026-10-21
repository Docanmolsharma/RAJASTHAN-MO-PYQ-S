# CORTEX GT Extractor

CORTEX GT Extractor is an Apple-friendly capture workflow with a Python/FastAPI OCR backend. It accepts multiple screenshots or ZIP archives, normalizes supported image formats, extracts OCR text and candidate question/options, and keeps two data concepts separate:

1. **Question capture bank** — reusable question stem/options, source/module, private screenshot path, answer key only when reliably extracted, and verification status.
2. **Source attempt history** — selected option, correct option, outcome (`correct`, `incorrect`, `unattempted`, or `unknown`) and evidence. Explanations are deliberately not copied into the reusable question record.

Supported source labels: PrepLadder, Marrow, Cerebellum, Book, Other. These are user-selected labels, not official integrations.

## Backend setup

```bash
cd gt-extractor/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The Docker image installs PaddleOCR/PaddlePaddle for CPU OCR. Configure `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, and `GT_ALLOWED_ORIGINS` in the host environment. `GT_ALLOWED_ORIGINS` is a comma-separated allowlist of exact frontend origins (scheme + host, no path); wildcard CORS is not enabled. Non-health API routes validate the signed-in user's bearer token with Supabase Auth.

Open `capture-studio.html` from the same deployed CORTEX origin to reuse the signed-in Supabase session. The browser upload currently supports multiple image files; the backend API also supports ZIP archives. The older `frontend/index.html` is a developer preview, not the authenticated capture interface.

## Persistence and deployment

Set `GT_DATA_DIR` to a persistent mounted disk. The SQLite database stores owner-scoped capture/attempt records, job summaries and complete batch-result JSON. Original processing files and preview images remain on local disk and require persistence for preview access. This version does not provide a durable multi-instance queue or horizontally shared file storage; deploy a single backend instance with a persistent volume for the first live test.

Supabase has separate owner-RLS tables for `question_capture_bank` and `question_source_attempts`, plus a private `question-captures` Storage bucket. The capture UI uploads original screenshots to that bucket and stores the bucket path with the capture record. Upload rollback/cleanup is best-effort and must be checked in live testing.

## Upload/archive limits

The API reads each upload in 1 MiB chunks and enforces the aggregate request budget before retaining more bytes. It creates per-job disk state only after the request passes upload/archive validation. Defaults:
- `GT_MAX_UPLOAD_BYTES`: 512 MiB total request upload
- `GT_MAX_FILES`: 500 supported images
- `GT_MAX_ARCHIVE_BYTES`: 2 GiB compressed ZIP
- `GT_MAX_MEMBER_BYTES`: 40 MiB per image
- `GT_MAX_TOTAL_EXTRACTED_BYTES`: 256 MiB of supported images extracted from one ZIP

Tune these to the deployment's memory and disk limits.

## API

- `POST /api/jobs`: multi-image/ZIP capture; form fields `gt_id`, `expected_questions`, `source_app`, `files`.
- `GET /api/jobs`: signed-in user's job summaries.
- `GET /api/jobs/{id}` and `GET /api/jobs/{id}/download`: owner-scoped batch result and JSON download.
- `GET /api/questions?source_app=PrepLadder&outcome=incorrect`: question bank with latest attempt summary.
- `GET /api/attempts?source_app=Marrow&outcome=correct`: attempt history.
- `PATCH /api/questions/{id}`: manually verify/correct question, options, answer key and module.
- `PATCH /api/attempts/{id}`: correct selected/correct answer and outcome.

## Tests

Run from `gt-extractor/backend`:

```bash
pip install -r requirements.txt
pytest -q
```

The suite includes parser, storage, upload/archive-limit, attempt-consistency, durable job recovery and API-flow tests. The API flow tests mock OCR and image decoding; they validate application plumbing but do not replace visual calibration on real PrepLadder/Marrow/Cerebellum screenshots.

## Answer-status rules and release gate

The parser is intentionally conservative and never uses medical knowledge to invent an answer. Explicit answer text and visual markers are compared; conflicting evidence becomes `unknown`. A detected “You missed this question” banner means unattempted, with no selected option. Green/red option-marker detection exists as a baseline but its HSV crop assumptions have **not yet been validated against a representative set of real review screenshots**. The parser must be calibrated on real examples and ambiguous cases must remain unknown.

Before production use, still perform: (1) automated CI/test verification, (2) real screenshot calibration for OCR and green/red status, (3) live Supabase auth/RLS/private Storage upload and signed-preview test, (4) deployment with persistent disk and CORS configured, and (5) one end-to-end GT1 batch test before processing the full 200-question batch. Do not promote unverified captures into the live quiz bank.
