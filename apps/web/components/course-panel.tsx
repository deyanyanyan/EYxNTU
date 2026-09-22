"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, CheckCircle2, Download, Play, RotateCw } from "lucide-react";
import type { Stage } from "@/components/pipeline-stepper";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api, ApiError, downloadFile, watchJob, type CourseExport, type CoursePlan, type Job, type LessonDetail, type Reference } from "@/lib/api";

/** What the inspector pane shows: a search hit or a cited source passage. */
export type Inspected = {
  chunk_id: string; source_name: string; text: string; heading_path: string | null;
  page_start: number | null; page_end: number | null; similarity: number | null; quote?: string | null;
};

type Step = "plan" | "lessons" | "export";
const JOB_KIND: Record<Step, string> = { plan: "generate_plan", lessons: "generate_lesson_assets", export: "package_scorm" };
const ENDPOINT: Record<Step, string> = { plan: "plan", lessons: "lessons/generate", export: "export" };
const MARKER = /(\[\d{1,3}\])/g;
// Separate, non-global pattern for testing a single part: a /g regex's .test() keeps state between calls.
const IS_MARKER = /^\[\d{1,3}\]$/;

const isActive = (j?: Job) => j?.status === "pending" || j?.status === "running";
const num = (r: Record<string, unknown> | null, k: string) => Number(r?.[k] ?? 0);
const duration = (s: number) => (s >= 90 ? `${(s / 60).toFixed(1)} min` : `${Math.round(s)} s`);
const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

function summary(step: Step, r: Record<string, unknown> | null): string[] {
  if (!r) return [];
  const cost = `${num(r, "llm_calls")} model calls · ${duration(num(r, "seconds"))}`;
  if (step === "plan") {
    const lines = [`${num(r, "lessons")} lessons in ${num(r, "modules")} modules from ${num(r, "evidence_chunks")} source excerpts · ${cost}`];
    if (num(r, "lessons_without_sources")) lines.push(`${num(r, "lessons_without_sources")} lessons have no linked source passage`);
    if (num(r, "invalid_reference_numbers")) lines.push(`${num(r, "invalid_reference_numbers")} references pointed at passages that were not provided`);
    return lines;
  }
  if (step === "lessons") {
    const lines = [
      `${num(r, "decks")} decks · ${num(r, "slides")} slides · ${num(r, "questions_accepted")} quiz questions (${num(r, "questions_rejected")} rejected by validation) · ${cost}`,
      `${num(r, "bullets_without_citation")} of ${num(r, "bullets_checked")} content bullets carry no citation · ${num(r, "invalid_citation_numbers")} citations point nowhere`,
    ];
    const errors = (r.errors as string[] | undefined) ?? [];
    if (errors.length) lines.push(`${errors.length} step${errors.length > 1 ? "s" : ""} failed — ${errors[0]}`);
    return lines;
  }
  return [`${num(r, "lessons")} lessons · ${num(r, "questions")} quiz questions packaged`];
}

function JobStatus({ step, job }: { step: Step; job?: Job }) {
  if (!job) return null;
  if (isActive(job)) {
    return (
      <div className="space-y-1">
        <Progress value={job.progress_total ? (job.progress_current / job.progress_total) * 100 : 4} />
        <p className="text-xs text-muted-foreground">{job.message ?? "Queued — waiting for the worker"}</p>
      </div>
    );
  }
  if (job.status === "failed") return <p className="text-xs text-destructive">Failed: {(job.error_message ?? job.error_type ?? "unknown error").split("\n")[0]}</p>;
  if (job.status === "cancelled") return <p className="text-xs text-muted-foreground">Cancelled.</p>;
  return (
    <ul className="space-y-0.5 font-mono text-[11px] text-muted-foreground">
      {summary(step, job.result).map((line) => <li key={line}>{line}</li>)}
    </ul>
  );
}

function StepCard({ n, title, hint, action, children }: { n: number; title: string; hint: string; action: React.ReactNode; children?: React.ReactNode }) {
  return (
    <section className="space-y-3 rounded-md border bg-surface p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-sm font-semibold"><span className="mr-2 font-mono text-xs text-muted-foreground">{n}</span>{title}</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>
        </div>
        <div className="flex shrink-0 gap-2">{action}</div>
      </div>
      {children}
    </section>
  );
}

