// Tiny HTTP client for the POST /api/research endpoint.

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface CreateResearchResponse {
  report_id: string;
}

export async function createResearch(question: string): Promise<CreateResearchResponse> {
  const res = await fetch(`${BASE}/api/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to create research (${res.status}): ${text}`);
  }
  return (await res.json()) as CreateResearchResponse;
}
