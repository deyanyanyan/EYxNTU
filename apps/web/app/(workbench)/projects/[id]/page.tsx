"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { Eye, FileUp, RefreshCw, Search, Trash2 } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PaneHeader, ThreePane } from "@/components/layout/three-pane";
import type { Inspected } from "@/components/course/lesson-pane";
import { isGenerated, lessonFlags, numbered } from "@/components/course/lesson-status";
import { LessonsTab } from "@/components/course/lessons-tab";
import { OutlineTab } from "@/components/course/outline-tab";
import { PublishTab } from "@/components/course/publish-tab";
import { useCourse } from "@/components/course/use-course";
import { SourceViewer } from "@/components/source-viewer";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Dialog } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { api, watchJob, type Job, type Project, type SearchHit, type Source, type SourceUsage } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

export default function ProjectWorkbench({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [selected, setSelected] = useState<Inspected | null>(null);
  const [tab, setTab] = useState<Tab>("sources");
  const [lessonId, setLessonId] = useState<string | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<{ source: Source; usage: SourceUsage | null; busy: boolean; error: string | null } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.get<Project>(`/projects/${id}`).then(setProject), [id]);
  useEffect(() => {
    load();
  }, [load]);

  // follow active ingest jobs for this project
  useEffect(() => {
    let stops: Array<() => void> = [];
    api.get<Job[]>(`/jobs?project_id=${id}&recent_minutes=5`).then((list) => {
      stops = list
        .filter((j) => j.status === "pending" || j.status === "running")
        .map((j) => watchJob(j.id, (u) => setJobs((m) => ({ ...m, [u.id]: u })), load));
    });
    return () => stops.forEach((s) => s());
  }, [id, load]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append("file", f);
      await api.post(`/projects/${id}/sources`, fd);
    }
    await load();
    const list = await api.get<Job[]>(`/jobs?project_id=${id}&recent_minutes=1`);
    list.filter((j) => j.status !== "completed").forEach((j) => watchJob(j.id, (u) => setJobs((m) => ({ ...m, [u.id]: u })), load));
  }

  async function search(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setHits(await api.post<SearchHit[]>(`/projects/${id}/search`, { query }));
  }

  const ready = project?.sources.some((s) => s.status === "ready");
  const sourcesKey = project?.sources.map((s) => `${s.id}:${s.status}`).join(",");
  const course = useCourse(id, sourcesKey);
  const outdated = (course.plan?.new_sources ?? []).map((s) => s.id);
  const openLesson = (lesson: string) => {
    setLessonId(lesson);
    setTab("lessons");
  };
  const viewing = project?.sources.find((s) => s.id === viewingId) ?? null;
  async function askDelete(source: Source) {
    setDeleting({ source, usage: null, busy: false, error: null });
    const usage = await api.get<SourceUsage>(`/projects/${id}/sources/${source.id}/usage`).catch(() => ({ in_course: false, lessons: [] }));
    setDeleting((d) => (d?.source.id === source.id ? { ...d, usage } : d));
  }

  // Deleting a source the course draws on: keep the course as it is, or plan it again without the source.
  async function remove(regenerate: boolean) {
    if (!deleting) return;
    setDeleting({ ...deleting, busy: true, error: null });
    try {
      await api.del(`/projects/${id}/sources/${deleting.source.id}`);
    } catch (e) {
      setDeleting((d) => d && { ...d, busy: false, error: `Could not delete it: ${(e as Error).message}` });
      return;
    }
    await load();
    if (regenerate) {
      if (!(await course.generateOutline())) {
        setDeleting((d) => d && { ...d, busy: false, error: "Deleted, but the outline could not be rebuilt. See the Outline tab." });
        return;
      }
      setTab("outline");
    }
    setDeleting(null);
  }

  const view = (sourceId: string) => {
    setViewingId(sourceId);
    setTab("sources");
  };

  return (
    <Shell
      title={project ? project.name : <Skeleton className="h-4 w-40" />}
    >
      <ThreePane
        left={
          <>
            <PaneHeader right={<Button size="sm" variant="ghost" onClick={() => fileRef.current?.click()}><FileUp /> Add</Button>}>Sources</PaneHeader>
            <input ref={fileRef} type="file" multiple accept=".pdf,.docx,.pptx,.md,.txt" className="hidden" onChange={(e) => upload(e.target.files)} />
            <ul className="divide-y">
              {project?.sources.map((s) => {
                const job = Object.values(jobs).find((j) => j.payload.source_id === s.id && (j.status === "running" || j.status === "pending"));
                return (
                  <li key={s.id} className="space-y-1.5 p-3 text-sm">
                    <div className="flex items-start justify-between gap-2">
                      <button className="min-w-0 truncate text-left font-medium hover:underline" title={`View ${s.filename}`} onClick={() => view(s.id)}>{s.filename}</button>
                      <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span className="font-mono">{formatBytes(s.size_bytes)}{s.page_count ? ` · ${s.page_count}p` : ""}{s.chunk_count ? ` · ${s.chunk_count} chunks` : ""}</span>
                      <span className="flex gap-1">
                        <button title="View" className="hover:text-foreground" onClick={() => view(s.id)}><Eye className="size-3.5" /></button>
                        <button title="Re-ingest" className="hover:text-foreground" onClick={() => api.post(`/projects/${id}/sources/${s.id}/reingest`).then(load)}><RefreshCw className="size-3.5" /></button>
                        <button title="Delete" className="hover:text-destructive" onClick={() => askDelete(s)}><Trash2 className="size-3.5" /></button>
                      </span>
                    </div>
                    {job && (
                      <div className="space-y-1">
                        <Progress value={job.progress_total ? (job.progress_current / job.progress_total) * 100 : 5} />
                        <p className="truncate text-[11px] text-muted-foreground">{job.message ?? "queued"}</p>
                      </div>
                    )}
                    {s.error && <p className="text-[11px] text-destructive">{s.error}</p>}
                    {outdated.includes(s.id) && (
                      <button className="text-left text-[11px] text-warning hover:underline" title="Rebuild the outline or regenerate the lessons to include it" onClick={() => setTab("outline")}>Not in the course yet</button>
                    )}
                  </li>
                );
              })}
              {project && project.sources.length === 0 && <li className="p-6 text-center text-xs text-muted-foreground">Upload PDF, DOCX, PPTX or Markdown to build the knowledge base.</li>}
            </ul>
          </>
        }
        center={
          <div className="flex min-h-full flex-col">
            <div role="tablist" aria-label="Course stages" className="flex flex-wrap gap-1 border-b px-6 pt-3">
              {stageTabs(project, course).map((t) => (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={tab === t.key}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium ${tab === t.key ? "border-accent text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                >
                  {t.label}
                  {t.badge && <Badge tone={t.tone}>{t.badge}</Badge>}
                  {t.key === "outline" && outdated.length > 0 && <span className="inline-block size-1.5 rounded-full bg-warning" title="New sources are not in this course yet" />}
                </button>
              ))}
            </div>
            {tab === "outline" && <OutlineTab projectId={id} project={project} course={course} ready={!!ready} onOpenLesson={openLesson} goTo={setTab} />}
            {tab === "lessons" && <LessonsTab projectId={id} course={course} selected={lessonId} onSelect={setLessonId} onInspect={setSelected} goTo={setTab} />}
            {tab === "publish" && <PublishTab projectId={id} course={course} goTo={setTab} />}
          {viewing && tab === "sources" && <SourceViewer projectId={id} source={viewing} onClose={() => setViewingId(null)} />}
          <div hidden={tab !== "sources" || !!viewing} className="mx-auto w-full max-w-3xl space-y-6 p-6">
            <div>
              <h2 className="text-base font-semibold">Knowledge base</h2>
              <p className="text-sm text-muted-foreground">Every generated block will cite one of these chunks. Search to verify what the model can see.</p>
            </div>
            <form onSubmit={search} className="flex gap-2">
              <Input placeholder="Ask the sources…" value={query} onChange={(e) => setQuery(e.target.value)} disabled={!ready} />
              <Button type="submit" variant="accent" disabled={!ready}><Search /> Search</Button>
            </form>
            {hits && hits.length === 0 && <p className="text-sm text-muted-foreground">No chunks above the similarity threshold.</p>}
            <ul className="space-y-2">
              {hits?.map((h, i) => (
                <li key={h.chunk_id}>
                  <button onClick={() => setSelected(h)} className={`w-full rounded-md border p-3 text-left text-sm transition-colors hover:border-accent/60 ${selected?.chunk_id === h.chunk_id ? "border-accent bg-accent-soft/40" : "bg-surface"}`}>
                    <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      <span className="citation-chip">[{i + 1}]</span>
                      <span className="truncate">{h.source_name}{h.heading_path ? ` › ${h.heading_path}` : ""}{h.page_start ? ` · p.${h.page_start}` : ""}</span>
                      <span className="font-mono">{h.similarity.toFixed(2)}</span>
                    </div>
                    <p className="line-clamp-3 whitespace-pre-line">{h.text}</p>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          </div>
        }
        right={
          <>
            <PaneHeader>Inspector</PaneHeader>
            {selected ? (
              <div className="space-y-3 p-3 text-sm">
                <div className="space-y-1 text-xs text-muted-foreground">
                  <div><span className="font-medium text-foreground">Source</span> {selected.source_name}</div>
                  {selected.heading_path && <div><span className="font-medium text-foreground">Section</span> {selected.heading_path}</div>}
                  {selected.page_start && <div><span className="font-medium text-foreground">Pages</span> {selected.page_start}{selected.page_end && selected.page_end !== selected.page_start ? `–${selected.page_end}` : ""}</div>}
                  {selected.similarity !== null && <div><span className="font-medium text-foreground">Similarity</span> <span className="font-mono">{selected.similarity}</span></div>}
                  <div><span className="font-medium text-foreground">Chunk</span> <span className="font-mono">{selected.chunk_id.slice(0, 8)}</span></div>
                </div>
                {selected.quote && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium">Quoted as evidence</p>
                    <blockquote className="border-l-2 border-accent pl-2 text-xs">{selected.quote}</blockquote>
                  </div>
                )}
                <pre className="whitespace-pre-wrap rounded-md border bg-muted/50 p-3 font-sans text-xs leading-relaxed">{selected.text}</pre>
              </div>
            ) : (
              <div className="p-6 text-center text-xs text-muted-foreground">
                {project && (
                  <div className="space-y-2 text-left">
                    <p className="font-medium text-foreground">Course brief</p>
                    <p><span className="text-foreground">Audience:</span> {project.target_audience || "—"}</p>
                    <p><span className="text-foreground">Duration:</span> {project.duration_minutes ? `${project.duration_minutes} min` : "—"}</p>
                    <p><span className="text-foreground">Goals:</span> {project.learning_goals || "—"}</p>
                    <p className="pt-2 opacity-70">Select a search result or a citation to inspect its provenance. Course planning unlocks once at least one source is ready.</p>
                  </div>
                )}
              </div>
            )}
          </>
        }
      />
      <Dialog open={!!deleting} onClose={() => !deleting?.busy && setDeleting(null)} title={`Delete ${deleting?.source.filename ?? "source"}?`}>
        {deleting && !deleting.usage ? (
          <Skeleton className="h-20 w-full" />
        ) : deleting?.usage?.in_course ? (
          <>
            <p className="text-sm text-muted-foreground">
              {deleting.usage.lessons.length ? (
                <>Used in {deleting.usage.lessons.length === 1 ? "1 lesson" : `${deleting.usage.lessons.length} lessons`}: <span className="text-foreground">{deleting.usage.lessons.map((l) => l.title).join(", ")}</span></>
              ) : (
                "The course plan draws on it."
              )}
            </p>
            <div className="grid gap-2">
              {[
                { regenerate: false, title: "Keep the course as it is", detail: "Lessons keep what they took from this file." },
                { regenerate: true, title: "Regenerate the course without it", detail: "A new plan from the remaining sources, for you to approve." },
              ].map((o) => (
                <button
                  key={o.title}
                  disabled={deleting.busy}
                  onClick={() => remove(o.regenerate)}
                  className="rounded-md border p-3 text-left transition-colors hover:border-accent hover:bg-accent-soft/40 disabled:opacity-50"
                >
                  <span className="block text-sm font-medium">{o.title}</span>
                  <span className="block text-xs text-muted-foreground">{o.detail}</span>
                </button>
              ))}
            </div>
          </>
        ) : null}
        {deleting?.error && <p className="text-sm text-destructive">{deleting.error}</p>}
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" disabled={deleting?.busy} onClick={() => setDeleting(null)}>{deleting?.error ? "Close" : "Cancel"}</Button>
          {deleting?.usage && !deleting.usage.in_course && !deleting.error && (
            <Button size="sm" variant="destructive" disabled={deleting.busy} onClick={() => remove(false)}><Trash2 /> Delete</Button>
          )}
        </div>
      </Dialog>
    </Shell>
  );
}

type Tab = "sources" | "outline" | "lessons" | "publish";
type Tone = "neutral" | "accent" | "success" | "warning";

/** The stage tabs and the one status each shows, so the state of the course reads from the tab bar. */
function stageTabs(project: Project | null, course: ReturnType<typeof useCourse>): { key: Tab; label: string; badge?: string; tone?: Tone }[] {
  const plan = course.plan;
  const rows = plan ? numbered(plan) : [];
  const generated = rows.filter((r) => isGenerated(r.lesson)).length;
  const flags = rows.reduce((n, r) => n + lessonFlags(r.lesson), 0);
  const waiting = rows.reduce((n, r) => n + r.lesson.proposals, 0);
  const ready = project?.sources.filter((s) => s.status === "ready").length ?? 0;
  const lessons: { badge?: string; tone?: Tone } =
    course.busy.lessons || course.busy.revise ? { badge: "working", tone: "accent" }
    : waiting ? { badge: `${waiting} to review`, tone: "accent" }
    : flags ? { badge: `${flags} flags`, tone: "warning" }
    : rows.length && generated === rows.length && rows.every((r) => r.lesson.approved) ? { badge: "approved", tone: "success" }
    : rows.length ? { badge: `${generated}/${rows.length}`, tone: "neutral" } : {};
  const exported = course.exports[0];
  return [
    { key: "sources", label: "Sources", badge: project ? String(ready) : undefined, tone: "neutral" },
    { key: "outline", label: "Outline", ...(plan ? { badge: `v${plan.version} ${plan.status}`, tone: plan.status === "approved" ? "success" : "warning" } : course.busy.plan ? { badge: "working", tone: "accent" } : {}) },
    { key: "lessons", label: "Lessons", ...lessons },
    { key: "publish", label: "Publish", ...(course.busy.export ? { badge: "working", tone: "accent" as Tone } : exported ? { badge: `exported ${new Date(exported.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`, tone: "neutral" as Tone } : {}) },
  ];
}
