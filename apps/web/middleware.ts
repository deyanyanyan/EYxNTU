import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side route gate. The JWT is mirrored into a cookie at login so the
 * edge middleware can read it; the API still verifies the signature on every
 * request. Here we only decode (not verify) to route by role.
 */
const PUBLIC = ["/login", "/_next", "/fonts", "/favicon.ico", "/api/health"];

const ROLE_PREFIXES: Record<string, string[]> = {
  "/admin": ["admin"],
  "/projects": ["admin", "instructor"],
  "/jobs": ["admin", "instructor"],
  "/learn": ["admin", "instructor", "learner"],
};

function decodeRole(token: string | undefined): { role?: string; exp?: number } | null {
  if (!token) return null;
  try {
    const payload = token.split(".")[1];
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/"));
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
  if (PUBLIC.some((p) => pathname.startsWith(p))) return NextResponse.next();

  const claims = decodeRole(req.cookies.get("lms_token")?.value);
  const expired = !claims?.exp || claims.exp * 1000 < Date.now();
  if (!claims || expired) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }

  for (const [prefix, roles] of Object.entries(ROLE_PREFIXES)) {
    if (pathname.startsWith(prefix) && !roles.includes(claims.role ?? "")) {
      const url = req.nextUrl.clone();
      url.pathname = claims.role === "learner" ? "/learn" : "/projects";
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };
