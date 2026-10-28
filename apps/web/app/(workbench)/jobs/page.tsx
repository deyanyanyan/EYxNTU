"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Shell } from "@/components/layout/shell";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api, type Job } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

const KIND: Record<string, string> = {
  ingest_source: "Ingest source",
  generate_plan: "Plan course",
  generate_lesson_assets: "Generate lessons",
  critique_asset: "Critique content",
  render_slides: "Render slides",
  render_video: "Render video",
  package_scorm: "Export course",
  eval_run: "Evaluation run",
  revise_content: "Prepare changes",
};

/** What the job worked on: the file it ingested, or what a finished step produced. */
function subject(j: Job): string | null {
  const r = j.result ?? {};
  if (j.kind === "ingest_source") return j.source_name ?? "a deleted source";
  if (j.kind === "generate_plan" && r.version) return `Plan v${r.version}`;
  if (j.kind === "generate_lesson_assets" && typeof r.lessons === "number") return `${r.lessons} lessons`;
  if (j.kind === "package_scorm" && r.plan_version) return `Plan v${r.plan_version} · ${r.lessons} lessons`;
  if (j.kind === "revise_content" && typeof r.proposals === "number") return `${r.proposals} proposed ${r.proposals === 1 ? "change" : "changes"}`;
  return null;
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const load = () => api.get<Job[]>("/jobs?recent_minutes=120").then(setJobs);

  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  return (
    <Shell title="Job centre" actions={<Button size="sm" variant="ghost" onClick={load}>Refresh</Button>}>
      <div className="container py-6">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr className="border-b">
              <th className="py-2 pr-3 font-medium">Job</th>
              <th className="py-2 pr-3 font-medium">Course</th>
              <th className="py-2 pr-3 font-medium">Status</th>
              <th className="py-2 pr-3 font-medium">Progress</th>
              <th className="py-2 pr-3 font-medium">Message</th>
              <th className="py-2 pr-3 font-medium">Created</th>
              <th className="py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {jobs.map((j) => {
              const about = subject(j);
              return (
                <tr key={j.id} className="align-top">
                  <td className="py-2 pr-3">
                    <p title={j.kind}>{KIND[j.kind] ?? j.kind}</p>
                    {about && <p className="max-w-[16rem] truncate font-mono text-[11px] text-muted-foreground" title={about}>{about}</p>}
                  </td>
                  <td className="py-2 pr-3">
                    {j.project_id ? (
                      <Link href={`/projects/${j.project_id}`} className="group block max-w-[18rem]">
                        <p className="truncate group-hover:underline">{j.course_title ?? j.project_name ?? "Deleted project"}</p>
                        {j.course_title && j.project_name && j.project_name !== j.course_title && (
                          <p className="truncate text-[11px] text-muted-foreground">{j.project_name}</p>
                        )}
                        {!j.course_title && j.project_name && <p className="text-[11px] text-muted-foreground">no course yet</p>}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">–</span>
                    )}
                  </td>
                  <td className="py-2 pr-3"><Badge tone={statusTone(j.status)}>{j.status}</Badge></td>
                  <td className="w-40 py-2 pr-3">
                    {j.progress_total > 0 && <Progress value={(j.progress_current / j.progress_total) * 100} className="mt-1.5" />}
                    <span className="font-mono text-[11px] text-muted-foreground">{j.progress_total ? `${j.progress_current}/${j.progress_total}` : ""}</span>
                  </td>
                  <td className="max-w-md py-2 pr-3 text-xs text-muted-foreground">
                    <span className="line-clamp-2">{j.error_message ? <span className="text-destructive">{j.error_message.split("\n")[0]}</span> : j.message}</span>
                  </td>
                  <td className="whitespace-nowrap py-2 pr-3 text-xs text-muted-foreground">{timeAgo(j.created_at)}</td>
                  <td className="py-2 text-right">
                    {(j.status === "pending" || j.status === "running") && (
                      <Button size="sm" variant="ghost" onClick={() => api.post(`/jobs/${j.id}/cancel`).then(load)}>Cancel</Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {jobs.length === 0 && (
              <tr><td colSpan={7} className="py-10 text-center text-xs text-muted-foreground">No recent jobs.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}
