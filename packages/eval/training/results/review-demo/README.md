# Trained reviewer on a mock course

This is the record of the released reviewer reviewing a mock course with planted errors. It ran as batch job 95508 on NTU GaaS on 28 October 2026. These files are its unedited requests and output; the app's reviewer findings for the demo project were imported from them.

| | |
|---|---|
| Reviewer | `Qwen/Qwen3.8-27B` at `1d4bf0f2ff60…` with adapter `main-27b-v1` (`checkpoint-1044`, training hash `14187ac9a2fd46dd`), the release in [`data/models/adapters/reviewer-main-27b-v1`](../../../../../data/models/adapters/reviewer-main-27b-v1) |
| Settings | Prompts `66e720f8e43d`, greedy decoding, thinking off, vLLM 0.32.0 on one H200 |
| Run | 21 requests, all answered with valid JSON; 6 seconds of inference after the model loaded |

## The course

[`scripts/seed_review_demo.py`](../../../../../scripts/seed_review_demo.py) creates the mock course "Northwind Information Security Essentials" from a short staff handbook. It has 3 lessons, 9 slides and 6 quiz questions.

- **Planted slide errors:** six, all in the first two lessons.
- **Planted quiz defect:** one question has absurd wrong options.
- **Clean lesson:** the phishing lesson is faithful to the handbook.

The app exported one request per slide (grounding), two per lesson (rubric criteria), and one per question (distractors).

## What the reviewer found

| Lesson | Slide checks against the handbook | Lesson rubric (1–5) | Quiz distractors (1–5) |
|---|---|---|---|
| Passwords and multi-factor authentication | All 3 planted errors flagged:<br>– "12 characters" (handbook: 14): contradicts<br>– "change your password every 30 days": not in the handbook<br>– "SMS codes are a fine permanent alternative" (handbook: 7-day fallback only): contradicts | Depth 3, fit 3 | 4, and **1** for the planted question ("1 character", "a password made of emoji") |
| Reporting security incidents | All 3 planted errors flagged as contradicting the handbook:<br>– "within 24 hours" (handbook: 1 hour)<br>– "delete the suspicious message" (handbook: do not)<br>– speaker notes saying self-reports earn a formal warning<br>The clean first slide: no flags | Depth 2, fit 3 | 3, 4 |
| Recognising phishing (clean) | No flags on its 3 slides | Depth 3, fit 5 | 1, 4 |

- **Slide checks:** all 6 planted errors were caught, each by quoting the exact wrong words, and none of the 4 clean slides was flagged.
- **Rubric feedback:** the lesson feedback also names the planted errors, e.g. "the required reporting time is stated as 24 hours instead of the mandated 1 hour".
- **Distractor score with no planted defect:** one phishing question also scored 1. Its wrong options ("an email sent during working hours", "a message written in formal English") are easy to rule out. Its probability-weighted score was 2.5, so the model was split on it.

This is one small synthetic course with errors planted by the team. It shows the review round trip works and the model catches clear contradictions. It does not measure accuracy on real courses. As in the app, the rubric and distractor scores are advisory.

## Files

| File | Contents |
|---|---|
| `requests.jsonl` | The app's export (`python -m app.core.review export`): the reviewed text, its source passages, and a `ref` naming the slide, lesson criterion or question |
| `requests.jsonl.manifest.json` | The plan and asset versions that were reviewed |
| `results.jsonl` | One reviewer answer per request (`evaltrain.review_batch`): raw text, parsed JSON, validity, score probabilities, and the request's `ref` |
| `results.jsonl.meta.json` | Reviewer identity and timing, stored with every imported finding |

The job log is kept with the run backup, not in the repository; it holds cluster paths.

The `ref` fields point at the asset IDs of the demo database the course was seeded into. Seeding again creates new IDs, so `python -m app.core.review import` would skip these results on a fresh database. To review a freshly seeded course, export its requests and run the reviewer again. Without GaaS, [`review_batch --adapter-dir`](../../evaltrain/review_batch.py) runs the same review on any GPU machine.
