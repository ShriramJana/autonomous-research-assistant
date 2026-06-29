// Pure timing helper for client-side demo replay. Given recorded event
// offsets (t_ms from run start), produce the per-event delay (ms) to wait
// before dispatching each one, so the visual cadence matches the real run —
// while clamping long idle gaps so a recorded pause never stalls the demo.

export interface TimedEvent {
  t_ms: number;
}

export interface DelayOptions {
  maxGapMs: number;
}

export function computeDelays(
  events: readonly TimedEvent[],
  { maxGapMs }: DelayOptions,
): number[] {
  return events.map((ev, i) => {
    if (i === 0) return 0;
    const gap = ev.t_ms - events[i - 1].t_ms;
    if (gap < 0) return 0;
    return Math.min(gap, maxGapMs);
  });
}
