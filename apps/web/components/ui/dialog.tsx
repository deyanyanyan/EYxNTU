"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/** A modal on the native <dialog>: focus trap, Esc to close and inert background come from the browser. */
export function Dialog({ open, onClose, title, children, className }: { open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()} // a click on the backdrop
      className={cn("w-[min(30rem,calc(100vw-2rem))] rounded-lg border bg-surface p-0 text-foreground shadow-xl backdrop:bg-black/40", className)}
    >
      {open && (
        <div className="space-y-4 p-5">
          <h2 className="text-base font-semibold">{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}
