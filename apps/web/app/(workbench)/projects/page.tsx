"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FileText, Plus } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Project } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", target_audience: "", duration_minutes: "", learning_goals: "" });

  const load = () => api.get<Project[]>("/projects").then(setProjects);
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    await api.post("/projects", { ...form, duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null });
    setCreating(false);
    setForm({ name: "", description: "", target_audience: "", duration_minutes: "", learning_goals: "" });
    load();
  }

  return (
    <Shell
      title="Projects"
      actions={
        <Button size="sm" variant="accent" onClick={() => setCreating((v) => !v)}>
          <Plus /> New project
        </Button>
      }
    >
      <div className="container space-y-6 py-6">
        {creating && (
          <Card className="animate-fade-in">
            <CardHeader>
              <CardTitle>Course brief</CardTitle>
              <CardDescription>The planner uses audience, duration and goals to shape objectives and syllabus.</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={create} className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1.5 md:col-span-2">
                  <Label>Project name</Label>
                  <Input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Target audience</Label>
                  <Input placeholder="e.g. new field technicians" value={form.target_audience} onChange={(e) => setForm({ ...form, target_audience: e.target.value })} />
                </div>
                <div className="space-y-1.5">
                  <Label>Duration (minutes)</Label>
                  <Input type="number" min={5} value={form.duration_minutes} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })} />
                </div>
                <div className="space-y-1.5 md:col-span-2">
                  <Label>Learning goals</Label>
                  <Textarea value={form.learning_goals} onChange={(e) => setForm({ ...form, learning_goals: e.target.value })} />
                </div>
                <div className="flex gap-2 md:col-span-2">
                  <Button type="submit" variant="accent">Create</Button>
                  <Button type="button" variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
                </div>
              </form>
            </CardContent>
          </Card>
        )}

        {projects === null ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}
          </div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border border-dashed p-10 text-center text-sm text-muted-foreground">No projects yet. Create one and upload your first source document.</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {projects.map((p) => (
              <Link key={p.id} href={`/projects/${p.id}`} className="group">
                <Card className="h-full transition-colors group-hover:border-accent/60">
                  <CardHeader>
                    <CardTitle className="truncate">{p.name}</CardTitle>
                    <CardDescription className="line-clamp-2">{p.description || p.learning_goals || "No brief yet"}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex items-center justify-between text-xs text-muted-foreground">
                    <span className="flex items-center gap-1"><FileText className="size-3.5" /> {p.sources.length} sources</span>
                    <span className="flex items-center gap-2">
                      {p.sources.some((s) => s.status === "failed") && <Badge tone="destructive">failed</Badge>}
                      {timeAgo(p.updated_at)}
                    </span>
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </div>
    </Shell>
  );
}
