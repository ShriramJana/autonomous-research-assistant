"use client";

import { GlobeLock } from "lucide-react";

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
    <div className="bg-card flex h-full flex-col overflow-hidden rounded-lg">
      <div className="border-border/40 flex flex-col gap-2 border-b px-5 py-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-widest">
          Research plan
        </p>
        {originalQuestion ? (
          <p className="text-foreground line-clamp-3 text-sm leading-snug">
            {originalQuestion}
          </p>
        ) : null}
        {offline ? (
          <div
            className="border-border/60 bg-secondary/50 text-muted-foreground mt-1 inline-flex items-center gap-1.5 self-start rounded px-2 py-1"
            title="Researchers answered from training knowledge — sources may be sparse or canonical-only."
          >
            <GlobeLock className="h-3 w-3" strokeWidth={1.75} />
            <span className="font-mono text-[10px] uppercase tracking-wider">
              Web search disabled
            </span>
          </div>
        ) : null}
      </div>
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {isPlanning && agents.length === 0 ? (
          <>
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </>
        ) : null}
        {agents.map((agent, i) => (
          <AgentRow key={agent.subQueryId} index={i + 1} agent={agent} />
        ))}
      </div>
    </div>
  );
}

function AgentRow({ index, agent }: { index: number; agent: AgentState }) {
  return (
    <div className="hover:bg-secondary/40 flex flex-col gap-2 rounded-md p-3 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="text-muted-foreground/60 mt-0.5 font-mono text-[10px]">
            {String(index).padStart(2, "0")}
          </span>
          <p className="text-foreground min-w-0 text-sm leading-snug">
            {agent.question}
          </p>
        </div>
        <AgentStatus phase={agent.phase} />
      </div>
      {agent.lastToolCall ? (
        <p className="text-muted-foreground/70 truncate pl-6 font-mono text-[10px]">
          → {agent.lastToolCall}
        </p>
      ) : null}
      {agent.errorMessage ? (
        <p className="text-destructive pl-6 font-mono text-[10px]">
          {agent.errorMessage}
        </p>
      ) : null}
      {agent.finding && agent.phase === "done" ? (
        <p className="text-muted-foreground/80 line-clamp-2 pl-6 text-xs leading-snug">
          {agent.finding.summary}
        </p>
      ) : null}
    </div>
  );
}

export { PRIORITY_LABEL };
