import { ShieldCheck, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { GroundingIssue, ReviewerReview } from "@/lib/api";
import { cn } from "@/lib/utils";

/** How the trained reviewer's findings appear in the lesson view. Every finding is advisory. */

type SlideReview = ReviewerReview["slides"][string];
type QuestionReview = ReviewerReview["questions"][string];

const MARKER = /\[\d{1,3}\]/g;
const CONFLICT = "underline decoration-destructive decoration-wavy decoration-1 underline-offset-4";
const BASELESS = "underline decoration-warning decoration-wavy decoration-1 underline-offset-4";

// The RAGTruth issue types the reviewer was trained on, in an instructor's words.
const ISSUE: Record<string, { label: string; tone: "destructive" | "warning" }> = {
  evident_conflict: { label: "Contradicts the source", tone: "destructive" },
  subtle_conflict: { label: "Subtly contradicts the source", tone: "destructive" },
  evident_baseless: { label: "Not in the source", tone: "warning" },
  subtle_baseless: { label: "Goes beyond the source", tone: "warning" },
};
const issueKind = (type: string) => ISSUE[type] ?? { label: "Unclassified issue", tone: "warning" as const };
const isConflict = (i: GroundingIssue) => i.type.endsWith("_conflict");

// Oak MinDiff anchors: 5 = minimally distinct options, 1 = clearly distinct.
const DISTRACTORS: Record<number, string> = {
  1: "wrong options are easy to rule out",
  2: "most wrong options are easy to rule out",
  3: "some wrong options are plausible",
  4: "wrong options are mostly plausible",
  5: "wrong options differ only subtly from the answer",
};

// Spans are copied from the text the reviewer saw: "- " before bullets, "Speaker notes: " before notes.
const PREFIX = /^\s*(speaker notes:|[-•])\s*/i;
const norm = (s: string) => s.replace(MARKER, "").replace(PREFIX, "").replace(/\s+/g, " ").trim().toLowerCase();

/** Wavy-underline class for a piece of slide text that a flagged span overlaps, or "". */
function flagClass(text: string, review?: SlideReview): string {
  const t = norm(text);
  if (!review?.issues.length || !t) return "";
  const hits = review.issues.filter((i) => {
    const s = norm(i.span);
    return s.length > 0 && (t.includes(s) || (t.length >= 12 && s.includes(t)));
  });
  if (!hits.length) return "";
  return hits.some(isConflict) ? CONFLICT : BASELESS;
}

/**
 * Splits slide text around the reviewer's flagged spans so only the flagged words are underlined.
 * A span that is not found verbatim (it crosses a citation marker, or covers several bullets)
 * underlines the whole piece it overlaps instead.
 */
export function flagPieces(text: string, review?: SlideReview): { text: string; flag: string }[] {
  const lower = text.toLowerCase();
  const ranges = (review?.issues ?? [])
    .map((i) => {
      const span = i.span.replace(PREFIX, "").trim();
      const at = span ? lower.indexOf(span.toLowerCase()) : -1;
      return { at, end: at + span.length, flag: isConflict(i) ? CONFLICT : BASELESS };
    })
    .filter((r) => r.at >= 0)
    .sort((a, b) => a.at - b.at);
  if (!ranges.length) return [{ text, flag: flagClass(text, review) }];
  const pieces: { text: string; flag: string }[] = [];
  let pos = 0;
  for (const r of ranges) {
    if (r.at < pos) continue; // overlaps a span already marked
    if (r.at > pos) pieces.push({ text: text.slice(pos, r.at), flag: "" });
    pieces.push({ text: text.slice(r.at, r.end), flag: r.flag });
    pos = r.end;
  }
  if (pos < text.length) pieces.push({ text: text.slice(pos), flag: "" });
  return pieces;
}

const weighted = (expected: number | null) => (expected != null ? `Weighted by the reviewer's score probabilities: ${expected.toFixed(1)}` : undefined);

function Pips({ score }: { score: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-hidden>
      {[1, 2, 3, 4, 5].map((n) => <span key={n} className={`h-1.5 w-3 rounded-sm ${n <= score ? "bg-foreground/70" : "bg-muted"}`} />)}
    </span>
  );
}

export function ReviewerSummary({ deck, quiz }: { deck?: ReviewerReview; quiz?: ReviewerReview }) {
  const r = deck ?? quiz;
  if (!r) return null;
  const slides = Object.values(deck?.slides ?? {});
  const issues = slides.flatMap((s) => s.issues);
  const questions = Object.values(quiz?.questions ?? {});
  const scored = questions.filter((q) => q.valid && q.score != null).map((q) => q.score as number);
  const unreadable = slides.filter((s) => !s.valid).length + questions.filter((q) => !q.valid).length + (deck?.rubric ?? []).filter((c) => !c.valid).length;
  const stale = Boolean(deck?.stale || quiz?.stale);
  const conflicts = issues.filter(isConflict).length;
  const kinds = [
    conflicts ? `${conflicts} ${conflicts === 1 ? "contradicts" : "contradict"} the source` : "",
    issues.length - conflicts ? `${issues.length - conflicts} not supported by it` : "",
  ].filter(Boolean).join(", ");
  const weak = scored.filter((s) => s <= 2).length;

  return (
    <section className="space-y-3 rounded-md border bg-surface p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <ShieldCheck className="size-4 text-muted-foreground" />
        <h3 className="font-semibold">Reviewer findings</h3>
        <Badge>advisory</Badge>
        {stale && <Badge tone="warning">out of date</Badge>}
      </div>
      <p className="font-mono text-[11px] text-muted-foreground">
        {r.base_model ?? "unknown model"}{r.adapter ? ` + adapter ${r.adapter}${r.adapter_checkpoint ? ` (${r.adapter_checkpoint})` : ""}` : " (no adapter)"}
        {r.reviewed_at ? ` · reviewed ${r.reviewed_at.replace("T", " ").slice(0, 16)}` : ""}{r.prompt_version ? ` · prompts ${r.prompt_version}` : ""}
      </p>
      {stale && <p className="text-xs text-warning">This lesson was edited after it was reviewed. The findings describe the earlier version.</p>}
      {(deck?.changed?.length || quiz?.changed?.length) ? (
        <p className="text-xs text-muted-foreground">
          {[deck?.changed?.length ? `${deck.changed.length} ${deck.changed.length === 1 ? "slide" : "slides"}` : "", quiz?.changed?.length ? `${quiz.changed.length} ${quiz.changed.length === 1 ? "question" : "questions"}` : ""].filter(Boolean).join(" and ")}{" "}
          changed since this review, so their findings were cleared.
        </p>
      ) : null}

      <ul className="space-y-0.5 text-xs">
        {deck && (
          <li>
            {issues.length ? (
              <><span className="font-medium">{issues.length} flagged {issues.length === 1 ? "span" : "spans"}</span> on {slides.filter((s) => s.issues.length).length} of {slides.length} slides ({kinds})</>
            ) : (
              <>No unsupported or conflicting statements found on {slides.length} slides</>
            )}
          </li>
        )}
        {scored.length > 0 && (
          <li>Quiz distractor quality: {scored.map((s) => `${s}/5`).join(", ")}{weak ? ` · ${weak} ${weak === 1 ? "question has" : "questions have"} easy-to-rule-out options` : ""}</li>
        )}
        {unreadable > 0 && <li className="text-muted-foreground">{unreadable} reviewer {unreadable === 1 ? "reply" : "replies"} could not be read</li>}
      </ul>

      {deck && deck.rubric.length > 0 && (
        // Folded by default: the feedback is long, and the flagged slides below matter more.
        <details className="group/scores">
          <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-1 text-xs [&::-webkit-details-marker]:hidden">
            <span className="font-medium">Lesson scores</span>
            {deck.rubric.map((c) => (
              <span key={c.criterion_id} className="flex items-center gap-1.5" title={weighted(c.expected)}>
                {c.criterion} {c.valid && c.score != null ? <><Pips score={c.score} /><span className="font-mono font-semibold">{c.score}/5</span></> : <span className="text-muted-foreground">unreadable</span>}
              </span>
            ))}
            {deck.rubric_stale && <span className="text-muted-foreground">scored before the latest changes</span>}
            <span className="ml-auto text-muted-foreground underline decoration-dotted underline-offset-4 group-open/scores:hidden">Show feedback</span>
          </summary>
          <div className="mt-3 space-y-3">
            <div className={cn("grid gap-2 sm:grid-cols-2", deck.rubric_stale && "opacity-70")}>
              {deck.rubric.map((c) => (
                <div key={c.criterion_id} className="rounded-md border p-3">
                  <p className="text-xs font-medium">{c.criterion}{c.valid && c.score != null ? ` · ${c.score}/5` : ""}</p>
                  {c.feedback && <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{c.feedback}</p>}
                </div>
              ))}
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              Each slide is checked against the source passages its deck was generated from. The two lesson scores apply the reviewer&apos;s
              general rubric training to course criteria it was not trained on, so treat them as a second opinion. Findings never change approval.
            </p>
          </div>
        </details>
      )}
    </section>
  );
}

export function SlideFindings({ review, onFix }: { review?: SlideReview; onFix?: () => void }) {
  if (!review) return null;
  if (!review.valid) {
    return <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">The reviewer&apos;s reply for this slide could not be read{review.error ? ` (${review.error})` : ""}.</p>;
  }
  if (!review.issues.length) {
    return <p className="mt-3 flex items-center gap-1.5 border-t pt-2 text-xs text-success"><ShieldCheck className="size-3.5" />Reviewer found nothing unsupported or conflicting.</p>;
  }
  return (
    <div className="mt-3 space-y-1.5 border-t pt-2">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <TriangleAlert className="size-3.5 text-warning" />Reviewer flagged {review.issues.length} {review.issues.length === 1 ? "span" : "spans"}
        {onFix && <Button size="sm" variant="accent" className="ml-auto h-7" onClick={onFix}>Fix</Button>}
      </p>
      <ul className="space-y-1.5">
        {review.issues.map((i, k) => (
          <li key={k} className="text-xs leading-relaxed">
            <Badge tone={issueKind(i.type).tone} className="mr-1.5">{issueKind(i.type).label}</Badge>
            “{i.span.replace(PREFIX, "")}”
            {/^\s*speaker notes:/i.test(i.span) && <span className="text-muted-foreground"> · in the speaker notes</span>}
            {i.implicit_true && <span className="text-muted-foreground"> · probably true, but the source does not say it</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DistractorFinding({ review, onImprove }: { review?: QuestionReview; onImprove?: () => void }) {
  if (!review) return null;
  if (!review.valid || review.score == null) return <p className="mt-2 text-xs text-muted-foreground">The reviewer&apos;s reply for this question could not be read.</p>;
  const tone = review.score >= 4 ? "success" : review.score <= 2 ? "warning" : "neutral";
  return (
    <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
      <Badge tone={tone} title={weighted(review.expected)}>Distractors {review.score}/5</Badge>
      <span>{DISTRACTORS[review.score]}</span>
      {onImprove && review.score <= 2 && <Button size="sm" variant="outline" className="ml-auto h-7" onClick={onImprove}>Improve options</Button>}
    </p>
  );
}
