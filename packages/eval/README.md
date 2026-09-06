# Evaluation harness (milestone M5)

Purpose: produce the model evaluation report comparing baseline and optimised
configurations across grounding, content quality, visual usability, latency and
hardware consumption.

## Planned layout
```
packages/eval/
├── datasets/        fixed source corpus + hand-labelled retrieval questions (recall@k)
├── configs/         one YAML per configuration: model, quantisation, prompt version, reranker on/off, critique on/off, adapter
├── judges/          LLM-as-judge prompts (grounding, coherence, pedagogy) run with the local model
├── rubrics/         human review sheets (5-point) for instructors
├── run.py           runs the pipeline for a config over the corpus via the API, records outputs + timings
└── report.py        aggregates scores into the tables used in the final report
```

## Metrics
| dimension | automatic | human |
|---|---|---|
| grounding | citation validity rate; judge faithfulness score; quiz `source_span` verbatim rate | unsupported-claim count |
| content quality | judge coherence/pedagogy; objective coverage | rubric |
| visual usability | slide bullet/word limits, overflow checks on rendered PNGs | rubric |
| latency | per-stage wall clock from `jobs` timestamps; tokens/s from vLLM metrics | – |
| hardware | peak VRAM (`nvidia-smi` sampling), RAM, disk of artefacts | – |

Each `eval_run` job stores its config hash so results are reproducible.
