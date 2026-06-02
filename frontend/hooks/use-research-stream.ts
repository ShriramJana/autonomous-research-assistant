"use client";

import { useEffect, useReducer } from "react";
import type { ResearchEvent } from "@/lib/events";
import type { FinalReport, ResearchPlan, SubQueryFinding } from "@/lib/types";

export type StreamStatus =
  | "idle"
  | "planning"
  | "researching"
  | "synthesizing"
  | "complete"
  | "error";

export type AgentPhase = "pending" | "running" | "done" | "error";

export interface AgentState {
  subQueryId: string;
  question: string;
  phase: AgentPhase;
  lastToolCall: string | null;
  finding: SubQueryFinding | null;
  errorMessage: string | null;
}

export interface ResearchStreamState {
  status: StreamStatus;
  plan: ResearchPlan | null;
  agents: AgentState[];
  streamedMarkdown: string;
  report: FinalReport | null;
  errorMessage: string | null;
  cumulativeCostUsd: number;
  costByModel: Record<string, { inputTokens: number; outputTokens: number; usd: number }>;
}

const initialState: ResearchStreamState = {
  status: "idle",
  plan: null,
  agents: [],
  streamedMarkdown: "",
  report: null,
  errorMessage: null,
  cumulativeCostUsd: 0,
  costByModel: {},
};

type Action = { kind: "event"; event: ResearchEvent } | { kind: "reset" };

function reducer(state: ResearchStreamState, action: Action): ResearchStreamState {
  if (action.kind === "reset") return initialState;
  const event = action.event;
  switch (event.type) {
    case "plan_ready":
      return {
        ...state,
        status: "researching",
        plan: event.plan,
        agents: event.plan.sub_queries.map((sq) => ({
          subQueryId: sq.id,
          question: sq.question,
          phase: "pending",
          lastToolCall: null,
          finding: null,
          errorMessage: null,
        })),
      };
    case "researcher_started":
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.subQueryId === event.sub_query_id ? { ...a, phase: "running" } : a,
        ),
      };
    case "researcher_progress":
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.subQueryId === event.sub_query_id ? { ...a, lastToolCall: event.tool_call } : a,
        ),
      };
    case "researcher_complete":
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.subQueryId === event.sub_query_id
            ? { ...a, phase: a.errorMessage ? "error" : "done", finding: event.finding }
            : a,
        ),
      };
    case "synthesis_token":
      return {
        ...state,
        status: state.status === "researching" ? "synthesizing" : state.status,
        streamedMarkdown: state.streamedMarkdown + event.token,
      };
    case "report_complete":
      return {
        ...state,
        status: "complete",
        report: event.report,
      };
    case "error": {
      const scoped = event.sub_query_id
        ? state.agents.map((a) =>
            a.subQueryId === event.sub_query_id
              ? { ...a, phase: "error" as AgentPhase, errorMessage: event.message }
              : a,
          )
        : state.agents;
      // Stage-scoped research errors don't abort the whole stream;
      // plan/synthesis errors are terminal.
      const newStatus: StreamStatus = event.stage === "research" ? state.status : "error";
      return {
        ...state,
        status: newStatus,
        agents: scoped,
        errorMessage:
          event.stage === "research" ? state.errorMessage : event.message,
      };
    }
    case "cost_update": {
      const prev = state.costByModel[event.model] ?? {
        inputTokens: 0,
        outputTokens: 0,
        usd: 0,
      };
      const updated = {
        inputTokens: prev.inputTokens + event.input_tokens,
        outputTokens: prev.outputTokens + event.output_tokens,
        usd: event.cumulative_usd, // cumulative per the contract; use latest
      };
      return {
        ...state,
        cumulativeCostUsd: event.cumulative_usd,
        costByModel: { ...state.costByModel, [event.model]: updated },
      };
    }
  }
}

export function useResearchStream(
  reportId: string | null,
  shareToken?: string,
  streamUrl?: string,
): ResearchStreamState {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    if (!reportId && !streamUrl) return;
    dispatch({ kind: "reset" });

    // Same-origin via the Next.js /api/:path* rewrite. EventSource can't
    // attach custom headers; only cookies. Supabase cookies are scoped to
    // the Next dev origin (:3000), so we MUST hit :3000 here — going to
    // :8000 directly would drop the session and 403 on private reports.
    let url: string;
    if (streamUrl) {
      url = streamUrl;
    } else {
      const qs = shareToken ? `?t=${encodeURIComponent(shareToken)}` : "";
      url = `/api/research/${reportId}/stream${qs}`;
    }
    const es = new EventSource(url, { withCredentials: true });

    es.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as ResearchEvent;
        dispatch({ kind: "event", event: parsed });
      } catch {
        // Ignore malformed lines rather than crashing the stream.
      }
    };

    // When status reaches 'complete' or terminal 'error', the server
    // closes the connection and EventSource fires onerror; that's OK.
    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [reportId, shareToken, streamUrl]);

  // Special-case: the very first event after submit is plan_ready, but
  // before that arrives, surface "planning" so the UI shows progress.
  const effectiveStatus: StreamStatus =
    state.status === "idle" && (reportId || streamUrl) ? "planning" : state.status;

  return { ...state, status: effectiveStatus };
}
