from app.services.question_parser import parse_question_regions

def row(text, y):
    return {"text": text, "bbox": [[0,y],[100,y],[100,y+10],[0,y+10]], "confidence": .99}

def test_parser_stops_after_d_boundary_and_ignores_explanation():
    rows = [row("A. alpha", 10), row("B. beta", 20), row("C. gamma", 30),
            row("D. delta", 40), row("Explanation: ignored", 60)]
    parsed = parse_question_regions(rows)
    assert parsed["options"] == {"A": "alpha", "B": "beta", "C": "gamma", "D": "delta"}
    assert "Explanation" not in str(parsed)
    assert parsed["explanation"] is None

def test_unclear_options_are_flagged():
    parsed = parse_question_regions([row("A. only", 10)])
    assert parsed["correct_answer"] is None
    assert parsed["result"] == "unknown"
    assert parsed["warnings"]
