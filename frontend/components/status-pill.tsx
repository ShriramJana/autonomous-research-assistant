"use client";

import { Badge } from "@/components/ui/badge";
import type { StreamStatus } from "@/hooks/use-research-stream";

const LABEL: Record<StreamStatus, string> = {
  idle: "Ready",
  planning: "Planning",
  researching: "Researching",
  synthesizing: "Synthesizing",
  complete: "Complete",
  error: "Error",
};

const VARIANT: Record<StreamStatus, "default" | "secondary" | "destructive" | "outline"> = {
  idle: "outline",
  planning: "default",
  researching: "default",
  synthesizing: "default",
  complete: "secondary",
  error: "destructive",
};

export function StatusPill({ status }: { status: StreamStatus }) {
  const animated = status === "planning" || status === "researching" || status === "synthesizing";
  return (
    <Badge variant={VARIANT[status]} className="gap-1.5 py-1">
      {animated ? (
        <span className="bg-primary-foreground inline-block size-1.5 animate-pulse rounded-full" />
      ) : null}
      {LABEL[status]}
    </Badge>
  );
}
