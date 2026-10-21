from __future__ import annotations

import re
from typing import Any

OPTION_RE = re.compile(r"^\s*([A-D])\s*[).:]\s*(.*)$", re.I)
LOOSE_OPTION_RE = re.compile(r"^\s*([A-D])\s+([A-Za-z(].*)$", re.I)
ANSWER_RE = re.compile(r"(?im)^[ \t]*correct[ \t]+answer[ \t]*[:：-]?[ \t]*\(?[ \t]*([A-D])\b")
MISSED_RE = re.compile(r"(?i)you\s+missed\s+this\s+question")

QUESTION_COUNTER_RE = re.compile(r"(?i)\bquestion\s*#?\s*\d{1,4}\s+of\s+\d{1,4}\b")
TIME_DATE_RE = re.compile(r"(?i)^\s*(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?\b.*(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|%|question)")

def _clean_screen_chrome(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip status-bar/counter artifacts while preserving the actual question text."""
    cleaned: list[dict[str, Any]] = []
    chrome_prefix = re.compile(
        r"(?i)^\s*(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:am|pm)?\s+"
        r"(?:(?:mon|tue|wed|thu|fri|sat|sun)\w*\s+)?"
        r"(?:\d{1,2}\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*"
        r"(?:\s+\d{2,4})?\s*"
    )
    for row in rows:
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        # Remove the question counter wherever it occurs.
        text = QUESTION_COUNTER_RE.sub(" ", text)
        # Status-bar OCR can be fused with the first clinical line. Strip only its
        # clock/date prefix; do not discard the remainder of the same line.
        text = chrome_prefix.sub(" ", text)
        # Remove standalone battery/time debris left after prefix cleanup.
        text = re.sub(r"(?i)^\s*(?:=|@|%|\|)+\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" =@|·{}%")
        if not text:
            continue
        # Pure status-bar fragments have no meaningful question text.
        if re.fullmatch(r"(?i)(?:\d{1,3}%?|[=*@|·\s]+|(?:question\s*)?\d{1,4}\s*(?:of\s*\d{1,4})?)", text):
            continue
        cleaned.append({**row, "text": text})
    return cleaned

def _row_y(row: dict[str, Any]) -> float:
    return min((p[1] for p in row.get("bbox", [])), default=0)


def _row_x(row: dict[str, Any]) -> float:
    return min((p[0] for p in row.get("bbox", [])), default=0)


def _marker(row: dict[str, Any]) -> str | None:
    """Optional marker label emitted by a separate image-colour detector."""
    value = str(row.get("option_marker", row.get("marker", ""))).strip().lower()
    aliases = {"green": "green", "correct": "green", "correct_green": "green", "red": "red", "wrong": "red", "incorrect": "red", "selected_wrong": "red"}
    return aliases.get(value)


def _logical_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine Tesseract word-level tokens into visual lines before parsing."""
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    # Legacy/test rows without Tesseract line ids remain separate input lines.
    for index, row in enumerate(rows):
        key = (int(row.get("block_num", -1)), int(row.get("par_num", -1)), int(row.get("line_num", index)))
        grouped.setdefault(key, []).append(row)
    result: list[dict[str, Any]] = []
    for tokens in grouped.values():
        tokens = sorted(tokens, key=_row_x)
        if len(tokens) == 1:
            result.append(tokens[0])
            continue
        points = [p for token in tokens for p in token.get("bbox", [])]
        merged = {
            "text": " ".join(str(t.get("text", "")).strip() for t in tokens if t.get("text")).strip(),
            "bbox": points,
            "confidence": sum(float(t.get("confidence") or 0) for t in tokens) / max(1, len(tokens)),
            "block_num": tokens[0].get("block_num", -1),
            "par_num": tokens[0].get("par_num", -1),
            "line_num": tokens[0].get("line_num", -1),
        }
        markers = [str(t.get("option_marker", "")).lower() for t in tokens]
        if "green" in markers:
            merged["option_marker"] = "green"
        elif "red" in markers:
            merged["option_marker"] = "red"
        result.append(merged)
    return result


def parse_question_regions(ocr_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse question text conservatively and use explicit review-screen signals.

    OCR rows may optionally include option_marker for A-D rows when a separate
    image-colour detector has classified the option badge. Plain OCR text alone
    is not treated as proof of a user's selected option.
    """
    ordered = sorted(_clean_screen_chrome(_logical_lines(ocr_rows)), key=lambda r: (_row_y(r), _row_x(r)))
    warnings: list[str] = []
    all_text = "\n".join(str(r.get("text", "")).strip() for r in ordered if r.get("text"))
    missed = bool(MISSED_RE.search(all_text))
    # First identify explicit A./A)/A: option labels. Only use the looser
    # "A text" form if at least three distinct A-D labels appear, preventing
    # clinical prose like "A 62-year-old man..." from becoming option A.
    option_matches: dict[int, re.Match[str]] = {}
    explicit_letters: set[str] = set()
    for i, row in enumerate(ordered):
        match = OPTION_RE.match(str(row.get("text", "")))
        if match:
            option_matches[i] = match
            explicit_letters.add(match.group(1).upper())
    if len(explicit_letters) < 3:
        loose: dict[int, re.Match[str]] = {}
        loose_letters: set[str] = set()
        for i, row in enumerate(ordered):
            match = LOOSE_OPTION_RE.match(str(row.get("text", "")))
            if match:
                loose[i] = match
                loose_letters.add(match.group(1).upper())
        if len(loose_letters) >= 3:
            option_matches.update({i:m for i,m in loose.items() if i not in option_matches})
    option_starts: dict[str, int] = {}
    for i, match in option_matches.items():
        option_starts.setdefault(match.group(1).upper(), i)
    if not all(k in option_starts for k in "ABCD"):
        warnings.append("Could not confidently identify all four option boundaries")
    d_index = option_starts.get("D")
    # Keep wrapped D-option lines, but stop before explicit answer/explanation metadata.
    # This avoids the old bug where option D was always truncated to its first OCR line.
    explanation_start = re.compile(
        r"(?i)^\s*(?:explanation|solution|discussion|correct\s+answer|answer\s+key|reference|why\s+others|pearls?)\s*(?:[:：-].*|$)"
    )
    included: list[dict[str, Any]] = []
    for idx, row in enumerate(ordered):
        text = str(row.get("text", "")).strip()
        # Review banners are evidence for attempt status, not part of Option D.
        # Keep them in all_text for detection, but exclude them from question content.
        if d_index is not None and idx > d_index and (
            explanation_start.search(text) or MISSED_RE.search(text)
            or re.match(r"(?i)^\s*(?:incorrect|correct)\s+answer\s*$", text)
        ):
            break
        included.append(row)
    options: dict[str, str] = {}
    option_rows: dict[str, dict[str, Any]] = {}
    current: str | None = None
    stem: list[str] = []
    for row in included:
        text = str(row.get("text", "")).strip()
        if not text:
            continue
        match = option_matches.get(idx)
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
    explicit_correct = answer_match.group(1).upper() if answer_match else None
    # Conflicting colour and OCR evidence must never be silently converted into
    # a confident correct/incorrect result.
    marker_conflict = len(green_options) > 1 or len(red_options) > 1
    if explicit_correct and len(green_options) == 1 and explicit_correct != green_options[0]:
        marker_conflict = True
        warnings.append("Explicit correct-answer text conflicts with the green option marker")
    if marker_conflict:
        warnings.append("Conflicting or multiple option markers; manual review required")
        correct_answer = None
    else:
        correct_answer = explicit_correct or (green_options[0] if len(green_options) == 1 else None)
    selected_answer: str | None = None
    if not missed and not marker_conflict:
        if len(red_options) == 1:
            selected_answer = red_options[0]
        elif len(green_options) == 1 and len(red_options) == 0:
            selected_answer = green_options[0]
    if missed:
        result = "unattempted"
        selected_answer = None
        if not correct_answer:
            warnings.append("Missed-question banner found, but correct option could not be identified reliably")
    elif marker_conflict:
        result = "unknown"
    elif correct_answer and selected_answer:
        result = "correct" if selected_answer == correct_answer else "incorrect"
    else:
        result = "unknown"
        warnings.append("Answer/attempt status could not be established from reliable screenshot signals")
    if d_index is None:
        warnings.append("Explanation exclusion boundary is uncertain; review required")
    return {"question_text": " ".join(stem).strip(), "options": {k: options[k] for k in "ABCD" if k in options}, "correct_answer": correct_answer, "selected_answer": selected_answer, "result": result, "explanation": None, "warnings": warnings, "review_status": "pending" if warnings or result == "unknown" else "needs_review"}
