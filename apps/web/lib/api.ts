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

/** Fetch an authenticated file's bytes. */
export async function fetchBlob(path: string): Promise<Blob> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.blob();
}

/** Fetch an authenticated file and hand it to the browser as a download. */
export async function downloadFile(path: string, filename: string) {
  const url = URL.createObjectURL(await fetchBlob(path));
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
  /** Filled by the job list: the project, its latest course plan's title, and an ingested file's name. */
  project_name?: string | null; course_title?: string | null; source_name?: string | null;
};
export type Source = {
  id: string; filename: string; content_type: string; size_bytes: number; status: string; error: string | null; page_count: number | null; chunk_count: number; created_at: string;
  /** How the source viewer shows it: the PDF (Word and PowerPoint are rendered to PDF), text, or nothing viewable yet. */
  viewer: "pdf" | "text" | null;
};
/** How the project's current course draws on one source (lessons that cite it or were planned from it). */
export type SourceUsage = { in_course: boolean; lessons: { id: string; title: string }[] };
export type Project = { id: string; name: string; description: string | null; owner_id: string; target_audience: string | null; duration_minutes: number | null; learning_goals: string | null; created_at: string; updated_at: string; sources: Source[] };
export type SearchHit = { chunk_id: string; source_id: string; source_name: string; text: string; heading_path: string | null; page_start: number | null; page_end: number | null; similarity: number };
export type User = { id: string; email: string; name: string; role: string; org_unit: string | null; is_active: boolean };
export type PromptVersion = { id: string; task: string; name: string; system_prompt: string | null; templates: Record<string, string>; notes: string | null; is_active: boolean; created_by_name: string | null; last_activated_at: string | null; created_at: string };

// ---- course authoring (mirror apps/api/app/schemas/course.py) ----
export type Objective = { id: string; text: string; bloom_level: string; source_chunk_ids: string[] };
export type LessonSummary = {
  id: string; position: number; title: string; estimated_minutes: number | null; objective_ids: string[]; source_chunk_count: number;
  slides: number; questions: number; generated_at: string | null; reviewer_flags: number | null;
  /** Questions whose wrong options the reviewer found easy to rule out. */
  weak_questions: number; approved: boolean; proposals: number;
};
export type CourseModule = { id: string; position: number; title: string; description: string | null; lessons: LessonSummary[] };
export type CoursePlan = {
  id: string; version: number; title: string; summary: string | null; status: "draft" | "in_review" | "approved" | "rejected";
  learning_objectives: Objective[]; coverage: Record<string, number> | null; source_names: Record<string, string>; modules: CourseModule[]; created_at: string;
  /** Ready sources added or re-ingested after this plan and its lessons were generated. */
  new_sources: { id: string; filename: string; ready_at: string }[];
  /** Why this version exists: the instructions it was rebuilt with, or the edits that created it. */
  meta: { note?: string; instructions?: string | null; intents?: string[]; edited_from?: number; changes?: string[] } | null;
  latest: boolean;
};
export type PlanVersion = { id: string; version: number; status: string; title: string; created_at: string; meta: CoursePlan["meta"]; lessons: number };
export type OutlineChange = { kind: "added" | "removed" | "renamed" | "moved"; what: string; detail: string };
export type OutlineEdit =
  | { op: "rename_course"; title: string }
  | { op: "rename_module"; module_id: string; title: string }
  | { op: "rename_lesson"; lesson_id: string; title: string }
  | { op: "move_lesson"; lesson_id: string; delta: -1 | 1 }
  | { op: "add_lesson"; module_id: string; title: string }
  | { op: "remove_lesson"; lesson_id: string };
export type Intent = "simpler" | "examples" | "shorter" | "fix";
/** What steers a regeneration (mirror apps/api/app/schemas/course.py Steering). */
export type Steering = { instructions?: string; intents?: Intent[] };
export type ReviseTarget = { lesson_id: string; kind: "slide" | "question"; block: string };
export type LessonsRequestBody = { lesson_ids?: string[] } & Steering;
/** A proposed change waiting on a slide or question (apps/api/app/core/generation/revision.py). */
export type Proposal<B> = { id: string; kind: "slide" | "question"; block: string; before: B; after: B; reason: "fix" | "regenerate"; instructions: string; findings: string[]; created_at: string };
export type AssetVersion = { asset_id: string; kind: string; version: number; created_at: string; current: boolean; approval: string; note: string; instructions: string | null };
export type Reference = { chunk_id: string; source_name: string; heading_path: string | null; page_start: number | null; page_end: number | null };
export type SlideContent = { id: string; layout: string; title: string; bullets: string[]; table: string[][] | null; notes: string };
export type Revision = { note: string; at: string; instructions?: string | null; intents?: string[]; from_version?: number };
export type DeckContent = {
  slides: SlideContent[]; references: Record<string, Reference>;
  citation_stats: { slides: number; citation_markers: number; invalid_citation_numbers: number[]; bullets_checked: number; bullets_without_citation: number };
  proposals?: Proposal<SlideContent>[]; revision?: Revision;
};
export type QuizQuestion = { stem: string; options: string[]; answer_index: number; explanation: string; difficulty: string; source_span: string; chunk_id: string | null };
export type QuizContent = {
  questions: QuizQuestion[]; rejected: { issues: { code: string; detail: string }[] }[]; references: Record<string, Reference>;
  proposals?: Proposal<QuizQuestion>[]; revision?: Revision;
};
export type GroundingIssue = { span: string; type: string; implicit_true: boolean | null };
export type RubricFinding = { criterion_id: string; criterion: string; valid: boolean; score: number | null; expected: number | null; feedback: string | null };
/** Findings from the trained reviewer, attached by a batch review (app/core/review). Advisory only. */
export type ReviewerReview = {
  source: string; base_model: string | null; base_revision: string | null; adapter: string | null; adapter_checkpoint: string | null;
  prompt_version: string | null; criteria_version: string; reviewed_at: string | null; advisory: boolean; asset_version: number; stale: boolean;
  slides: Record<string, { valid: boolean; error: string | null; issues: GroundingIssue[] }>;
  rubric: RubricFinding[];
  questions: Record<string, { valid: boolean; score: number | null; expected: number | null }>;
  /** Blocks edited since this review, so their findings were dropped; rubric scores then predate the edit. */
  changed?: string[]; rubric_stale?: boolean;
};
export type Asset<C> = {
  id: string; kind: string; version: number; approval: string; content: C | null;
  critique: { reviewer?: ReviewerReview } | null; generated_with_model: string | null; created_at: string;
};
export type CitationDetail = { block_id: string; chunk_id: string; quote: string | null; source_name: string; heading_path: string | null; page_start: number | null; page_end: number | null; text: string };
export type LessonDetail = { lesson: LessonSummary; module_title: string; slides: Asset<DeckContent> | null; quiz: Asset<QuizContent> | null; citations: CitationDetail[] };
export type CourseExport = {
  id: string; created_at: string;
  content: { course_title: string; plan_version: number; lessons: number; questions: number; includes_unapproved: boolean; files: Record<string, string> } | null;
};
/** A node of the package's organization tree (imsmanifest.xml); `href` is null for a grouping item. */
export type ScormItem = { id: string; title: string; href: string | null; mastery_score: number | null; launch_data: string; children: ScormItem[] };
/** A preview session for one exported package. Package files resolve against `${API_URL}${base_path}`. */
export type PreviewSession = { title: string; items: ScormItem[]; base_path: string; expires_at: string; export: CourseExport };
