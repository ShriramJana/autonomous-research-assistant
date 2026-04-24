"use client";

import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Skeleton } from "@/components/ui/skeleton";
import { Citation } from "@/components/citation";
import { composeReportMarkdown } from "@/lib/report";
import type { FinalReport, Source } from "@/lib/types";

const CITE_RE = /\[(\d+)\]/g;

export interface ReportStats {
  subQueries: number;
  sources: number;
  cumulativeUsd: number;
}

export function ReportStream({
  streamedMarkdown,
  report,
  isSynthesizing,
  isPending,
  questionForPrint,
  title,
  stats,
}: {
  streamedMarkdown: string;
  report: FinalReport | null;
  isSynthesizing: boolean;
  isPending: boolean;
  questionForPrint?: string | null;
  title?: string | null;
  stats?: ReportStats;
}) {
  const citations: Source[] = useMemo(() => report?.citations ?? [], [report]);
  const markdown = report ? composeReportMarkdown(report) : streamedMarkdown;
  const showCompletedHeader = report !== null && title;

  return (
    <div className="bg-card flex h-full flex-col overflow-hidden rounded-lg print:block print:h-auto print:overflow-visible print:border-0 print:bg-transparent print:shadow-none">
      <div className="flex-1 overflow-y-auto px-8 py-8 print:overflow-visible print:p-0">
        {questionForPrint ? (
          <div className="hidden print:mb-6 print:block">
            <p className="text-muted-foreground font-mono text-xs uppercase tracking-wider">
              Research question
            </p>
            <h1 className="text-xl font-semibold">{questionForPrint}</h1>
          </div>
        ) : null}

        {showCompletedHeader ? (
          <div className="mb-8 flex max-w-2xl flex-col gap-3 print:hidden">
            <p className="text-primary font-mono text-[10px] uppercase tracking-[0.2em]">
              Report output · stable
            </p>
            <h1 className="text-foreground text-2xl font-semibold leading-tight tracking-tight md:text-3xl">
              {title}
            </h1>
            {stats ? (
              <div className="text-muted-foreground/70 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-widest">
                <span>
                  <span className="text-foreground">
                    {String(stats.subQueries).padStart(2, "0")}
                  </span>{" "}
                  sub-queries
                </span>
                <span>
                  <span className="text-foreground">
                    {String(stats.sources).padStart(2, "0")}
                  </span>{" "}
                  sources
                </span>
                <span>
                  <span className="text-foreground">
                    ${stats.cumulativeUsd.toFixed(4)}
                  </span>{" "}
                  cost
                </span>
              </div>
            ) : null}
          </div>
        ) : null}

        {isPending ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-11/12" />
            <Skeleton className="h-4 w-10/12" />
          </div>
        ) : (
          <article className="prose prose-sm dark:prose-invert prose-headings:font-semibold prose-headings:tracking-tight prose-p:leading-relaxed max-w-2xl">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                p: ({ children }) => (
                  <p>{renderWithCitations(children, citations)}</p>
                ),
                li: ({ children }) => (
                  <li>{renderWithCitations(children, citations)}</li>
                ),
              }}
            >
              {markdown}
            </ReactMarkdown>
            {isSynthesizing && !report ? (
              <span className="bg-primary inline-block h-4 w-1 translate-y-0.5 animate-pulse rounded-sm align-middle" />
            ) : null}
          </article>
        )}
      </div>
    </div>
  );
}

function renderWithCitations(
  children: React.ReactNode,
  citations: Source[],
): React.ReactNode {
  if (children == null) return children;
  if (Array.isArray(children)) {
    return children.map((c, i) => (
      <span key={i}>{renderWithCitations(c, citations)}</span>
    ));
  }
  if (typeof children !== "string") return children;
  const out: React.ReactNode[] = [];
  let lastIdx = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(CITE_RE.source, "g");
  while ((match = re.exec(children)) !== null) {
    const [full, numStr] = match;
    const n = Number(numStr);
    if (match.index > lastIdx) out.push(children.slice(lastIdx, match.index));
    out.push(
      <Citation
        key={`${match.index}-${n}`}
        number={n}
        source={citations[n - 1]}
      />,
    );
    lastIdx = match.index + full.length;
  }
  if (lastIdx < children.length) out.push(children.slice(lastIdx));
  return out.length > 0 ? out : children;
}
