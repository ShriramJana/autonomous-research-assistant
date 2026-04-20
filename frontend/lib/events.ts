// SSE event envelope types — discriminated union keyed on `type`.
// Mirrors backend/src/ara/models/events.py.

import type { FinalReport, ResearchPlan, SubQueryFinding } from "@/lib/types";

export type ErrorStage = "plan" | "research" | "synthesis";

export interface PlanReadyEvent {
  type: "plan_ready";
  plan: ResearchPlan;
}

export interface ResearcherStartedEvent {
  type: "researcher_started";
  sub_query_id: string;
  question: string;
}

export interface ResearcherProgressEvent {
  type: "researcher_progress";
  sub_query_id: string;
  tool_call: string;
}

export interface ResearcherCompleteEvent {
  type: "researcher_complete";
  sub_query_id: string;
  finding: SubQueryFinding;
}

export interface SynthesisTokenEvent {
  type: "synthesis_token";
  token: string;
}

export interface ReportCompleteEvent {
  type: "report_complete";
  report: FinalReport;
}

export interface ResearchErrorEvent {
  type: "error";
  stage: ErrorStage;
  message: string;
  sub_query_id?: string | null;
}

export interface CostUpdateEvent {
  type: "cost_update";
  model: string;
  input_tokens: number;
  output_tokens: number;
  cumulative_usd: number;
}

export type ResearchEvent =
  | PlanReadyEvent
  | ResearcherStartedEvent
  | ResearcherProgressEvent
  | ResearcherCompleteEvent
  | SynthesisTokenEvent
  | ReportCompleteEvent
  | ResearchErrorEvent
  | CostUpdateEvent;
