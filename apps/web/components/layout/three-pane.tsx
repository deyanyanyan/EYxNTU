import { cn } from "@/lib/utils";

/** Left outline · centre canvas · right inspector. Collapses to a single column on small screens. */
export function ThreePane({ left, center, right, className }: { left: React.ReactNode; center: React.ReactNode; right: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid h-full min-h-0 grid-cols-1 lg:grid-cols-[260px_minmax(0,1fr)_320px]", className)}>
      <aside className="pane hidden min-h-0 flex-col overflow-auto border-r lg:flex">{left}</aside>
      <section className="min-h-0 overflow-auto">{center}</section>
      <aside className="pane hidden min-h-0 flex-col overflow-auto border-l lg:flex">{right}</aside>
    </div>
  );
}

export function PaneHeader({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="pane-header">
      <span>{children}</span>
      {right}
    </div>
  );
}
