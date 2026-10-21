from app.services.question_parser import parse_question_regions


def row(text, y, marker=None):
    result = {"text": text, "bbox": [[0, y], [100, y], [100, y + 10], [0, y + 10]], "confidence": .99}
    if marker:
        result["option_marker"] = marker
    return result


def base_rows():
    return [
        row("Question stem", 1),
        row("A. alpha", 10),
        row("B. beta", 20),
        row("C. gamma", 30),
        row("D. delta", 40),
        row("Correct Answer: B) beta", 60),
        row("Explanation: do not copy", 70),
    ]


def test_parser_stops_after_d_boundary_and_ignores_explanation():
    parsed = parse_question_regions(base_rows())
    assert parsed["options"] == {"A": "alpha", "B": "beta", "C": "gamma", "D": "delta"}
    assert parsed["correct_answer"] == "B"
    assert parsed["explanation"] is None
    assert "Explanation" not in str(parsed)


def test_correct_attempt_green_only():
    rows = [row("Question stem", 1), row("A. alpha", 10), row("B. beta", 20, "green"),
            row("C. gamma", 30), row("D. delta", 40), row("Correct Answer: B", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] == "B"
    assert parsed["selected_answer"] == "B"
    assert parsed["result"] == "correct"


def test_incorrect_attempt_red_selected_green_correct():
    rows = [row("Question stem", 1), row("A. alpha", 10, "red"), row("B. beta", 20),
            row("C. gamma", 30, "green"), row("D. delta", 40), row("Correct Answer: C", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] == "C"
    assert parsed["selected_answer"] == "A"
    assert parsed["result"] == "incorrect"


def test_missed_banner_overrides_green_only_and_means_unattempted():
    rows = [row("Question stem", 1), row("A. alpha", 10), row("B. beta", 20),
            row("C. gamma", 30), row("D. delta", 40, "green"),
            row("You missed this question", 50), row("Correct Answer: D", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] == "D"
    assert parsed["selected_answer"] is None
    assert parsed["result"] == "unattempted"


def test_unclear_options_are_flagged_unknown():
    parsed = parse_question_regions([row("A. only", 10)])
    assert parsed["correct_answer"] is None
    assert parsed["selected_answer"] is None
    assert parsed["result"] == "unknown"
    assert parsed["warnings"]


def test_parser_supports_badge_labels_without_punctuation():
    rows = [row("Question stem", 1), row("A Analytical statistics", 10, "red"),
            row("B Inferential statistics", 20), row("C Descriptive statistics", 30, "green"),
            row("D Theoretical statistics", 40), row("Correct Answer: C", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["A"].startswith("Analytical")
    assert parsed["options"]["C"].startswith("Descriptive")
    assert parsed["selected_answer"] == "A"
    assert parsed["correct_answer"] == "C"
    assert parsed["result"] == "incorrect"


def test_wrapped_option_d_is_preserved_without_copying_explanation():
    rows = [
        row("Question stem", 1),
        row("A. alpha", 10),
        row("B. beta", 20),
        row("C. gamma", 30),
        row("D. first line of option", 40),
        row("continued second line of option", 45),
        row("Correct Answer: D", 60),
        row("Explanation: private solution text", 70),
    ]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["D"] == "first line of option continued second line of option"
    assert parsed["correct_answer"] == "D"
    assert parsed["explanation"] is None
    assert "private solution text" not in str(parsed)
