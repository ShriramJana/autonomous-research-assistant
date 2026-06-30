// Pure run-gate copy. Kept out of the form component so it can be unit-tested
// like the other lib/* helpers. The BYOK string is the canonical one shared
// with the cold-start notice in research-form.tsx.

export interface QuotaInfo {
  used: number;
  limit: number;
  circuit_breaker_tripped: boolean;
  free_tier_available: boolean;
}

export const BYOK_MESSAGE =
  "This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report.";

// Why: in production the server has no ANTHROPIC_API_KEY, so the free tier is
// off and every "free"-provider user must bring their own key. We still cover
// the owner-key (local/dev) exhaustion and site-wide-cap states.
export function freeTierBlockMessage(quota: QuotaInfo | null): string | null {
  if (quota === null) return null;
  if (!quota.free_tier_available) return BYOK_MESSAGE;
  if (quota.circuit_breaker_tripped) {
    return "Free tier is capped site-wide for this month — add your Anthropic API key in Settings to keep running reports.";
  }
  if (quota.used >= quota.limit) {
    return "Free tier exhausted — add your Anthropic API key in Settings to keep running reports.";
  }
  return null;
}

export function friendlyRunError(status: number | undefined, fallback: string): string {
  if (status === 503) return BYOK_MESSAGE;
  if (status === 402) {
    return "Free-tier limit reached — add your own API key in Settings to keep running reports.";
  }
  return fallback;
}
