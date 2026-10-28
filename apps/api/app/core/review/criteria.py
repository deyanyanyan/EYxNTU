"""Lesson-level review criteria, scored 1-5 by the reviewer's rubric task.

Adapted from the content scorecard in packages/eval/FRAMEWORK_RESEARCH.md. The reviewer
learned rubric scoring from general Prometheus rubrics, not from course-quality labels,
so these scores are advisory. Changing any wording changes ``CRITERIA_VERSION``, which is
stored with every review.
"""
from __future__ import annotations

import hashlib
import json

CRITERIA = [
    {
        "id": "instructional_depth",
        "name": "Instructional depth",
        "criteria": "Does the lesson teach the required rules and procedures to the depth the learner needs, explaining what to do, how, and why, "
        "with a concrete example, rather than only listing assertions?",
        "score1": "Lists a few assertions with no explanation, procedure or example; key requirements are missing.",
        "score2": "Mentions most requirements but rarely explains how or why to follow them; no usable example.",
        "score3": "Explains the main requirements, but procedures or reasons are incomplete, or the example is generic.",
        "score4": "Explains the requirements, procedures and reasons clearly with a relevant example; only minor gaps.",
        "score5": "Explains every required rule, the exact procedure and its reason, with a concrete workplace example; nothing essential is missing.",
    },
    {
        "id": "audience_fit",
        "name": "Fit for the learners",
        "criteria": "Are the lesson's language, assumed knowledge and pacing appropriate for the stated learners?",
        "score1": "Language or assumed knowledge is unsuitable for these learners throughout; they could not follow it.",
        "score2": "Frequent unexplained terms or assumptions that these learners would struggle with.",
        "score3": "Mostly suitable, with several unexplained terms or abrupt jumps.",
        "score4": "Suitable language and pacing, with an occasional unexplained term.",
        "score5": "Language, assumed knowledge and pacing fit these learners throughout.",
    },
]

CRITERIA_VERSION = hashlib.sha256(json.dumps(CRITERIA, sort_keys=True).encode()).hexdigest()[:12]
