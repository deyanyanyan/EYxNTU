# Writer benchmark: local Qwen against hosted Gemini

Run 17–18 November 2026. Same source (the fictional Northwind handbook, [`scripts/fixtures/baseline_course.md`](../../../scripts/fixtures/baseline_course.md)), same brief, same pipeline, two writers:

| Folder | Writer | Generated |
|---|---|---|
| `results/qwen-7b/` | Qwen 2.5 7B through Ollama on a CPU laptop | 21 Sep 2026 |
| `results/gemini-flash/` | Gemini 3.8 Flash through its OpenAI-compatible API | 17 Nov 2026 |

Each folder holds the app's review export for that course (`requests.jsonl`, from `python -m app.core.review export`, with its manifest) and the judge's answers.

## Judge

The trained reviewer's own prompts (prompt version `66e720f8e43d`), sent to `gemini-pro-latest` with [`review_openai.py`](review_openai.py). That model only runs with thinking on, so it ran at the lowest effort, with temperature 0 and no score probabilities. The trained 27B reviewer could not grade these courses because it needs an 80 GB GPU that was not available.

### Can the judge stand in for the trained reviewer?

Both graded the reviewer's mock course with six planted errors ([`training/results/review-demo`](../training/results/review-demo/README.md)); see `results/agreement-gemini-pro-latest.json`.

| Check | Agreement |
|---|---|
| Slides flagged as unsupported | 7 of 9 slides agree. The judge flagged all 5 slides the 27B flagged, plus 2 clean slides for teaching directions such as "Ask learners which channels they use" |
| Lesson rubric (1–5) | Within 1 point on 4 of 6; mean difference 0.83 |
| Quiz distractors (1–5) | Within 1 point on 2 of 6; the judge is harsher and swings to extremes |

## Results

From `results/courses-gemini-pro-latest.json` and `results/repetition.json`. Time, citations and quiz counts come from the app's run records.

| | Qwen 7B (local) | Gemini Flash (hosted) |
|---|---|---|
| Time to generate | 27 min (CPU laptop) | 7.4 min |
| Bullets with citations | 84% | 100% |
| Quiz questions kept after validation | 12/18 | 18/18 |
| Words generated (slides + notes) | 1,450 (954 + 496) | 4,562 (1,662 + 2,900) |
| Slides with ≥1 unsupported claim | 7/39 (18%) | 23/36 (64%) |
| Unsupported claims per 1,000 words | 6.2 | 16.2 |
| …that contradict the source | 1 | 2 (both minor) |
| …in speaker notes | 5 of 9 | 57 of 74 |
| Lesson depth (1–5) | 2.0 | 4.8 |
| Fit for learners (1–5) | 3.5 | 4.8 |
| Quiz distractor quality (1–5) | 2.4 (7/12 weak) | 2.5 (11/18 weak) |
| Slides largely repeating another lesson | 16/39 (41%), 9 near-identical | 9/36 (25%), 0 near-identical |
| Quiz questions repeating another lesson | 4/12 | 0/18 |

- **The hosted writer teaches better but goes beyond the source.** Most of its flagged claims are plausible elaborations (rationale, examples) in speaker notes that the handbook never states: 69 of 74 were judged "probably true but unsupported". For compliance training that is a real grounding risk.
- **The local writer stays close to the source but is shallow and repetitive.** It copies terse bullets and repeats content across lessons.
- **Neither writes good quiz distractors.**
- **No sign of self-preference.** The Gemini judge was harsher on the Gemini course.

### Caveats

- One run per writer, one source document, no human ratings.
- The judge is from the same model family as one writer.
- Some flags are teaching directions rather than factual claims.
- Rubric and distractor scores are advisory.

## Reproduce

| File | What it does |
|---|---|
| [`run.sh`](run.sh) | Grades all three courses with a hosted judge and writes the two summaries |
| [`review_openai.py`](review_openai.py) | Sends review requests to any OpenAI-compatible API, using `evaltrain`'s templates and parser |
| [`summarize.py`](summarize.py) | Per-course flag rates and scores (`course`), and agreement between two reviewers (`agree`) |
| [`repetition.py`](repetition.py) | Cross-lesson repetition from BGE-M3 embeddings; runs inside the api container |

```sh
pip install numpy scipy pyyaml && pip install -e packages/eval/training --no-deps
sh packages/eval/benchmark/run.sh                       # independent judge: gpt-5.5 with OPENAI_API_KEY
sh packages/eval/benchmark/run.sh gemini-pro-latest \
   https://generativelanguage.googleapis.com/v1beta/openai GEMINI_API_KEY   # repeats this run
```

The key is read from the environment or from `.env`. To grade with the trained 27B instead, run `python -m evaltrain.review_batch --adapter-dir data/models/adapters/reviewer-main-27b-v1` on the two `requests.jsonl` files on a GPU machine, then summarise with `summarize.py course`.

To benchmark a new writer, generate a course with it (`scripts/course_baseline.py --keep` after changing `LLM_*` in `.env`), export its review requests, and grade them the same way.
