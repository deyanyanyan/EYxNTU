"""What steers a regeneration: the author's instructions, one-tap intents, and the trained
reviewer's findings turned into instructions (each flagged span with what was wrong, the
distractor score, and low lesson-level rubric scores with their feedback)."""
from __future__ import annotations

from app.models.asset import Asset

# One-tap intents offered wherever content is regenerated.
INTENTS = {
    "simpler": "Use simpler, plainer language for these learners: short sentences and everyday words.",
    "examples": "Add a concrete workplace example that fits these learners.",
    "shorter": "Make it shorter: fewer words and fewer bullets, keeping only what matters.",
}
WEAK_DISTRACTORS = 2  # reviewer distractor scores at or below this are flagged


def compose(instructions: str | None, intents: list[str] | None, findings: list[str] | None = None) -> str:
    """The author's instructions, the chosen intents and any reviewer findings, as one brief."""
    parts = [INTENTS[i] for i in intents or [] if i in INTENTS]
    if instructions and instructions.strip():
        parts.insert(0, instructions.strip())
    if findings:
        parts.append("The reviewer checked this against the references and found:\n" + "\n".join(f"- {f}" for f in findings)
                     + "\nFix these, and change as little else as possible.")
    return "\n".join(parts)


def appendix(brief: str) -> str:
    """Instructions appended to a whole-lesson or outline prompt."""
    return f"\n\nAuthor's instructions for this version (follow them unless they conflict with the references):\n{brief}" if brief else ""


# ---- reviewer findings -> instructions ----------------------------------------------
def slide_findings(critique: dict | None, block: str) -> list[str]:
    review = (critique or {}).get("reviewer") or {}
    out = []
    for issue in (review.get("slides", {}).get(block) or {}).get("issues", []):
        span = issue.get("span", "").replace("Speaker notes: ", "").lstrip("- ").strip()
        if issue.get("type", "").endswith("conflict"):
            out.append(f'"{span}" contradicts the references. Correct it to match them.')
        else:
            out.append(f'"{span}" is not supported by the references. Remove it, or replace it with what the references say.')
    return out


def question_findings(critique: dict | None, block: str) -> list[str]:
    review = (critique or {}).get("reviewer") or {}
    q = review.get("questions", {}).get(block) or {}
    if q.get("valid") and q.get("score") is not None and q["score"] <= WEAK_DISTRACTORS:
        return [f"The wrong options are easy to rule out (distractor score {q['score']}/5). Write three wrong options that are plausible and "
                "close to the correct answer but clearly wrong according to the references. Keep the question, the correct answer and the source span."]
    return []


def lesson_findings(deck: Asset | None, quiz: Asset | None) -> list[str]:
    """Everything the reviewer flagged in a lesson, for a whole-lesson regeneration."""
    out: list[str] = []
    for block in sorted(((deck.critique or {}).get("reviewer") or {}).get("slides", {})) if deck else []:
        out += [f"Slide {block.lstrip('s')}: {f}" for f in slide_findings(deck.critique, block)]
    for block in sorted(((quiz.critique or {}).get("reviewer") or {}).get("questions", {}), key=int) if quiz else []:
        out += [f"Question {int(block) + 1}: {f}" for f in question_findings(quiz.critique, block)]
    for c in ((deck.critique or {}).get("reviewer") or {}).get("rubric", []) if deck else []:
        if c.get("valid") and c.get("score") is not None and c["score"] <= 3 and c.get("feedback"):
            out.append(f"{c['criterion']} ({c['score']}/5): {c['feedback']}")
    return out


def flagged_blocks(deck: Asset | None, quiz: Asset | None) -> list[tuple[Asset, str]]:
    """(asset, block) for every slide with grounding issues and every weak question."""
    out: list[tuple[Asset, str]] = []
    if deck:
        for block, s in (((deck.critique or {}).get("reviewer") or {}).get("slides") or {}).items():
            if s.get("issues"):
                out.append((deck, block))
    if quiz:
        for block in (((quiz.critique or {}).get("reviewer") or {}).get("questions") or {}):
            if question_findings(quiz.critique, block):
                out.append((quiz, block))
    return out
