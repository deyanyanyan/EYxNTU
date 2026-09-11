# Sprint 1 deliverable for 14 to 25 September 2026

## Outcome

By Friday 25 September, all four students can start the same commit through Docker and demonstrate a grounded knowledge base from representative PDF, DOCX and PPTX sources. The team also delivers a repeatable baseline and an agreed interface for the upcoming course-planning workflow.

The project owner confirmed 14-25 September and the Docker setup / grounded-source demo. A-D are provisional owners, not assigned student names. Confirm the named owners and presentation arrangements at kickoff.

The committed demo is upload, parse, chunk, embed, search and inspect source evidence. A generated course-plan preview is stretch work after the foundation checks pass. Complete lesson authoring, video and SCORM remain later milestones. No training or fine-tuning is planned.

## Week 1 from 14 to 18 September

| Owner | Work | Evidence due Friday 18 September |
|---|---|---|
| A: documents and grounding | Select 3-5 public, reusable documents spanning PDF/DOCX/PPTX; record origin and permission; inspect headings, tables and page references | Corpus manifest, examples of extraction defects, 10 labelled retrieval questions |
| B: planning and review | Define the instructor brief, plan JSON schema, approval transitions and saved workflow state; agree interfaces with C | Versioned example brief/plan, schema validation, state diagram and API contract |
| C: authoring interface and export | Reproduce the workbench locally; check upload/search/error states; define lesson and citation payloads | UI smoke checklist, actionable bug fixes, sample lesson/citation JSON agreed with A/B |
| D: runtime and evaluation | Coordinate Docker onboarding; record hardware and startup results; verify local structured output and investigate tool calling | Four-machine setup matrix, first latency/RAM measurements, model/serving configuration, tool-call result |

Everyone performs a fresh-clone startup. Review each other's PRs. Pair B with D for local model compatibility; pair A with C for citation display. Friday integration must run from main without uncommitted fixes.

## Week 2 from 21 to 25 September

| Owner | Work | Evidence due Friday 25 September |
|---|---|---|
| A | Expand the retrieval set to 30 labelled questions; fix the highest-impact parsing/citation defects; define source versioning before generated assets depend on chunks | Recall@5 baseline, 5 reviewed evidence traces, table/page edge cases and limitations |
| B | Implement the smallest planning workflow if readiness permits: validated objectives/syllabus from retrieved evidence; keep approval/resume design explicit | Required: tested contract and workflow spike. Stretch: persisted draft plan with a minimal review screen |
| C | Close UI failures affecting the source demo; verify job progress and errors; add access-control regression coverage with A/D | Reliable source-inspection demo, bug checklist and project/job access tests |
| D | Automate baseline recording, run the offline rehearsal, compare a single-pass model call with one fixed revision; test persistence across restart | Reproducible command/config, raw results, offline report, startup/restart evidence |

Choose one primary local model/configuration for the baseline. Keep the source set, prompts, retrieval settings and rubric fixed when comparing approaches. Do not tune on the entire labelled evaluation set without reporting that limitation.

## Checkpoints

| Date | Decision or demonstration |
|---|---|
| Mon 14 Sep | Name owners; confirm supervisor deliverable; create issues; agree corpus and primary laptop configuration |
| Wed 16 Sep | Every teammate has attempted setup; triage blockers; approve source/plan/asset contracts |
| Fri 18 Sep | Main-branch demo: login, project, one uploaded source, completed job, retrieved passage and provenance |
| Mon 21 Sep | Freeze baseline corpus/questions; prioritize defects that block the final demo |
| Wed 23 Sep | Rehearse complete demo; decide whether the plan preview is ready or remains stretch |
| Fri 25 Sep | Final sprint demo, evidence bundle and supervisor update; agree the next sprint |

## Acceptance criteria

- [ ] Four teammates record OS/architecture, Docker version, available RAM and the same Git commit.
- [ ] Each can clone, generate private configuration, build, sign in and pass the foundation smoke check using only Git and Docker.
- [ ] TXT, PDF, DOCX and PPTX fixtures pass the model-dependent smoke check; parser fallback is explicitly reported.
- [ ] Three to five representative source documents are ingested; extracted text, headings, tables and page references are manually reviewed.
- [ ] A committed benchmark command reads 30 labelled questions and writes recall@5 plus per-query retrieval time. Record the initial score even if poor; agree a quality threshold after the first baseline.
- [ ] Five demonstrated answers link to the correct source passage. Invalid or mismatched citation references are rejected in tests.
- [ ] Re-ingestion cannot silently erase citations on retained assets; implement a guard or source-version strategy before authoring integration.
- [ ] Job read/stream/cancel access follows the agreed project permissions, with negative tests.
- [ ] Restarting the stack preserves users, projects and sources. The worker executes a new ingestion job after restart.
- [ ] Offline rehearsal passes or has a specific, reproducible blocker report; no unqualified air-gap claim.
- [ ] The brief/plan/lesson/citation contracts are committed, with review and resume semantics agreed.
- [ ] PR checks pass and the demo works from main without local patches.

## Delivery bundle

Commit `docs/sprint-01/report.md` and small, non-sensitive evidence under `docs/sprint-01/` at sprint close. Include:

1. Commit SHA, owner list and four-machine setup matrix.
2. Corpus manifest and the 30-question evaluation set (public data only).
3. Raw benchmark CSV/JSON, run configuration and a short explanation of failures.
4. Five source-trace examples and the offline/restart results.
5. API/schema examples for the next workflow stage.
6. A 5-8 minute demo script or recording link and the prioritized next-sprint backlog.

Keep model weights and generated course packages out of Git; share those separately if needed.

## Suggested GitHub issues

| ID | Title | Owner | Dependency |
|---|---|---|---|
| S1-01 | Verify fresh-clone Docker setup on all four machines | D + all | None |
| S1-02 | Commit corpus manifest and 30 retrieval questions | A | None |
| S1-03 | Establish plan, lesson and citation contracts | B + C | A's source metadata example |
| S1-04 | Repair citation validation and define re-ingestion safety | A | S1-03 |
| S1-05 | Enforce project access for job endpoints | C | Agreed permission policy |
| S1-06 | Add baseline runner and record local model compatibility | D | S1-01, S1-02 |
| S1-07 | Rehearse upload, source inspection and restart | C + A | S1-01, S1-02 |
| S1-08 | Verify offline operation and assemble sprint evidence | D + all | S1-04 to S1-07 |
| S1-09 | Optional draft-plan workflow spike | B | S1-03, S1-06 |

These are issue-ready proposals; they have not been created on GitHub.
