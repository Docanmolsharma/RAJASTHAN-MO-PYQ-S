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
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'legacy', job_id TEXT NOT NULL, source_name TEXT NOT NULL,
          source_app TEXT NOT NULL DEFAULT 'unknown', sha256 TEXT NOT NULL,
          original_path TEXT NOT NULL, preview_path TEXT NOT NULL,
          raw_ocr_json TEXT NOT NULL, parse_json TEXT, review_status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS module_questions (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'legacy', capture_item_id TEXT NOT NULL UNIQUE REFERENCES capture_items(id),
          question_text TEXT NOT NULL DEFAULT '', options_json TEXT NOT NULL DEFAULT '{}',
          correct_answer TEXT, question_image_path TEXT,
          source_app TEXT NOT NULL DEFAULT 'unknown', source_reference TEXT,
          module_name TEXT, verified INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS attempt_history (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL DEFAULT 'legacy', capture_item_id TEXT NOT NULL REFERENCES capture_items(id),
          question_id TEXT REFERENCES module_questions(id), source_app TEXT NOT NULL DEFAULT 'unknown',
          selected_answer TEXT, correct_answer TEXT, outcome TEXT NOT NULL DEFAULT 'unknown',
          evidence_json TEXT NOT NULL DEFAULT '{}', attempt_label TEXT, captured_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS job_runs (
          job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, gt_id TEXT NOT NULL,
          source_app TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'complete',
          expected_questions INTEGER NOT NULL DEFAULT 0, total_images_received INTEGER NOT NULL DEFAULT 0,
          unique_images_processed INTEGER NOT NULL DEFAULT 0, warnings_json TEXT NOT NULL DEFAULT '[]',
          result_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_job_runs_user_created ON job_runs(user_id, created_at);
        """)
        # Additive migration for databases created by earlier prototype builds.
        for table in ("capture_items", "module_questions", "attempt_history"):
            columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            if "user_id" not in columns:
                db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT 'legacy'")
        db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_capture_user ON capture_items(user_id);
        CREATE INDEX IF NOT EXISTS idx_module_user ON module_questions(user_id);
        CREATE INDEX IF NOT EXISTS idx_attempt_user ON attempt_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_module_source ON module_questions(source_app);
        CREATE INDEX IF NOT EXISTS idx_attempt_outcome ON attempt_history(outcome);
        CREATE INDEX IF NOT EXISTS idx_attempt_capture ON attempt_history(capture_item_id);
        """)

def save_capture(*, user_id: str, job_id: str, source_name: str, source_app: str, sha256: str,
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
          (id,user_id,job_id,source_name,source_app,sha256,original_path,preview_path,raw_ocr_json,parse_json,review_status)
          VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
          (capture_id,user_id,job_id,source_name,source_app,sha256,original_path,preview_path,
           json.dumps(raw_ocr,ensure_ascii=False),json.dumps(q,ensure_ascii=False) if q is not None else None,review_status))
        db.execute("""INSERT INTO module_questions
          (id,user_id,capture_item_id,question_text,options_json,correct_answer,question_image_path,source_app,verified)
          VALUES (?,?,?,?,?,?,?,?,0)""",
          (question_id,user_id,capture_id,question_text,json.dumps(options,ensure_ascii=False),correct,original_path,source_app))
        db.execute("""INSERT INTO attempt_history
          (id,user_id,capture_item_id,question_id,source_app,selected_answer,correct_answer,outcome,evidence_json)
          VALUES (?,?,?,?,?,?,?,?,?)""",
          (attempt_id,user_id,capture_id,question_id,source_app,selected,correct,outcome,json.dumps(evidence,ensure_ascii=False)))
    return {"capture_item_id":capture_id,"module_question_id":question_id,"attempt_history_id":attempt_id}

def list_questions(*, user_id: str, source_app: str | None = None, outcome: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = """SELECT q.*, c.source_name, c.review_status, a.selected_answer, a.outcome, a.attempt_label, a.captured_at
               FROM module_questions q JOIN capture_items c ON c.id=q.capture_item_id
               LEFT JOIN attempt_history a ON a.question_id=q.id WHERE q.user_id=?"""
    params: list[Any] = [user_id]
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

def list_attempts(*, user_id: str, outcome: str | None = None, source_app: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = """SELECT a.*, c.source_name, q.question_text, q.options_json, q.question_image_path
               FROM attempt_history a JOIN capture_items c ON c.id=a.capture_item_id
               LEFT JOIN module_questions q ON q.id=a.question_id WHERE a.user_id=?"""
    params: list[Any] = [user_id]
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

def update_question(question_id: str, user_id: str, payload: dict[str, Any]) -> bool:
    init_db()
    correct = payload.get("correct_answer")
    if correct not in (None,"A","B","C","D"):
        raise ValueError("correct_answer must be A, B, C, D or null")
    options = payload.get("options", {})
    if not isinstance(options, dict) or any(k not in {"A","B","C","D"} for k in options):
        raise ValueError("options must be a dictionary keyed by A/B/C/D")
    with connect() as db:
        cur = db.execute("""UPDATE module_questions SET question_text=?,options_json=?,correct_answer=?,
          module_name=?,verified=?,updated_at=datetime('now') WHERE id=? AND user_id=?""",
          (str(payload.get("question_text") or ""),json.dumps(options,ensure_ascii=False),correct,
           payload.get("module_name"),1 if payload.get("verified") else 0,question_id,user_id))
        if cur.rowcount:
            db.execute("""UPDATE attempt_history SET correct_answer=?,
              outcome=CASE WHEN outcome='unattempted' AND selected_answer IS NULL THEN 'unattempted'
                           WHEN ? IS NULL OR selected_answer IS NULL THEN 'unknown'
                           WHEN selected_answer=? THEN 'correct' ELSE 'incorrect' END
              WHERE question_id=? AND user_id=?""",(correct,correct,correct,question_id,user_id))
        return cur.rowcount > 0

def update_attempt(attempt_id: str, user_id: str, payload: dict[str, Any]) -> bool:
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
                            WHERE id=? AND user_id=?""",(selected,correct,outcome,payload.get("attempt_label"),attempt_id,user_id))
        return cur.rowcount > 0


def user_owns_job(user_id: str, job_id: str) -> bool:
    """Check durable ownership from SQLite, not the process-local jobs cache."""
    init_db()
    with connect() as db:
        row = db.execute(
            "SELECT 1 FROM capture_items WHERE user_id=? AND job_id=? LIMIT 1",
            (user_id, job_id),
        ).fetchone()
    return row is not None


def list_jobs_for_user(user_id: str) -> list[dict[str, Any]]:
    """List durable job summaries, including older jobs predating job_runs."""
    init_db()
    with connect() as db:
        rows = db.execute("""
            SELECT job_id, source_app, unique_images_processed AS processed,
                   created_at, status,
                   (SELECT COUNT(*) FROM capture_items c
                    WHERE c.user_id=j.user_id AND c.job_id=j.job_id
                      AND c.review_status='pending') AS pending_review
            FROM job_runs j WHERE user_id=?
            UNION ALL
            SELECT c.job_id, c.source_app, COUNT(*) AS processed,
                   MIN(c.created_at) AS created_at, 'stored' AS status,
                   SUM(CASE WHEN c.review_status='pending' THEN 1 ELSE 0 END) AS pending_review
            FROM capture_items c
            WHERE c.user_id=? AND NOT EXISTS (
                SELECT 1 FROM job_runs j WHERE j.user_id=c.user_id AND j.job_id=c.job_id
            )
            GROUP BY c.job_id, c.source_app
            ORDER BY created_at DESC
        """, (user_id,user_id)).fetchall()
    return [
        {"job_id": row["job_id"], "source_app": row["source_app"],
         "processed": row["processed"], "created_at": row["created_at"],
         "pending_review": row["pending_review"], "status": row["status"]}
        for row in rows
    ]

def save_job_result(*, user_id: str, result: dict[str, Any]) -> None:
    """Persist a complete batch result so API downloads survive process restarts."""
    init_db()
    with connect() as db:
        db.execute("""INSERT INTO job_runs
          (job_id,user_id,gt_id,source_app,status,expected_questions,total_images_received,
           unique_images_processed,warnings_json,result_json)
          VALUES (?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(job_id) DO UPDATE SET
            user_id=excluded.user_id,gt_id=excluded.gt_id,source_app=excluded.source_app,
            status=excluded.status,expected_questions=excluded.expected_questions,
            total_images_received=excluded.total_images_received,
            unique_images_processed=excluded.unique_images_processed,
            warnings_json=excluded.warnings_json,result_json=excluded.result_json""",
          (str(result["job_id"]),user_id,str(result.get("gt_id") or ""),
           str(result.get("source_app") or "Other"),"complete",
           int(result.get("expected_questions") or 0),int(result.get("total_images_received") or 0),
           int(result.get("unique_images_processed") or 0),
           json.dumps(result.get("warnings") or [],ensure_ascii=False),
           json.dumps(result,ensure_ascii=False)))

def get_job_result(*, user_id: str, job_id: str) -> dict[str, Any] | None:
    """Fetch a batch result only for its owner."""
    init_db()
    with connect() as db:
        row=db.execute("SELECT result_json FROM job_runs WHERE user_id=? AND job_id=?",(user_id,job_id)).fetchone()
    return json.loads(row["result_json"]) if row else None
