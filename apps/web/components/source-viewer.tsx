"use client";

import { useEffect, useState } from "react";
import { Download, X } from "lucide-react";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { downloadFile, fetchBlob, type Source } from "@/lib/api";
import { formatBytes } from "@/lib/utils";

type Loaded = { kind: "pdf"; url: string } | { kind: "text"; text: string };

/**
 * An uploaded source in its own format: PDFs, and Word and PowerPoint files rendered to PDF at
 * ingestion (app/core/rag/rendition.py), open in the browser's PDF viewer; Markdown and text show
 * as text. The bytes arrive with the login token, so the PDF is handed to the viewer as a blob URL
 * typed application/pdf.
 */
export function SourceViewer({ projectId, source, onClose }: { projectId: string; source: Source; onClose: () => void }) {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const viewer = source.viewer;

  useEffect(() => {
    if (!viewer) return;
    let url: string | null = null;
    let cancelled = false;
    setLoaded(null);
    setError(null);
    fetchBlob(`/projects/${projectId}/sources/${source.id}/view`)
      .then(async (blob) => {
        if (cancelled) return;
        if (viewer === "pdf") {
          url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
          setLoaded({ kind: "pdf", url });
        } else {
          setLoaded({ kind: "text", text: await blob.text() });
        }
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [projectId, source.id, viewer]);

  const rendered = /\.(docx|pptx)$/i.test(source.filename);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between gap-3 border-b px-6 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium" title={source.filename}>{source.filename}</p>
          <p className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
            <span>{formatBytes(source.size_bytes)}{source.page_count ? ` · ${source.page_count}p` : ""}{source.chunk_count ? ` · ${source.chunk_count} chunks` : ""}</span>
            <Badge tone={statusTone(source.status)}>{source.status}</Badge>
            {rendered && viewer && <span className="font-sans">Shown as a PDF rendering of the original</span>}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" onClick={() => downloadFile(`/projects/${projectId}/sources/${source.id}/original`, source.filename).catch((e: Error) => setError(e.message))}>
            <Download /> Original
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close the viewer"><X /></Button>
        </div>
      </div>
      {error ? (
        <p className="p-6 text-sm text-destructive">Could not open this file: {error}</p>
      ) : !viewer ? (
        <p className="p-6 text-sm text-muted-foreground">
          {rendered
            ? source.status === "ready" || source.status === "failed"
              ? "No viewable copy of this file was made. Re-ingest it to render one, or download the original."
              : "A viewable copy is made while the file is ingested. Check back when it is ready."
            : "This file type cannot be shown here. Download the original to open it."}
        </p>
      ) : !loaded ? (
        <div className="p-6"><Skeleton className="h-[60vh] w-full" /></div>
      ) : loaded.kind === "pdf" ? (
        <iframe src={loaded.url} title={source.filename} className="min-h-[60vh] w-full flex-1 bg-muted" />
      ) : (
        <pre className="m-0 min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words bg-surface p-6 font-mono text-[13px] leading-relaxed">{loaded.text}</pre>
      )}
    </div>
  );
}
