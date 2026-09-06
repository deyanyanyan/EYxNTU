from app.core.generation.quiz.service import RawQuestion, validate

CTX = "[1] handbook.pdf › 2 Safety (p.4)\nWorkers must wear eye protection when operating the lathe. Inspection happens every 30 days."


def _q(**kw):
    base = dict(
        stem="How often are inspections carried out?",
        correct_answer="Every 30 days",
        distractors=["Every 7 days", "Every 90 days", "Every 12 months"],
        explanation="See [1].",
        source_span="Inspection happens every 30 days.",
        reference=1,
        difficulty="easy",
    )
    base.update(kw)
    return RawQuestion(**base)


def test_valid_question_passes():
    assert validate(_q(), CTX) == []


def test_span_must_be_verbatim():
    issues = validate(_q(source_span="Inspections are done monthly."), CTX)
    assert any(i.code == "span_not_found" for i in issues)


def test_answer_leak_detected():
    issues = validate(_q(stem="Inspections happen every 30 days; how often?"), CTX)
    assert any(i.code == "answer_leak" for i in issues)
