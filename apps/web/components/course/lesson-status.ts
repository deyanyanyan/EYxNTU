import type { CoursePlan, LessonSummary } from "@/lib/api";

/** One state per lesson, shown the same way in the outline, the lesson list and the tab badge. */
export type LessonState = { label: string; tone: "neutral" | "accent" | "success" | "warning" };

export const lessonFlags = (l: LessonSummary) => (l.reviewer_flags ?? 0) + l.weak_questions;
export const isGenerated = (l: LessonSummary) => l.slides > 0 || l.questions > 0;

export function lessonState(l: LessonSummary): LessonState {
  if (!isGenerated(l)) return { label: "not generated", tone: "neutral" };
  if (l.approved) return { label: "approved", tone: "success" };
  if (l.proposals) return { label: `${l.proposals} to review`, tone: "accent" };
  const flags = lessonFlags(l);
  if (flags) return { label: `${flags} flagged`, tone: "warning" };
  if (l.reviewer_flags === null && !l.weak_questions) return { label: "not reviewed", tone: "neutral" };
  return { label: "no flags", tone: "success" };
}

/** Lessons in teaching order, numbered as the outline numbers them ("1.2"). */
export function numbered(plan: CoursePlan): { lesson: LessonSummary; index: string; moduleId: string; moduleTitle: string }[] {
  return [...plan.modules]
    .sort((a, b) => a.position - b.position)
    .flatMap((m) => [...m.lessons].sort((a, b) => a.position - b.position).map((lesson) => ({ lesson, index: `${m.position}.${lesson.position}`, moduleId: m.id, moduleTitle: m.title })));
}
