"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, RotateCcw } from "lucide-react";
import { Shell } from "@/components/layout/shell";
import { ScormPlayer } from "@/components/scorm-player";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/hooks/use-session";
import { api, type PreviewSession } from "@/lib/api";

/** Interactive preview of one exported SCORM package, played as an LMS would play it. */
export default function CoursePreviewPage({ params }: { params: Promise<{ projectId: string; exportId: string }> }) {
  const { projectId, exportId } = use(params);
  const { user, ready } = useSession();
  const [session, setSession] = useState<PreviewSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState(0);

  // Each open gets a fresh preview link; resetting remounts the player, so progress starts over.
  const open = useCallback(() => {
    setError(null);
    api
      .post<PreviewSession>(`/projects/${projectId}/exports/${exportId}/preview`)
      .then((s) => {
        setSession(s);
        setRun((r) => r + 1);
      })
      .catch((e: Error) => setError(e.message));
  }, [projectId, exportId]);

  useEffect(() => {
    open();
  }, [open]);

  const exported = session?.export;
  return (
    <Shell
      title={
        <span className="flex items-center gap-2">
          Course preview{session ? <span className="text-muted-foreground">· {session.title}</span> : null}
          {exported?.content?.includes_unapproved && <Badge tone="warning">includes unreviewed content</Badge>}
        </span>
      }
      actions={
        <>
          {exported && (
            <span className="hidden font-mono text-[11px] text-muted-foreground md:inline">
              exported {new Date(exported.created_at).toLocaleString()} · plan v{exported.content?.plan_version}
            </span>
          )}
          <Button size="sm" variant="ghost" onClick={open} title="Start the preview again with no progress"><RotateCcw /> Reset</Button>
          <Button size="sm" variant="ghost" asChild>
            <Link href={`/projects/${projectId}`}><ArrowLeft /> Project</Link>
          </Button>
        </>
      }
    >
      {error ? (
        <p className="p-6 text-sm text-destructive">Could not open the preview: {error}</p>
      ) : !session || !ready ? (
        <div className="space-y-3 p-6"><Skeleton className="h-6 w-64" /><Skeleton className="h-96 w-full" /></div>
      ) : (
        <ScormPlayer key={run} session={session} learnerId={user?.id ?? "preview"} learnerName={user?.name ?? "Preview learner"} />
      )}
    </Shell>
  );
}
