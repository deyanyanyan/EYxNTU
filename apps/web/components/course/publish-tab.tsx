"use client";

import Link from "next/link";
import { CheckCircle2, CircleAlert, Download, MonitorPlay, Play } from "lucide-react";
import { isGenerated, lessonFlags, numbered } from "@/components/course/lesson-status";
import { messageOf, type Course } from "@/components/course/use-course";
import { Button } from "@/components/ui/button";
import { downloadFile, type CourseExport } from "@/lib/api";

/** Export, the in-app preview and the export history, with what is still open shown first. None of it blocks an export. */
export function PublishTab({ projectId, course, goTo }: { projectId: string; course: Course; goTo: (tab: "lessons" | "outline") => void }) {
  const plan = course.plan;
  const rows = plan ? numbered(plan) : [];
  const generated = rows.filter((r) => isGenerated(r.lesson));
  const flags = generated.reduce((n, r) => n + lessonFlags(r.lesson), 0);
  const waiting = generated.reduce((n, r) => n + r.lesson.proposals, 0);
  const approved = generated.filter((r) => r.lesson.approved).length;
  const latest = course.exports[0];
  const checks: { ok: boolean; text: string; go?: "lessons" | "outline" }[] = plan
    ? [
        { ok: plan.status === "approved", text: plan.status === "approved" ? `Outline v${plan.version} approved` : `Outline v${plan.version} is waiting for approval`, go: "outline" },
        { ok: generated.length === rows.length, text: `${generated.length} of ${rows.length} lessons generated`, go: "lessons" },
        { ok: flags === 0, text: flags ? `${flags} flagged ${flags === 1 ? "issue" : "issues"} open` : "No open flags", go: "lessons" },
        ...(waiting ? [{ ok: false, text: `${waiting} proposed ${waiting === 1 ? "change" : "changes"} waiting`, go: "lessons" as const }] : []),
        { ok: approved === generated.length && generated.length > 0, text: `${approved} of ${generated.length} lessons approved`, go: "lessons" },
      ]
    : [];

  async function download(x: CourseExport, kind: "scorm" | "pptx") {
    try {
      await downloadFile(`/projects/${projectId}/exports/${x.id}/files/${kind}`, kind === "scorm" ? "course_scorm12.zip" : "course.pptx");
    } catch (e) {
      course.setError(messageOf(e));
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      {course.error && <p className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{course.error}</p>}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Publish</p>
          <h2 className="text-lg font-semibold">{plan ? `${generated.length} lessons · ${generated.reduce((n, r) => n + r.lesson.questions, 0)} quiz questions` : "Nothing to publish yet"}</h2>
          <p className="text-sm text-muted-foreground">An editable PowerPoint and a SCORM 1.2 package, one unit per lesson, that an LMS can import.</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {latest && (
            <Button size="sm" variant="outline" asChild><Link href={`/learn/${projectId}/${latest.id}`}><MonitorPlay /> Preview as a learner</Link></Button>
          )}
          <Button size="sm" variant="accent" disabled={!generated.length || course.busy.export || course.busy.lessons} onClick={() => course.exportCourse()}>
            <Play /> {course.busy.export ? "Exporting…" : "Export PowerPoint and SCORM"}
          </Button>
        </div>
      </div>

      {checks.length > 0 && (
        <ul className="grid gap-x-6 gap-y-1.5 rounded-md border bg-surface px-4 py-3 text-sm sm:grid-cols-2">
          {checks.map((c) => (
            <li key={c.text} className="flex items-center gap-2">
              {c.ok ? <CheckCircle2 className="size-4 shrink-0 text-success" /> : <CircleAlert className="size-4 shrink-0 text-warning" />}
              {c.ok || !c.go ? <span>{c.text}</span> : <button className="text-left underline decoration-dotted underline-offset-4 hover:text-foreground" onClick={() => goTo(c.go!)}>{c.text}</button>}
            </li>
          ))}
        </ul>
      )}
      {course.busy.export && <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">{course.jobs.export?.message ?? "Queued: waiting for the worker"}</p>}

      <section className="overflow-hidden rounded-md border bg-surface">
        <div className="flex items-center justify-between border-b bg-muted/60 px-3 py-2">
          <h3 className="text-sm font-semibold">Exports</h3>
          <span className="font-mono text-[11px] text-muted-foreground">{course.exports.length}</span>
        </div>
        {course.exports.length === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground">No exports yet.</p>
        ) : (
          <ul className="divide-y text-sm">
            {course.exports.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                <span className="min-w-0">
                  <span className="font-mono text-[11px] text-muted-foreground">{new Date(x.created_at).toLocaleString()} · plan v{x.content?.plan_version} · {x.content?.lessons} lessons</span>
                  {x.content?.includes_unapproved && <span className="ml-2 text-[11px] text-warning">includes unapproved lessons</span>}
                </span>
                <span className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" asChild><Link href={`/learn/${projectId}/${x.id}`}><MonitorPlay /> Preview</Link></Button>
                  <Button size="sm" variant="ghost" onClick={() => download(x, "scorm")}><Download /> SCORM</Button>
                  <Button size="sm" variant="ghost" onClick={() => download(x, "pptx")}><Download /> PPTX</Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
