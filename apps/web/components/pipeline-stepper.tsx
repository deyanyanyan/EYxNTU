import { cn } from "@/lib/utils";

export const STAGES = ["Ingest", "Plan", "Generate", "Export"] as const;
export type Stage = (typeof STAGES)[number];

/** Signature element: the document-to-course pipeline as a horizontal stepper. */
export function PipelineStepper({ current, done = [] }: { current: Stage; done?: Stage[] }) {
  return (
    <ol className="flex items-center gap-1 text-xs">
      {STAGES.map((s, i) => {
        const isDone = done.includes(s);
        const isCurrent = s === current;
        return (
          <li key={s} className="flex items-center gap-1">
            <span
              className={cn(
                "flex h-6 items-center gap-1.5 rounded-sm border px-2 font-medium",
                isCurrent && "border-accent bg-accent-soft text-foreground",
                isDone && !isCurrent && "border-success/40 text-success",
                !isDone && !isCurrent && "border-border text-muted-foreground",
              )}
            >
              <span className="font-mono text-[10px] opacity-70">{i + 1}</span>
              {s}
            </span>
            {i < STAGES.length - 1 && <span className="h-px w-3 bg-border" />}
          </li>
        );
      })}
    </ol>
  );
}
