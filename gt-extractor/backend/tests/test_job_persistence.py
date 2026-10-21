from app.services import data_store


def _save(data_store, user_id, job_id, source_name="q.png"):
    return data_store.save_capture(
        user_id=user_id,
        job_id=job_id,
        source_name=source_name,
        source_app="PrepLadder",
        sha256=job_id + source_name,
        original_path="/tmp/" + source_name,
        preview_path="/tmp/preview.jpg",
        raw_ocr=[],
        candidate={
            "question_text": "Example?",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "correct_answer": None,
            "selected_answer": None,
            "result": "unknown",
            "warnings": ["needs review"],
            "review_status": "pending",
        },
    )


def test_job_ownership_and_recent_jobs_survive_process_cache_loss(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "jobs.sqlite3")
    _save(data_store, "user-a", "job-a", "one.png")
    _save(data_store, "user-a", "job-a", "two.png")
    _save(data_store, "user-a", "job-b", "three.png")
    _save(data_store, "user-b", "job-secret", "secret.png")

    assert data_store.user_owns_job("user-a", "job-a")
    assert not data_store.user_owns_job("user-b", "job-a")
    assert not data_store.user_owns_job("user-a", "job-secret")

    jobs = data_store.list_jobs_for_user("user-a")
    assert {item["job_id"] for item in jobs} == {"job-a", "job-b"}
    job_a = next(item for item in jobs if item["job_id"] == "job-a")
    assert job_a["processed"] == 2
    assert job_a["pending_review"] == 2
    assert all(item["status"] == "stored" for item in jobs)


def test_job_listing_is_scoped_to_authenticated_user(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "jobs.sqlite3")
    _save(data_store, "user-a", "job-a")
    _save(data_store, "user-b", "job-b")

    assert [item["job_id"] for item in data_store.list_jobs_for_user("user-a")] == ["job-a"]
    assert [item["job_id"] for item in data_store.list_jobs_for_user("user-b")] == ["job-b"]


def test_job_result_survives_restart_and_is_owner_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "results.sqlite3")
    result = {
        "job_id": "job-persisted",
        "gt_id": "GT1",
        "source_app": "PrepLadder",
        "expected_questions": 200,
        "total_images_received": 2,
        "unique_images_processed": 2,
        "warnings": [],
        "images": [{"sha256": "abc", "question_candidate": {"result": "unknown"}}],
    }
    data_store.save_job_result(user_id="user-a", result=result)

    # Re-read from the database rather than any process-local cache or JSON file.
    assert data_store.get_job_result(user_id="user-a", job_id="job-persisted") == result
    assert data_store.get_job_result(user_id="user-b", job_id="job-persisted") is None
    jobs = data_store.list_jobs_for_user("user-a")
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "job-persisted"
    assert jobs[0]["processed"] == 2
    assert jobs[0]["status"] == "complete"


def test_job_result_without_capture_rows_still_has_owner_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "empty-job.sqlite3")
    data_store.save_job_result(user_id="user-a", result={
        "job_id": "job-no-valid-images", "gt_id": "GT2", "source_app": "Book",
        "expected_questions": 10, "total_images_received": 1,
        "unique_images_processed": 0, "warnings": ["invalid image"], "images": [],
    })
    assert data_store.user_owns_job("user-a", "job-no-valid-images")
    assert not data_store.user_owns_job("user-b", "job-no-valid-images")
