"use client";

import { clearSession, getToken } from "@/lib/auth";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  const res = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = `/login?next=${encodeURIComponent(window.location.pathname)}`;
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T>(p: string) => request<T>(p),
  post: <T>(p: string, body?: unknown) => request<T>(p, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  patch: <T>(p: string, body: unknown) => request<T>(p, { method: "PATCH", body: JSON.stringify(body) }),
  del: <T>(p: string) => request<T>(p, { method: "DELETE" }),
};

export async function login(email: string, password: string) {
  const form = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_URL}/auth/token`, { method: "POST", body: form, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => ({}))).detail ?? "Login failed");
  return res.json() as Promise<{ access_token: string; user: import("@/lib/auth").SessionUser }>;
}

/** Fetch an authenticated file and hand it to the browser as a download. */
export async function downloadFile(path: string, filename: string) {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Subscribe to a job's SSE stream. Returns an unsubscribe function. */
export function watchJob(jobId: string, onUpdate: (job: Job) => void, onEnd?: () => void) {
  const token = getToken();
  const es = new EventSource(`${API_URL}/jobs/stream/${jobId}?token=${token}`);
  es.onmessage = (e) => onUpdate(JSON.parse(e.data));
  es.addEventListener("end", () => {
    es.close();
    onEnd?.();
  });
  es.onerror = () => es.close();
  return () => es.close();
}

// ---- shared types (mirror apps/api/app/schemas) ----
export type Job = {
  id: string; kind: string; status: "pending" | "running" | "completed" | "failed" | "cancelled";
  project_id: string | null; payload: Record<string, unknown>; result: Record<string, unknown> | null;
  progress_current: number; progress_total: number; message: string | null;
  error_type: string | null; error_message: string | null; cancel_requested: boolean;
  created_at: string; started_at: string | null; completed_at: string | null;
};
export type Source = { id: string; filename: string; content_type: string; size_bytes: number; status: string; error: string | null; page_count: number | null; chunk_count: number; created_at: string };
export type Project = { id: string; name: string; description: string | null; owner_id: string; target_audience: string | null; duration_minutes: number | null; learning_goals: string | null; created_at: string; updated_at: string; sources: Source[] };
export type SearchHit = { chunk_id: string; source_id: string; source_name: string; text: string; heading_path: string | null; page_start: number | null; page_end: number | null; similarity: number };
export type User = { id: string; email: string; name: string; role: string; org_unit: string | null; is_active: boolean };
export type PromptVersion = { id: string; task: string; name: string; system_prompt: string | null; templates: Record<string, string>; notes: string | null; is_active: boolean; created_by_name: string | null; last_activated_at: string | null; created_at: string };

// ---- offline evaluation artifacts (admin-only) ----
export type EvaluationDimension = { score: number; feedback: string; issues: string[] };
export type EvaluationUsage = {
  calls: number; prompt_tokens: number | null; completion_tokens: number | null;
  usage_reported_calls: number; latency_ms: number; errors: number;
};
export type EvaluationScore = {
  score_version: number; run_id: string | null; generator: Record<string, unknown>;
  generation: Record<string, unknown>; lesson_id: string | null; title: string | null;
  checks: { lesson_id: string | null; title: string | null; counts: Record<string, unknown>; findings: Record<string, unknown>[] };
  judge: {
    status: string; model: string | null; prompt_sha256: string | null;
    same_model_endpoint_as_generator: boolean;
    dimensions: Partial<Record<"grounding" | "coherence" | "pedagogy", EvaluationDimension>>;
    dimension_errors: Record<string, string>; usage: EvaluationUsage | null;
  };
};
export type EvaluationCourse = {
  score_version: number; run_id: string | null; generator: Record<string, unknown>;
  generation: Record<string, unknown>; lessons_scored: number;
  judge_means: Record<"grounding" | "coherence" | "pedagogy", number | null>;
  judge_lesson_score_stddev: Record<"grounding" | "coherence" | "pedagogy", number | null>;
  check_totals: Record<string, unknown>;
  course_overlap: {
    shared_cited_chunks: number; shared_chunk_examples: { chunk_id: string; lesson_ids: string[] }[];
    near_duplicate_bullet_pairs: number; near_duplicate_examples: Record<string, unknown>[];
  };
};
export type EvaluationBatch = {
  batch_id: string; created_at: string;
  input_runs: { run_id: string | null; generator: Record<string, unknown> | null; data_classification: string | null }[];
  judge: { model: string; base_url: string; temperature: number; max_tokens: number; context_tokens: number; timeout_seconds: number; prompt_sha256: string } | null;
  output_files: string[];
};
export type EvaluationBatchDetail = {
  manifest: EvaluationBatch; scores: EvaluationScore[]; courses: EvaluationCourse[]; summary_markdown: string;
};
export type EvaluationJudgeConfig = { judge_configured: boolean; judge_model: string | null };
export type EvaluationRun = {
  run_id: string; captured_at: string; data_classification: string; generator: Record<string, unknown>;
  source_names: string[]; lesson_count: number;
};
export type EvaluationJob = {
  job_id: string; status: "queued" | "running" | "completed" | "failed"; phase: string; message: string;
  use_judge: boolean; judge_model: string | null; created_at: string; updated_at: string;
  run_id: string | null; batch_id: string | null; completed_at: string | null;
};

// ---- course authoring (mirror apps/api/app/schemas/course.py) ----
export type Objective = { id: string; text: string; bloom_level: string; source_chunk_ids: string[] };
export type LessonSummary = { id: string; position: number; title: string; estimated_minutes: number | null; objective_ids: string[]; source_chunk_count: number; slides: number; questions: number; generated_at: string | null };
export type CourseModule = { id: string; position: number; title: string; description: string | null; lessons: LessonSummary[] };
export type CoursePlan = {
  id: string; version: number; title: string; summary: string | null; status: "draft" | "in_review" | "approved" | "rejected";
  learning_objectives: Objective[]; coverage: Record<string, number> | null; source_names: Record<string, string>; modules: CourseModule[]; created_at: string;
};
export type Reference = { chunk_id: string; source_name: string; heading_path: string | null; page_start: number | null; page_end: number | null };
export type SlideContent = { id: string; layout: string; title: string; bullets: string[]; table: string[][] | null; notes: string };
export type DeckContent = {
  slides: SlideContent[]; references: Record<string, Reference>;
  citation_stats: { slides: number; citation_markers: number; invalid_citation_numbers: number[]; bullets_checked: number; bullets_without_citation: number };
};
export type QuizQuestion = { stem: string; options: string[]; answer_index: number; explanation: string; difficulty: string; source_span: string; chunk_id: string | null };
export type QuizContent = { questions: QuizQuestion[]; rejected: { issues: { code: string; detail: string }[] }[]; references: Record<string, Reference> };
export type Asset<C> = { id: string; kind: string; version: number; approval: string; content: C | null; generated_with_model: string | null; created_at: string };
export type CitationDetail = { block_id: string; chunk_id: string; quote: string | null; source_name: string; heading_path: string | null; page_start: number | null; page_end: number | null; text: string };
export type LessonDetail = { lesson: LessonSummary; module_title: string; slides: Asset<DeckContent> | null; quiz: Asset<QuizContent> | null; citations: CitationDetail[] };
export type CourseExport = {
  id: string; created_at: string;
  content: { course_title: string; plan_version: number; lessons: number; questions: number; includes_unapproved: boolean; files: Record<string, string> } | null;
};
