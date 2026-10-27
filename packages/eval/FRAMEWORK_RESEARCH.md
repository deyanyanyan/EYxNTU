# Course content quality framework research

Research date: 21 October 2026. Repository inspected: `24303e9`.

**Recommendation: build the course-content scorecard around LORI's educational-resource quality concepts, adapt concrete criteria from the openly published Anthropic/Learning Commons rubrics and OSCQR, and add an independent comprehensiveness map.** Learning Commons Evaluators is the strongest reusable educational evaluator library found, but covers specific qualities rather than a complete adult professional course. Among GitHub rubric assets, Anthropic/Learning Commons' `evals` directory is the most useful starting point for explicit, auditable lesson and assessment criteria.

These are complementary resources: an educational review instrument, reusable scoring criteria, and executable specialist evaluators. None of the reviewed projects provides a verified turnkey evaluator of an arbitrary generated LMS course's comprehensiveness and learning quality. The adaptation below is a proposed project design, not an established validated combination of these instruments.

**What the repository actually produces and currently measures**

The current pipeline turns uploaded documents into objectives, an approved syllabus, lessons with slides and speaker notes, quizzes, and PPTX/SCORM exports. Evaluation should ask whether that combined material adequately teaches the agreed subject to the intended learner.

- The brief captures audience, learning goals and duration in [Project](../../apps/api/app/models/project.py). Those fields are nullable and mutable; evaluation needs a frozen, agreed scope rather than silent defaults.
- [Plan generation](../../apps/api/app/core/generation/plan/service.py) creates its own objectives and Bloom-level labels from abbreviated, budgeted source excerpts. Its `coverage` field counts referenced offered excerpts. This is not a measure of how comprehensively the finished course teaches the required material.
- [Lesson generation](../../apps/api/app/core/generation/lesson/service.py) supplies slides, tables and notes. Review all of them together: notes can contain a necessary explanation that the slide abbreviates. Objective text reaches the generator, but its stored Bloom-level field is omitted from that text.
- [Quiz generation](../../apps/api/app/core/generation/quiz/service.py) stores answers, explanations, difficulty and source evidence, but no explicit objective ID. Quiz difficulty labels do not establish cognitive demand or assessment coverage.
- The [pedagogy prompt](../prompts/critique/pedagogy.md) already asks about objectives, examples/practice and learner clarity. Its broad score needs explicit criteria and an independently defined subject scope.
- The [recorded baseline](../../docs/HANDOFF.md) found topic bleed and repeated questions. Repeating an accurate fact in several lessons does not compensate for missing an essential procedure elsewhere.

The original DOCX proposal also calls for worked examples, tutorials, quizzes and consistency. The revised [project brief](../../docs/project-brief.html) places grounding, coherence and pedagogy at the center of the evaluation layer. Static content review can assess whether materials are designed to support learning; actual learning gains require learner performance evidence.

**Relevant open-source projects and educational frameworks**

