"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/layout/shell";
import { PaneHeader, ThreePane } from "@/components/layout/three-pane";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type PromptVersion } from "@/lib/api";

const TASKS = ["critique", "quiz", "plan", "slides"];
type PromptSet = { task: string; system_prompt: string; templates: Record<string, string>; version_id: string | null };

export default function PromptsPage() {
  const [task, setTask] = useState(TASKS[0]);
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [active, setActive] = useState<PromptSet | null>(null);
  const [draft, setDraft] = useState<{ name: string; system_prompt: string; templates: Record<string, string> } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async () => {
    setVersions(await api.get<PromptVersion[]>(`/prompts?task=${task}`));
    setActive(await api.get<PromptSet>(`/prompts/active/${task}`));
  };
  useEffect(() => {
    load();
    setDraft(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task]);

  function startDraft(from: PromptSet | PromptVersion) {
    setDraft({ name: `${task}-${new Date().toISOString().slice(0, 10)}`, system_prompt: from.system_prompt ?? "", templates: { ...from.templates } });
  }

  async function save() {
    if (!draft) return;
    await api.post("/prompts", { task, ...draft });
    setDraft(null);
    setMsg("Saved as a new version (inactive). Activate it to use it.");
    load();
  }

  return (
    <Shell
      title="Prompt versions"
      actions={
        <select className="h-8 rounded-md border bg-surface px-2 text-xs" value={task} onChange={(e) => setTask(e.target.value)}>
          {TASKS.map((t) => <option key={t}>{t}</option>)}
        </select>
      }
    >
      <ThreePane
        left={
          <>
            <PaneHeader right={active && <Button size="sm" variant="ghost" onClick={() => startDraft(active)}>Fork active</Button>}>Versions · {task}</PaneHeader>
            <ul className="divide-y text-sm">
              <li className="flex items-center justify-between p-3">
                <span>File defaults</span>
                {active?.version_id === null && <Badge tone="accent">active</Badge>}
              </li>
              {versions.map((v) => (
                <li key={v.id} className="space-y-1 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <button className="truncate text-left font-medium hover:underline" onClick={() => startDraft(v)}>{v.name}</button>
                    {v.is_active ? <Badge tone="accent">active</Badge> : <Button size="sm" variant="ghost" onClick={() => api.post(`/prompts/${v.id}/activate`).then(load)}>Activate</Button>}
                  </div>
                  <p className="text-[11px] text-muted-foreground">{v.created_by_name ?? "—"} · {new Date(v.created_at).toLocaleDateString()}</p>
                </li>
              ))}
            </ul>
          </>
        }
        center={
          <div className="mx-auto max-w-3xl space-y-4 p-6">
            {msg && <p className="rounded-md border border-success/40 bg-success/10 p-2 text-xs text-success">{msg}</p>}
            {draft ? (
              <>
                <div className="space-y-1.5"><Label>Version name</Label><Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
                <div className="space-y-1.5"><Label>System prompt</Label><Textarea rows={5} className="font-mono text-xs" value={draft.system_prompt} onChange={(e) => setDraft({ ...draft, system_prompt: e.target.value })} /></div>
                {Object.entries(draft.templates).map(([k, v]) => (
                  <div key={k} className="space-y-1.5">
                    <Label>{k}</Label>
                    <Textarea rows={8} className="font-mono text-xs" value={v} onChange={(e) => setDraft({ ...draft, templates: { ...draft.templates, [k]: e.target.value } })} />
                  </div>
                ))}
                <div className="flex gap-2"><Button variant="accent" onClick={save}>Save as new version</Button><Button variant="ghost" onClick={() => setDraft(null)}>Discard</Button></div>
              </>
            ) : active ? (
              <>
                <h2 className="text-base font-semibold">Active prompt set <span className="font-mono text-xs text-muted-foreground">{active.version_id ? active.version_id.slice(0, 8) : "file defaults"}</span></h2>
                <pre className="whitespace-pre-wrap rounded-md border bg-muted/50 p-3 text-xs">{active.system_prompt}</pre>
                {Object.entries(active.templates).map(([k, v]) => (
                  <details key={k} className="rounded-md border" open>
                    <summary className="cursor-pointer px-3 py-2 text-sm font-medium">{k}</summary>
                    <pre className="whitespace-pre-wrap border-t bg-muted/30 p-3 text-xs">{v}</pre>
                  </details>
                ))}
              </>
            ) : null}
          </div>
        }
        right={
          <>
            <PaneHeader>Placeholders</PaneHeader>
            <div className="space-y-2 p-3 text-xs text-muted-foreground">
              <p>Templates use <code>{"{name}"}</code> placeholders filled at runtime. Unknown braces are left as-is.</p>
              <ul className="list-inside list-disc space-y-1 font-mono">
                <li>{"{rag_context}"}</li><li>{"{content}"}</li><li>{"{audience}"}</li><li>{"{objectives}"}</li><li>{"{count}"} · {"{difficulty_mix}"}</li><li>{"{lesson_title}"} · {"{estimated_minutes}"}</li>
              </ul>
              <p className="pt-2">The prompt-lab A/B comparison (run two versions over the same lesson and diff critique scores) lands in milestone M5.</p>
            </div>
          </>
        }
      />
    </Shell>
  );
}
