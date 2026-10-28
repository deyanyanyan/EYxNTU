"""Versioned review prompts shared by training, evaluation and batch inference.

Training targets, prompted baselines and LMS review requests all render through these
templates, so a base model and its adapter always receive identical inputs.
``PROMPT_VERSION`` hashes every template and is recorded in run bundles and prediction
files; editing any wording therefore produces a visibly different prompt version.

Each template asks for one criterion (or one closely related criterion group) and a
single JSON object. Fields the source dataset cannot supervise are not requested.
"""
from __future__ import annotations

import hashlib
import json

SYSTEM = (
    "You are a careful reviewer of educational and informational content. "
    "Judge only against the criteria, reference material and sources supplied in the request, "
    "and never invent evidence. "
    "Reply with a single JSON object in exactly the requested format and nothing else."
)

RUBRIC = """Assess the response against the score rubric. A reference answer that would receive a score of 5 is provided for comparison. Write concise feedback that justifies the score strictly in terms of the rubric, then give an integer score from 1 to 5.

### Instruction given to the respondent
{instruction}

### Response to evaluate
{response}

### Reference answer (score 5)
{reference}

### Score rubric
{criteria}
Score 1: {score1}
Score 2: {score2}
Score 3: {score3}
Score 4: {score4}
Score 5: {score5}

Return JSON: {{"feedback": "<feedback>", "score": <integer 1-5>}}"""

GROUNDING = """Check whether the response is supported by the source material. List every span of the response that contradicts the source ("conflict") or adds information the source does not support ("baseless"). Use "evident" when the problem is clear-cut and "subtle" when it needs careful reading or inference. Set "implicit_true" to true for baseless information that is probably accurate but is not stated in the source: unsupported is not the same as false. Copy each span exactly from the response, in order of appearance. If everything is supported, return an empty list.

### Request and source material given to the writer
{context}

### Response to check
{response}

Return JSON: {{"issues": [{{"span": "<exact text from the response>", "type": "evident_conflict" | "subtle_conflict" | "evident_baseless" | "subtle_baseless", "implicit_true": true | false}}]}}"""

GROUNDING_TYPES = ("evident_conflict", "subtle_conflict", "evident_baseless", "subtle_baseless")

DISTRACTORS = """Rate the quality of the distractors (the incorrect options) of this multiple-choice question on the rubric below.

### Rubric
{rubric}

### Question
{question}

### Correct answer
{answer}

### Distractors
{distractors}

Return JSON: {{"score": <integer 1-5>}}"""

SLIDE = """Rate this lecture slide (image) together with the lecturer's spoken explanation of it (transcript) on each criterion below, using integers from 1 to 5.

{criteria}

### Transcript of the explanation
{transcript}

Return JSON: {{{keys}}}"""

TEMPLATES = {"system": SYSTEM, "rubric": RUBRIC, "grounding": GROUNDING, "distractors": DISTRACTORS, "slide": SLIDE}
PROMPT_VERSION = hashlib.sha256(json.dumps(TEMPLATES, sort_keys=True).encode()).hexdigest()[:12]


def chat(user: str, system: str = SYSTEM) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
