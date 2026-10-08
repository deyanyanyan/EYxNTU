"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, type EvaluationBatch, type EvaluationBatchDetail, type EvaluationCourse, type EvaluationDimension, type EvaluationJob, type EvaluationJudgeConfig, type EvaluationRun, type EvaluationScore } from "@/lib/api";

const DIMENSIONS = ["grounding", "coherence", "pedagogy"] as const;

function displayDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function metric(value: unknown) {
  return typeof value === "number" ? value.toLocaleString() : "—";
}

function scoreText(value: number | null | undefined) {
  return typeof value === "number" ? value.toFixed(2) : "—";
}

function DimensionMetric({ name, mean, spread }: { name: string; mean: number | null; spread: number | null }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{name}</p>
        <p className="mt-2 text-2xl font-semibold tabular-nums">{scoreText(mean)}<span className="ml-1 text-sm font-normal text-muted-foreground">/ 5</span></p>
        <p className="mt-1 text-xs text-muted-foreground">Lesson SD {scoreText(spread)}</p>
      </CardContent>
    </Card>
  );
}

function DimensionFeedback({ name, value }: { name: string; value?: EvaluationDimension }) {
  if (!value) return null;
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide">{name}</h4>
        <Badge tone="accent">{value.score}/5</Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm text-muted-foreground">{value.feedback || "No feedback returned."}</p>
      {value.issues.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-muted-foreground">
          {value.issues.map((issue, index) => <li key={`${name}-${index}`}>{issue}</li>)}
        </ul>
      )}
    </div>
  );
}

