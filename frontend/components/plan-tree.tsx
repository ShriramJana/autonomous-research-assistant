"use client";

import { GlobeLock } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { AgentStatus } from "@/components/agent-status";
import type { AgentState } from "@/hooks/use-research-stream";

const PRIORITY_LABEL = { 3: "HIGH", 2: "MED", 1: "LOW" } as const;

export function PlanTree({
  originalQuestion,
  agents,
  isPlanning,
  webSearchEnabled,
}: {
  originalQuestion: string | null;
  agents: AgentState[];
  isPlanning: boolean;
  webSearchEnabled?: boolean;
}) {
  const offline = webSearchEnabled === false;
  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium tracking-tight">
          Research plan
        </CardTitle>
        {originalQuestion ? (
          <p className="text-muted-foreground line-clamp-3 text-xs">
            {originalQuestion}
          </p>
        ) : null}
        {offline ? (
          <div
            className="border-border/60 bg-secondary/50 text-muted-foreground mt-2 inline-flex items-center gap-1.5 self-start rounded px-2 py-1"
            title="Researchers answered from training knowledge — sources may be sparse or canonical-only."
          >
            <GlobeLock className="h-3 w-3" strokeWidth={1.75} />
            <span className="font-mono text-[10px] uppercase tracking-wider">
              Web search disabled
            </span>
          </div>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3 overflow-y-auto pb-4">
        {isPlanning && agents.length === 0 ? (
          <>
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </>
        ) : null}
        {agents.map((agent, i) => (
          <AgentRow key={agent.subQueryId} index={i + 1} agent={agent} />
        ))}
      </CardContent>
    </Card>
  );
}

function AgentRow({ index, agent }: { index: number; agent: AgentState }) {
  return (
    <div className="group border-border/60 bg-card hover:border-border flex flex-col gap-2 rounded-md border p-3 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <span className="text-muted-foreground mt-0.5 font-mono text-[11px]">
            {String(index).padStart(2, "0")}
          </span>
          <p className="text-foreground text-sm leading-snug">{agent.question}</p>
        </div>
        <AgentStatus phase={agent.phase} />
      </div>
      {agent.lastToolCall ? (
        <p className="text-muted-foreground truncate font-mono text-[11px]">
          → {agent.lastToolCall}
        </p>
      ) : null}
      {agent.errorMessage ? (
        <p className="text-destructive text-xs">{agent.errorMessage}</p>
      ) : null}
      {agent.finding && agent.phase === "done" ? (
        <p className="text-muted-foreground line-clamp-2 text-xs">
          {agent.finding.summary}
        </p>
      ) : null}
    </div>
  );
}

// Exporting PRIORITY_LABEL to silence unused-var warnings if other callers
// want to render priority later; PlanTree itself doesn't render it yet.
export { PRIORITY_LABEL };
