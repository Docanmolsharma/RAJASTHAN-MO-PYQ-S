import json
from app.services import data_store

def test_module_bank_and_attempt_history_are_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "test.sqlite3")
    saved = data_store.save_capture(user_id="user-1", 
        job_id="job-1", source_name="screen.heic", source_app="PrepLadder",
        sha256="abc123", original_path="/tmp/screen.heic", preview_path="/tmp/preview.jpg",
        raw_ocr=[{"text":"A. option one"}],
        candidate={"question_text":"Example question?","options":{"A":"one","B":"two","C":"three","D":"four"},
                   "correct_answer":None,"selected_answer":None,"result":"unknown",
                   "warnings":["answer colors not calibrated"],"review_status":"pending"}
    )
    questions = data_store.list_questions(user_id="user-1")
    attempts = data_store.list_attempts(user_id="user-1")
    assert len(questions) == 1 and len(attempts) == 1
    assert questions[0]["question_text"] == "Example question?"
    assert questions[0]["options"]["D"] == "four"
    assert questions[0]["correct_answer"] is None
    assert attempts[0]["outcome"] == "unknown"
    assert attempts[0]["selected_answer"] is None
    assert saved["module_question_id"] == questions[0]["id"]
    assert saved["attempt_history_id"] == attempts[0]["id"]

def test_manual_answer_verification_updates_history(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, "DB_PATH", tmp_path / "test.sqlite3")
    saved = data_store.save_capture(user_id="user-1", job_id="j",source_name="q.png",source_app="Book",sha256="x",
        original_path="/tmp/q.png",preview_path="/tmp/p.jpg",raw_ocr=[],
        candidate={"question_text":"Q","options":{"A":"a","B":"b","C":"c","D":"d"},
                   "correct_answer":None,"selected_answer":"B","result":"unknown"})
    assert data_store.update_question(saved["module_question_id"], "user-1", {
        "question_text":"Q","options":{"A":"a","B":"b","C":"c","D":"d"},
        "correct_answer":"B","module_name":"Cardiology","verified":True
    })
    attempts=data_store.list_attempts(user_id="user-1")
    assert attempts[0]["outcome"] == "correct"
    assert attempts[0]["correct_answer"] == "B"