function LessonResult({ row }: { row: EvaluationScore }) {
  const counts = row.checks.counts ?? {};
  const dimensions = row.judge.dimensions ?? {};
  const countLabels = [
    ["bullets_uncited", "Uncited bullets"],
    ["citations_invalid", "Invalid citations"],
    ["bullets_low_lexical_overlap", "Low evidence overlap"],
    ["slides_over_density_limit", "Dense slides"],
    ["quiz_span_not_found", "Quiz spans not found"],
  ] as const;

  return (
    <details className="group rounded-lg border bg-surface">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 p-3 [&::-webkit-details-marker]:hidden">
        <span className="min-w-48 flex-1">
          <span className="block text-sm font-medium">{row.title || "Untitled lesson"}</span>
          <span className="font-mono text-[11px] text-muted-foreground">{row.lesson_id || "lesson id unavailable"}</span>
        </span>
        <div className="flex flex-wrap items-center gap-2 text-xs tabular-nums">
          {DIMENSIONS.map((name) => <span key={name} className="rounded border px-2 py-1"><span className="text-muted-foreground">{name.slice(0, 3)} </span>{scoreText(dimensions[name]?.score)}</span>)}
        </div>
        <Badge tone={statusTone(row.judge.status)}>{row.judge.status.replaceAll("_", " ")}</Badge>
      </summary>
      <div className="space-y-4 border-t p-4">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {countLabels.map(([key, label]) => (
            <div key={key} className="rounded-md bg-muted/40 p-2">
              <p className="text-[11px] text-muted-foreground">{label}</p>
              <p className="mt-1 text-sm font-semibold tabular-nums">{metric(counts[key])}</p>
            </div>
          ))}
        </div>

        {row.judge.same_model_endpoint_as_generator && (
          <p className="rounded-md border border-warning/40 bg-warning/10 p-2 text-xs text-warning">Judge and generator use the same model endpoint; treat these scores as self-judged.</p>
        )}
        {Object.keys(row.judge.dimension_errors).length > 0 && (
          <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs">
            <p className="font-medium">Judge dimension errors</p>
            {Object.entries(row.judge.dimension_errors).map(([name, error]) => <p key={name} className="mt-1 text-muted-foreground">{name}: {error}</p>)}
          </div>
        )}
        {Object.keys(dimensions).length > 0 ? (
          <div className="grid gap-3 lg:grid-cols-3">
            {DIMENSIONS.map((name) => <DimensionFeedback key={name} name={name} value={dimensions[name]} />)}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No judge scores were requested for this batch. Deterministic checks are still available.</p>
        )}

        {row.checks.findings.length > 0 ? (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Diagnostic findings · {row.checks.findings.length}</h4>
            <ul className="space-y-2">
              {row.checks.findings.map((finding, index) => (
                <li key={`${String(finding.type)}-${index}`} className="rounded-md border p-3 text-xs">
                  <p className="font-medium">{String(finding.type ?? "finding").replaceAll("_", " ")}</p>
                  {typeof finding.slide_id === "string" && <p className="mt-1 text-muted-foreground">Slide {finding.slide_id}</p>}
                  {typeof finding.question === "number" && <p className="mt-1 text-muted-foreground">Question {finding.question}</p>}
                  {typeof finding.ratio === "number" && <p className="mt-1 text-muted-foreground">Lexical overlap: {(finding.ratio * 100).toFixed(1)}%</p>}
                  {typeof finding.text === "string" && <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{finding.text}</p>}
                  {Array.isArray(finding.references) && finding.references.length > 0 && <p className="mt-2 font-mono text-[11px] text-muted-foreground">Evidence refs: {finding.references.map((ref) => typeof ref === "object" && ref !== null && "chunk_id" in ref ? String(ref.chunk_id) : "").filter(Boolean).join(", ")}</p>}
                  {typeof finding.chunk_id === "string" && <p className="mt-2 font-mono text-[11px] text-muted-foreground">Evidence chunk: {finding.chunk_id}</p>}
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No deterministic findings were recorded for this lesson.</p>
        )}
      </div>
    </details>
  );
}

function RunResults({ course, scores }: { course: EvaluationCourse; scores: EvaluationScore[] }) {
  const totals = course.check_totals ?? {};
  const overlap = course.course_overlap;
  const means = course.judge_means;
  const spreads = course.judge_lesson_score_stddev;
  const hasJudgeScores = DIMENSIONS.some((name) => means[name] !== null);
  const runScores = scores.filter((score) => score.run_id === course.run_id);
  const metrics = [
    ["Uncited bullets", totals.bullets_uncited],
    ["Invalid citations", totals.citations_invalid],
    ["Missing quiz spans", totals.quiz_span_not_found],
    ["Accepted questions", totals.quiz_accepted],
    ["Rejected questions", totals.quiz_rejected],
    ["Dense slides", totals.slides_over_density_limit],
  ] as const;

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">Generator run <span className="font-mono text-xs text-muted-foreground">{course.run_id || "unknown"}</span></h2>
          <p className="mt-1 text-xs text-muted-foreground">{String(course.generator.arm ?? "unnamed arm")} · {String(course.generator.model ?? "model not recorded")} · {course.lessons_scored} lessons</p>
        </div>
        <p className="text-xs text-muted-foreground">Generation: {metric(course.generation.llm_calls)} calls · {metric(course.generation.seconds)} sec</p>
      </div>

      {hasJudgeScores ? (
        <div className="grid gap-3 sm:grid-cols-3">
          {DIMENSIONS.map((name) => <DimensionMetric key={name} name={name} mean={means[name]} spread={spreads[name]} />)}
        </div>
      ) : (
        <p className="rounded-lg border bg-surface p-4 text-sm text-muted-foreground">This batch contains deterministic checks only; no AI judge scores were requested.</p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {metrics.map(([label, value]) => (
          <div key={label} className="rounded-lg border bg-surface p-3">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-1 text-lg font-semibold tabular-nums">{metric(value)}</p>
          </div>
        ))}
        <div className="rounded-lg border bg-surface p-3">
          <p className="text-xs text-muted-foreground">Shared cited chunks</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{metric(overlap.shared_cited_chunks)}</p>
        </div>
        <div className="rounded-lg border bg-surface p-3">
          <p className="text-xs text-muted-foreground">Near-duplicate bullet pairs</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{metric(overlap.near_duplicate_bullet_pairs)}</p>
        </div>
      </div>

      {overlap.shared_chunk_examples.length > 0 && (
        <details className="rounded-lg border bg-surface p-3">
          <summary className="cursor-pointer text-xs font-medium">Shared evidence examples ({overlap.shared_chunk_examples.length})</summary>
          <ul className="mt-3 space-y-2 text-xs">
            {overlap.shared_chunk_examples.map((example) => <li key={example.chunk_id} className="font-mono text-muted-foreground">{example.chunk_id} <span className="font-sans">· {example.lesson_ids.join(", ")}</span></li>)}
          </ul>
        </details>
      )}

      <div className="space-y-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Lesson results</h3>
        {runScores.length > 0 ? runScores.map((row) => <LessonResult key={`${row.run_id}-${row.lesson_id}`} row={row} />) : <p className="rounded-lg border p-4 text-sm text-muted-foreground">This run has no per-lesson score rows.</p>}
      </div>
    </section>
  );
}

export default function EvaluationPage() {
  const [batches, setBatches] = useState<EvaluationBatch[]>([]);
  const [runs, setRuns] = useState<EvaluationRun[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvaluationBatchDetail | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [listLoading, setListLoading] = useState(true);
  const [runsLoading, setRunsLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [judgeConfig, setJudgeConfig] = useState<EvaluationJudgeConfig | null>(null);
  const [evaluationJob, setEvaluationJob] = useState<EvaluationJob | null>(null);
  const [useJudge, setUseJudge] = useState(false);
  const [evaluatingRunId, setEvaluatingRunId] = useState<string | null>(null);
  const evaluationJobId = evaluationJob?.job_id;
  const evaluationJobStatus = evaluationJob?.status;

  useEffect(() => {
    api.get<EvaluationJudgeConfig>("/evaluation/judge-config")
      .then((config) => { setJudgeConfig(config); setUseJudge(config.judge_configured); })
      .catch((cause) => setActionError(cause instanceof Error ? cause.message : "Could not load judge configuration."));
    api.get<{ job: EvaluationJob | null }>("/evaluation/jobs/status")
      .then((result) => setEvaluationJob(result.job))
      .catch((cause) => setActionError(cause instanceof Error ? cause.message : "Could not load evaluation status."));
  }, []);

  useEffect(() => {
    if (!evaluationJobId || (evaluationJobStatus !== "queued" && evaluationJobStatus !== "running")) return;
    const timer = window.setInterval(() => {
      api.get<{ job: EvaluationJob | null }>("/evaluation/jobs/status")
        .then((result) => { if (result.job) setEvaluationJob(result.job); })
        .catch((cause) => setActionError(cause instanceof Error ? cause.message : "Could not refresh evaluation status."));
    }, 3000);
    return () => window.clearInterval(timer);
  }, [evaluationJobId, evaluationJobStatus]);

  useEffect(() => {
    if (evaluationJob?.status === "completed" && evaluationJob.batch_id) {
      setSelectedId(evaluationJob.batch_id);
      setRefreshKey((key) => key + 1);
    }
  }, [evaluationJob?.status, evaluationJob?.batch_id]);

  async function evaluateRun(run: EvaluationRun) {
    setEvaluatingRunId(run.run_id);
    setActionError(null);
    try {
      const judgeAllowed = ["public", "fictional"].includes(run.data_classification);
      const job = await api.post<EvaluationJob>(`/evaluation/runs/${encodeURIComponent(run.run_id)}/evaluate`, { use_judge: useJudge && judgeAllowed });
      setEvaluationJob(job);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : "Could not evaluate this saved run.");
    } finally {
      setEvaluatingRunId(null);
    }
  }

  useEffect(() => {
    let current = true;
    setRunsLoading(true);
    api.get<EvaluationRun[]>("/evaluation/runs")
      .then((items) => { if (current) { setRuns(items); setRunsError(null); } })
      .catch((cause) => { if (current) setRunsError(cause instanceof Error ? cause.message : "Could not load saved generation runs."); })
      .finally(() => { if (current) setRunsLoading(false); });
    return () => { current = false; };
  }, [refreshKey]);

  useEffect(() => {
    let current = true;
    setListLoading(true);
    api.get<EvaluationBatch[]>("/evaluation/batches")
      .then((items) => {
        if (!current) return;
        setBatches(items);
        setSelectedId((selected) => selected && items.some((item) => item.batch_id === selected) ? selected : items[0]?.batch_id ?? null);
        setError(null);
      })
      .catch((cause) => {
        if (current) setError(cause instanceof Error ? cause.message : "Could not load evaluation batches.");
      })
      .finally(() => { if (current) setListLoading(false); });
    return () => { current = false; };
  }, [refreshKey]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    let current = true;
    setDetailLoading(true);
    setDetail(null);
    api.get<EvaluationBatchDetail>(`/evaluation/batches/${encodeURIComponent(selectedId)}`)
      .then((value) => { if (current) { setDetail(value); setError(null); } })
      .catch((cause) => { if (current) setError(cause instanceof Error ? cause.message : "Could not load this evaluation batch."); })
      .finally(() => { if (current) setDetailLoading(false); });
    return () => { current = false; };
  }, [selectedId]);

  const selected = batches.find((batch) => batch.batch_id === selectedId) ?? null;
  const evaluationRunning = evaluationJob !== null && ["queued", "running"].includes(evaluationJob.status);

  return (
    <Shell title="Evaluation benchmark" actions={<Button size="sm" variant="outline" disabled={listLoading || runsLoading} onClick={() => setRefreshKey((key) => key + 1)}><RefreshCw className={listLoading || runsLoading ? "animate-spin" : ""} /> Refresh</Button>}>
      <div className="space-y-5 p-5 lg:p-6">
        <div className="rounded-lg border border-accent/30 bg-accent-soft/40 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-lg font-semibold">Offline batch evaluation</h1>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">Review saved model runs, dimension scores, and diagnostic findings. Scores are exploratory and not SME-calibrated; evaluation never approves, revises, or blocks generated content.</p>
            </div>
            <Badge tone="neutral">{batches.length} {batches.length === 1 ? "batch" : "batches"}</Badge>
          </div>
        </div>

        <Card>
          <CardHeader className="border-b">
            <CardTitle>Saved generation runs</CardTitle>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">Evaluate a captured run that already exists. Starting an evaluation does not generate or change any content.</p>
          </CardHeader>
          <CardContent className="space-y-4 pt-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <label className={`inline-flex items-center gap-2 text-sm ${judgeConfig?.judge_configured ? "cursor-pointer" : "cursor-not-allowed text-muted-foreground"}`}>
                <input type="checkbox" checked={useJudge} disabled={!judgeConfig?.judge_configured || evaluationRunning || evaluatingRunId !== null} onChange={(event) => setUseJudge(event.target.checked)} />
                Also score with Gemini
              </label>
              {judgeConfig?.judge_configured ? <Badge tone="success">Gemini configured · {judgeConfig.judge_model}</Badge> : <Badge tone="neutral">Deterministic checks only</Badge>}
            </div>
            {!judgeConfig?.judge_configured && (
              <div className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
                <p>Gemini judging is optional. Without it, the evaluator still checks citations, slide density, quiz outcomes, and repeated evidence. To enable Gemini rubric scores, add these values to the root <code>.env</code> and recreate the API container. The key stays on this machine.</p>
                <pre className="mt-2 overflow-x-auto rounded bg-muted/50 p-2">{`JUDGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/\nJUDGE_API_KEY=<your Gemini API key>\nJUDGE_MODEL=<Gemini model id>`}</pre>
              </div>
            )}
            {useJudge && <p className="text-xs text-muted-foreground">Gemini is used only for saved runs marked public or fictional.</p>}
            {runsError && <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{runsError}</p>}
            {actionError && <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{actionError}</p>}
            {evaluationJob && (
              <div className={`flex flex-wrap items-center gap-2 rounded-md border p-3 text-sm ${evaluationJob.status === "failed" ? "border-destructive/40 bg-destructive/5" : "bg-muted/20"}`} aria-live="polite">
                <Badge tone={statusTone(evaluationJob.status)}>{evaluationJob.status}</Badge>
                <span>{evaluationJob.message}</span>
                {evaluationJob.status === "completed" && evaluationJob.batch_id && <span className="font-mono text-xs text-muted-foreground">Batch {evaluationJob.batch_id}</span>}
              </div>
            )}
            {runsLoading ? <p className="text-sm text-muted-foreground">Loading saved runs…</p> : runs.length === 0 ? (
              <p className="rounded-md border p-4 text-sm text-muted-foreground">No captured runs are available to score yet. Evaluation will not start generation; it needs a saved run bundle first.</p>
            ) : (
              <div className="divide-y rounded-lg border">
                {runs.map((run) => {
                  const judgeAllowed = ["public", "fictional"].includes(run.data_classification);
                  const evaluating = evaluatingRunId === run.run_id;
                  return (
                    <div key={run.run_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate font-mono text-xs font-medium">{run.run_id}</p>
                        <p className="mt-1 text-xs text-muted-foreground">{String(run.generator.arm ?? "unnamed arm")} · {String(run.generator.model ?? "model not recorded")} · {run.lesson_count} lessons · {displayDate(run.captured_at)}</p>
                        <p className="mt-1 text-xs text-muted-foreground">Source: {run.source_names.join(", ") || "not recorded"} · {run.data_classification}</p>
                        {useJudge && !judgeAllowed && <p className="mt-1 text-xs text-warning">Gemini is unavailable for this run; the button will use deterministic checks only.</p>}
                      </div>
                      <Button size="sm" onClick={() => evaluateRun(run)} disabled={evaluationRunning || evaluatingRunId !== null}>
                        {evaluating ? "Evaluating…" : useJudge && judgeAllowed ? "Evaluate with Gemini" : "Evaluate"}
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {error && <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}

        {batches.length === 0 && !listLoading ? (
          <Card>
            <CardHeader><CardTitle>No evaluation batches yet</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>Choose a saved run above and click <strong>Evaluate</strong>. Reports are stored in <code>data/artifacts/eval/batches/</code> on the host.</p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid min-w-0 gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
            <Card className="h-fit overflow-hidden">
              <CardHeader className="border-b"><CardTitle>Saved batches</CardTitle></CardHeader>
              <div className="divide-y">
                {listLoading && batches.length === 0 ? <p className="p-4 text-sm text-muted-foreground">Loading batches…</p> : batches.map((batch) => (
                  <button key={batch.batch_id} type="button" onClick={() => setSelectedId(batch.batch_id)} aria-pressed={selectedId === batch.batch_id} className={`block w-full p-3 text-left transition-colors hover:bg-muted/50 ${selectedId === batch.batch_id ? "bg-accent-soft/60" : ""}`}>
                    <span className="flex items-center justify-between gap-2"><span className="truncate font-mono text-xs font-medium">{batch.batch_id}</span><Badge tone={batch.judge ? "accent" : "neutral"}>{batch.judge ? "judge" : "checks"}</Badge></span>
                    <span className="mt-1 block text-xs text-muted-foreground">{displayDate(batch.created_at)}</span>
                    <span className="mt-1 block text-[11px] text-muted-foreground">{batch.input_runs.length} {batch.input_runs.length === 1 ? "run" : "runs"}{batch.judge?.model ? ` · ${batch.judge.model}` : " · deterministic only"}</span>
                  </button>
                ))}
              </div>
            </Card>

            <div className="min-w-0 space-y-5">
              {detailLoading && <p className="text-sm text-muted-foreground">Loading batch report…</p>}
              {detail && selected && (
                <>
                  <Card>
                    <CardHeader className="flex-row items-start justify-between gap-3 border-b">
                      <div><CardTitle>Batch {detail.manifest.batch_id}</CardTitle><p className="mt-1 text-xs text-muted-foreground">Created {displayDate(detail.manifest.created_at)}</p></div>
                      <Badge tone={detail.manifest.judge ? "accent" : "neutral"}>{detail.manifest.judge ? `Judge · ${detail.manifest.judge.model}` : "Deterministic only"}</Badge>
                    </CardHeader>
                    <CardContent className="grid gap-3 pt-4 sm:grid-cols-2">
                      <div><p className="text-xs text-muted-foreground">Judge prompt hash</p><p className="mt-1 break-all font-mono text-xs">{detail.manifest.judge?.prompt_sha256 ?? "Not used"}</p></div>
                      <div><p className="text-xs text-muted-foreground">Input runs</p><div className="mt-1 flex flex-wrap gap-2">{detail.manifest.input_runs.map((run, index) => <Badge key={`${run.run_id}-${index}`} tone="neutral">{run.run_id ?? "run id unavailable"} · {run.data_classification ?? "unclassified"}</Badge>)}</div></div>
                    </CardContent>
                  </Card>

                  {detail.courses.map((course, index) => <RunResults key={`${course.run_id}-${index}`} course={course} scores={detail.scores} />)}

                  {detail.summary_markdown && (
                    <details className="rounded-lg border bg-surface p-3">
                      <summary className="cursor-pointer text-xs font-medium">Open generated Markdown scorecard</summary>
                      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-md bg-muted/40 p-3 text-xs">{detail.summary_markdown}</pre>
                    </details>
                  )}
                </>
              )}
              {!detail && !detailLoading && selected && <p className="text-sm text-muted-foreground">Select a saved batch to see its report.</p>}
            </div>
          </div>
        )}
      </div>
    </Shell>
  );
}
