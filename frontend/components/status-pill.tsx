"use client";

import type { StreamStatus } from "@/hooks/use-research-stream";

const LABEL: Record<StreamStatus, string> = {
  idle: "Ready",
  planning: "Planning",
  researching: "Researching",
  synthesizing: "Synthesizing",
  complete: "Synthesized",
  error: "Error",
};

export function StatusPill({ status }: { status: StreamStatus }) {
  const animated =
    status === "planning" || status === "researching" || status === "synthesizing";
  const tone =
    status === "error"
      ? "text-destructive"
      : status === "idle"
        ? "text-muted-foreground"
        : "text-primary";
  const dot =
    status === "error"
      ? "bg-destructive"
      : status === "idle"
        ? "bg-muted-foreground/60"
        : "bg-primary";
  return (
    <div className="inline-flex items-center gap-2">
      <span
        className={`h-1.5 w-1.5 rounded-full ${dot} ${animated ? "animate-pulse" : ""}`}
      />
      <span
        className={`font-mono text-[10px] uppercase tracking-widest ${tone}`}
      >
        {LABEL[status]}
      </span>
    </div>
  );
}
