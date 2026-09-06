"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/layout/shell";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { api, type Job } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

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
              <th className="py-2 pr-3 font-medium">Kind</th>
              <th className="py-2 pr-3 font-medium">Status</th>
              <th className="py-2 pr-3 font-medium">Progress</th>
              <th className="py-2 pr-3 font-medium">Message</th>
              <th className="py-2 pr-3 font-medium">Created</th>
              <th className="py-2 font-medium"></th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {jobs.map((j) => (
              <tr key={j.id} className="align-top">
                <td className="py-2 pr-3 font-mono text-xs">{j.kind}</td>
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
            ))}
            {jobs.length === 0 && (
              <tr><td colSpan={6} className="py-10 text-center text-xs text-muted-foreground">No recent jobs.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Shell>
  );
}
