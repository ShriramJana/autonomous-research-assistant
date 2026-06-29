// Pure derivation of the four-stage research timeline from stream state.
// Reads only ResearchStreamState, so the live UI and the demo replay show an
// identical timeline. No I/O.

import type { ResearchStreamState } from "@/hooks/use-research-stream";

export type StageKey = "plan" | "research" | "synthesize" | "report";
export type StageStatus = "pending" | "active" | "done" | "error";

export interface TimelineStage {
  key: StageKey;
  label: string;
  status: StageStatus;
  detail?: string;
}

export function deriveStages(state: ResearchStreamState): TimelineStage[] {
  const { status, agents } = state;
  const total = agents.length;
  const finished = agents.filter((a) => a.phase === "done" || a.phase === "error").length;
  const researchComplete = total > 0 && finished === total;
  const allErrored = total > 0 && agents.every((a) => a.phase === "error");
  const hasPlan = state.plan !== null;
  const isComplete = status === "complete";

  let plan: StageStatus;
  if (hasPlan) plan = "done";
  else if (status === "planning") plan = "active";
  else plan = "pending";

  let research: StageStatus;
  if (!hasPlan && total === 0) research = "pending";
  else if (allErrored) research = "error";
  else if (researchComplete) research = "done";
  else research = "active";

  let synthesize: StageStatus;
  if (isComplete) synthesize = "done";
  else if (researchComplete) synthesize = "active";
  else synthesize = "pending";

  const report: StageStatus = isComplete ? "done" : "pending";

  const stages: TimelineStage[] = [
    { key: "plan", label: "Plan", status: plan },
    { key: "research", label: "Research", status: research, detail: total > 0 ? `${finished}/${total}` : undefined },
    { key: "synthesize", label: "Synthesize", status: synthesize },
    { key: "report", label: "Report", status: report },
  ];

  // A terminal plan/synthesis error (status === "error") aborts the run; mark
  // the first not-yet-done stage as error. Research-scoped failures don't set
  // status === "error" (the reducer keeps the stream alive), so they surface
  // on the agent rows, not here.
  if (status === "error") {
    const firstOpen = stages.find((s) => s.status !== "done");
    if (firstOpen) firstOpen.status = "error";
  }
  return stages;
}
