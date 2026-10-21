from app.services import data_store


def _capture(store, outcome, selected=None, correct=None):
    return store.save_capture(
        user_id="user-1", job_id="job-1", source_name="q.png",
        source_app="Book", sha256="abc", original_path="/tmp/q.png",
        preview_path="/tmp/p.jpg", raw_ocr=[],
        candidate={
            "question_text": "Q",
            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "selected_answer": selected, "correct_answer": correct,
            "result": outcome, "review_status": "pending",
        },
    )


def test_answer_verification_does_not_leave_stale_unknown_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "history.sqlite3")
    saved = _capture(data_store, "unknown", selected="B", correct=None)

    data_store.update_question(saved["module_question_id"], "user-1", {
        "question_text": "Q",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "correct_answer": None,
        "module_name": "Test",
        "verified": False,
    })
    attempt = data_store.list_attempts(user_id="user-1")[0]
    assert attempt["outcome"] == "unknown"


def test_unattempted_remains_unattempted_after_answer_verification(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "history.sqlite3")
    saved = _capture(data_store, "unattempted", selected=None, correct="D")

    data_store.update_question(saved["module_question_id"], "user-1", {
        "question_text": "Q",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "correct_answer": "D",
        "module_name": "Test",
        "verified": True,
    })
    attempt = data_store.list_attempts(user_id="user-1")[0]
    assert attempt["outcome"] == "unattempted"


def test_attempt_patch_cannot_claim_correct_without_selected_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "patch-history.sqlite3")
    saved = _capture(data_store, "unknown", selected=None, correct="B")
    assert data_store.update_attempt(saved["attempt_history_id"], "user-1", {
        "selected_answer": None, "correct_answer": "B", "outcome": "correct",
    })
    attempt = data_store.list_attempts(user_id="user-1")[0]
    assert attempt["selected_answer"] is None
    assert attempt["outcome"] == "unknown"


def test_attempt_patch_derives_outcome_from_verified_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "patch-history.sqlite3")
    saved = _capture(data_store, "unknown", selected="A", correct="B")
    assert data_store.update_attempt(saved["attempt_history_id"], "user-1", {
        "selected_answer": "A", "correct_answer": "B", "outcome": "correct",
    })
    attempt = data_store.list_attempts(user_id="user-1")[0]
    assert attempt["outcome"] == "incorrect"
