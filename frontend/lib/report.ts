// Compose the human-readable markdown for a completed FinalReport.
// Kept in lib/ (rather than inline in ReportStream) so header actions like
// Copy-to-clipboard can render the same thing the reader sees.

import type { FinalReport } from "@/lib/types";

export function composeReportMarkdown(report: FinalReport): string {
  const parts: string[] = [];
  parts.push(`# Executive Summary\n\n${report.executive_summary}\n`);
  for (const sec of report.sections) {
    parts.push(`# ${sec.heading}\n\n${sec.content}\n`);
  }
  if (report.citations.length > 0) {
    parts.push(`# Sources\n`);
    report.citations.forEach((src, i) => {
      parts.push(`[${i + 1}] ${src.title} — ${src.url}`);
    });
  }
  return parts.join("\n");
}
