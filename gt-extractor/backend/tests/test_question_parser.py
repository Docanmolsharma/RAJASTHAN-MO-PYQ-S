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


def test_missed_banner_is_not_appended_to_option_d():
    rows = [
        row("Question stem", 1),
        row("A. alpha", 10),
        row("B. beta", 20),
        row("C. gamma", 30),
        row("D. delta", 40, "green"),
        row("You missed this question", 50),
        row("Correct Answer: D", 60),
        row("Explanation: private solution text", 70),
    ]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["D"] == "delta"
    assert parsed["selected_answer"] is None
    assert parsed["correct_answer"] == "D"
    assert parsed["result"] == "unattempted"
    assert "You missed this question" not in str(parsed)
    assert "private solution text" not in str(parsed)


def test_conflicting_green_marker_and_explicit_answer_stays_unknown():
    rows = [row("Question stem", 1), row("A. alpha", 10),
            row("B. beta", 20, "green"), row("C. gamma", 30),
            row("D. delta", 40), row("Correct Answer: C", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] is None
    assert parsed["result"] == "unknown"
    assert parsed["warnings"]


def test_multiple_green_markers_stay_unknown():
    rows = [row("Question stem", 1), row("A. alpha", 10, "green"),
            row("B. beta", 20), row("C. gamma", 30, "green"),
            row("D. delta", 40)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] is None
    assert parsed["result"] == "unknown"
    assert any("multiple option markers" in warning for warning in parsed["warnings"])


def test_bare_solution_heading_is_not_appended_to_option_d():
    rows = [
        row("Question stem", 1), row("A. alpha", 10), row("B. beta", 20),
        row("C. gamma", 30), row("D. delta", 40),
        row("Solution", 50), row("The explanation text must not be copied", 60),
    ]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["D"] == "delta"
    assert "explanation text" not in str(parsed).lower()
    assert parsed["explanation"] is None


def test_bare_explanation_heading_is_not_appended_to_option_d():
    rows = [
        row("Question stem", 1), row("A. alpha", 10), row("B. beta", 20),
        row("C. gamma", 30), row("D. delta", 40),
        row("Explanation", 50), row("This content must be excluded", 60),
    ]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["D"] == "delta"
    assert "This content must be excluded" not in str(parsed)


def test_explicit_answer_heading_with_option_text_keeps_letter():
    rows = [row("Question stem", 1), row("A. alpha", 10), row("B. beta", 20),
            row("C. gamma", 30), row("D. delta", 40),
            row("Correct Answer: B) beta", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] == "B"


def test_answer_parser_does_not_take_letter_from_following_option_row():
    rows = [row("Question stem", 1), row("Correct Answer", 5),
            row("A. alpha", 10), row("B. beta", 20),
            row("C. gamma", 30), row("D. delta", 40)]
    parsed = parse_question_regions(rows)
    assert parsed["correct_answer"] is None
    assert parsed["result"] == "unknown"


def test_removes_status_bar_and_question_counter_from_stem():
    rows = [
        row("12:58PM Wed 21 Oct 0167% @ Question 190 of 200", 0),
        row("A 62-year-old man with diabetes presents with erectile dysfunction", 10),
        row("A. alpha", 30), row("B. beta", 40), row("C. gamma", 50), row("D. delta", 60),
    ]
    parsed = parse_question_regions(rows)
    assert "12:58PM" not in parsed["question_text"]
    assert "Question 190 of 200" not in parsed["question_text"]
    assert "62-year-old man" in parsed["question_text"]


def test_question_counter_is_removed_when_attached_to_header_text():
    rows = [
        row("Question 191 of 200", 0),
        row("A 35-year-old man presents after being stabbed", 10),
        row("A. alpha", 30), row("B. beta", 40), row("C. gamma", 50), row("D. delta", 60),
    ]
    parsed = parse_question_regions(rows)
    assert "Question 191 of 200" not in parsed["question_text"]
    assert "35-year-old man" in parsed["question_text"]


def test_status_bar_and_counter_do_not_delete_clinical_stem():
    rows = [
        row("12:58PM Wed 21 Oct 0167% @ Question 190 of 200 A 62-year-old man with diabetes", 1),
        row("A. alpha", 20), row("B. beta", 30), row("C. gamma", 40), row("D. delta", 50),
    ]
    parsed = parse_question_regions(rows)
    assert "62-year-old man with diabetes" in parsed["question_text"]
    assert "12:58PM" not in parsed["question_text"]
    assert "Question 190 of 200" not in parsed["question_text"]


def test_battery_artifact_is_removed_without_dropping_clinical_stem():
    rows = [
        row("0167% @ A 62-year-old man with diabetes and hypertension", 1),
        row("A. alpha", 20), row("B. beta", 30), row("C. gamma", 40), row("D. delta", 50),
    ]
    parsed = parse_question_regions(rows)
    assert "0167%" not in parsed["question_text"]
    assert "62-year-old man" in parsed["question_text"]


def test_incomplete_options_are_explicitly_flagged():
    parsed = parse_question_regions([
        row("A 35-year-old patient presents with acute chest pain", 1),
        row("A. alpha", 20), row("B. beta", 30),
    ])
    assert len(parsed["options"]) < 4
    assert any("options were extracted" in warning for warning in parsed["warnings"])
    assert parsed["review_status"] == "pending"


def test_realistic_prep_ladder_question_with_unpunctuated_badges():
    rows = [
        row("A 35-year-old man presents to the casualty after being stabbed in the precordial region.", 10),
        row("He is in shock with elevated jugular venous pressure and muffled heart sounds. Which of", 20),
        row("the following statements is incorrect?", 30),
        row("A Cardiac tamponade is the most likely diagnosis [5%]", 40),
        row("B If an open pneumothorax is suspected, the chest wound should be sealed completely", 50),
        row("on all four sides with an occlusive dressing [64%]", 60),
        row("C_ eFAST can identify fluid around the heart [8%]", 70),
        row("D_ Needle pericardiocentesis is not routinely recommended [23%]", 80),
        row("64% got this correct", 90),
        row("Solution", 100),
        row("Correct Answer: B) If an open pneumothorax is suspected", 110),
        row("Explanation: do not include this", 120),
    ]
    parsed = parse_question_regions(rows)
    assert "35-year-old man" in parsed["question_text"]
    assert "statements is incorrect" in parsed["question_text"]
    assert parsed["options"]["A"].startswith("Cardiac tamponade")
    assert "all four sides" in parsed["options"]["B"]
    assert parsed["options"]["C"].startswith("eFAST")
    assert parsed["options"]["D"].startswith("Needle pericardiocentesis")
    assert all("%" not in value for value in parsed["options"].values())
    assert parsed["correct_answer"] == "B"
    assert "Explanation" not in str(parsed)


def test_realistic_question_with_missing_d_badge_glyph():
    rows = [
        row("A 62-year-old man with diabetes presents with erectile dysfunction", 10),
        row("A Misoprostol [10%]", 20),
        row("B Alprostadil [72%]", 30, "green"),
        row("C€ Carboprost [10%]", 40),
        row("[> | Latanoprost [8%]", 50, "red"),
        row("72% got this correct", 60),
        row("Solution", 70),
        row("Correct Answer: B) Alprostadil", 80),
        row("Explanation: do not include this", 90),
    ]
    parsed = parse_question_regions(rows)
    assert "62-year-old man" in parsed["question_text"]
    assert parsed["options"]["A"].startswith("Misoprostol")
    assert parsed["options"]["B"].startswith("Alprostadil")
    assert parsed["options"]["C"].startswith("Carboprost")
    assert parsed["options"]["D"].startswith("Latanoprost")
    assert parsed["correct_answer"] == "B"
    assert parsed["selected_answer"] == "D"
    assert parsed["result"] == "incorrect"
    assert "Explanation" not in str(parsed)



def test_standalone_option_badges_are_joined_to_same_row_text():
    rows = [
        row("A 62-year-old man presents with erectile dysfunction", 1),
        row("A", 20), row("Misoprostol [10%]", 20),
        row("B", 30, "green"), row("Alprostadil [72%]", 30),
        row("C", 40), row("Carboprost [10%]", 40),
        row("D", 50, "red"), row("Latanoprost [8%]", 50),
        row("Solution", 60), row("Correct Answer: B", 70),
    ]
    parsed = parse_question_regions(rows)
    assert parsed["options"]["A"].startswith("Misoprostol")
    assert parsed["options"]["B"].startswith("Alprostadil")
    assert parsed["options"]["C"].startswith("Carboprost")
    assert parsed["options"]["D"].startswith("Latanoprost")
    assert parsed["correct_answer"] == "B"
    assert parsed["selected_answer"] == "D"
    assert parsed["result"] == "incorrect"
