"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { CheckCircle2, History as HistoryIcon, Pencil, RotateCw } from "lucide-react";
import type { Course } from "@/components/course/use-course";
import { DistractorFinding, flagPieces, ReviewerSummary, SlideFindings } from "@/components/reviewer-findings";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type AssetVersion, type LessonDetail, type Proposal, type QuizQuestion, type Reference, type ReviewerReview, type SlideContent } from "@/lib/api";
import { cn } from "@/lib/utils";

/** What the inspector pane shows: a search hit or a cited source passage. */
export type Inspected = {
  chunk_id: string; source_name: string; text: string; heading_path: string | null;
  page_start: number | null; page_end: number | null; similarity: number | null; quote?: string | null;
};
/** Where a regeneration was asked for; the composer offers this scope and wider ones. */
export type ComposeFrom = { kind: "slide" | "question" | "lesson"; block?: string };

const MARKER = /(\[\d{1,3}\])/g;
// Separate, non-global pattern for testing a single part: a /g regex's .test() keeps state between calls.
const IS_MARKER = /^\[\d{1,3}\]$/;

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

/** Cited text with the reviewer's flagged spans underlined. */
function Flagged({ text, review, onCite }: { text: string; review?: ReviewerReview["slides"][string]; onCite: (n: string) => void }) {
  return <>{flagPieces(text, review).map((p, i) => <span key={i} className={p.flag || undefined}><Cited text={p.text} onCite={onCite} /></span>)}</>;
}

// ---- proposed changes ---------------------------------------------------------------
function Line({ kind, children }: { kind: "del" | "ins" | "same"; children: React.ReactNode }) {
  return (
    <div className={cn("flex gap-2 px-3 py-1", kind === "del" && "bg-destructive/10", kind === "ins" && "bg-success/10", kind === "same" && "text-muted-foreground")}>
      <span aria-hidden className={cn("w-3 shrink-0", kind === "del" && "text-destructive", kind === "ins" && "text-success")}>{kind === "del" ? "−" : kind === "ins" ? "+" : ""}</span>
      <span className={cn(kind === "del" && "line-through decoration-destructive/50")}>{children}</span>
    </div>
  );
}

function SlideDiff({ before, after }: { before: SlideContent; after: SlideContent }) {
  const removed = before.bullets.filter((b) => !after.bullets.includes(b));
  return (
    <div className="py-1 text-[13px] leading-relaxed">
      {before.title !== after.title && <><Line kind="del">{before.title}</Line><Line kind="ins">{after.title}</Line></>}
      {removed.map((b, i) => <Line key={`d${i}`} kind="del">{b}</Line>)}
      {after.bullets.map((b, i) => <Line key={`a${i}`} kind={before.bullets.includes(b) ? "same" : "ins"}>{b}</Line>)}
      {before.notes !== after.notes && <><Line kind="del">Notes: {before.notes || "none"}</Line><Line kind="ins">Notes: {after.notes || "none"}</Line></>}
    </div>
  );
}

function QuestionDiff({ before, after }: { before: QuizQuestion; after: QuizQuestion }) {
  const right = (q: QuizQuestion) => q.options[q.answer_index];
  const removed = before.options.filter((o) => !after.options.includes(o));
  return (
    <div className="py-1 text-[13px] leading-relaxed">
      {before.stem !== after.stem && <><Line kind="del">{before.stem}</Line><Line kind="ins">{after.stem}</Line></>}
      {removed.map((o, i) => <Line key={`d${i}`} kind="del">{o}{o === right(before) ? " (answer)" : ""}</Line>)}
      {after.options.map((o, i) => <Line key={`a${i}`} kind={before.options.includes(o) ? "same" : "ins"}>{o}{o === right(after) ? " (answer)" : ""}</Line>)}
    </div>
  );
}

