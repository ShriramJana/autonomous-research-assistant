// Pure helpers for the Sources control, citation rendering and the knowledge banner.

import type { Source } from "@/lib/types";

export const CATALOG_LABELS: Record<string, string> = {
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  arxiv: "arXiv",
  pubmed: "PubMed",
};

// Shown until /api/config answers (Semantic Scholar is key-gated server-side).
export const DEFAULT_CATALOGS = ["openalex", "arxiv", "pubmed"];

export function catalogLabel(id: string): string {
  return CATALOG_LABELS[id] ?? id;
}

export type SourcesLabel = "Web + Scholarly" | "Web" | "Scholarly" | "None";

export function sourcesLabel(web: boolean, scholarly: boolean): SourcesLabel {
  if (web && scholarly) return "Web + Scholarly";
  if (web) return "Web";
  if (scholarly) return "Scholarly";
  return "None";
}

const MAX_AUTHORS = 3;

export function authorsShort(authors: string[] | undefined, max = MAX_AUTHORS): string {
  if (!authors || authors.length === 0) return "";
  const head = authors.slice(0, max).join(", ");
  return authors.length > max ? `${head} et al.` : head;
}

export function sourceMeta(src: Source): string | null {
  if (src.kind !== "scholarly") return null;
  const head = [authorsShort(src.authors), src.year ? `(${src.year})` : ""]
    .filter(Boolean)
    .join(" ");
  const cites =
    typeof src.citation_count === "number"
      ? `${src.citation_count.toLocaleString("en-US")} citations`
      : "";
  const parts = [head, src.venue ?? "", cites].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export type KnowledgeBanner = "offline" | "scholarly-only" | null;

export function knowledgeBanner(
  web: boolean | undefined,
  scholarly: boolean | undefined,
): KnowledgeBanner {
  if (web !== false) return null;
  return scholarly ? "scholarly-only" : "offline";
}
