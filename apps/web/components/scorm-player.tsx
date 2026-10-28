"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, CircleCheck, CircleDashed, CircleDot, CircleX, RotateCcw, TriangleAlert } from "lucide-react";
import { PaneHeader, ThreePane } from "@/components/layout/three-pane";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { API_URL, type PreviewSession, type ScormItem } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Plays an exported SCORM 1.2 package the way an LMS would, without saving anything.
 *
 * The API serves each SCO page with a SCORM run-time injected (app/core/export/scorm_preview.py);
 * the page runs sandboxed and reports every API call here by postMessage. This component is the
 * LMS side: it launches SCOs with the learner record kept so far, keeps what each SCO commits,
 * and shows the calls, so an author sees both the learner's view and what an LMS would record.
 */

type CmiRecord = {
  lesson_status: string; score_raw: string; score_min: string; score_max: string; lesson_location: string;
  suspend_data: string; comments: string; exit: string; session_time: string;
};
type ScoState = { committed: CmiRecord | null; live: CmiRecord | null; totalTime: string };
type Call = { n: number; sco: string; attempt: string; fn: string; args: string[]; result: string; error: string };
type Launch = { index: number; attempt: string; url: string; loaded: boolean; ready: boolean };
type Sco = ScormItem & { module: string };

const ERRORS: Record<string, string> = {
  "101": "General exception", "201": "Invalid argument", "202": "Element cannot have children", "203": "Element is not an array",
  "301": "Not initialized", "401": "Not implemented in this preview", "402": "Element is a keyword", "403": "Element is read only",
  "404": "Element is write only", "405": "Incorrect data type",
};
const DONE = ["passed", "completed"];

function flatten(items: ScormItem[], module = ""): Sco[] {
  return items.flatMap((i) => [...(i.href ? [{ ...i, module }] : []), ...flatten(i.children, i.href ? module : i.title)]);
}

const seconds = (t: string) => {
  const m = /^(\d{2,4}):(\d{2}):(\d{2}(?:\.\d{1,2})?)$/.exec(t);
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : 0;
};
const timespan = (s: number) => {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${String(h).padStart(4, "0")}:${String(m).padStart(2, "0")}:${(s - h * 3600 - m * 60).toFixed(2).padStart(5, "0")}`;
};
// Identifies one launch to the messages it sends. Not crypto.randomUUID: that needs a secure
// context, and the app may be served over plain HTTP; getRandomValues does not.
const nonce = () => Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) => b.toString(16).padStart(2, "0")).join("");

/** The SCO's launch URL: its package path, a per-launch query so a relaunch reloads, and the launch state. */
function launchUrl(basePath: string, href: string, attempt: string, state: object): string {
  const hash = href.indexOf("#");
  const [path, fragment] = hash === -1 ? [href, ""] : [href.slice(0, hash), href.slice(hash + 1)];
  const query = `${path.includes("?") ? "&" : "?"}attempt=${attempt}`;
  return `${API_URL}${basePath}${path}${query}#${fragment ? `${fragment}&` : ""}lms=${encodeURIComponent(JSON.stringify(state))}`;
}

const statusOf = (s?: ScoState) => s?.committed?.lesson_status || "not attempted";

function StatusIcon({ status }: { status: string }) {
  if (DONE.includes(status)) return <CircleCheck className="size-3.5 shrink-0 text-success" />;
  if (status === "failed") return <CircleX className="size-3.5 shrink-0 text-destructive" />;
  if (status === "incomplete") return <CircleDot className="size-3.5 shrink-0 text-warning" />;
  return <CircleDashed className="size-3.5 shrink-0 text-muted-foreground" />;
}

