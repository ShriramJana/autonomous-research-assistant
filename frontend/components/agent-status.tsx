"use client";

import { Badge } from "@/components/ui/badge";
import type { AgentPhase } from "@/hooks/use-research-stream";
import { cn } from "@/lib/utils";

const LABEL: Record<AgentPhase, string> = {
  pending: "Queued",
  running: "Researching",
  done: "Done",
  error: "Failed",
};

const VARIANT: Record<AgentPhase, "secondary" | "default" | "destructive" | "outline"> = {
  pending: "outline",
  running: "default",
  done: "secondary",
  error: "destructive",
};

export function AgentStatus({ phase }: { phase: AgentPhase }) {
  return (
    <Badge variant={VARIANT[phase]} className={cn("gap-1.5")}>
      {phase === "running" ? (
        <span className="bg-primary-foreground inline-block size-1.5 animate-pulse rounded-full" />
      ) : null}
      {LABEL[phase]}
    </Badge>
  );
}