function Cited({ text, onCite }: { text: string; onCite: (n: string) => void }) {
  return (
    <>
      {text.split(MARKER).map((part, i) =>
        IS_MARKER.test(part) ? (
          <button key={i} className="citation-chip mx-0.5 align-baseline hover:border-accent" onClick={() => onCite(part.slice(1, -1))}>{part.slice(1, -1)}</button>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

function LessonView({ detail, onBack, onInspect }: { detail: LessonDetail; onBack: () => void; onInspect: (i: Inspected) => void }) {
  const deck = detail.slides?.content;
  const quiz = detail.quiz?.content;
  const inspect = (ref: Reference | undefined, quote?: string | null) => {
    if (!ref) return;
    const cited = detail.citations.find((c) => c.chunk_id === ref.chunk_id);
    onInspect({ ...ref, text: cited?.text ?? "This passage is no longer in the knowledge base.", similarity: null, quote });
  };
  const stats = deck?.citation_stats;

  return (
    <div className="space-y-5">
      <button onClick={onBack} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="size-3.5" /> Course</button>
      <div>
        <p className="text-xs text-muted-foreground">{detail.module_title}{detail.lesson.estimated_minutes ? ` · ${detail.lesson.estimated_minutes} min` : ""}</p>
        <h2 className="text-base font-semibold">{detail.lesson.title}</h2>
        {stats && (
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {stats.slides} slides · {stats.citation_markers} citations · {stats.bullets_without_citation}/{stats.bullets_checked} bullets uncited
            {stats.invalid_citation_numbers.length ? ` · ${stats.invalid_citation_numbers.length} broken` : ""}
          </p>
        )}
      </div>

      {!deck && <p className="text-sm text-muted-foreground">No slides were generated for this lesson. Check the lesson run&apos;s errors.</p>}
      {deck?.slides.map((s) => (
        <article key={s.id} className="rounded-md border bg-surface p-4 text-sm">
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="font-semibold">{s.title}</h3>
            <span className="font-mono text-[10px] text-muted-foreground">{s.id} · {s.layout}</span>
          </div>
          {s.table && s.table.length > 0 && (
            <div className="mb-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <tbody>
                  {s.table.map((row, r) => (
                    <tr key={r} className={r === 0 ? "bg-muted/60 font-medium" : ""}>
                      {row.map((cell, c) => <td key={c} className="border px-2 py-1"><Cited text={cell} onCite={(n) => inspect(deck.references[n])} /></td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {s.bullets.length > 0 && (
            <ul className="list-disc space-y-1 pl-5">
              {s.bullets.map((b, i) => <li key={i}><Cited text={b} onCite={(n) => inspect(deck.references[n])} /></li>)}
            </ul>
          )}
          {s.notes && <p className="mt-3 border-t pt-2 text-xs leading-relaxed text-muted-foreground"><Cited text={s.notes} onCite={(n) => inspect(deck.references[n])} /></p>}
        </article>
      ))}

      {quiz && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold">Quiz <span className="font-normal text-muted-foreground">· {quiz.questions.length} kept, {quiz.rejected.length} rejected by validation</span></h3>
          {quiz.questions.map((q, i) => (
            <article key={i} className="rounded-md border bg-surface p-4 text-sm">
              <p className="font-medium">{i + 1}. {q.stem}</p>
              <ol className="mt-2 space-y-1">
                {q.options.map((opt, j) => (
                  <li key={j} className={j === q.answer_index ? "flex items-center gap-1.5 text-success" : "pl-5 text-muted-foreground"}>
                    {j === q.answer_index && <CheckCircle2 className="size-3.5" />}{opt}
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-xs text-muted-foreground">{q.explanation.replace(MARKER, "").trim()}</p>
              {q.chunk_id && (
                <button
                  className="mt-2 text-left text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => inspect(Object.values(quiz.references).find((r) => r.chunk_id === q.chunk_id), q.source_span)}
                >
                  <span className="citation-chip mr-1">source</span>“{q.source_span}”
                </button>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}

export function CoursePanel({ projectId, ready, onStage, onInspect }: {
  projectId: string; ready: boolean;
  onStage: (s: { current: Stage; done: Stage[] }) => void;
  onInspect: (i: Inspected) => void;
}) {
  const [plan, setPlan] = useState<CoursePlan | null | undefined>(undefined);
  const [exports, setExports] = useState<CourseExport[]>([]);
  const [jobs, setJobs] = useState<Partial<Record<Step, Job>>>({});
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<LessonDetail | null>(null);
  const openLesson = useRef<string | null>(null);
  const stops = useRef<Array<() => void>>([]);

  const loadPlan = useCallback(async () => {
    try {
      setPlan(await api.get<CoursePlan>(`/projects/${projectId}/plan`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPlan(null);
      else setError(messageOf(e));
    }
  }, [projectId]);

  const loadExports = useCallback(() => api.get<CourseExport[]>(`/projects/${projectId}/exports`).then(setExports).catch(() => {}), [projectId]);

  const showLesson = useCallback(
    async (lessonId: string) => {
      openLesson.current = lessonId;
      try {
        setDetail(await api.get<LessonDetail>(`/projects/${projectId}/lessons/${lessonId}`));
      } catch (e) {
        setError(messageOf(e));
      }
    },
    [projectId],
  );

  const follow = useCallback(
    (step: Step, job: Job) => {
      stops.current.push(
        watchJob(job.id, (u) => setJobs((m) => ({ ...m, [step]: u })), () => {
          loadPlan();
          loadExports();
          if (openLesson.current) showLesson(openLesson.current);
        }),
      );
    },
    [loadPlan, loadExports, showLesson],
  );

  useEffect(() => {
    loadPlan();
    loadExports();
    // Resume watching runs that are still going, and keep the last result of each step on screen.
    api.get<Job[]>(`/jobs?project_id=${projectId}&recent_minutes=1440`).then((list) => {
      const latest: Partial<Record<Step, Job>> = {};
      for (const step of Object.keys(JOB_KIND) as Step[]) {
        const job = list.find((j) => j.kind === JOB_KIND[step]);
        if (!job) continue;
        latest[step] = job;
        if (isActive(job)) follow(step, job);
      }
      setJobs(latest);
    });
    const current = stops.current;
    return () => current.forEach((stop) => stop());
  }, [projectId, loadPlan, loadExports, follow]);

  const generated = plan?.modules.some((m) => m.lessons.some((l) => l.slides || l.questions)) ?? false;
  const exported = !!plan && exports.some((x) => x.content?.plan_version === plan.version);

  useEffect(() => {
    if (!ready) onStage({ current: "Ingest", done: [] });
    else if (!plan || plan.status !== "approved") onStage({ current: "Plan", done: ["Ingest"] });
    else if (!generated) onStage({ current: "Generate", done: ["Ingest", "Plan"] });
    else onStage({ current: "Export", done: exported ? ["Ingest", "Plan", "Generate", "Export"] : ["Ingest", "Plan", "Generate"] });
  }, [ready, plan, generated, exported, onStage]);

  async function start(step: Step) {
    setError(null);
    try {
      const job = await api.post<Job>(`/projects/${projectId}/${ENDPOINT[step]}`);
      setJobs((m) => ({ ...m, [step]: job }));
      follow(step, job);
    } catch (e) {
      setError(messageOf(e));
    }
  }

  async function approve() {
    if (!plan) return;
    setError(null);
    try {
      setPlan(await api.post<CoursePlan>(`/projects/${projectId}/plan/${plan.id}/approve`));
    } catch (e) {
      setError(messageOf(e));
    }
  }

  async function download(x: CourseExport, kind: "scorm" | "pptx") {
    try {
      await downloadFile(`/projects/${projectId}/exports/${x.id}/files/${kind}`, kind === "scorm" ? "course_scorm12.zip" : "course.pptx");
    } catch (e) {
      setError(messageOf(e));
    }
  }

  if (detail) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <LessonView detail={detail} onInspect={onInspect} onBack={() => { openLesson.current = null; setDetail(null); }} />
      </div>
    );
  }

  const planBusy = isActive(jobs.plan);
  const lessonsBusy = isActive(jobs.lessons);
  const approved = plan?.status === "approved";

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div>
        <h2 className="text-base font-semibold">Course</h2>
        <p className="text-sm text-muted-foreground">Single-pass baseline: each step runs once with no critique or revision. The numbers under each step are what the evaluation layer will later be measured against.</p>
      </div>
      {error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

      <StepCard
        n={1}
        title="Plan the course"
        hint="Objectives, modules and lessons drawn from every ready source. Uses the audience, duration and goals in the course brief."
        action={
          <Button size="sm" variant={plan ? "outline" : "accent"} disabled={!ready || planBusy || lessonsBusy} onClick={() => start("plan")}>
            {plan ? <RotateCw /> : <Play />} {plan ? "New version" : "Generate plan"}
          </Button>
        }
      >
        <JobStatus step="plan" job={jobs.plan} />
        {!ready && <p className="text-xs text-muted-foreground">Waiting for at least one source to finish ingesting.</p>}
        {plan && (
          <div className="space-y-4 border-t pt-3">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{plan.title}</p>
                {plan.summary && <p className="text-sm text-muted-foreground">{plan.summary}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="font-mono text-[11px] text-muted-foreground">v{plan.version}</span>
                <Badge tone={statusTone(plan.status)}>{plan.status}</Badge>
              </div>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium">Learning objectives</p>
              <ul className="space-y-1 text-sm">
                {plan.learning_objectives.map((o) => (
                  <li key={o.id} className="flex gap-2">
                    <span className="font-mono text-[11px] text-muted-foreground">{o.id}</span>
                    <span className="flex-1">{o.text}</span>
                    <span className="text-[11px] text-muted-foreground">{o.bloom_level}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="space-y-3">
              {plan.modules.map((m) => (
                <div key={m.id}>
                  <p className="text-xs font-medium">{m.position}. {m.title}</p>
                  <ul className="mt-1 divide-y rounded-md border">
                    {m.lessons.map((l) => (
                      <li key={l.id}>
                        <button
                          disabled={!l.slides && !l.questions}
                          onClick={() => showLesson(l.id)}
                          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm enabled:hover:bg-muted/50 disabled:cursor-default"
                        >
                          <span className="min-w-0 truncate">{l.title}</span>
                          <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
                            {l.estimated_minutes ? `${l.estimated_minutes}m · ` : ""}{l.objective_ids.join(" ") || "no objective"} · {l.source_chunk_count} src
                            {l.slides || l.questions ? ` · ${l.slides} slides · ${l.questions} q` : ""}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            {plan.coverage && Object.keys(plan.coverage).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium">Share of each source&apos;s excerpts the plan drew on</p>
                <ul className="space-y-1 text-xs">
                  {Object.entries(plan.coverage).map(([sid, frac]) => (
                    <li key={sid} className="flex items-center gap-2">
                      <span className="w-40 truncate text-muted-foreground" title={plan.source_names[sid]}>{plan.source_names[sid] ?? sid.slice(0, 8)}</span>
                      <Progress value={frac * 100} className="flex-1" />
                      <span className="w-10 text-right font-mono">{Math.round(frac * 100)}%</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!approved && (
              <div className="flex items-center justify-between gap-3 rounded-md bg-accent-soft/60 px-3 py-2">
                <p className="text-xs">Review the plan above. Lessons are generated only from an approved plan.</p>
                <Button size="sm" variant="accent" onClick={approve} disabled={planBusy}><CheckCircle2 /> Approve plan</Button>
              </div>
            )}
          </div>
        )}
      </StepCard>

      <StepCard
        n={2}
        title="Generate lessons"
        hint="A slide deck with speaker notes and a validated quiz for every lesson. Slow on a laptop: allow a few minutes per lesson."
        action={
          <Button size="sm" variant={generated ? "outline" : "accent"} disabled={!approved || lessonsBusy || planBusy} onClick={() => start("lessons")}>
            {generated ? <RotateCw /> : <Play />} {generated ? "Regenerate" : "Generate lessons"}
          </Button>
        }
      >
        <JobStatus step="lessons" job={jobs.lessons} />
        {generated && !lessonsBusy && <p className="text-xs text-muted-foreground">Open a lesson in the plan above to read its slides and quiz and check each citation.</p>}
      </StepCard>

      <StepCard
        n={3}
        title="Export"
        hint="An editable PowerPoint and a SCORM 1.2 package, one SCO per lesson, that an LMS can import."
        action={
          <Button size="sm" variant="accent" disabled={!generated || lessonsBusy || isActive(jobs.export)} onClick={() => start("export")}>
            <Play /> Export course
          </Button>
        }
      >
        <JobStatus step="export" job={jobs.export} />
        {exports.length > 0 && (
          <ul className="divide-y rounded-md border text-sm">
            {exports.map((x) => (
              <li key={x.id} className="flex items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0 truncate">
                  <span className="font-mono text-[11px] text-muted-foreground">{new Date(x.created_at).toLocaleString()} · plan v{x.content?.plan_version}</span>
                  {x.content?.includes_unapproved && <span className="ml-2 text-[11px] text-warning">unreviewed content</span>}
                </span>
                <span className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" onClick={() => download(x, "scorm")}><Download /> SCORM</Button>
                  <Button size="sm" variant="ghost" onClick={() => download(x, "pptx")}><Download /> PPTX</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </StepCard>
    </div>
  );
}
