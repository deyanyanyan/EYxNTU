"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import type { Intent, Steering } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The one panel every regeneration goes through. It names the scope it was opened from
 * (and offers the wider ones), takes optional instructions and one-tap intents, and says
 * what will change before anything runs. Mount it only while open, so each opening starts
 * clean.
 */
export type Scope = {
  key: string;
  label: string;
  impact: string; // what happens, in one sentence
  action: string; // the submit button's label
  flags?: number; // flagged issues in this scope, offered as "Fix N flagged"
  disabled?: string; // why this scope cannot run right now
};

const INTENTS: { key: Exclude<Intent, "fix">; label: string }[] = [
  { key: "simpler", label: "Simpler language" },
  { key: "examples", label: "More examples" },
  { key: "shorter", label: "Shorter" },
];

export function Composer({ title, scopes, initial, onClose, onSubmit }: {
  title: string; scopes: Scope[]; initial?: string; onClose: () => void;
  onSubmit: (scope: Scope, steering: Steering) => Promise<unknown>;
}) {
  const [scopeKey, setScopeKey] = useState(initial ?? scopes[0]?.key);
  const [text, setText] = useState("");
  const [intents, setIntents] = useState<Intent[]>([]);
  const [busy, setBusy] = useState(false);
  const scope = scopes.find((s) => s.key === scopeKey) ?? scopes[0];
  const flags = scope?.flags ?? 0;
  const chosen = intents.filter((i) => i !== "fix" || flags > 0);
  const toggle = (i: Intent) => setIntents((xs) => (xs.includes(i) ? xs.filter((x) => x !== i) : [...xs, i]));

  async function submit() {
    if (!scope || scope.disabled) return;
    setBusy(true);
    await onSubmit(scope, { instructions: text.trim() || undefined, intents: chosen });
    setBusy(false);
    onClose();
  }

  return (
    <Dialog open onClose={() => !busy && onClose()} title={title} className="w-[min(34rem,calc(100vw-2rem))]">
      {scopes.length > 1 ? (
        <label className="grid gap-1.5 text-xs font-medium" htmlFor="composer-scope">
          What to change
          <select
            id="composer-scope"
            value={scope?.key}
            onChange={(e) => setScopeKey(e.target.value)}
            className="h-9 rounded-md border bg-surface px-2 text-sm font-normal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {scopes.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </label>
      ) : (
        <p className="text-sm font-medium">{scope?.label}</p>
      )}
      <label className="grid gap-1.5 text-xs font-medium" htmlFor="composer-instructions">
        <span>What should change? <span className="font-normal text-muted-foreground">Optional</span></span>
        <textarea
          id="composer-instructions"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="For example: lead with the 1-hour rule and add a worked example."
          className="resize-y rounded-md border bg-surface px-3 py-2 text-sm font-normal leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </label>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Quick changes">
        {INTENTS.map((i) => <Chip key={i.key} on={intents.includes(i.key)} onClick={() => toggle(i.key)}>{i.label}</Chip>)}
        {flags > 0 && <Chip on={intents.includes("fix")} onClick={() => toggle("fix")}>Fix {flags} flagged {flags === 1 ? "issue" : "issues"}</Chip>}
      </div>
      <p className={cn("rounded-md px-3 py-2 text-xs", scope?.disabled ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground")}>{scope?.disabled ?? scope?.impact}</p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
        <Button size="sm" variant="accent" disabled={busy || !!scope?.disabled} onClick={submit}>{busy ? "Starting…" : scope?.action}</Button>
      </div>
    </Dialog>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cn("rounded-full border px-2.5 py-1 text-xs font-medium transition-colors", on ? "border-accent bg-accent-soft" : "hover:bg-muted")}
    >
      {on ? "✓ " : ""}{children}
    </button>
  );
}
