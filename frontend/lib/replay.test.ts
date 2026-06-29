import { describe, expect, it } from "vitest";
import { computeDelays } from "@/lib/replay";

describe("computeDelays", () => {
  it("returns the gap between consecutive timestamps", () => {
    const events = [{ t_ms: 0 }, { t_ms: 200 }, { t_ms: 500 }];
    expect(computeDelays(events, { maxGapMs: 1000 })).toEqual([0, 200, 300]);
  });

  it("clamps long idle gaps to maxGapMs so replay never stalls", () => {
    const events = [{ t_ms: 0 }, { t_ms: 30_000 }];
    expect(computeDelays(events, { maxGapMs: 800 })).toEqual([0, 800]);
  });

  it("never emits a negative delay if timestamps go backwards", () => {
    const events = [{ t_ms: 100 }, { t_ms: 50 }];
    expect(computeDelays(events, { maxGapMs: 1000 })).toEqual([0, 0]);
  });

  it("returns [] for no events", () => {
    expect(computeDelays([], { maxGapMs: 1000 })).toEqual([]);
  });
});
