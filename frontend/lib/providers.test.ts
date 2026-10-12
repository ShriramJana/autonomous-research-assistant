import { describe, expect, it } from "vitest";
import { PROVIDER_PRESETS, presetFor } from "@/lib/providers";

describe("PROVIDER_PRESETS", () => {
  it("has unique ids and a model, base URL and key hint for every preset", () => {
    const ids = PROVIDER_PRESETS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const p of PROVIDER_PRESETS) {
      expect(p.label.length).toBeGreaterThan(0);
      expect(p.baseUrl).toMatch(/^https?:\/\//);
      expect(p.defaultModel.length).toBeGreaterThan(0);
      expect(p.keyPlaceholder.length).toBeGreaterThan(0);
      if (p.id !== "ollama") expect(p.keyUrl).toMatch(/^https:\/\//);
    }
  });

  it("only Ollama is local-only and keyless", () => {
    const localOnly = PROVIDER_PRESETS.filter((p) => p.localOnly);
    expect(localOnly.map((p) => p.id)).toEqual(["ollama"]);
    expect(localOnly[0].keyUrl).toBeNull();
    expect(localOnly[0].baseUrl).toBe("http://localhost:11434/v1");
  });

  it("uses the base URL each vendor documents, including the DeepSeek no-/v1 quirk", () => {
    const byId = Object.fromEntries(PROVIDER_PRESETS.map((p) => [p.id, p.baseUrl]));
    expect(byId.gemini).toBe("https://generativelanguage.googleapis.com/v1beta/openai/");
    expect(byId.groq).toBe("https://api.groq.com/openai/v1");
    expect(byId.deepseek).toBe("https://api.deepseek.com");
    expect(byId.openrouter).toBe("https://openrouter.ai/api/v1");
  });
});

describe("presetFor", () => {
  it("matches a stored base URL back to its preset, ignoring a trailing slash", () => {
    expect(presetFor("https://api.groq.com/openai/v1")?.id).toBe("groq");
    expect(presetFor("https://api.groq.com/openai/v1/")?.id).toBe("groq");
    expect(presetFor("https://generativelanguage.googleapis.com/v1beta/openai")?.id).toBe("gemini");
  });
  it("returns null for unknown, empty or null URLs", () => {
    expect(presetFor("https://my-proxy.internal/v1")).toBeNull();
    expect(presetFor("")).toBeNull();
    expect(presetFor(null)).toBeNull();
  });
});