| Candidate | What exists | Relevance to course-content quality | Recommendation |
|---|---|---|---|
| [LOEP / LORI](https://github.com/agordillo/LOEP) | Human-review platform implementing educational-resource instruments, including LORI v1.5. | Broad review of content quality, learning-goal alignment, feedback, motivation and presentation. | **Best broad conceptual reference.** Reuse the educational approach; the legacy Rails application is not an automatic LLM course assessor. |
| [Anthropic / Learning Commons instructional rubrics](https://github.com/anthropics/k12-teacher-skills/tree/main/evals) | Public CSV criteria, applicability rules and an example judge prompt for lessons and checks for understanding. | Prerequisites, instructional sequence, cognitive demand, task alignment, misconceptions, feedback and consistency across artifacts. | **Best GitHub rubric assets to adapt.** Replace K–12, classroom and curriculum-specific assumptions with adult professional-learning requirements. |
| [Learning Commons Evaluators](https://github.com/learning-commons-org/evaluators) | SDKs, executable evaluators, prompts, schemas and annotated validation data. | Text complexity, background knowledge demands, clarity, organization, graphics and certain assessment-alignment tasks. | **Best specialist evaluator library found.** Select relevant components; it does not establish whole-course completeness. |
| [OSCQR](https://oscqr.suny.edu/) | Openly licensed online-course design review rubric, guidance and action-planning process. | Alignment of outcomes, activities and assessments; authentic applications; self-checks and useful feedback. | **Strong openly reusable source of criteria.** Select content-relevant standards rather than applying all course-delivery requirements. It is not a GitHub scoring package. |
| [EduPlanner](https://github.com/Zc0812/Edu_Planner) | Research code with a lesson-plan evaluator/optimizer. | Advertises clarity, integrity, depth, practicality and learner pertinence. | Research reference. The released judge differs from the advertised dimensions; no public license was found. |
| [LecEval](https://github.com/JoylimJY/LecEval) | Research dataset/toolkit for slide-plus-explanation quality. | Relevance of explanation to slide, clarity, logical structure and engagement. | Potential specialist reference for slides/notes. Does not assess full-course coverage or objective–assessment alignment; verify scorer availability before adoption. |

**LORI and LOEP**

The [author-hosted LORI paper](https://www.sfu.ca/~jcnesbit/articles/LeacockNesbit2007.pdf) describes educational-resource review across content quality, learning-goal alignment, feedback/adaptation, motivation, presentation and technical/accessibility dimensions. Content quality includes appropriate detail and harmful omissions. Its scope is multimedia learning objects, not a sufficient evaluation of a whole educational program. This makes it a useful foundation for lessons and modules, with a separate course-wide completeness check.

LOEP contains an actual [LORI v1.5 implementation](https://github.com/agordillo/LOEP/blob/master/app/models/evaluations/lori.rb), using nine items, ratings from 1 to 5 and an N/A option. Its [README](https://github.com/agordillo/LOEP) describes review forms, metrics and LMS integration, but specifies Rails 3.2.22 and MySQL 5.5+. It collects and aggregates reviews; it does not supply an automatic pedagogical judge. The code is [AGPL-3.0-or-later](https://github.com/agordillo/LOEP/blob/master/LICENSE). That software license does not establish the original LORI instrument's reuse terms; no explicit open license for the original instrument was verified.

**Anthropic and Learning Commons rubrics**

The [rubric README](https://github.com/anthropics/k12-teacher-skills/blob/main/evals/README.md) provides independently judged criteria with explicit pass conditions, including conditional applicability. Their buckets are pedagogy, rigor, output and model scaffolding. For this project, assess content-facing criteria; conversational model-scaffolding criteria should not enter a course-content score. Some criteria require external Learning Commons curriculum knowledge, so replace those dependencies with the agreed source/competency map or mark them inapplicable.

The [shared lesson rubric](https://github.com/anthropics/k12-teacher-skills/blob/main/evals/k12-lesson-plan-creation/rubrics/shared.csv) includes concrete checks for prerequisite specificity, realistic sequencing and timing, reasoning tasks, consistent materials and contradictions. The [assessment rubric](https://github.com/anthropics/k12-teacher-skills/blob/main/evals/k12-check-for-understanding/rubrics/math.csv) offers useful patterns for checking objective scope, distractors, answer validity and informative feedback. Adapt these ideas rather than importing school-specific counts, standards and teacher-observation requirements. The repository is [Apache-2.0](https://github.com/anthropics/k12-teacher-skills/blob/main/LICENSE).

**Learning Commons executable evaluators**

The [Python SDK](https://github.com/learning-commons-org/evaluators/blob/main/sdks/python/README.md) can return structured judgments for particular educational qualities. Its [validation guidance](https://docs.learningcommons.org/evaluators/understanding-evaluators/core-concepts) ties performance to each evaluator's domain and default judge. Adult workplace content and a different local model need fresh calibration. Its critical-thinking evaluator assesses student writing; that is not evidence that a course teaches critical thinking.

The [current provider configuration](https://github.com/learning-commons-org/evaluators/blob/main/sdks/python/src/learning_commons_evaluators/config.py) uses external model providers, and a local OpenAI-compatible endpoint is not a documented drop-in option. Running notebooks on a laptop does not establish offline inference. Code is MIT, evaluator prompts/settings are CC BY 4.0, and some annotated datasets carry noncommercial terms; see the [license breakdown](https://github.com/learning-commons-org/evaluators/blob/main/LICENSE.md). Relevant initial components are clarity, organization, vocabulary and prerequisite-knowledge demands, rather than K–12 standards alignment.

**OSCQR and other references**

OSCQR is explicitly a formative course-design improvement framework. Its [official rubric](https://oscqr.suny.edu/wp-content/uploads/2024/08/OSCQR_version-4.0-Accessible-PDF_04.27.2022_YX.pdf) is CC BY 4.0. Useful content standards include [outcome/activity/assessment alignment](https://oscqr.suny.edu/standard9/), [appropriate higher-order thinking](https://oscqr.suny.edu/standard30/), [real-world application](https://oscqr.suny.edu/standard31/) and [self-assessment with feedback](https://oscqr.suny.edu/standard47/). Any numerical score, weights or pass threshold we add would be our adaptation. Teacher-contact, institutional-policy and campus-support criteria may be outside a self-paced generated course's scope.

Quality Matters' [Continuing and Professional Education rubric](https://www.qualitymatters.org/qa-resources/rubric-standards/cpe-rubric) is domain-relevant, but is a subscription/proprietary resource rather than an assumed open-source dependency. It is useful for comparison, not for copying into the project without the appropriate rights.

EduPlanner's released [judge prompt](https://github.com/Zc0812/Edu_Planner/blob/main/CIDPP.py) merges clarity and integrity and adds constraints, rather than cleanly implementing the five advertised dimensions. LecEval's [paper](https://arxiv.org/abs/2505.02078) is relevant to slides and explanatory notes, but its inspected [evaluator source](https://github.com/JoylimJY/LecEval/blob/main/src/evaluator.py) compares precomputed predictions with annotated ratings. The README's simple scorer example was not verified as a working implementation in the source tree. Neither should be adopted on README claims alone.

**Proposed content scorecard for EYxNTU**

These dimensions are a project-specific adaptation, to be refined with an instructional designer or subject expert.

| Dimension | What the reviewer must establish | Evidence returned |
|---|---|---|
| Accuracy | Facts, procedures, examples and quiz explanations agree with authoritative material. | Claim, cited passage, discrepancy and affected block. |
| Comprehensiveness | Required concepts, procedures, exceptions and prerequisites are taught to the agreed depth within scope. | Required content item → teaching blocks; explicit gaps and justified exclusions. |
| Learning alignment | Stated outcomes are appropriate and supported by explanations, activities and assessment. | Outcome → teaching → practice → assessment mapping and cognitive-demand rationale. |
| Instructional depth | Learners receive explanations and suitable worked examples, not only lists of assertions. | Explanations, examples, anticipated misunderstandings and missing steps. |
| Sequencing and coherence | Prerequisites precede dependent material; terminology agrees; repetition has a teaching purpose. | Dependency gaps, contradictions and unnecessary duplication. |
| Audience and application | Language, assumed knowledge, pacing and workplace scenarios fit the intended learner. | Assumptions, unexplained terms, authentic tasks and workload concerns. |
| Assessment and feedback | Questions are correct, aligned and informative; distractors reveal plausible errors; feedback explains the reasoning. | Item-level findings and uncovered outcomes. |

Readability, multimedia design and accessibility can be reviewed as an additional artifact dimension using rendered slides and the learner-facing course. They should not be inferred solely from text. Bloom levels classify the type of thinking demanded, not course quality: recall can be appropriate for a fact, while application requires evidence of using knowledge in a situation.

**Measuring comprehensiveness without circular scoring**

Before assessing the generated course, create an instructor-reviewed reference map from the complete uploaded source set and the agreed brief. List required concepts, procedures, critical exceptions, prerequisites and intended depth, with source passages. Record exclusions justified by learner needs and duration. This map must not be derived solely from the generated objective list or the passages selected for generation.

For each required item, record whether it is missing, merely mentioned, adequately explained, demonstrated in an example, practised and assessed, as applicable. These are separate observations rather than a universal ladder: an incidental fact does not need its own practice question. Calculate scoped teaching coverage from the required items judged adequately taught; report assessment coverage separately. Subject experts should set importance weights and define adequate treatment. Keep critical omissions visible regardless of an overall percentage.

The map should also flag missing authoritative information: a required skill absent from the sources is a source/scope gap for instructor review, not permission for the evaluator to invent a policy.

For example, the repository's [Northwind source fixture](../../scripts/fixtures/baseline_course.md) requires incident reporting within one hour, identifies reporting channels, and explains what to do afterward. A lesson that accurately states only the deadline and tests recall of that deadline can satisfy a narrow generated objective while failing the practical goal of knowing how to report an incident. The content review should identify missing channels and follow-up actions, and inspect an application scenario rather than count another deadline question. This is an illustrative evaluation case, not a new measurement of generated output.

**How this would enter the project**

Start with a versioned set of observable content criteria and the reference map. Evaluate the plan against the brief/map, each lesson and quiz against its intended outcomes, and the complete course for omissions and consistency. Extend the existing critique input to include the reference map and course-wide context. Add explicit assessment-to-objective links; the current quiz schema does not preserve them.

Return each criterion's applicable status, judgment, supporting course/source passages, omissions and revision suggestions. Keep criterion results visible instead of immediately averaging them into one pedagogy score. Use instructor judgments on representative courses to calibrate automated scoring and test whether real defects are detected. A course can be well designed on these criteria without yet having demonstrated learner gains.

The earlier comparison of Pydantic Evals, DeepEval and other software is retained separately as [implementation tooling research](IMPLEMENTATION_TOOLING_RESEARCH.md). Those tools can execute chosen checks; the content scorecard and its evidence define what course quality means.
