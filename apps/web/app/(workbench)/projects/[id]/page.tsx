"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { FileUp, RefreshCw, Search, Trash2 } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { PaneHeader, ThreePane } from "@/components/layout/three-pane";
import { CoursePanel, type Inspected } from "@/components/course-panel";
import { PipelineStepper, type Stage } from "@/components/pipeline-stepper";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { api, watchJob, type Job, type Project, type SearchHit } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

export default function ProjectWorkbench({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [project, setProject] = useState<Project | null>(null);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [selected, setSelected] = useState<Inspected | null>(null);
  const [tab, setTab] = useState<"sources" | "course">("sources");
  const [stage, setStage] = useState<{ current: Stage; done: Stage[] }>({ current: "Ingest", done: [] });
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

  return (
    <Shell
      title={project ? project.name : <Skeleton className="h-4 w-40" />}
      actions={<PipelineStepper current={stage.current} done={stage.done} />}
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
                      <span className="min-w-0 truncate font-medium" title={s.filename}>{s.filename}</span>
                      <Badge tone={statusTone(s.status)}>{s.status}</Badge>
                    </div>
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span className="font-mono">{formatBytes(s.size_bytes)}{s.page_count ? ` · ${s.page_count}p` : ""}{s.chunk_count ? ` · ${s.chunk_count} chunks` : ""}</span>
                      <span className="flex gap-1">
                        <button title="Re-ingest" className="hover:text-foreground" onClick={() => api.post(`/projects/${id}/sources/${s.id}/reingest`).then(load)}><RefreshCw className="size-3.5" /></button>
                        <button title="Delete" className="hover:text-destructive" onClick={() => confirm(`Delete ${s.filename}?`) && api.del(`/projects/${id}/sources/${s.id}`).then(load)}><Trash2 className="size-3.5" /></button>
                      </span>
                    </div>
                    {job && (
                      <div className="space-y-1">
                        <Progress value={job.progress_total ? (job.progress_current / job.progress_total) * 100 : 5} />
                        <p className="truncate text-[11px] text-muted-foreground">{job.message ?? "queued"}</p>
                      </div>
                    )}
                    {s.error && <p className="text-[11px] text-destructive">{s.error}</p>}
                  </li>
                );
              })}
              {project && project.sources.length === 0 && <li className="p-6 text-center text-xs text-muted-foreground">Upload PDF, DOCX, PPTX or Markdown to build the knowledge base.</li>}
            </ul>
          </>
        }
        center={
          <div>
            <div role="tablist" aria-label="Workbench view" className="flex gap-1 border-b px-6 pt-3">
              {(["sources", "course"] as const).map((t) => (
                <button
                  key={t}
                  role="tab"
                  aria-selected={tab === t}
                  onClick={() => setTab(t)}
                  className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize ${tab === t ? "border-accent text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
                >
                  {t}
                </button>
              ))}
            </div>
            {/* Kept mounted while hidden so running jobs keep streaming progress. */}
            <div hidden={tab !== "course"}>
              <CoursePanel projectId={id} ready={!!ready} onStage={setStage} onInspect={setSelected} />
            </div>
          <div hidden={tab !== "sources"} className="mx-auto max-w-3xl space-y-6 p-6">
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
    </Shell>
  );
}
