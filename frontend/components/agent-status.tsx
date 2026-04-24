"use client";

import type { AgentPhase } from "@/hooks/use-research-stream";

const LABEL: Record<AgentPhase, string> = {
  pending: "Queued",
  running: "Researching",
  done: "Done",
  error: "Failed",
};

export function AgentStatus({ phase }: { phase: AgentPhase }) {
  const tone =
    phase === "error"
      ? "text-destructive"
      : phase === "pending"
        ? "text-muted-foreground/60"
        : phase === "done"
          ? "text-muted-foreground"
          : "text-primary";
  const dot =
    phase === "error"
      ? "bg-destructive"
      : phase === "pending"
        ? "bg-muted-foreground/40"
        : phase === "done"
          ? "bg-muted-foreground/60"
          : "bg-primary animate-pulse";
  return (
    <div className="inline-flex shrink-0 items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      <span
        className={`font-mono text-[10px] uppercase tracking-widest ${tone}`}
      >
        {LABEL[phase]}
      </span>
    </div>
  );
}