function Outline({ items, scos, states, current, onOpen }: { items: ScormItem[]; scos: Sco[]; states: Record<string, ScoState>; current: number; onOpen: (i: number) => void }) {
  return (
    <ul className="space-y-0.5">
      {items.map((item) => {
        const index = item.href ? scos.findIndex((s) => s.id === item.id) : -1;
        const state = item.href ? states[item.id] : undefined;
        return (
          <li key={item.id}>
            {item.href ? (
              <button
                onClick={() => onOpen(index)}
                className={cn("flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted", index === current && "bg-accent-soft")}
              >
                <span className="mt-0.5"><StatusIcon status={statusOf(state)} /></span>
                <span className="min-w-0 flex-1">
                  <span className="block leading-snug">{item.title}</span>
                  <span className="block font-mono text-[10px] text-muted-foreground">
                    {statusOf(state)}{state?.committed?.score_raw ? ` · ${state.committed.score_raw}%` : ""}{item.mastery_score != null ? ` · pass ${item.mastery_score}%` : ""}
                  </span>
                </span>
              </button>
            ) : (
              <p className="px-2 pb-1 pt-3 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{item.title}</p>
            )}
            {item.children.length > 0 && <div className={item.href ? "pl-4" : ""}><Outline items={item.children} scos={scos} states={states} current={current} onOpen={onOpen} /></div>}
          </li>
        );
      })}
    </ul>
  );
}

function Check({ state, children }: { state: "ok" | "missing" | "pending"; children: React.ReactNode }) {
  return (
    <li className="flex items-start gap-1.5">
      {state === "ok" ? <CircleCheck className="mt-0.5 size-3 shrink-0 text-success" /> : state === "missing" ? <TriangleAlert className="mt-0.5 size-3 shrink-0 text-warning" /> : <CircleDashed className="mt-0.5 size-3 shrink-0 text-muted-foreground" />}
      <span className={state === "pending" ? "text-muted-foreground" : ""}>{children}</span>
    </li>
  );
}

