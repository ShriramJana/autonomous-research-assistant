"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { createResearch } from "@/lib/api";

export function ResearchForm({
  initialQuestion = "",
  compact = false,
}: {
  initialQuestion?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [question, setQuestion] = useState(initialQuestion);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    setError(null);
    setSubmitting(true);
    try {
      const { report_id } = await createResearch(question.trim());
      router.push(`/r/${report_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="flex w-full flex-col gap-3">
      <Textarea
        placeholder="e.g. How should we evaluate RAG vs fine-tuning for enterprise LLM apps in 2026?"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={compact ? 3 : 5}
        disabled={submitting}
        className="resize-none"
      />
      <div className="flex items-center justify-between gap-3">
        {error ? (
          <p className="text-destructive text-sm">{error}</p>
        ) : (
          <span className="text-muted-foreground text-xs">
            ⌘/Ctrl + Enter to submit
          </span>
        )}
        <Button type="submit" disabled={!question.trim() || submitting}>
          {submitting ? "Starting…" : "Research"}
        </Button>
      </div>
    </form>
  );
}
