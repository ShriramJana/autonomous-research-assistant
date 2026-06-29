// frontend/lib/timeline.test.ts
import { describe, expect, it } from "vitest";
import { deriveStages } from "@/lib/timeline";
import { initialState } from "@/hooks/use-research-stream";
import type { AgentState, ResearchStreamState } from "@/hooks/use-research-stream";
import type { ResearchPlan } from "@/lib/types";

const PLAN = { original_question: "q", web_search_enabled: true, sub_queries: [] } as unknown as ResearchPlan;

function agent(phase: AgentState["phase"]): AgentState {
  return { subQueryId: Math.random().toString(), question: "q", phase, lastToolCall: null, finding: null, errorMessage: null };
}
function state(p: Partial<ResearchStreamState>): ResearchStreamState {
  return { ...initialState, ...p };
}
function statusOf(s: ResearchStreamState) {
  return Object.fromEntries(deriveStages(s).map((x) => [x.key, x.status]));
}

describe("deriveStages", () => {
  it("idle → everything pending", () => {
    expect(statusOf(state({ status: "idle" }))).toEqual({
      plan: "pending", research: "pending", synthesize: "pending", report: "pending",
    });
  });

  it("planning → plan active, rest pending", () => {
    expect(statusOf(state({ status: "planning" }))).toEqual({
      plan: "active", research: "pending", synthesize: "pending", report: "pending",
    });
  });

  it("researching partway → plan done, research active with k/N detail", () => {
    const s = state({ status: "researching", plan: PLAN, agents: [agent("done"), agent("running"), agent("pending")] });
    const stages = deriveStages(s);
    expect(statusOf(s)).toEqual({ plan: "done", research: "active", synthesize: "pending", report: "pending" });
    expect(stages.find((x) => x.key === "research")?.detail).toBe("1/3");
  });

  it("all researchers done but no token yet → synthesize active (no dead-air)", () => {
    const s = state({ status: "researching", plan: PLAN, agents: [agent("done"), agent("done")] });
    expect(statusOf(s)).toEqual({ plan: "done", research: "done", synthesize: "active", report: "pending" });
  });

  it("synthesizing → synthesize active", () => {
    const s = state({ status: "synthesizing", plan: PLAN, agents: [agent("done")], streamedMarkdown: "x" });
    expect(statusOf(s)).toEqual({ plan: "done", research: "done", synthesize: "active", report: "pending" });
  });

  it("complete → all done", () => {
    const s = state({ status: "complete", plan: PLAN, agents: [agent("done")] });
    expect(statusOf(s)).toEqual({ plan: "done", research: "done", synthesize: "done", report: "done" });
  });

  it("terminal synthesis error → synthesize error", () => {
    const s = state({ status: "error", plan: PLAN, agents: [agent("done")], errorMessage: "boom" });
    expect(statusOf(s)).toEqual({ plan: "done", research: "done", synthesize: "error", report: "pending" });
  });

  it("all researchers errored → research error", () => {
    const s = state({ status: "researching", plan: PLAN, agents: [agent("error"), agent("error")] });
    expect(statusOf(s).research).toBe("error");
  });
});
