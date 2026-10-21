from __future__ import annotations

import re
from typing import Any

OPTION_RE = re.compile(r"^\s*([A-D])(?:\s*[).:]|\s+)\s*(.*)$", re.I)
ANSWER_RE = re.compile(r"(?i)\bcorrect\s+answer\s*[:：-]?\s*\(?\s*([A-D])\s*\)?")
MISSED_RE = re.compile(r"(?i)you\s+missed\s+this\s+question")


def _row_y(row: dict[str, Any]) -> float:
    return min((p[1] for p in row.get("bbox", [])), default=0)


def _row_x(row: dict[str, Any]) -> float:
    return min((p[0] for p in row.get("bbox", [])), default=0)


def _marker(row: dict[str, Any]) -> str | None:
    """Optional marker label emitted by a separate image-colour detector."""
    value = str(row.get("option_marker", row.get("marker", ""))).strip().lower()
    aliases = {"green": "green", "correct": "green", "correct_green": "green", "red": "red", "wrong": "red", "incorrect": "red", "selected_wrong": "red"}
    return aliases.get(value)


def parse_question_regions(ocr_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse question text conservatively and use explicit review-screen signals.

    OCR rows may optionally include option_marker for A-D rows when a separate
    image-colour detector has classified the option badge. Plain OCR text alone
    is not treated as proof of a user's selected option.
    """
    ordered = sorted(ocr_rows, key=lambda r: (_row_y(r), _row_x(r)))
    warnings: list[str] = []
    all_text = "\n".join(str(r.get("text", "")).strip() for r in ordered if r.get("text"))
    missed = bool(MISSED_RE.search(all_text))
    option_starts: dict[str, int] = {}
    for i, row in enumerate(ordered):
        match = OPTION_RE.match(str(row.get("text", "")))
        if match:
            option_starts.setdefault(match.group(1).upper(), i)
    if not all(k in option_starts for k in "ABCD"):
        warnings.append("Could not confidently identify all four option boundaries")
    d_index = option_starts.get("D")
    included = ordered[:d_index + 1] if d_index is not None else ordered
    options: dict[str, str] = {}
    option_rows: dict[str, dict[str, Any]] = {}
    current: str | None = None
    stem: list[str] = []
    for row in included:
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        match = OPTION_RE.match(text)
        if match:
            current = match.group(1).upper()
            options.setdefault(current, match.group(2).strip())
            option_rows.setdefault(current, row)
        elif current:
            options[current] = (options.get(current, "") + " " + text).strip()
        else:
            stem.append(text)
    answer_match = ANSWER_RE.search(all_text)
    green_options = [letter for letter, row in option_rows.items() if _marker(row) == "green"]
    red_options = [letter for letter, row in option_rows.items() if _marker(row) == "red"]
    correct_answer = answer_match.group(1).upper() if answer_match else None
    if correct_answer is None and len(green_options) == 1:
        correct_answer = green_options[0]
    selected_answer: str | None = None
    if not missed:
        if len(red_options) == 1:
            selected_answer = red_options[0]
        elif len(green_options) == 1 and len(red_options) == 0:
            selected_answer = green_options[0]
    if missed:
        result = "unattempted"
        selected_answer = None
        if not correct_answer:
            warnings.append("Missed-question banner found, but correct option marker was not identified")
    elif correct_answer and selected_answer:
        result = "correct" if selected_answer == correct_answer else "incorrect"
    else:
        result = "unknown"
        warnings.append("Answer/attempt status could not be established from reliable screenshot signals")
    if d_index is None:
        warnings.append("Explanation exclusion boundary is uncertain; review required")
    return {"question_text": " ".join(stem).strip(), "options": {k: options[k] for k in "ABCD" if k in options}, "correct_answer": correct_answer, "selected_answer": selected_answer, "result": result, "explanation": None, "warnings": warnings, "review_status": "pending" if warnings or result == "unknown" else "needs_review"}