function ProposalBox({ proposal, onDecide, children }: { proposal: Proposal<unknown>; onDecide: (accept: boolean) => void; children: React.ReactNode }) {
  return (
    <div className="mt-3 overflow-hidden rounded-md border border-accent/60">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-accent-soft/60 px-3 py-1.5">
        <span className="text-xs font-medium">Proposed change{proposal.reason === "fix" ? " · fixes the flagged issues" : ""}</span>
        <span className="flex gap-1">
          <Button size="sm" variant="ghost" className="h-7" onClick={() => onDecide(false)}>Keep original</Button>
          <Button size="sm" variant="accent" className="h-7" onClick={() => onDecide(true)}>Accept</Button>
        </span>
      </div>
      {children}
    </div>
  );
}

// ---- editors ---------------------------------------------------------------------------
const field = "w-full rounded-md border bg-surface px-2.5 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function SlideEditor({ slide, onCancel, onSave }: { slide: SlideContent; onCancel: () => void; onSave: (v: Partial<SlideContent>) => void }) {
  const [title, setTitle] = useState(slide.title);
  const [bullets, setBullets] = useState(slide.bullets.join("\n"));
  const [notes, setNotes] = useState(slide.notes);
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); onSave({ title, bullets: bullets.split("\n"), notes }); }}>
      <label className="block text-xs font-medium" htmlFor={`edit-title-${slide.id}`}>Title</label>
      <input id={`edit-title-${slide.id}`} className={field} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
      <label className="block text-xs font-medium" htmlFor={`edit-bullets-${slide.id}`}>Bullets, one per line. Keep the [n] markers that cite the sources.</label>
      <textarea id={`edit-bullets-${slide.id}`} className={cn(field, "font-mono text-[13px]")} rows={Math.max(3, slide.bullets.length + 1)} value={bullets} onChange={(e) => setBullets(e.target.value)} />
      <label className="block text-xs font-medium" htmlFor={`edit-notes-${slide.id}`}>Speaker notes</label>
      <textarea id={`edit-notes-${slide.id}`} className={field} rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div className="flex justify-end gap-2"><Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button><Button type="submit" size="sm" variant="accent">Save</Button></div>
    </form>
  );
}

function QuestionEditor({ question, id, onCancel, onSave }: { question: QuizQuestion; id: string; onCancel: () => void; onSave: (v: Partial<QuizQuestion>) => void }) {
  const [stem, setStem] = useState(question.stem);
  const [options, setOptions] = useState(question.options);
  const [answer, setAnswer] = useState(question.answer_index);
  const [explanation, setExplanation] = useState(question.explanation);
  return (
    <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); onSave({ stem, options, answer_index: answer, explanation }); }}>
      <label className="block text-xs font-medium" htmlFor={`edit-stem-${id}`}>Question</label>
      <input id={`edit-stem-${id}`} className={field} value={stem} onChange={(e) => setStem(e.target.value)} autoFocus />
      <fieldset className="space-y-1.5">
        <legend className="text-xs font-medium">Options. Select the correct answer.</legend>
        {options.map((o, i) => (
          <div key={i} className="flex items-center gap-2">
            <input type="radio" id={`edit-answer-${id}-${i}`} name={`answer-${id}`} checked={answer === i} onChange={() => setAnswer(i)} aria-label={`Option ${i + 1} is correct`} />
            <input id={`edit-option-${id}-${i}`} className={field} value={o} onChange={(e) => setOptions(options.map((x, j) => (j === i ? e.target.value : x)))} aria-label={`Option ${i + 1}`} />
          </div>
        ))}
      </fieldset>
      <label className="block text-xs font-medium" htmlFor={`edit-expl-${id}`}>Explanation</label>
      <textarea id={`edit-expl-${id}`} className={field} rows={2} value={explanation} onChange={(e) => setExplanation(e.target.value)} />
      <div className="flex justify-end gap-2"><Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button><Button type="submit" size="sm" variant="accent">Save</Button></div>
    </form>
  );
}

