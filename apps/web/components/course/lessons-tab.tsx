"use client";

import { useEffect, useMemo, useState } from "react";
import { Play } from "lucide-react";
import { Composer, type Scope } from "@/components/course/composer";
import { LessonPane, type ComposeFrom, type Inspected } from "@/components/course/lesson-pane";
import { isGenerated, lessonFlags, lessonState, numbered } from "@/components/course/lesson-status";
import type { Course } from "@/components/course/use-course";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type LessonDetail, type Steering } from "@/lib/api";
import { cn } from "@/lib/utils";

type Row = ReturnType<typeof numbered>[number];
type Opened = ComposeFrom | { kind: "selection" } | { kind: "all" };

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The scopes a regeneration opened from `from` offers, narrowest first. */
function scopesFor(from: Opened, rows: Row[], current: Row | undefined, detail: LessonDetail | null, checked: string[]): Scope[] {
  const regenerate = (list: Row[]) => {
    const approved = list.filter((r) => r.lesson.approved).length;
    const kept = approved ? `; ${plural(approved, "approved lesson")} ${approved === 1 ? "stays" : "stay"} as ${approved === 1 ? "it is" : "they are"}` : "";
    return { flags: list.reduce((n, r) => n + lessonFlags(r.lesson), 0), impact: `Regenerates ${plural(list.length - approved, "lesson")} at once${kept}. Earlier versions stay under History.` };
  };
  const out: Scope[] = [];
  if (from.kind === "slide" && detail?.slides?.content) {
    const slide = detail.slides.content.slides.find((s) => s.id === from.block);
    out.push({ key: "slide", label: `This slide: ${slide?.title ?? from.block}`, action: "Propose a change", flags: detail.slides.critique?.reviewer?.slides[from.block ?? ""]?.issues.length ?? 0,
      impact: "Proposes a new version of this slide. Nothing changes until you accept it." });
  }
  if (from.kind === "question" && detail?.quiz?.content) {
    const q = detail.quiz.content.questions[Number(from.block)];
    const score = detail.quiz.critique?.reviewer?.questions[from.block ?? ""]?.score;
    out.push({ key: "question", label: `This question: ${q ? q.stem : from.block}`, action: "Propose a change", flags: score != null && score <= 2 ? 1 : 0,
      impact: "Proposes a new version of this question. Nothing changes until you accept it." });
  }
  if (current && from.kind !== "selection" && from.kind !== "all") {
    const l = current.lesson;
    out.push({ key: "lesson", label: `This lesson: ${l.title}`, action: "Regenerate lesson", flags: lessonFlags(l),
      impact: `Replaces this lesson's ${plural(l.slides, "slide")} and ${plural(l.questions, "question")} at once. The current version stays under History.`,
      disabled: l.approved ? "This lesson is approved. Reopen it to regenerate it." : undefined });
    const inModule = rows.filter((r) => r.moduleId === current.moduleId);
    if (inModule.length > 1 && inModule.length < rows.length) {
      out.push({ key: "module", label: `Module: ${current.moduleTitle} (${plural(inModule.length, "lesson")})`, action: "Regenerate module", ...regenerate(inModule) });
    }
  }
  if (from.kind === "selection") {
    out.push({ key: "selection", label: `The ${plural(checked.length, "selected lesson")}`, action: "Regenerate selected", ...regenerate(rows.filter((r) => checked.includes(r.lesson.id))) });
  }
  out.push({ key: "all", label: `All lessons (${rows.length})`, action: "Regenerate all lessons", ...regenerate(rows) });
  return out;
}

