"use client";

import { PlanTree } from "@/components/plan-tree";
import { ReportStream } from "@/components/report-stream";
import { CostMeter } from "@/components/cost-meter";
import { StatusPill } from "@/components/status-pill";
import { useResearchStream } from "@/hooks/use-research-stream";

export function ResearchLive({ reportId }: { reportId: string }) {
  const state = useResearchStream(reportId);
  const originalQuestion = state.plan?.original_question ?? state.report?.original_question ?? null;

  return (
    <div className="bg-background flex h-[100dvh] flex-col">
      <header className="flex items-center justify-between gap-4 border-b px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="font-semibold tracking-tight">Autonomous Research Assistant</h1>
          <StatusPill status={state.status} />
        </div>
        <CostMeter cumulativeUsd={state.cumulativeCostUsd} costByModel={state.costByModel} />
      </header>

      <main className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 md:grid-cols-[minmax(320px,420px)_1fr]">
        <aside className="overflow-hidden">
          <PlanTree
            originalQuestion={originalQuestion}
            agents={state.agents}
            isPlanning={state.status === "planning"}
          />
        </aside>
        <section className="overflow-hidden">
          <ReportStream
            streamedMarkdown={state.streamedMarkdown}
            report={state.report}
            isSynthesizing={state.status === "synthesizing"}
            isPending={
              state.status === "planning" ||
              (state.status === "researching" && state.streamedMarkdown.length === 0)
            }
          />
        </section>
      </main>

      {state.status === "error" && state.errorMessage ? (
        <footer className="border-destructive/40 bg-destructive/5 text-destructive border-t px-6 py-3 text-sm">
          Error: {state.errorMessage}
        </footer>
      ) : null}
    </div>
  );
}