// ---- version history ------------------------------------------------------------------
function History({ projectId, lessonId, disabled, onRestore }: { projectId: string; lessonId: string; disabled: boolean; onRestore: (assetId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<AssetVersion[] | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    api.get<AssetVersion[]>(`/projects/${projectId}/lessons/${lessonId}/versions`).then(setVersions).catch(() => setVersions([]));
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, projectId, lessonId]);
  return (
    <div ref={box} className="relative">
      <Button size="sm" variant="ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}><HistoryIcon /> History</Button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-80 rounded-md border bg-surface p-2 shadow-lg">
          {!versions ? <p className="p-2 text-xs text-muted-foreground">Loading…</p> : (["slides", "quiz"] as const).map((kind) => {
            const list = versions.filter((v) => v.kind === kind);
            return list.length ? (
              <div key={kind} className="py-1">
                <p className="px-2 pb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{kind === "slides" ? "Slides" : "Quiz"}</p>
                {list.map((v) => (
                  <div key={v.asset_id} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-xs hover:bg-muted">
                    <span className="min-w-0">
                      <span className="font-mono">v{v.version}</span> · {v.note}
                      <span className="block text-[11px] text-muted-foreground" title={v.instructions ?? undefined}>{new Date(v.created_at).toLocaleString()}{v.instructions ? " · with instructions" : ""}</span>
                    </span>
                    {v.current ? <Badge tone="success">current</Badge> : <Button size="sm" variant="outline" className="h-6 px-2" disabled={disabled} onClick={() => { setOpen(false); onRestore(v.asset_id); }}>Restore</Button>}
                  </div>
                ))}
              </div>
            ) : null;
          })}
        </div>
      )}
    </div>
  );
}

