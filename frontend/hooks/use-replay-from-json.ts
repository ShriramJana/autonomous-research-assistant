"use client";

import { useEffect, useReducer, useState } from "react";

import { initialState, reducer } from "@/hooks/use-research-stream";
import type { ResearchStreamState } from "@/hooks/use-research-stream";
import { computeReplaySchedule } from "@/lib/replay";
import type { DemoEvent } from "@/lib/demos";

export interface ReplayResult {
  state: ResearchStreamState;
  /** Restart the replay from the beginning. */
  restart: () => void;
}

// Drives the SHARED live reducer over a static recorded array on a timer, so
// the demo is visually identical to a live run but makes zero network calls.
export function useReplayFromJson(events: DemoEvent[] | null): ReplayResult {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!events || events.length === 0) return;
    dispatch({ kind: "reset" });

    const delays = computeReplaySchedule(
      events.map((e) => ({ t_ms: e.t_ms, type: e.event.type })),
    );
    const timers: ReturnType<typeof setTimeout>[] = [];
    let elapsed = 0;
    for (let i = 0; i < events.length; i++) {
      elapsed += delays[i];
      const event = events[i].event;
      timers.push(setTimeout(() => dispatch({ kind: "event", event }), elapsed));
    }

    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [events, nonce]);

  return { state, restart: () => setNonce((n) => n + 1) };
}
