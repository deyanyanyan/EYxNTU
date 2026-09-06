"use client";

/**
 * Token storage: localStorage for the app + a same-site cookie mirror for middleware.
 * The API is the only place that verifies signatures.
 */
export type SessionUser = { id: string; email: string; name: string; role: "admin" | "instructor" | "learner"; org_unit: string | null };

const KEY = "lms_session";
const COOKIE = "lms_token";

export function saveSession(token: string, user: SessionUser) {
  localStorage.setItem(KEY, JSON.stringify({ token, user }));
  const exp = decode(token)?.exp;
  const expires = exp ? `; expires=${new Date(exp * 1000).toUTCString()}` : "";
  document.cookie = `${COOKIE}=${token}; path=/; SameSite=Lax${expires}`;
}

export function clearSession() {
  localStorage.removeItem(KEY);
  document.cookie = `${COOKIE}=; path=/; Max-Age=0`;
}

export function getSession(): { token: string; user: SessionUser } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    const exp = decode(s.token)?.exp;
    if (exp && exp * 1000 < Date.now()) {
      clearSession();
      return null;
    }
    return s;
  } catch {
    return null;
  }
}

export function getToken() {
  return getSession()?.token ?? null;
}

function decode(token: string): { exp?: number; role?: string } | null {
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}