// ---- the pane --------------------------------------------------------------------------
export function LessonPane({ projectId, detail, index, course, onChange, onInspect, onCompose }: {
  projectId: string; detail: LessonDetail; index: string; course: Course;
  onChange: (d: LessonDetail) => void; onInspect: (i: Inspected) => void; onCompose: (from: ComposeFrom) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null); // "slide:s2" or "question:0"
  const [error, setError] = useState<string | null>(null);
  const lessonId = detail.lesson.id;
  const deck = detail.slides?.content;
  const quiz = detail.quiz?.content;
  const deckReview = detail.slides?.critique?.reviewer;
  const quizReview = detail.quiz?.critique?.reviewer;
  const approved = detail.lesson.approved;
  const working = course.busy.revise || course.busy.lessons;
  const job = course.busy.revise ? course.jobs.revise : course.busy.lessons ? course.jobs.lessons : undefined;
  const scope = job?.payload as { lesson_ids?: string[]; targets?: { lesson_id: string }[] } | undefined;
  const mine = !!job && !!scope && ((scope.lesson_ids ?? []).includes(lessonId) || (scope.targets ?? []).some((t) => t.lesson_id === lessonId)
    || (job.kind === "generate_lesson_assets" && !(scope.lesson_ids ?? []).length)); // a run over every lesson
  const slideProposals = deck?.proposals ?? [];
  const questionProposals = quiz?.proposals ?? [];
  const waiting = slideProposals.length + questionProposals.length;
  const flags = (detail.lesson.reviewer_flags ?? 0) + detail.lesson.weak_questions;
  const changed = new Set([...(deckReview?.changed ?? []), ...(quizReview?.changed ?? []).map((b) => `q${b}`)]);

  const inspect = (ref: Reference | undefined, quote?: string | null) => {
    if (!ref) return;
    const cited = detail.citations.find((c) => c.chunk_id === ref.chunk_id);
    onInspect({ ...ref, text: cited?.text ?? "This passage is no longer in the knowledge base.", similarity: null, quote });
  };
  async function act(path: string, body?: unknown, method: "post" | "patch" = "post") {
    setError(null);
    try {
      const next = method === "post" ? await api.post<LessonDetail>(`/projects/${projectId}/lessons/${lessonId}${path}`, body) : await api.patch<LessonDetail>(`/projects/${projectId}/lessons/${lessonId}${path}`, body);
      onChange(next);
      setEditing(null);
      course.loadPlan();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  const decide = (ids: string[] | null, accept: boolean) => act(`/proposals/${accept ? "accept" : "discard"}`, { ids });
  const fix = (kind: "slide" | "question", block: string) => course.revise({ targets: [{ lesson_id: lessonId, kind, block }], fix: true });
  const tools = (onRegenerate: () => void, onEdit: () => void) =>
    !approved && (
      <span className="flex gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        <Button size="sm" variant="ghost" className="h-7 px-2" disabled={working} onClick={onRegenerate}><RotateCw /> Regenerate</Button>
        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={onEdit}><Pencil /> Edit</Button>
      </span>
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">{detail.module_title} · Lesson {index}{detail.lesson.estimated_minutes ? ` · ${detail.lesson.estimated_minutes} min` : ""}</p>
          <h2 className="text-base font-semibold">{detail.lesson.title}</h2>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {deck ? `${deck.citation_stats.slides} slides · ${deck.citation_stats.citation_markers} citations · ${deck.citation_stats.bullets_without_citation}/${deck.citation_stats.bullets_checked} bullets uncited` : "no slides"}
            {detail.slides ? ` · v${detail.slides.version}` : ""}{deck?.revision ? ` · ${deck.revision.note}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <History projectId={projectId} lessonId={lessonId} disabled={approved || working} onRestore={(asset_id) => act("/restore", { asset_id })} />
          {approved ? (
            <>
              <Badge tone="success" className="h-7 px-2"><CheckCircle2 className="mr-1 size-3.5" /> Approved</Badge>
              <Button size="sm" variant="outline" onClick={() => act("/reopen")}>Reopen</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" disabled={working} onClick={() => onCompose({ kind: "lesson" })}><RotateCw /> Regenerate lesson…</Button>
              {flags > 0 && <Button size="sm" variant="outline" onClick={() => act("/approve")}>Approve</Button>}
              {flags > 0 ? (
                <Button size="sm" variant="accent" disabled={working} onClick={() => course.revise({ lesson_ids: [lessonId], fix: true })}>Fix {flags} flagged</Button>
              ) : (
                <Button size="sm" variant="accent" onClick={() => act("/approve")}><CheckCircle2 /> Approve lesson</Button>
              )}
            </>
          )}
        </div>
      </div>

      {mine && job && <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{job.message ?? "Queued: waiting for the worker"}</p>}
      {error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {waiting > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-accent/60 bg-accent-soft/50 px-3 py-2 text-sm">
          <span><span className="font-medium">{waiting} proposed {waiting === 1 ? "change" : "changes"}</span> waiting for you below</span>
          <span className="flex gap-1">
            <Button size="sm" variant="ghost" onClick={() => decide(null, false)}>Discard all</Button>
            <Button size="sm" variant="accent" onClick={() => decide(null, true)}>Accept all</Button>
          </span>
        </div>
      )}

      <ReviewerSummary deck={deckReview} quiz={quizReview} />

      {!deck && <p className="text-sm text-muted-foreground">This lesson has no slides yet.</p>}
      {deck?.slides.map((s) => {
        const sr = deckReview?.slides[s.id];
        const proposal = slideProposals.find((p) => p.block === s.id);
        const tone = sr?.issues.some((i) => i.type.endsWith("_conflict")) ? "border-destructive/50" : sr?.issues.length ? "border-warning/50" : "";
        return (
          <article key={s.id} className={`group rounded-md border bg-surface p-4 text-sm ${tone}`}>
            {editing === `slide:${s.id}` ? (
              <SlideEditor slide={s} onCancel={() => setEditing(null)} onSave={(value) => act("/blocks", { kind: "slide", block: s.id, value }, "patch")} />
            ) : (
              <>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 className="font-semibold">{flagPieces(s.title, sr).map((p, i) => <span key={i} className={p.flag || undefined}>{p.text}</span>)}</h3>
                  <span className="flex items-center gap-2">
                    {tools(() => onCompose({ kind: "slide", block: s.id }), () => setEditing(`slide:${s.id}`))}
                    <span className="font-mono text-[10px] text-muted-foreground">{s.id}</span>
                  </span>
                </div>
                {s.table && s.table.length > 0 && (
                  <div className="mb-2 overflow-x-auto">
                    <table className="w-full border-collapse text-xs">
                      <tbody>
                        {s.table.map((row, r) => (
                          <tr key={r} className={r === 0 ? "bg-muted/60 font-medium" : ""}>
                            {row.map((cell, c) => <td key={c} className="border px-2 py-1"><Flagged text={cell} review={sr} onCite={(n) => inspect(deck.references[n])} /></td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {s.bullets.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5">
                    {s.bullets.map((b, i) => <li key={i}><Flagged text={b} review={sr} onCite={(n) => inspect(deck.references[n])} /></li>)}
                  </ul>
                )}
                {s.notes && <p className="mt-3 border-t pt-2 text-xs leading-relaxed text-muted-foreground"><Flagged text={s.notes} review={sr} onCite={(n) => inspect(deck.references[n])} /></p>}
                {changed.has(s.id) ? (
                  <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">Changed since the review.</p>
                ) : (
                  <SlideFindings review={sr} onFix={!approved && !proposal && !working && sr?.issues.length ? () => fix("slide", s.id) : undefined} />
                )}
              </>
            )}
            {proposal && <ProposalBox proposal={proposal} onDecide={(ok) => decide([proposal.id], ok)}><SlideDiff before={proposal.before} after={proposal.after} /></ProposalBox>}
          </article>
        );
      })}

      {quiz && (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold">Quiz <span className="font-normal text-muted-foreground">· {quiz.questions.length} questions{quiz.rejected.length ? `, ${quiz.rejected.length} rejected by validation` : ""}</span></h3>
          {quiz.questions.map((q, i) => {
            const block = String(i);
            const proposal = questionProposals.find((p) => p.block === block);
            return (
              <article key={i} className="group rounded-md border bg-surface p-4 text-sm">
                {editing === `question:${block}` ? (
                  <QuestionEditor question={q} id={block} onCancel={() => setEditing(null)} onSave={(value) => act("/blocks", { kind: "question", block, value }, "patch")} />
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-medium">{i + 1}. {q.stem}</p>
                      {tools(() => onCompose({ kind: "question", block }), () => setEditing(`question:${block}`))}
                    </div>
                    <ol className="mt-2 space-y-1">
                      {q.options.map((opt, j) => (
                        <li key={j} className={j === q.answer_index ? "flex items-center gap-1.5 text-success" : "pl-5 text-muted-foreground"}>
                          {j === q.answer_index && <CheckCircle2 className="size-3.5" />}{opt}
                        </li>
                      ))}
                    </ol>
                    <p className="mt-2 text-xs text-muted-foreground">{q.explanation.replace(MARKER, "").trim()}</p>
                    {q.chunk_id && (
                      <button className="mt-2 text-left text-xs text-muted-foreground hover:text-foreground" onClick={() => inspect(Object.values(quiz.references).find((r) => r.chunk_id === q.chunk_id), q.source_span)}>
                        <span className="citation-chip mr-1">source</span>“{q.source_span}”
                      </button>
                    )}
                    {changed.has(`q${block}`) ? (
                      <p className="mt-2 text-xs text-muted-foreground">Changed since the review.</p>
                    ) : (
                      <DistractorFinding review={quizReview?.questions[block]} onImprove={!approved && !proposal && !working ? () => fix("question", block) : undefined} />
                    )}
                  </>
                )}
                {proposal && <ProposalBox proposal={proposal} onDecide={(ok) => decide([proposal.id], ok)}><QuestionDiff before={proposal.before} after={proposal.after} /></ProposalBox>}
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
