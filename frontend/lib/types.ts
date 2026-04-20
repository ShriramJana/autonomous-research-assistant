// TypeScript mirrors of the backend Pydantic models (backend/src/ara/models/research.py).
// Keep these in sync with the backend — the SSE payloads are the source of truth.

export type Priority = 1 | 2 | 3;

export interface SubQuery {
  id: string; // UUID
  question: string;
  rationale: string;
  priority: Priority;
}

export interface ResearchPlan {
  original_question: string;
  sub_queries: SubQuery[];
}

export interface Source {
  id: string; // UUID — stable across dedup
  url: string;
  title: string;
}

export interface KeyFact {
  statement: string;
  citation_ids: string[]; // UUIDs referencing Source.id
}

export interface SubQueryFinding {
  sub_query_id: string;
  summary: string;
  key_facts: KeyFact[];
  sources: Source[];
}

export interface ReportSection {
  heading: string;
  content: string;
  citation_ids: string[];
}

export interface FinalReport {
  report_id: string;
  original_question: string;
  executive_summary: string;
  sections: ReportSection[];
  citations: Source[];
}
