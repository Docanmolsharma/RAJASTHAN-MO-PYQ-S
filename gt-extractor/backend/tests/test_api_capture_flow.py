from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.services import data_store


class FakeOCR:
    def extract(self, image):
        # Explicit option markers simulate OCR/color-detector output. A is the
        # selected wrong option; B is the correct green option.
        return [
            {"text": "Which option is correct?", "bbox": [[10, 10], [200, 10], [200, 25], [10, 25]]},
            {"text": "A. Wrong answer", "bbox": [[10, 40], [150, 40], [150, 55], [10, 55]], "option_marker": "red"},
            {"text": "B. Correct answer", "bbox": [[10, 65], [150, 65], [150, 80], [10, 80]], "option_marker": "green"},
            {"text": "C. Third answer", "bbox": [[10, 90], [150, 90], [150, 105], [10, 105]]},
            {"text": "D. Fourth answer", "bbox": [[10, 115], [150, 115], [150, 130], [10, 130]]},
        ]


def test_authenticated_capture_flow_persists_candidate_and_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "extractor.sqlite3")
    uploads, previews, results = (tmp_path / "uploads", tmp_path / "previews", tmp_path / "results")
    for folder in (uploads, previews, results):
        folder.mkdir()
    monkeypatch.setattr(main, "UPLOADS", uploads)
    monkeypatch.setattr(main, "PREVIEWS", previews)
    monkeypatch.setattr(main, "RESULTS", results)
    monkeypatch.setattr(main, "ocr", FakeOCR())

    image_bytes = b"test image bytes"
    digest = hashlib.sha256(image_bytes).hexdigest()
    monkeypatch.setattr(
        main, "normalize_image",
        lambda data: (Image.new("RGB", (320, 240)), digest, b"preview-jpeg-bytes"),
    )
    main.app.dependency_overrides[main.require_cortex_session] = lambda: {
        "user_id": "test-user", "email": "test@example.com"
    }
    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/jobs",
                data={"gt_id": "GT-test", "expected_questions": "1", "source_app": "PrepLadder"},
                files=[("files", ("question.png", image_bytes, "image/png"))],
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            job_id = payload["result"]["job_id"]
            candidate = payload["result"]["images"][0]["question_candidate"]
            assert candidate["correct_answer"] == "B"
            assert candidate["selected_answer"] == "A"
            assert candidate["result"] == "incorrect"
            assert candidate["explanation"] is None

            attempts = client.get("/api/attempts?outcome=incorrect")
            assert attempts.status_code == 200
            assert len(attempts.json()) == 1
            assert attempts.json()[0]["selected_answer"] == "A"
            assert attempts.json()[0]["correct_answer"] == "B"

            # Result retrieval must work from the durable store even after the
            # local JSON fast-path is removed.
            (results / f"{job_id}.json").unlink()
            recovered = client.get(f"/api/jobs/{job_id}")
            assert recovered.status_code == 200
            assert recovered.json()["job_id"] == job_id
            assert client.get(f"/api/jobs/{job_id}/download").status_code == 200
    finally:
        main.app.dependency_overrides.pop(main.require_cortex_session, None)


def test_capture_api_does_not_expose_another_users_job(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "isolation.sqlite3")
    data_store.save_job_result(user_id="owner", result={
        "job_id": "private-job", "gt_id": "GT1", "source_app": "Book",
        "expected_questions": 1, "total_images_received": 1,
        "unique_images_processed": 0, "warnings": [], "images": [],
    })
    main.app.dependency_overrides[main.require_cortex_session] = lambda: {
        "user_id": "other-user", "email": None
    }
    try:
        with TestClient(main.app) as client:
            assert client.get("/api/jobs/private-job").status_code == 404
            assert client.get("/api/jobs/private-job/download").status_code == 404
    finally:
        main.app.dependency_overrides.pop(main.require_cortex_session, None)
