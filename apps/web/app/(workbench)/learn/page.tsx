"use client";

import { Shell } from "@/components/layout/shell";

export default function LearnPage() {
  return (
    <Shell title="Learn">
      <div className="container py-10 text-sm text-muted-foreground">
        <p className="text-foreground font-medium">Learner preview</p>
        <p>Approved courses will appear here as an HTML preview of the SCORM package (milestone M4). Learners can step through lessons and take quizzes without leaving the browser.</p>
      </div>
    </Shell>
  );
}