export function LessonsTab({ projectId, course, selected, onSelect, onInspect, goTo }: {
  projectId: string; course: Course; selected: string | null; onSelect: (lessonId: string) => void;
  onInspect: (i: Inspected) => void; goTo: (tab: "outline") => void;
}) {
  const plan = course.plan;
  const rows = useMemo(() => (plan ? numbered(plan) : []), [plan]);
  const current = rows.find((r) => r.lesson.id === selected) ?? rows.find((r) => isGenerated(r.lesson)) ?? rows[0];
  const [checked, setChecked] = useState<string[]>([]);
  const [detail, setDetail] = useState<LessonDetail | null>(null);
  const [opened, setOpened] = useState<Opened | null>(null);
  const [error, setError] = useState<string | null>(null);
  const working = course.busy.lessons || course.busy.revise;
  const generated = rows.filter((r) => isGenerated(r.lesson)).length;

  const currentId = current?.lesson.id;
  const currentGenerated = current ? isGenerated(current.lesson) : false;
  // A lesson's summary changes when its content does (a run, an accept, an approval): reload it then.
  const stamp = current ? `${current.lesson.generated_at}|${current.lesson.proposals}|${current.lesson.approved}|${course.contentTick}` : "";
  useEffect(() => {
    if (!currentId || !currentGenerated) {
      setDetail(null);
      return;
    }
    let live = true;
    api.get<LessonDetail>(`/projects/${projectId}/lessons/${currentId}`).then((d) => live && setDetail(d)).catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [projectId, currentId, currentGenerated, stamp]);

  if (!plan) {
    return <Empty title="No outline yet" detail="Lessons are generated from an approved outline." action={<Button size="sm" variant="accent" onClick={() => goTo("outline")}>Go to the outline</Button>} />;
  }
  if (plan.status !== "approved" && generated === 0) {
    return <Empty title="The outline is waiting for approval" detail="Approve it to generate its lessons." action={<Button size="sm" variant="accent" onClick={() => goTo("outline")}>Review the outline</Button>} />;
  }

  const toggle = (id: string) => setChecked((xs) => (xs.includes(id) ? xs.filter((x) => x !== id) : [...xs, id]));
  const chosen = rows.filter((r) => checked.includes(r.lesson.id));
  const chosenFlags = chosen.reduce((n, r) => n + lessonFlags(r.lesson), 0);
  async function approveChosen() {
    setError(null);
    try {
      for (const r of chosen.filter((r) => isGenerated(r.lesson) && !r.lesson.approved)) await api.post(`/projects/${projectId}/lessons/${r.lesson.id}/approve`);
      setChecked([]);
      course.loadPlan();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function submit(scope: Scope, steering: Steering) {
    if (!opened) return;
    if ((scope.key === "slide" || scope.key === "question") && currentId && "block" in opened && opened.block) {
      return course.revise({ targets: [{ lesson_id: currentId, kind: scope.key, block: opened.block }], ...steering });
    }
    const ids = scope.key === "lesson" && currentId ? [currentId]
      : scope.key === "module" ? rows.filter((r) => r.moduleId === current?.moduleId).map((r) => r.lesson.id)
      : scope.key === "selection" ? checked : [];
    return course.generateLessons({ lesson_ids: ids.length ? ids : undefined, ...steering });
  }

  return (
    <div className="grid min-h-0 lg:grid-cols-[17rem_minmax(0,1fr)]">
      <aside className="flex flex-col border-b bg-surface lg:sticky lg:top-0 lg:max-h-[calc(100vh-6.5rem)] lg:self-start lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between border-b px-3 py-2 text-xs">
          <label className="flex items-center gap-2 font-medium">
            <input type="checkbox" checked={checked.length === rows.length && rows.length > 0} onChange={(e) => setChecked(e.target.checked ? rows.map((r) => r.lesson.id) : [])} aria-label="Select all lessons" />
            Lessons
          </label>
          <span className="font-mono text-muted-foreground">{generated}/{rows.length} generated</span>
        </div>
        <ul className="min-h-0 flex-1 overflow-auto">
          {rows.map((r, i) => {
            const state = lessonState(r.lesson);
            const first = i === 0 || rows[i - 1].moduleId !== r.moduleId;
            return (
              <li key={r.lesson.id}>
                {first && plan.modules.length > 1 && <p className="px-3 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{r.moduleTitle}</p>}
                <div className={cn("flex items-start gap-2 border-b px-3 py-2.5", r.lesson.id === current?.lesson.id && "bg-accent-soft")}>
                  <input type="checkbox" className="mt-1" checked={checked.includes(r.lesson.id)} onChange={() => toggle(r.lesson.id)} aria-label={`Select ${r.lesson.title}`} />
                  <button className="min-w-0 flex-1 text-left" onClick={() => onSelect(r.lesson.id)}>
                    <span className="block text-sm font-medium leading-snug"><span className="mr-1 font-mono text-[11px] text-muted-foreground">{r.index}</span>{r.lesson.title}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5">
                      <Badge tone={state.tone}>{state.label}</Badge>
                      {isGenerated(r.lesson) && <span className="font-mono text-[11px] text-muted-foreground">{r.lesson.slides} slides · {r.lesson.questions} q</span>}
                    </span>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
        {checked.length > 0 && (
          <div className="space-y-2 border-t bg-foreground p-3 text-background">
            <p className="text-xs font-medium">{plural(checked.length, "lesson")} selected</p>
            <div className="flex flex-wrap gap-1.5">
              {chosenFlags > 0 && <Button size="sm" variant="accent" disabled={working} onClick={() => course.revise({ lesson_ids: checked, fix: true })}>Fix {chosenFlags} flagged</Button>}
              <Button size="sm" variant="outline" className="border-background/40 bg-transparent text-background hover:bg-background/10" disabled={working} onClick={() => setOpened({ kind: "selection" })}>Regenerate…</Button>
              <Button size="sm" variant="outline" className="border-background/40 bg-transparent text-background hover:bg-background/10" onClick={approveChosen}>Approve</Button>
            </div>
          </div>
        )}
      </aside>

      <section className="min-w-0 space-y-4 p-6">
        {(error || course.error) && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error ?? course.error}</p>}
        {generated === 0 ? (
          <Empty
            title="No lessons generated yet"
            detail={`The approved outline has ${plural(rows.length, "lesson")}. Generating them takes a few minutes per lesson on a laptop.`}
            action={
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={working} onClick={() => setOpened({ kind: "all" })}>With instructions…</Button>
                <Button size="sm" variant="accent" disabled={working} onClick={() => course.generateLessons()}><Play /> Generate all lessons</Button>
              </div>
            }
            note={course.busy.lessons ? course.jobs.lessons?.message ?? "Queued: waiting for the worker" : undefined}
          />
        ) : current && !isGenerated(current.lesson) ? (
          <Empty title={`Lesson ${current.index} is not generated yet`} detail={current.lesson.title}
                 action={<Button size="sm" variant="accent" disabled={working || plan.status !== "approved"} onClick={() => course.generateLessons({ lesson_ids: [current.lesson.id] })}><Play /> Generate this lesson</Button>} />
        ) : detail && current ? (
          <LessonPane projectId={projectId} detail={detail} index={current.index} course={course} onChange={setDetail} onInspect={onInspect} onCompose={(from) => setOpened(from)} />
        ) : (
          <p className="text-sm text-muted-foreground">Loading the lesson…</p>
        )}
      </section>

      {opened && (
        <Composer
          title="Regenerate"
          scopes={scopesFor(opened, rows, current, detail, checked)}
          initial={opened.kind === "lesson" ? "lesson" : opened.kind}
          onClose={() => setOpened(null)}
          onSubmit={submit}
        />
      )}
    </div>
  );
}

function Empty({ title, detail, action, note }: { title: string; detail: string; action?: React.ReactNode; note?: string }) {
  return (
    <div className="mx-auto max-w-md space-y-3 py-16 text-center">
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground">{detail}</p>
      {action && <div className="flex justify-center">{action}</div>}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </div>
  );
}
