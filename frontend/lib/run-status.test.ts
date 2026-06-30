import { describe, expect, it } from "vitest";

import { freeTierBlockMessage, friendlyRunError, type QuotaInfo } from "./run-status";

const base: QuotaInfo = {
  used: 0,
  limit: 3,
  circuit_breaker_tripped: false,
  free_tier_available: true,
};

const BYOK =
  "This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report.";

describe("freeTierBlockMessage", () => {
  it("returns null when quota is unknown", () => {
    expect(freeTierBlockMessage(null)).toBeNull();
  });

  it("returns null when free tier is available and quota remains", () => {
    expect(freeTierBlockMessage(base)).toBeNull();
  });

  it("asks for a key when the server has no free tier", () => {
    expect(freeTierBlockMessage({ ...base, free_tier_available: false })).toBe(BYOK);
  });

  it("explains the site-wide cap", () => {
    expect(freeTierBlockMessage({ ...base, circuit_breaker_tripped: true })).toContain(
      "capped site-wide",
    );
  });

  it("explains personal exhaustion", () => {
    expect(freeTierBlockMessage({ ...base, used: 3, limit: 3 })).toContain("exhausted");
  });
});

describe("friendlyRunError", () => {
  it("maps 503 to the BYOK message", () => {
    expect(friendlyRunError(503, "API 503")).toBe(BYOK);
  });

  it("maps 402 to a quota message", () => {
    expect(friendlyRunError(402, "API 402")).toContain("limit reached");
  });

  it("passes other errors through", () => {
    expect(friendlyRunError(500, "boom")).toBe("boom");
  });
});
