# Roadmap

15 weeks, Mon 7 Sep → Fri 18 Dec 2026. Four workstreams from the project scope:
**A** Ingestion & grounding · **B** Planning & pedagogy · **C** Asset generation & export · **D** Video & model optimisation.
One owner per workstream; everyone contributes to eval and docs. Friday integration checkpoint; `main` always demoable.

## Milestones

| # | Milestone | Weeks (dates) | Exit criteria |
|---|---|---|---|
| **M0** Foundation | Wk 1–2 (7–18 Sep) | Boilerplate cut & scrubbed; `make up` on laptops (Ollama) and on the H100 (vLLM Qwen 32B AWQ); auth + roles + projects; ONBOARDING done; baseline latency/VRAM numbers; sample corpus chosen (3–5 public documents). |
| **M1** Grounded knowledge base (A) | Wk 2–4 (14 Sep–9 Oct) | Docling ingest for PDF/DOCX/PPTX; structure-aware chunks; bge-m3 + pgvector; search API + chunk browser; citation objects; retrieval eval (recall@k on 30 hand-labelled questions). |
| **M2** Course plan (B) | Wk 4–6 (28 Sep–23 Oct) | Brief form; objectives + syllabus (structured JSON); coverage map; review/approve gate UI; plan-quality rubric v1. |
| **M3** Asset generation (C) | Wk 6–9 (12 Oct–6 Nov) | Slides + notes, quiz + key, tutorial per lesson with citations; citation validator; critique agent + auto-revise; block editor; PPTX + HTML export. **Mid-project demo end of Wk 9.** |
| **M4** Video & SCORM (C+D) | Wk 9–11 (2–20 Nov) | Script generation; TTS service; ffmpeg pipeline with subtitles; SCORM 1.2 packager validated in an offline SCORM player; learner preview. |
| **M5** Optimisation & evaluation (D + all) | Wk 10–13 (9 Nov–4 Dec) | Benchmark harness; baseline vs prompt/template tuning, reranker, critique loop, AWQ/FP8 quantisation, **QLoRA adapter** on approved outputs; report tables (grounding, quality, visual usability, latency, VRAM). |
| **M6** Hardening & delivery | Wk 13–15 (30 Nov–18 Dec) | End-to-end sample course; tests (unit + API + one e2e); API docs; air-gapped deployment guide incl. model weights; evaluation report; final presentation + demo. |

## Workstream backlogs

### A — Ingestion & grounding
- [x] Docling parser with python-docx / pptx / pypdf fallbacks
- [x] Structure-aware chunker (heading breadcrumb, page range, tables whole)
- [x] Local embeddings (bge-m3) + pgvector HNSW
- [x] Project-scoped semantic search + inspector UI
- [ ] Hybrid retrieval (BM25 via `pg_trgm`/`tsvector` + vector, RRF fusion)
- [ ] Reranker (`bge-reranker-v2-m3`)
- [ ] Figure/diagram captions via Qwen-VL (stretch)
- [ ] Retrieval eval set + recall@k script in `packages/eval`

### B — Planning & pedagogy
- [ ] `generate_plan` handler: objectives → syllabus (prompts exist in `packages/prompts/plan`)
- [ ] Coverage map (which chunks each lesson draws on; % of each source used)
- [ ] Plan editor + approve/reject with comments (`reviews` table)
- [ ] Plan rubric (objective quality, sequencing, duration fit)

### C — Asset generation & export
- [ ] `generate_lesson_assets` handler: slides/notes/quiz/tutorial JSON with `[n]` markers
- [ ] Citation validator (marker ∈ retrieved set) + `citations` rows
- [ ] `critique_asset` handler wired to `core/generation/critique`
- [ ] Block editor (TipTap) with citation chips and critique panel
- [ ] `render_slides`: python-pptx themes → PPTX; LibreOffice → PDF/PNG
- [ ] `package_scorm`: HTML shell + imsmanifest (1.2) + API wrapper; validate in two players

### D — Video & model optimisation
- [ ] Script generation (`packages/prompts/slides/script.md`)
- [ ] TTS service voices vendored; per-segment WAV
- [ ] `render_video`: ffmpeg slides + audio + SRT
- [ ] vLLM tuning: prefix caching, speculative decoding, AWQ vs FP8
- [ ] QLoRA (Unsloth) on instructor-approved outputs + synthetic critiques; serve as LoRA module
- [ ] LLM-as-judge + human rubric sheets; latency/VRAM capture from vLLM metrics

## Post-MVP
1. SCORM 2004 + xAPI statements; learner analytics from the SCORM runtime
2. Multi-language output
3. Avatar / talking-head video; open image generation for slide visuals
4. Multi-reviewer approval workflows, audit log, LDAP/SSO
5. Model registry UI (swap models/adapters without redeploy)

## Risks
| Risk | Mitigation |
|---|---|
| H100 access delayed | cpu profile from day 1; all model calls behind one `LLM_BASE_URL` |
| 32B too slow for interactive editing | generation is async via jobs; consider 14B for interactive edits, 32B for batch; speculative decoding |
| Hallucinated citations | validator rejects unknown markers; critique agent checks claim support; quiz `source_span` must be verbatim |
| QLoRA shows no gain | it is one arm of the evaluation; a negative result is still a reportable finding |
| SCORM player quirks | target 1.2 only for MVP; test in two players |
