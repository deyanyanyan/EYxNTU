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
