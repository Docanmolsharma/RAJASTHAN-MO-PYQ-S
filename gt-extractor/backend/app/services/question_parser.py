from __future__ import annotations

import re
from typing import Any

OPTION_RE = re.compile(r"^\s*([A-D])\s*[).:]\s*(.*)$", re.I)
LOOSE_OPTION_RE = re.compile(r"^\s*([A-D])(?:\s*[_€|>]+\s*|\s+)([A-Za-z(].*)$", re.I)
REVIEW_START_RE = re.compile(r"(?i)^\s*(?:(?:\d{1,3}%\s*)?got this correct|solution\b|explanation\s*:|correct\s+answer\b|tags based on question\b)")
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
        # OCR may misread a 67% battery icon as "0167%"; strip that debris only
        # at the start of the remaining line, after the clock/date prefix.
        text = re.sub(r"(?i)^\s*\d{1,4}\s*%\s*[@=|·]*\s*", " ", text)
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
    # Keep answer/explanation evidence in all_text, but parse question content only
    # until the review/solution panel begins. This prevents explanation paragraphs
    # being appended to option D when its visual badge was not OCR-recognized.
    content_rows: list[dict[str, Any]] = []
    for row in ordered:
        text = str(row.get("text", "")).strip()
        if REVIEW_START_RE.search(text) or MISSED_RE.search(text):
            break
        content_rows.append(row)

    # Detect explicit labels first. OCR often reads coloured badges as C_ / C€,
    # so allow a small set of badge artifacts only in the loose-label fallback.
    option_matches: dict[int, re.Match[str]] = {}
    explicit_letters: set[str] = set()
    for i, row in enumerate(content_rows):
        match = OPTION_RE.match(str(row.get("text", "")))
        if match:
            option_matches[i] = match
            explicit_letters.add(match.group(1).upper())
    if len(explicit_letters) < 3:
        loose: dict[int, re.Match[str]] = {}
        loose_letters: set[str] = set()
        for i, row in enumerate(content_rows):
            match = LOOSE_OPTION_RE.match(str(row.get("text", "")))
            if match:
                loose[i] = match
                loose_letters.add(match.group(1).upper())
        if len(loose_letters) >= 3:
            option_matches.update({i: m for i, m in loose.items() if i not in option_matches})

    option_starts: dict[str, int] = {}
    for i, match in option_matches.items():
        option_starts.setdefault(match.group(1).upper(), i)

    # If OCR entirely loses the D badge (e.g. it reads "[> | Latanoprost"),
    # recover D conservatively only when A/B/C were detected and the next row
    # after C is a short option-like row before the review panel.
    if "D" not in option_starts and all(k in option_starts for k in "ABC"):
        c_idx = option_starts["C"]
        candidate_idx = c_idx + 1
        if candidate_idx < len(content_rows):
            candidate_text = str(content_rows[candidate_idx].get("text", "")).strip()
            cleaned_candidate = re.sub(r"^[\\[<>{}|!>Il1\\s]+", "", candidate_text).strip()
            if cleaned_candidate and len(cleaned_candidate) <= 100 and not re.match(r"(?i)^(?:which|why|the following|correct answer|solution|explanation)", cleaned_candidate):
                option_matches[candidate_idx] = re.match(r"(?s)^D\\s*(.*)$", "D " + cleaned_candidate)
                option_starts["D"] = candidate_idx

    if not all(k in option_starts for k in "ABCD"):
        warnings.append("Could not confidently identify all four option boundaries")
    d_index = option_starts.get("D")
    explanation_start = re.compile(
        r"(?i)^\\s*(?:explanation|solution|discussion|correct\\s+answer|answer\\s+key|reference|why\\s+others|pearls?)\\s*(?:[:：-].*|$)"
    )
    included: list[dict[str, Any]] = []
    for idx, row in enumerate(content_rows):
        if d_index is not None and idx > d_index and explanation_start.search(str(row.get("text", ""))):
            break
        included.append(row)

    options: dict[str, str] = {}
    option_rows: dict[str, dict[str, Any]] = {}
    current: str | None = None
    stem: list[str] = []
    for idx, row in enumerate(included):
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
    question_text = " ".join(stem).strip()
    # Remove per-option response percentages from the source app's answer distribution.
    final_options = {
        k: re.sub(r"\s*[\[(]?\s*\d{1,3}%\s*[\])]?\s*$", "", options[k]).strip()
        for k in "ABCD" if options.get(k, "").strip()
    }
    if not question_text or len(question_text) < 18:
        warnings.append("Question stem is missing or suspiciously short; manual review required")
    if len(final_options) != 4:
        warnings.append(f"Only {len(final_options)} of 4 options were extracted; manual review required")
    if any(re.search(r"(?i)(?:\b\d{1,3}%\b|\bquestion\s*\d+\s+of\s+\d+\b|\b(?:am|pm)\s+(?:mon|tue|wed|thu|fri)\b)", value) for value in [question_text, *final_options.values()]):
        warnings.append("Possible screen chrome remains in extracted text; manual review required")
    if d_index is None:
        warnings.append("Explanation exclusion boundary is uncertain; review required")
    return {"question_text": question_text, "options": final_options, "correct_answer": correct_answer, "selected_answer": selected_answer, "result": result, "explanation": None, "warnings": list(dict.fromkeys(warnings)), "review_status": "pending"}
