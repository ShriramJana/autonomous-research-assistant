// frontend/lib/demos.contract.test.ts
// Locks the recorder ↔ frontend contract: a real recorded run, replayed through
// the SHARED live reducer, must terminate in a complete report. This is the one
// link the recorder (live API, untested) and the UI share.
import { describe, expect, it } from "vitest";

import { initialState, reducer } from "@/hooks/use-research-stream";
import quantum from "@/public/demos/quantum-supremacy.json";
import type { DemoFile } from "@/lib/demos";

describe("recorded demo ↔ reducer contract", () => {
  it("replays a real recording to a complete report with sources", () => {
    const file = quantum as unknown as DemoFile;
    let state = initialState;
    for (const { event } of file.events) {
      state = reducer(state, { kind: "event", event });
    }
    expect(state.status).toBe("complete");
    expect(state.report).not.toBeNull();
    expect(state.report?.citations.length).toBeGreaterThan(0);
  });
});
