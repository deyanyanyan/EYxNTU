import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badge = cva("inline-flex items-center rounded-sm border px-1.5 py-0.5 text-[11px] font-medium leading-none", {
  variants: {
    tone: {
      neutral: "border-border bg-muted text-muted-foreground",
      accent: "border-accent/50 bg-accent-soft text-foreground",
      success: "border-success/40 bg-success/10 text-success",
      warning: "border-warning/40 bg-warning/10 text-warning",
      destructive: "border-destructive/40 bg-destructive/10 text-destructive",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({ className, tone, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...p} />;
}

export function statusTone(status: string): VariantProps<typeof badge>["tone"] {
  if (["ready", "completed", "approved"].includes(status)) return "success";
  if (["failed", "rejected"].includes(status)) return "destructive";
  if (["running", "parsing", "embedding", "in_review", "pending"].includes(status)) return "warning";
  return "neutral";
}
