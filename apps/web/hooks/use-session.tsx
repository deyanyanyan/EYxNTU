"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { getSession, type SessionUser } from "@/lib/auth";

type Ctx = { user: SessionUser | null; ready: boolean; refresh: () => void };
const SessionContext = createContext<Ctx>({ user: null, ready: false, refresh: () => {} });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(false);
  const refresh = () => setUser(getSession()?.user ?? null);

  useEffect(() => {
    refresh();
    setReady(true);
    const onStorage = (e: StorageEvent) => e.key === "lms_session" && refresh();
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return <SessionContext.Provider value={{ user, ready, refresh }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);