/** `lmsView` adds a right pane with the learner record, launch checks and every API call (off for now). */
export function ScormPlayer({ session, learnerId, learnerName, lmsView = false }: { session: PreviewSession; learnerId: string; learnerName: string; lmsView?: boolean }) {
  const scos = useMemo(() => flatten(session.items), [session.items]);
  const [states, setStates] = useState<Record<string, ScoState>>({});
  const [calls, setCalls] = useState<Call[]>([]);
  const [launch, setLaunch] = useState<Launch | null>(null);
  const [stalled, setStalled] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  const attempts = useRef(new Set<string>());
  const statesRef = useRef(states);
  const launchRef = useRef(launch);
  const pending = useRef<number | null>(null);
  const counter = useRef(0);
  useEffect(() => {
    statesRef.current = states;
    launchRef.current = launch;
  }, [states, launch]);

  const launchNow = useCallback(
    (index: number) => {
      const sco = scos[index];
      if (!sco?.href) return;
      const prior = statesRef.current[sco.id];
      const attempt = nonce();
      attempts.current.add(attempt);
      const state = {
        sco: sco.id, attempt, student_id: learnerId, student_name: learnerName, credit: "credit", lesson_mode: "normal",
        // SCORM 1.2 cmi.core.entry: first launch, resuming a suspended attempt, or any other re-entry.
        entry: !prior?.committed ? "ab-initio" : prior.committed.exit === "suspend" ? "resume" : "",
        mastery_score: sco.mastery_score, launch_data: sco.launch_data, total_time: prior?.totalTime, cmi: prior?.committed ?? undefined,
      };
      setStalled(false);
      setLaunch({ index, attempt, url: launchUrl(session.base_path, sco.href, attempt, state), loaded: false, ready: false });
    },
    [scos, learnerId, learnerName, session.base_path],
  );

  // Like an LMS, unload the current SCO first, so its LMSFinish is recorded before the next launch reads the record.
  const start = useCallback(
    (index: number) => {
      pending.current = index;
      if (!launchRef.current) return launchNow(index);
      setLaunch((l) => (l ? { ...l, url: "about:blank" } : l));
      window.setTimeout(() => {
        if (pending.current !== index) return;
        pending.current = null;
        launchNow(index);
      }, 300);
    },
    [launchNow],
  );

  useEffect(() => {
    launchNow(0);
  }, [launchNow]);

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      const m = e.data;
      // The attempt nonce, known only to the page we launched, identifies the sender. A SCO's
      // unload-time LMSFinish arrives after its document is gone, so its source is null.
      if (m?.channel !== "lms-preview" || !attempts.current.has(m.attempt)) return;
      if (e.source !== null && e.source !== frame.current?.contentWindow) return;
      if (m.type === "launch") {
        setLaunch((l) => (l && l.attempt === m.attempt ? { ...l, ready: true } : l));
        return;
      }
      if (m.type !== "call") return;
      const n = ++counter.current; // read now: the updater below runs later, after more calls may have arrived
      setCalls((c) => [{ n, sco: m.sco, attempt: m.attempt, fn: m.fn, args: m.args, result: m.result, error: m.error }, ...c].slice(0, 400));
      const ok = m.result === "true";
      setStates((all) => {
        const prev = all[m.sco] ?? { committed: null, live: null, totalTime: "0000:00:00.00" };
        const next: ScoState = { ...prev, live: m.record };
        // An LMS keeps what a SCO commits; LMSFinish commits too, and adds the session to the total time.
        if (ok && (m.fn === "LMSCommit" || m.fn === "LMSFinish")) next.committed = m.record;
        if (ok && m.fn === "LMSFinish" && m.record.session_time) next.totalTime = timespan(seconds(prev.totalTime) + seconds(m.record.session_time));
        return { ...all, [m.sco]: next };
      });
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  if (!scos.length) return <p className="p-6 text-sm text-muted-foreground">This package has no launchable lessons.</p>;
  const index = launch?.index ?? 0;
  const sco = scos[index];
  const state = states[sco.id];
  const done = scos.filter((s) => DONE.includes(statusOf(states[s.id]))).length;
  const failed = scos.filter((s) => statusOf(states[s.id]) === "failed").length;
  const mine = calls.filter((c) => c.attempt === launch?.attempt);
  const succeeded = (fn: string, element?: string) => mine.some((c) => c.fn === fn && c.result === "true" && (!element || c.args[0] === element));
  const initialized = succeeded("LMSInitialize");
  const uncommitted = state?.live && JSON.stringify(state.live) !== JSON.stringify(state.committed);
  const failures = mine.filter((c) => c.error !== "0");

  return (
    <ThreePane
      left={
        <>
          <PaneHeader>Course</PaneHeader>
          <div className="space-y-2 border-b p-3">
            <p className="text-sm font-medium leading-snug">{session.title}</p>
            <Progress value={(done / scos.length) * 100} />
            <p className="text-[11px] text-muted-foreground">
              {done} of {scos.length} lessons complete{failed ? ` · ${failed} failed` : ""}
            </p>
          </div>
          <div className="p-2">
            <Outline items={session.items} scos={scos} states={states} current={index} onOpen={start} />
          </div>
          <p className="mt-auto border-t p-3 text-[11px] leading-relaxed text-muted-foreground">
            Preview only: progress lives in this tab and is not saved. The lessons are the exported package, unchanged.
          </p>
        </>
      }
      center={
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex items-center justify-between gap-3 border-b px-4 py-2">
            <div className="min-w-0">
              <p className="truncate text-[11px] text-muted-foreground">{sco.module ? `${sco.module} · ` : ""}Lesson {index + 1} of {scos.length}</p>
              <p className="truncate text-sm font-medium">{sco.title}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button size="sm" variant="ghost" disabled={index === 0} onClick={() => start(index - 1)}><ChevronLeft /> Previous</Button>
              <Button size="sm" variant="ghost" title="Relaunch this lesson" aria-label="Relaunch this lesson" onClick={() => start(index)}><RotateCcw /></Button>
              <Button size="sm" variant="ghost" disabled={index === scos.length - 1} onClick={() => start(index + 1)}>Next <ChevronRight /></Button>
            </div>
          </div>
          {stalled && (
            <p className="flex items-center gap-1.5 border-b bg-warning/10 px-4 py-2 text-xs text-warning">
              <TriangleAlert className="size-3.5" />This lesson did not start the preview run-time. The preview link may have expired: reset the preview.
            </p>
          )}
          {launch && (
            <iframe
              ref={frame}
              src={launch.url}
              title={sco.title}
              sandbox="allow-scripts allow-forms"
              className="min-h-0 w-full flex-1 bg-white"
              onLoad={() => {
                if (launch.url === "about:blank") return;
                const attempt = launch.attempt;
                setLaunch((l) => (l && l.attempt === attempt ? { ...l, loaded: true } : l));
                window.setTimeout(() => setStalled(launchRef.current?.attempt === attempt && !launchRef.current.ready), 1500);
              }}
            />
          )}
        </div>
      }
      right={
        lmsView && <>
          <PaneHeader right={<Badge>SCORM 1.2</Badge>}>LMS view</PaneHeader>
          <div className="space-y-5 p-3 text-xs">
            <section>
              <p className="mb-1.5 flex items-center justify-between font-medium">
                Learner record {uncommitted && <Badge tone="warning">not committed</Badge>}
              </p>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono text-[11px]">
                <dt className="text-muted-foreground">lesson_status</dt><dd>{state?.live?.lesson_status ?? "not attempted"}</dd>
                <dt className="text-muted-foreground">score</dt>
                <dd>{state?.live?.score_raw ? `${state.live.score_raw} (${state.live.score_min || "?"}–${state.live.score_max || "?"})` : "–"}</dd>
                <dt className="text-muted-foreground">mastery_score</dt><dd>{sco.mastery_score ?? "–"}</dd>
                <dt className="text-muted-foreground">total_time</dt><dd>{state?.totalTime ?? "0000:00:00.00"}</dd>
                <dt className="text-muted-foreground">session_time</dt><dd>{state?.live?.session_time || "–"}</dd>
                <dt className="text-muted-foreground">exit</dt><dd>{state?.live?.exit || "–"}</dd>
                <dt className="text-muted-foreground">location</dt><dd className="truncate">{state?.live?.lesson_location || "–"}</dd>
                <dt className="text-muted-foreground">suspend_data</dt><dd className="truncate">{state?.live?.suspend_data || "–"}</dd>
              </dl>
            </section>

            <section>
              <p className="mb-1.5 font-medium">This launch</p>
              <ul className="space-y-1">
                <Check state={initialized ? "ok" : launch?.loaded ? "missing" : "pending"}>LMSInitialize called</Check>
                <Check state={succeeded("LMSSetValue", "cmi.core.lesson_status") ? "ok" : initialized ? "missing" : "pending"}>Lesson status reported</Check>
                {sco.mastery_score != null && (
                  <Check state={succeeded("LMSSetValue", "cmi.core.score.raw") ? "ok" : "pending"}>Score reported (submit the quiz)</Check>
                )}
                <Check state={succeeded("LMSCommit") || succeeded("LMSFinish") ? "ok" : initialized ? "missing" : "pending"}>Data committed</Check>
                <Check state={succeeded("LMSFinish") ? "ok" : "pending"}>LMSFinish called (when the learner leaves)</Check>
                <Check state={succeeded("LMSSetValue", "cmi.core.session_time") ? "ok" : "pending"}>Session time reported{initialized && !succeeded("LMSSetValue", "cmi.core.session_time") ? ": not yet, so an LMS would record no time" : ""}</Check>
                {failures.length > 0 && <Check state="missing">{failures.length} call{failures.length === 1 ? "" : "s"} returned an error</Check>}
              </ul>
            </section>

            <section>
              <p className="mb-1.5 font-medium">API calls <span className="font-normal text-muted-foreground">· newest first</span></p>
              {calls.length === 0 ? (
                <p className="text-muted-foreground">None yet.</p>
              ) : (
                <ol className="space-y-1 font-mono text-[10.5px] leading-snug">
                  {calls.map((c) => (
                    <li key={c.n} className={cn(c.error !== "0" && "text-destructive", c.attempt !== launch?.attempt && "opacity-60")}>
                      <span className="text-muted-foreground">{c.n}. </span>
                      {c.fn}({c.args.map((a) => JSON.stringify(a)).join(", ")}) → {JSON.stringify(c.result)}
                      {c.error !== "0" && ` · ${c.error} ${ERRORS[c.error] ?? ""}`}
                      {c.sco !== sco.id && <span className="text-muted-foreground"> · {scos.find((s) => s.id === c.sco)?.title ?? c.sco}</span>}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        </>
      }
    />
  );
}
