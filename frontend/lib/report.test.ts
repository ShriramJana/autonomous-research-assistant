import { describe, expect, it } from "vitest";
import { composeReportMarkdown } from "@/lib/report";
import type { FinalReport } from "@/lib/types";

const report: FinalReport = {
  report_id: "r",
  original_question: "q",
  executive_summary: "E",
  sections: [{ heading: "H", content: "C [1] [2].", citation_ids: [] }],
  citations: [
    {
      id: "1", url: "https://doi.org/10.1/x", title: "Paper", kind: "scholarly",
      authors: ["A", "B"], year: 2020, venue: "V", citation_count: 5,
    },
    { id: "2", url: "https://a.com", title: "Web" },
  ],
};

describe("composeReportMarkdown", () => {
  it("adds a meta line under scholarly sources only", () => {
    const md = composeReportMarkdown(report);
    expect(md).toContain("[1] Paper — https://doi.org/10.1/x\n    A, B (2020) · V · 5 citations");
    expect(md).toContain("[2] Web — https://a.com");
    expect(md).not.toContain("[2] Web — https://a.com\n    ");
  });
});
