"use client";

import { GlobeLock } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { AgentStatus } from "@/components/agent-status";
import { deriveStages } from "@/lib/timeline";
import type { StageStatus, TimelineStage } from "@/lib/timeline";
import type { AgentState, ResearchStreamState } from "@/hooks/use-research-stream";

function dotClass(status: StageStatus): string {
  if (status === "error") return "bg-destructive";
  if (status === "active") return "bg-primary animate-pulse";
  if (status === "done") return "bg-primary";
  return "border border-muted-foreground/40 bg-transparent";
}

export function ResearchTimeline({ state }: { state: ResearchStreamState }) {
  const stages = deriveStages(state);
  const originalQuestion =
    state.plan?.original_question ?? state.report?.original_question ?? null;
  const webSearchEnabled =
    state.plan?.web_search_enabled ?? state.report?.web_search_enabled;
  const offline = webSearchEnabled === false;
  const isPlanning = state.status === "planning";

  return (
    <div className="bg-card flex h-full flex-col overflow-hidden rounded-lg">
      <div className="border-border/40 flex flex-col gap-2 border-b px-5 py-4">
        <p className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-widest">
          Research timeline
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
      <div className="flex flex-1 flex-col overflow-y-auto p-4">
        {stages.map((stage, i) => (
          <StageNode key={stage.key} stage={stage} isLast={i === stages.length - 1}>
            {stage.key === "research" ? (
              <div className="mt-1 flex flex-col gap-1">
                {isPlanning && state.agents.length === 0 ? (
                  <>
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                  </>
                ) : null}
                {state.agents.map((agent, idx) => (
                  <AgentRow key={agent.subQueryId} index={idx + 1} agent={agent} />
                ))}
              </div>
            ) : null}
          </StageNode>
        ))}
      </div>
    </div>
  );
}

function StageNode({
  stage,
  isLast,
  children,
}: {
  stage: TimelineStage;
  isLast: boolean;
  children?: React.ReactNode;
}) {
  const muted = stage.status === "pending";
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <span className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${dotClass(stage.status)}`} />
        {!isLast ? <span className="bg-border/60 w-px flex-1" /> : null}
      </div>
      <div className="flex-1 pb-5">
        <div className="flex items-center justify-between gap-2">
          <span
            className={`font-mono text-[11px] uppercase tracking-widest ${
              muted ? "text-muted-foreground/50" : "text-foreground"
            }`}
          >
            {stage.label}
          </span>
          {stage.detail ? (
            <span className="text-muted-foreground/60 font-mono text-[10px]">
              {stage.detail}
            </span>
          ) : null}
        </div>
        {children}
      </div>
    </div>
  );
}

function AgentRow({ index, agent }: { index: number; agent: AgentState }) {
  return (
    <div className="hover:bg-secondary/40 flex flex-col gap-1.5 rounded-md p-2.5 transition-colors">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="text-muted-foreground/60 mt-0.5 font-mono text-[10px]">
            {String(index).padStart(2, "0")}
          </span>
          <p className="text-foreground min-w-0 text-xs leading-snug">
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
