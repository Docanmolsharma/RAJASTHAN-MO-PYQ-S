from __future__ import annotations
import re
from typing import Any

OPTION_RE = re.compile(r"^\s*([A-D])\s*[).:]\s*(.*)$", re.I)

def parse_question_regions(ocr_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Conservative baseline. Does not infer answers; uncertain D boundary is flagged."""
    ordered = sorted(ocr_rows, key=lambda r: (
        min((p[1] for p in r.get("bbox", [])), default=0),
        min((p[0] for p in r.get("bbox", [])), default=0)
    ))
    option_starts: dict[str, int] = {}
    for i, row in enumerate(ordered):
        match = OPTION_RE.match(row.get("text", ""))
        if match:
            option_starts.setdefault(match.group(1).upper(), i)
    warnings: list[str] = []
    if not all(k in option_starts for k in "ABCD"):
        warnings.append("Could not confidently identify all four option boundaries")
    d_index = option_starts.get("D")
    included = ordered[:d_index + 1] if d_index is not None else ordered
    options: dict[str, str] = {}
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
        elif current:
            options[current] = (options.get(current, "") + " " + text).strip()
        else:
            stem.append(text)
    if d_index is None:
        warnings.append("Explanation exclusion boundary is uncertain; review required")
    return {
        "question_text": " ".join(stem).strip(),
        "options": {k: options[k] for k in "ABCD" if k in options},
        "correct_answer": None,
        "selected_answer": None,
        "result": "unknown",
        "explanation": None,
        "warnings": warnings,
        "review_status": "pending",
    }
