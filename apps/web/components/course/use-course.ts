"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, watchJob, type CourseExport, type CoursePlan, type Job, type LessonsRequestBody, type OutlineEdit, type ReviseTarget, type Steering } from "@/lib/api";

/**
 * Course state shared by the Outline, Lessons and Publish tabs: the latest outline, its
 * exports, and the runs (jobs) that change them. Runs are followed until they finish, then
 * the outline and exports are re-read and `contentTick` moves on so an open lesson reloads.
 */
export type Step = "plan" | "lessons" | "revise" | "export";
const JOB_KIND: Record<Step, string> = { plan: "generate_plan", lessons: "generate_lesson_assets", revise: "revise_content", export: "package_scorm" };

export const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));
export const isActive = (j?: Job | null) => j?.status === "pending" || j?.status === "running";

export function useCourse(projectId: string, sourcesKey?: string) {
  const [plan, setPlan] = useState<CoursePlan | null | undefined>(undefined);
  const [exports, setExports] = useState<CourseExport[]>([]);
  const [jobs, setJobs] = useState<Partial<Record<Step, Job>>>({});
  const [error, setError] = useState<string | null>(null);
  const [contentTick, setContentTick] = useState(0);
  const stops = useRef<Array<() => void>>([]);
  const followed = useRef(new Set<string>());

  const loadPlan = useCallback(async () => {
    try {
      setPlan(await api.get<CoursePlan>(`/projects/${projectId}/plan`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPlan(null);
      else setError(messageOf(e));
    }
  }, [projectId]);

  const loadExports = useCallback(() => api.get<CourseExport[]>(`/projects/${projectId}/exports`).then(setExports).catch(() => {}), [projectId]);

  const follow = useCallback(
    (step: Step, job: Job) => {
      if (followed.current.has(job.id)) return;
      followed.current.add(job.id);
      stops.current.push(
        watchJob(job.id, (u) => setJobs((m) => ({ ...m, [step]: u })), () => {
          loadPlan();
          loadExports();
          setContentTick((t) => t + 1);
        }),
      );
    },
    [loadPlan, loadExports],
  );

  // Resume watching runs that are still going, and keep the last result of each step on screen.
  const scanJobs = useCallback(
    () =>
      api.get<Job[]>(`/jobs?project_id=${projectId}&recent_minutes=1440`).then((list) => {
        const latest: Partial<Record<Step, Job>> = {};
        for (const step of Object.keys(JOB_KIND) as Step[]) {
          const job = list.find((j) => j.kind === JOB_KIND[step]);
          if (!job) continue;
          latest[step] = job;
          if (isActive(job)) follow(step, job);
        }
        setJobs(latest);
      }),
    [projectId, follow],
  );

  useEffect(() => {
    loadPlan();
    loadExports();
    scanJobs();
    const current = stops.current;
    return () => current.forEach((stop) => stop());
  }, [loadPlan, loadExports, scanJobs]);

  // Source changes can leave the course behind them, or start a run from the source list.
  useEffect(() => {
    if (sourcesKey === undefined) return;
    loadPlan();
    scanJobs();
  }, [sourcesKey, loadPlan, scanJobs]);

  const run = useCallback(
    async (step: Step, path: string, body?: unknown) => {
      setError(null);
      try {
        const job = await api.post<Job>(`/projects/${projectId}${path}`, body);
        setJobs((m) => ({ ...m, [step]: job }));
        follow(step, job);
        return job;
      } catch (e) {
        setError(messageOf(e));
        return null;
      }
    },
    [projectId, follow],
  );

  const guarded = useCallback(async <T,>(fn: () => Promise<T>) => {
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(messageOf(e));
      return null;
    }
  }, []);

  return {
    plan, exports, jobs, error, setError, contentTick, loadPlan,
    busy: { plan: isActive(jobs.plan), lessons: isActive(jobs.lessons), revise: isActive(jobs.revise), export: isActive(jobs.export) },
    generateOutline: (steering?: Steering) => run("plan", "/plan", steering ?? {}),
    generateLessons: (body?: LessonsRequestBody) => run("lessons", "/lessons/generate", body ?? {}),
    revise: (body: { targets?: ReviseTarget[]; lesson_ids?: string[]; fix?: boolean } & Steering) => run("revise", "/lessons/revise", body),
    exportCourse: () => run("export", "/export"),
    approveOutline: () => guarded(async () => plan && setPlan(await api.post<CoursePlan>(`/projects/${projectId}/plan/${plan.id}/approve`))),
    editOutline: (edit: OutlineEdit) => guarded(async () => plan && setPlan(await api.patch<CoursePlan>(`/projects/${projectId}/plan/${plan.id}/outline`, edit))),
  };
}

export type Course = ReturnType<typeof useCourse>;
