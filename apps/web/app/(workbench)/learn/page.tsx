"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { MonitorPlay } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/hooks/use-session";
import { api, type CourseExport, type Project } from "@/lib/api";

type Course = { project: Project; latest: CourseExport; count: number };

/**
 * Exported SCORM packages, each playable in the browser as a learner would see it in an LMS.
 * Learners have no access yet: there is no step that publishes a course to them.
 */
export default function LearnPage() {
  const { user, ready } = useSession();
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const author = user?.role === "admin" || user?.role === "instructor";

  useEffect(() => {
    if (!author) return;
    api
      .get<Project[]>("/projects")
      .then((projects) => Promise.all(projects.map(async (project) => ({ project, exports: await api.get<CourseExport[]>(`/projects/${project.id}/exports`) }))))
      .then((rows) => setCourses(rows.filter((r) => r.exports.length).map((r) => ({ project: r.project, latest: r.exports[0], count: r.exports.length }))))
      .catch((e: Error) => setError(e.message));
  }, [author]);

  return (
    <Shell title="Learn">
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <div>
          <h1 className="text-base font-semibold">Course previews</h1>
          <p className="text-sm text-muted-foreground">
            Each course plays from its exported SCORM package, exactly as an LMS would deliver it: step through the lessons, take the quizzes,
            and see what the package reports. Nothing is saved.
          </p>
        </div>
        {!ready ? null : !author ? (
          <p className="rounded-md border bg-surface p-4 text-sm text-muted-foreground">Courses will appear here once an instructor publishes them to learners. Publishing is not available yet.</p>
        ) : error ? (
          <p className="text-sm text-destructive">Could not load courses: {error}</p>
        ) : !courses ? (
          <Skeleton className="h-24 w-full" />
        ) : courses.length === 0 ? (
          <p className="rounded-md border bg-surface p-4 text-sm text-muted-foreground">No course has been exported yet. Export one from its project&apos;s Course tab to preview it here.</p>
        ) : (
          <ul className="space-y-2">
            {courses.map(({ project, latest, count }) => (
              <li key={project.id} className="flex items-center justify-between gap-4 rounded-md border bg-surface p-4">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{latest.content?.course_title ?? project.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{project.name}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
                    <span>{latest.content?.lessons ?? 0} lessons · {latest.content?.questions ?? 0} questions · exported {new Date(latest.created_at).toLocaleString()}</span>
                    {count > 1 && <span>· {count} exports, latest shown</span>}
                    {latest.content?.includes_unapproved && <Badge tone="warning">unreviewed content</Badge>}
                  </p>
                </div>
                <Button size="sm" variant="accent" asChild>
                  <Link href={`/learn/${project.id}/${latest.id}`}><MonitorPlay /> Preview</Link>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Shell>
  );
}
