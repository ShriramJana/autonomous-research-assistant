// Tiny HTTP client for the POST /api/research endpoint.

import type { Depth } from "@/hooks/use-depth";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface CreateResearchResponse {
  report_id: string;
}

export interface CreateResearchOptions {
  depth?: Depth;
}

export async function createResearch(
  question: string,
  options: CreateResearchOptions = {},
): Promise<CreateResearchResponse> {
  const body: Record<string, unknown> = { question };
  if (options.depth) body.depth = options.depth;

  const res = await fetch(`${BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to create research (${res.status}): ${text}`);
  }
  return (await res.json()) as CreateResearchResponse;
}
