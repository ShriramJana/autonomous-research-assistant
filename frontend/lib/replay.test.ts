import { describe, expect, it } from "vitest";
import { computeReplaySchedule } from "@/lib/replay";

describe("computeReplaySchedule", () => {
  it("returns [] for no events", () => {
    expect(computeReplaySchedule([])).toEqual([]);
  });

  it("scales raw gaps so the run fills the target window", () => {
    // raw gaps 0,100,200 (total 300) → scale 3000/300 = 10 → 0,1000,2000.
    const events = [
      { t_ms: 0, type: "cost_update" },
      { t_ms: 100, type: "researcher_progress" },
      { t_ms: 300, type: "researcher_complete" },
    ];
    expect(computeReplaySchedule(events, { targetTotalMs: 3000 })).toEqual([0, 1000, 2000]);
  });

  it("gives each stage's first event a minimum dwell", () => {
    // raw 0,10 (total 10) → scale 20/10 = 2 → scaled 0,20; researcher_started
    // is a stage-entry event so its delay floors to stageMinDwellMs.
    const events = [
      { t_ms: 0, type: "plan_ready" },
      { t_ms: 10, type: "researcher_started" },
    ];
    expect(
      computeReplaySchedule(events, { targetTotalMs: 20, stageMinDwellMs: 900 }),
    ).toEqual([0, 900]);
  });

  it("streams synthesis tokens at a readable minimum step", () => {
    // raw 0,1,1 (total 2) → scale 2/2 = 1 → scaled 0,1,1. First synth token is
    // the synthesize stage entry (floors to 900); the next floors to synthMinStepMs.
    const events = [
      { t_ms: 0, type: "synthesis_token" },
      { t_ms: 1, type: "synthesis_token" },
      { t_ms: 2, type: "synthesis_token" },
    ];
    expect(
      computeReplaySchedule(events, { targetTotalMs: 2, stageMinDwellMs: 900, synthMinStepMs: 14 }),
    ).toEqual([0, 900, 14]);
  });

  it("never emits negatives and falls back to even spacing when there is no spread", () => {
    const events = [
      { t_ms: 100, type: "cost_update" },
      { t_ms: 50, type: "cost_update" },
    ];
    // backwards gap clamps to 0 → rawTotal 0 → even spacing across target.
    expect(computeReplaySchedule(events, { targetTotalMs: 10 })).toEqual([0, 5]);
  });
});
