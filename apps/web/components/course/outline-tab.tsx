"use client";

import { useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp, CheckCircle2, Pencil, Play, Plus, RotateCw, Trash2, TriangleAlert } from "lucide-react";
import { Composer } from "@/components/course/composer";
import { lessonState, numbered } from "@/components/course/lesson-status";
import type { Course } from "@/components/course/use-course";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { api, type CoursePlan, type OutlineChange, type PlanVersion, type Project } from "@/lib/api";
import { cn } from "@/lib/utils";

type Editing = { kind: "course" | "module" | "lesson" | "add"; id: string; value: string } | null;

/** Text that becomes an input on click; Enter or leaving the field saves, Escape cancels. */
function Inline({ editing, value, onStart, onChange, onSave, onCancel, className, label }: {
  editing: boolean; value: string; onStart?: () => void; onChange: (v: string) => void; onSave: () => void; onCancel: () => void; className?: string; label: string;
}) {
  if (!editing) {
    return onStart ? <button className={cn("text-left hover:underline decoration-dotted underline-offset-4", className)} onClick={onStart} title={`Rename ${label}`}>{value}</button> : <span className={className}>{value}</span>;
  }
  return (
    <input
      autoFocus
      aria-label={`New name for ${label}`}
      className={cn("w-full rounded-md border bg-surface px-2 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onSave}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSave();
        if (e.key === "Escape") onCancel();
      }}
    />
  );
}

