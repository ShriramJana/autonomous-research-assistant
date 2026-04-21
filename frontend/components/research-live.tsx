"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { PlanTree } from "@/components/plan-tree";
import { ReportStream } from "@/components/report-stream";
import { CostMeter } from "@/components/cost-meter";
import { StatusPill } from "@/components/status-pill";
import { SourcesList } from "@/components/sources-list";
import { useResearchStream } from "@/hooks/use-research-stream";
import { updateHistoryItem } from "@/lib/history";
import type { Source } from "@/lib/types";

export function ResearchLive({ reportId }: { reportId: string }) {
  const state = useResearchStream(reportId);
  const originalQuestion =
    state.plan?.original_question ?? state.report?.original_question ?? null;

  // Sources visible under the report: prefer the deduped master list
  // from the final report; while still researching, show a running
  // URL-deduped union of whatever findings have arrived.
  const citations: Source[] = useMemo(() => {
    if (state.report) return state.report.citations;
    const seen = new Set<string>();
    const out: Source[] = [];
    for (const agent of state.agents) {
      for (const src of agent.finding?.sources ?? []) {
        if (!seen.has(src.url)) {
          seen.add(src.url);
          out.push(src);
        }
      }
    }
    return out;
  }, [state.report, state.agents]);

  // Mirror the stream state into the localStorage history entry.
  useEffect(() => {
    if (state.status === "complete" && state.report) {
      updateHistoryItem(reportId, {
        status: "complete",
        executiveSummary: state.report.executive_summary,
      });
    } else if (state.status === "error") {
      updateHistoryItem(reportId, { status: "error" });
    }
  }, [state.status, state.report, reportId]);

  const isComplete = state.status === "complete" && state.report !== null;

  return (
    <div className="bg-background flex h-[100dvh] flex-col print:block print:h-auto">
      <header className="flex items-center justify-between gap-4 border-b px-6 py-3 print:hidden">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="font-semibold tracking-tight hover:underline"
          >
            Autonomous Research Assistant
          </Link>
          <StatusPill status={state.status} />
        </div>
        <div className="flex items-center gap-2">
          {isComplete ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.print()}
              aria-label="Save report as PDF via your browser's print dialog"
            >
              Download PDF
            </Button>
          ) : null}
          <CostMeter
            cumulativeUsd={state.cumulativeCostUsd}
            costByModel={state.costByModel}
          />
        </div>
      </header>

      <main className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 md:grid-cols-[minmax(320px,420px)_1fr] print:grid-cols-1 print:gap-0 print:overflow-visible print:p-0">
        <aside className="overflow-hidden print:hidden">
          <PlanTree
            originalQuestion={originalQuestion}
            agents={state.agents}
            isPlanning={state.status === "planning"}
          />
        </aside>
        <section className="flex flex-col overflow-hidden print:overflow-visible">
          <ReportStream
            streamedMarkdown={state.streamedMarkdown}
            report={state.report}
            isSynthesizing={state.status === "synthesizing"}
            isPending={
              state.status === "planning" ||
              (state.status === "researching" && state.streamedMarkdown.length === 0)
            }
            footer={<SourcesList citations={citations} />}
            questionForPrint={originalQuestion}
          />
        </section>
      </main>

      {state.status === "error" && state.errorMessage ? (
        <footer className="border-destructive/40 bg-destructive/5 text-destructive border-t px-6 py-3 text-sm print:hidden">
          Error: {state.errorMessage}
        </footer>
      ) : null}
    </div>
  );
}
