"use client";

import { useMemo, useState } from "react";
import { Check, Copy, Download, Share2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { PlanTree } from "@/components/plan-tree";
import { ReportStream } from "@/components/report-stream";
import { CostMeter } from "@/components/cost-meter";
import { StatusPill } from "@/components/status-pill";
import { SourcesList } from "@/components/sources-list";
import { useResearchStream } from "@/hooks/use-research-stream";
import { composeReportMarkdown } from "@/lib/report";
import type { Source } from "@/lib/types";

type Tab = "plan" | "report" | "sources";

const TABS: Array<{ value: Tab; label: string }> = [
  { value: "plan", label: "Plan" },
  { value: "report", label: "Report" },
  { value: "sources", label: "Sources" },
];

type Flash = "copy" | "share" | null;

export function ResearchLive({
  reportId,
  shareToken,
}: {
  reportId: string;
  shareToken?: string;
}) {
  // TODO(Task 12): surface a proper "access denied" UI when SSE 403s.
  const state = useResearchStream(reportId, shareToken);
  const [mobileTab, setMobileTab] = useState<Tab>("report");
  const [flash, setFlash] = useState<Flash>(null);

  const originalQuestion =
    state.plan?.original_question ?? state.report?.original_question ?? null;

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

  const webSearchEnabled =
    state.plan?.web_search_enabled ?? state.report?.web_search_enabled;

  const isComplete = state.status === "complete" && state.report !== null;

  const flashFor = (kind: Exclude<Flash, null>) => {
    setFlash(kind);
    window.setTimeout(() => setFlash((prev) => (prev === kind ? null : prev)), 1800);
  };

  const onCopy = async () => {
    if (!state.report) return;
    try {
      await navigator.clipboard.writeText(composeReportMarkdown(state.report));
      flashFor("copy");
    } catch {
      /* clipboard API blocked — swallow silently */
    }
  };

  const onShare = async () => {
    const url =
      typeof window !== "undefined" ? window.location.href : `/r/${reportId}`;
    const title = originalQuestion ?? "ARA report";
    if (typeof navigator !== "undefined" && "share" in navigator) {
      try {
        await navigator.share({ title, url });
        return;
      } catch {
        /* user cancelled or share failed — fall through to clipboard */
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      flashFor("share");
    } catch {
      /* clipboard API blocked — swallow silently */
    }
  };

  const planPanel = (
    <PlanTree
      originalQuestion={originalQuestion}
      agents={state.agents}
      isPlanning={state.status === "planning"}
      webSearchEnabled={webSearchEnabled}
    />
  );
  const reportPanel = (
    <ReportStream
      streamedMarkdown={state.streamedMarkdown}
      report={state.report}
      isSynthesizing={state.status === "synthesizing"}
      isPending={
        state.status === "planning" ||
        (state.status === "researching" && state.streamedMarkdown.length === 0)
      }
      questionForPrint={originalQuestion}
      title={originalQuestion}
      stats={
        isComplete && state.report
          ? {
              subQueries: state.plan?.sub_queries.length ?? state.agents.length,
              sources: state.report.citations.length,
              cumulativeUsd: state.cumulativeCostUsd,
            }
          : undefined
      }
    />
  );
  const sourcesPanel = (
    <div className="flex h-full flex-col gap-4 overflow-hidden">
      <div className="bg-card flex-1 overflow-y-auto rounded-lg p-5">
        <SourcesList citations={citations} />
      </div>
      <CostMeter
        cumulativeUsd={state.cumulativeCostUsd}
        costByModel={state.costByModel}
      />
    </div>
  );

  return (
    <div className="bg-background flex flex-1 flex-col overflow-hidden print:block print:h-auto print:overflow-visible">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-6 py-3 print:hidden">
        <div className="flex min-w-0 items-center gap-3">
          <StatusPill status={state.status} />
          {originalQuestion ? (
            <p className="text-muted-foreground line-clamp-1 min-w-0 truncate text-sm">
              {originalQuestion}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {isComplete ? (
            <>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void onCopy()}
                aria-label="Copy the report markdown to the clipboard"
                className="text-muted-foreground hover:text-foreground font-mono text-xs uppercase tracking-wider"
              >
                {flash === "copy" ? (
                  <Check
                    className="mr-1.5 h-3.5 w-3.5 text-primary"
                    strokeWidth={2}
                  />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.75} />
                )}
                {flash === "copy" ? "Copied" : "Copy"}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void onShare()}
                aria-label="Share the report link"
                className="text-muted-foreground hover:text-foreground font-mono text-xs uppercase tracking-wider"
              >
                {flash === "share" ? (
                  <Check
                    className="mr-1.5 h-3.5 w-3.5 text-primary"
                    strokeWidth={2}
                  />
                ) : (
                  <Share2 className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.75} />
                )}
                {flash === "share" ? "Link copied" : "Share"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.print()}
                aria-label="Save report as PDF via your browser's print dialog"
                className="font-mono text-xs uppercase tracking-wider"
              >
                <Download className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.75} />
                PDF
              </Button>
            </>
          ) : null}
        </div>
      </header>

      <div className="flex items-center gap-1 border-b border-white/[0.06] px-4 py-2 lg:hidden print:hidden">
        {TABS.map((tab) => {
          const active = mobileTab === tab.value;
          return (
            <button
              key={tab.value}
              type="button"
              onClick={() => setMobileTab(tab.value)}
              className={
                active
                  ? "text-primary border-primary border-b-2 px-3 py-1.5 font-mono text-xs uppercase tracking-wider"
                  : "text-muted-foreground hover:text-foreground border-b-2 border-transparent px-3 py-1.5 font-mono text-xs uppercase tracking-wider transition-colors"
              }
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <main className="hidden flex-1 gap-4 overflow-hidden p-4 lg:grid lg:grid-cols-[minmax(280px,320px)_1fr_minmax(300px,360px)] print:hidden">
        <aside className="overflow-hidden">{planPanel}</aside>
        <section className="flex flex-col overflow-hidden">{reportPanel}</section>
        <aside className="overflow-hidden">{sourcesPanel}</aside>
      </main>

      <main className="flex flex-1 flex-col overflow-hidden p-4 lg:hidden print:hidden">
        {mobileTab === "plan" ? planPanel : null}
        {mobileTab === "report" ? reportPanel : null}
        {mobileTab === "sources" ? sourcesPanel : null}
      </main>

      <section className="hidden print:block">{reportPanel}</section>

      {state.status === "error" && state.errorMessage ? (
        <footer className="border-destructive/40 bg-destructive/5 text-destructive border-t px-6 py-3 text-sm print:hidden">
          Error: {state.errorMessage}
        </footer>
      ) : null}
    </div>
  );
}