export function OutlineTab({ projectId, project, course, ready, onOpenLesson, goTo }: {
  projectId: string; project: Project | null; course: Course; ready: boolean;
  onOpenLesson: (lessonId: string) => void; goTo: (tab: "lessons") => void;
}) {
  const latest = course.plan;
  const [viewing, setViewing] = useState<CoursePlan | null>(null); // an older version, read-only
  const [versions, setVersions] = useState<PlanVersion[] | null>(null);
  const [changes, setChanges] = useState<OutlineChange[] | null>(null);
  const [editing, setEditing] = useState<Editing>(null);
  const [removing, setRemoving] = useState<{ id: string; title: string } | null>(null);
  const [composing, setComposing] = useState(false);
  const plan = viewing ?? latest;
  const readOnly = !!viewing || course.busy.plan;
  const rows = plan ? numbered(plan) : [];
  const generated = rows.some((r) => r.lesson.slides || r.lesson.questions);

  async function loadVersions() {
    if (!versions) setVersions(await api.get<PlanVersion[]>(`/projects/${projectId}/plan/versions`).catch(() => []));
  }
  async function pickVersion(v: number) {
    setChanges(null);
    if (!latest || v === latest.version) return setViewing(null);
    setViewing(await api.get<CoursePlan>(`/projects/${projectId}/plan?version=${v}`));
  }
  async function showChanges() {
    if (!plan) return;
    setChanges(changes ? null : await api.get<OutlineChange[]>(`/projects/${projectId}/plan/${plan.id}/changes`));
  }
  async function save(edit: Parameters<Course["editOutline"]>[0]) {
    setEditing(null);
    await course.editOutline(edit);
    setVersions(null);
    setChanges(null);
  }
  function commit() {
    if (!editing || !plan) return;
    const value = editing.value.trim();
    if (!value) return setEditing(null);
    if (editing.kind === "course" && value !== plan.title) return save({ op: "rename_course", title: value });
    if (editing.kind === "module") return save({ op: "rename_module", module_id: editing.id, title: value });
    if (editing.kind === "lesson") return save({ op: "rename_lesson", lesson_id: editing.id, title: value });
    if (editing.kind === "add") return save({ op: "add_lesson", module_id: editing.id, title: value });
    setEditing(null);
  }

  const primary = !latest ? (
    <Button size="sm" variant="accent" disabled={!ready || course.busy.plan} onClick={() => setComposing(true)}><Play /> Generate outline</Button>
  ) : latest.status !== "approved" ? (
    <Button size="sm" variant="accent" disabled={course.busy.plan} onClick={() => course.approveOutline()}><CheckCircle2 /> Approve outline</Button>
  ) : !generated ? (
    <Button size="sm" variant="accent" disabled={course.busy.lessons} onClick={() => { course.generateLessons(); goTo("lessons"); }}><Play /> Generate lessons</Button>
  ) : (
    <Button size="sm" variant="accent" onClick={() => goTo("lessons")}>Go to lessons <ArrowRight /></Button>
  );
  const objectiveText = Object.fromEntries((plan?.learning_objectives ?? []).map((o) => [o.id, o]));

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      {course.error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{course.error}</p>}
      {course.busy.plan && <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{course.jobs.plan?.message ?? "Queued: waiting for the worker"}</p>}

      {latest === undefined ? null : !plan ? (
        <div className="mx-auto max-w-md space-y-3 py-16 text-center">
          <h2 className="text-base font-semibold">No outline yet</h2>
          <p className="text-sm text-muted-foreground">{ready ? "The outline sets the modules, lessons and objectives, drawn from every ready source and the course brief." : "Add a source and wait for it to finish ingesting first."}</p>
          <div className="flex justify-center">{primary}</div>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Course outline</p>
              <Inline
                label="the course" className="text-lg font-semibold leading-snug"
                editing={editing?.kind === "course"} value={editing?.kind === "course" ? editing.value : plan.title}
                onStart={readOnly ? undefined : () => setEditing({ kind: "course", id: plan.id, value: plan.title })}
                onChange={(v) => setEditing((e) => e && { ...e, value: v })} onSave={commit} onCancel={() => setEditing(null)}
              />
              {plan.summary && <p className="text-sm text-muted-foreground">{plan.summary}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <select
                aria-label="Outline version" value={plan.version} onFocus={loadVersions} onMouseDown={loadVersions}
                onChange={(e) => pickVersion(Number(e.target.value))}
                className="h-8 rounded-md border bg-surface px-2 text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {(versions ?? [{ version: plan.version, status: plan.status } as PlanVersion]).map((v) => (
                  <option key={v.version} value={v.version}>v{v.version} · {v.status}{latest && v.version === latest.version ? " (latest)" : ""}</option>
                ))}
              </select>
              {!viewing && <Button size="sm" variant="outline" disabled={course.busy.plan || !ready} onClick={() => setComposing(true)}><RotateCw /> Rebuild outline…</Button>}
              {!viewing && primary}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge tone={statusTone(plan.status)}>{plan.status}</Badge>
            <span>v{plan.version} · {new Date(plan.created_at).toLocaleDateString()}</span>
            {plan.meta?.note && <span>· {plan.meta.note}{plan.meta.edited_from ? ` from v${plan.meta.edited_from}` : ""}</span>}
            {plan.meta?.instructions && <span className="max-w-md truncate" title={plan.meta.instructions}>· “{plan.meta.instructions}”</span>}
            {plan.version > 1 && <button className="underline decoration-dotted underline-offset-4 hover:text-foreground" onClick={showChanges}>{changes ? "Hide changes" : "What changed"}</button>}
          </div>
          {viewing && (
            <p className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted px-3 py-2 text-xs">
              <span>You are viewing v{viewing.version}. Changes go to the latest version.</span>
              <Button size="sm" variant="ghost" className="h-7" onClick={() => pickVersion(latest?.version ?? viewing.version)}>Back to v{latest?.version}</Button>
            </p>
          )}
          {changes && (
            <ul className="space-y-1 rounded-md border bg-surface p-3 text-xs">
              {changes.length === 0 && <li className="text-muted-foreground">Same lessons as the version before.</li>}
              {changes.map((c, i) => (
                <li key={i} className="flex gap-2"><Badge tone={c.kind === "removed" ? "destructive" : c.kind === "added" ? "success" : "neutral"}>{c.kind}</Badge>{c.detail}</li>
              ))}
            </ul>
          )}

          {!viewing && plan.new_sources.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/50 bg-warning/10 px-3 py-2 text-sm">
              <span className="flex items-center gap-1.5"><TriangleAlert className="size-4 text-warning" />
                <span><span className="font-medium">{plan.new_sources.map((s) => s.filename).join(", ")}</span> {plan.new_sources.length === 1 ? "is" : "are"} not in this course yet.</span>
              </span>
              <span className="flex gap-1.5">
                <Button size="sm" variant="outline" disabled={latest?.status !== "approved" || course.busy.lessons} onClick={() => { course.generateLessons(); goTo("lessons"); }}>Regenerate lessons only</Button>
                <Button size="sm" variant="accent" disabled={course.busy.plan} onClick={() => setComposing(true)}>Rebuild outline…</Button>
              </span>
            </div>
          )}

          {project && (
            <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-md border bg-surface px-3 py-2 text-xs text-muted-foreground">
              <span><span className="font-medium text-foreground">For</span> {project.target_audience || "no audience set"}</span>
              {project.duration_minutes && <span><span className="font-medium text-foreground">Length</span> {project.duration_minutes} min</span>}
              {project.learning_goals && <span><span className="font-medium text-foreground">Goals</span> {project.learning_goals}</span>}
            </div>
          )}

          {[...plan.modules].sort((a, b) => a.position - b.position).map((m) => {
            const lessons = [...m.lessons].sort((a, b) => a.position - b.position);
            return (
              <section key={m.id} className="overflow-hidden rounded-md border bg-surface">
                <div className="flex items-center justify-between gap-3 border-b bg-muted/60 px-3 py-2">
                  <Inline
                    label={`module ${m.position}`} className="text-sm font-semibold"
                    editing={editing?.kind === "module" && editing.id === m.id} value={editing?.kind === "module" && editing.id === m.id ? editing.value : `Module ${m.position} · ${m.title}`}
                    onStart={readOnly ? undefined : () => setEditing({ kind: "module", id: m.id, value: m.title })}
                    onChange={(v) => setEditing((e) => e && { ...e, value: v })} onSave={commit} onCancel={() => setEditing(null)}
                  />
                  <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{lessons.length} lessons · {lessons.reduce((n, l) => n + (l.estimated_minutes ?? 0), 0)} min</span>
                </div>
                <ul className="divide-y">
                  {lessons.map((l, i) => {
                    const state = lessonState(l);
                    const isEditing = editing?.kind === "lesson" && editing.id === l.id;
                    return (
                      <li key={l.id} className="group flex items-start gap-3 px-3 py-2.5 hover:bg-muted/40">
                        <span className="w-7 shrink-0 pt-0.5 font-mono text-[11px] text-muted-foreground">{m.position}.{l.position}</span>
                        <div className="min-w-0 flex-1">
                          <Inline
                            label={`lesson ${m.position}.${l.position}`} className="text-sm font-medium"
                            editing={isEditing} value={isEditing ? editing.value : l.title}
                            onStart={readOnly ? undefined : () => setEditing({ kind: "lesson", id: l.id, value: l.title })}
                            onChange={(v) => setEditing((e) => e && { ...e, value: v })} onSave={commit} onCancel={() => setEditing(null)}
                          />
                          <p className="text-xs text-muted-foreground">
                            {l.objective_ids.map((id) => objectiveText[id]).filter(Boolean).map((o) => `${o.text} · ${o.bloom_level}`).join("; ") || "No objective linked"}
                          </p>
                        </div>
                        {!readOnly && (
                          <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
                            <Button size="icon" variant="ghost" className="size-7" aria-label={`Move ${l.title} up`} disabled={i === 0} onClick={() => save({ op: "move_lesson", lesson_id: l.id, delta: -1 })}><ArrowUp /></Button>
                            <Button size="icon" variant="ghost" className="size-7" aria-label={`Move ${l.title} down`} disabled={i === lessons.length - 1} onClick={() => save({ op: "move_lesson", lesson_id: l.id, delta: 1 })}><ArrowDown /></Button>
                            <Button size="icon" variant="ghost" className="size-7" aria-label={`Rename ${l.title}`} onClick={() => setEditing({ kind: "lesson", id: l.id, value: l.title })}><Pencil /></Button>
                            <Button size="icon" variant="ghost" className="size-7" aria-label={`Remove ${l.title}`} onClick={() => setRemoving({ id: l.id, title: l.title })}><Trash2 /></Button>
                          </span>
                        )}
                        <span className="flex shrink-0 items-center gap-2">
                          {l.estimated_minutes ? <span className="font-mono text-[11px] text-muted-foreground">{l.estimated_minutes} min</span> : null}
                          <button onClick={() => onOpenLesson(l.id)} className="rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" title="Open in Lessons">
                            <Badge tone={state.tone}>{state.label}</Badge>
                          </button>
                        </span>
                      </li>
                    );
                  })}
                  {!readOnly && (
                    <li className="px-3 py-2">
                      {editing?.kind === "add" && editing.id === m.id ? (
                        <Inline label="the new lesson" editing value={editing.value} onChange={(v) => setEditing((e) => e && { ...e, value: v })} onSave={commit} onCancel={() => setEditing(null)} className="text-sm" />
                      ) : (
                        <button className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground" onClick={() => setEditing({ kind: "add", id: m.id, value: "" })}><Plus className="size-3.5" /> Add lesson</button>
                      )}
                    </li>
                  )}
                </ul>
              </section>
            );
          })}

          <section className="rounded-md border bg-surface">
            <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-2">
              <h3 className="text-sm font-semibold">Objectives and where they are taught</h3>
              <span className="font-mono text-[11px] text-muted-foreground">{plan.learning_objectives.length} objectives</span>
            </div>
            <ul className="divide-y text-sm">
              {plan.learning_objectives.map((o) => {
                const taught = rows.filter((r) => r.lesson.objective_ids.includes(o.id)).map((r) => r.index);
                return (
                  <li key={o.id} className="flex items-start gap-3 px-3 py-2">
                    <span className="w-7 shrink-0 font-mono text-[11px] text-muted-foreground">{o.id}</span>
                    <span className="min-w-0 flex-1">{o.text}</span>
                    <Badge tone={taught.length ? "neutral" : "warning"}>{taught.length ? `${taught.join(", ")} · ${o.bloom_level}` : "not taught"}</Badge>
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}

      {composing && (
        <Composer
          title={latest ? "Rebuild outline" : "Generate outline"}
          scopes={[{
            key: "outline",
            label: "The course outline: modules, lessons and objectives",
            action: latest ? "Rebuild outline" : "Generate outline",
            impact: latest
              ? `Creates outline v${latest.version + 1} as a draft for you to approve. The current lessons stay with v${latest.version} until then.`
              : "Drafts the outline from every ready source and the course brief, for you to approve.",
          }]}
          onClose={() => setComposing(false)}
          onSubmit={(_, steering) => course.generateOutline(steering)}
        />
      )}
      <Dialog open={!!removing} onClose={() => setRemoving(null)} title={`Remove “${removing?.title ?? ""}”?`}>
        <p className="text-sm text-muted-foreground">
          {latest?.status === "approved" ? `This creates outline v${(latest?.version ?? 0) + 1} without it, for you to approve. v${latest?.version} keeps the lesson.` : "Its slides and quiz are removed with it."}
        </p>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setRemoving(null)}>Cancel</Button>
          <Button size="sm" variant="destructive" onClick={() => { if (removing) save({ op: "remove_lesson", lesson_id: removing.id }); setRemoving(null); }}><Trash2 /> Remove lesson</Button>
        </div>
      </Dialog>
    </div>
  );
}
