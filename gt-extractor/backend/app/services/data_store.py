from __future__ import annotations
import json, os, sqlite3, uuid
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("GT_DB_PATH", "data/cortex_extractor.sqlite3")).resolve()

def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db

def init_db() -> None:
    with connect() as db:
        db.executescript("""
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS capture_items (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, source_name TEXT NOT NULL,
          source_app TEXT NOT NULL DEFAULT 'unknown', sha256 TEXT NOT NULL,
          original_path TEXT NOT NULL, preview_path TEXT NOT NULL,
          raw_ocr_json TEXT NOT NULL, parse_json TEXT, review_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS module_questions (
          id TEXT PRIMARY KEY, capture_item_id TEXT NOT NULL UNIQUE REFERENCES capture_items(id),
          question_text TEXT NOT NULL DEFAULT '', options_json TEXT NOT NULL DEFAULT '{}',
          correct_answer TEXT, question_image_path TEXT,
          source_app TEXT NOT NULL DEFAULT 'unknown', source_reference TEXT,
          module_name TEXT, verified INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS attempt_history (
          id TEXT PRIMARY KEY, capture_item_id TEXT NOT NULL REFERENCES capture_items(id),
          question_id TEXT REFERENCES module_questions(id), source_app TEXT NOT NULL DEFAULT 'unknown',
          selected_answer TEXT, correct_answer TEXT, outcome TEXT NOT NULL DEFAULT 'unknown',
          evidence_json TEXT NOT NULL DEFAULT '{}', attempt_label TEXT, captured_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_module_source ON module_questions(source_app);
        CREATE INDEX IF NOT EXISTS idx_attempt_outcome ON attempt_history(outcome);
        CREATE INDEX IF NOT EXISTS idx_attempt_capture ON attempt_history(capture_item_id);
        """)

def save_capture(*, job_id: str, source_name: str, source_app: str, sha256: str,
                 original_path: str, preview_path: str, raw_ocr: list[dict[str, Any]],
                 candidate: dict[str, Any] | None) -> dict[str, str]:
    """Persist module-bank content and attempt-history evidence separately.
    Unknown answers/outcomes stay unknown; no answer is inferred from medical knowledge.
    """
    init_db()
    capture_id = str(uuid.uuid4())
    question_id = str(uuid.uuid4())
    attempt_id = str(uuid.uuid4())
    q = candidate or {}
    question_text = str(q.get("question_text") or "")
    options = q.get("options") if isinstance(q.get("options"), dict) else {}
    correct = q.get("correct_answer") if q.get("correct_answer") in {"A","B","C","D"} else None
    selected = q.get("selected_answer") if q.get("selected_answer") in {"A","B","C","D"} else None
    outcome = q.get("result") if q.get("result") in {"correct","incorrect","unattempted"} else "unknown"
    review_status = str(q.get("review_status") or "pending")
    evidence = {"warnings": q.get("warnings", []), "parser": "baseline-v1"}
    with connect() as db:
        db.execute("""INSERT INTO capture_items
          (id,job_id,source_name,source_app,sha256,original_path,preview_path,raw_ocr_json,parse_json,review_status)
          VALUES (?,?,?,?,?,?,?,?,?,?)""",
          (capture_id,job_id,source_name,source_app,sha256,original_path,preview_path,
           json.dumps(raw_ocr,ensure_ascii=False),json.dumps(q,ensure_ascii=False) if q is not None else None,review_status))
        db.execute("""INSERT INTO module_questions
          (id,capture_item_id,question_text,options_json,correct_answer,question_image_path,source_app,verified)
          VALUES (?,?,?,?,?,?,?,0)""",
          (question_id,capture_id,question_text,json.dumps(options,ensure_ascii=False),correct,original_path,source_app))
        db.execute("""INSERT INTO attempt_history
          (id,capture_item_id,question_id,source_app,selected_answer,correct_answer,outcome,evidence_json)
          VALUES (?,?,?,?,?,?,?,?)""",
          (attempt_id,capture_id,question_id,source_app,selected,correct,outcome,json.dumps(evidence,ensure_ascii=False)))
    return {"capture_item_id":capture_id,"module_question_id":question_id,"attempt_history_id":attempt_id}

def list_questions(*, source_app: str | None = None, outcome: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = """SELECT q.*, c.source_name, c.review_status, a.selected_answer, a.outcome, a.attempt_label, a.captured_at
               FROM module_questions q JOIN capture_items c ON c.id=q.capture_item_id
               LEFT JOIN attempt_history a ON a.question_id=q.id WHERE 1=1"""
    params: list[Any] = []
    if source_app:
        query += " AND q.source_app=?"; params.append(source_app)
    if outcome:
        query += " AND a.outcome=?"; params.append(outcome)
    query += " ORDER BY q.created_at DESC"
    with connect() as db:
        rows = db.execute(query,params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["options"] = json.loads(item.pop("options_json") or "{}")
        result.append(item)
    return result

def list_attempts(*, outcome: str | None = None, source_app: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = """SELECT a.*, c.source_name, q.question_text, q.options_json, q.question_image_path
               FROM attempt_history a JOIN capture_items c ON c.id=a.capture_item_id
               LEFT JOIN module_questions q ON q.id=a.question_id WHERE 1=1"""
    params: list[Any] = []
    if outcome:
        query += " AND a.outcome=?"; params.append(outcome)
    if source_app:
        query += " AND a.source_app=?"; params.append(source_app)
    query += " ORDER BY a.captured_at DESC"
    with connect() as db:
        rows = db.execute(query,params).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["options"] = json.loads(item.pop("options_json") or "{}")
        item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
        result.append(item)
    return result

def update_question(question_id: str, payload: dict[str, Any]) -> bool:
    init_db()
    correct = payload.get("correct_answer")
    if correct not in (None,"A","B","C","D"):
        raise ValueError("correct_answer must be A, B, C, D or null")
    options = payload.get("options", {})
    if not isinstance(options, dict) or any(k not in {"A","B","C","D"} for k in options):
        raise ValueError("options must be a dictionary keyed by A/B/C/D")
    with connect() as db:
        cur = db.execute("""UPDATE module_questions SET question_text=?,options_json=?,correct_answer=?,
          module_name=?,verified=?,updated_at=datetime('now') WHERE id=?""",
          (str(payload.get("question_text") or ""),json.dumps(options,ensure_ascii=False),correct,
           payload.get("module_name"),1 if payload.get("verified") else 0,question_id))
        if cur.rowcount:
            db.execute("""UPDATE attempt_history SET correct_answer=?,
              outcome=CASE WHEN ? IS NULL OR selected_answer IS NULL THEN outcome
                           WHEN selected_answer=? THEN 'correct' ELSE 'incorrect' END
              WHERE question_id=?""",(correct,correct,correct,question_id))
        return cur.rowcount > 0

def update_attempt(attempt_id: str, payload: dict[str, Any]) -> bool:
    selected = payload.get("selected_answer")
    correct = payload.get("correct_answer")
    outcome = payload.get("outcome","unknown")
    if selected not in (None,"A","B","C","D") or correct not in (None,"A","B","C","D"):
        raise ValueError("answers must be A, B, C, D or null")
    if outcome not in {"correct","incorrect","unattempted","unknown"}:
        raise ValueError("invalid outcome")
    if selected and correct:
        outcome = "correct" if selected == correct else "incorrect"
    with connect() as db:
        cur = db.execute("""UPDATE attempt_history SET selected_answer=?,correct_answer=?,outcome=?,attempt_label=?
                            WHERE id=?""",(selected,correct,outcome,payload.get("attempt_label"),attempt_id))
        return cur.rowcount > 0
