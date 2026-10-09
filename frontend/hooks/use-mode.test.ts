import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchConfig = vi.fn();
vi.mock("@/lib/config", () => ({ fetchConfig: () => fetchConfig() }));

async function load() {
  vi.resetModules();
  return (await import("@/hooks/use-mode")).fetchMode;
}

describe("fetchMode", () => {
  beforeEach(() => {
    fetchConfig.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  it("resolves local immediately with no network call when the env hint is set", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARA_MODE", "local");
    const fetchMode = await load();
    await expect(fetchMode()).resolves.toBe("local");
    expect(fetchConfig).not.toHaveBeenCalled();
  });

  it("uses the backend mode and caches it", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARA_MODE", "");
    fetchConfig.mockResolvedValue({ mode: "local" });
    const fetchMode = await load();
    await expect(fetchMode()).resolves.toBe("local");
    await fetchMode();
    expect(fetchConfig).toHaveBeenCalledTimes(1);
  });

  it("falls back to hosted on error", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARA_MODE", "");
    fetchConfig.mockRejectedValue(new Error("down"));
    const fetchMode = await load();
    await expect(fetchMode()).resolves.toBe("hosted");
  });

  it("falls back to hosted after 1500ms when the backend is cold", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARA_MODE", "");
    fetchConfig.mockReturnValue(new Promise(() => {}));
    const fetchMode = await load();
    const p = fetchMode();
    await vi.advanceTimersByTimeAsync(1500);
    await expect(p).resolves.toBe("hosted");
  });
});
