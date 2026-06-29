// Pure timing helper for client-side demo replay. Given recorded event offsets
// (t_ms from run start) and their types, produce the per-event delay (ms) to
// wait before dispatching each one. The schedule scales the recorded timing to
// a target total so a 3 s toy file and a 140 s real run both replay in roughly
// the same comfortable window, while guaranteeing a visible dwell at each stage
// boundary and a readable synthesis-token cadence.

export interface ScheduledEvent {
  t_ms: number;
  type: string;
}

export interface ScheduleOptions {
  targetTotalMs?: number;
  stageMinDwellMs?: number;
  synthMinStepMs?: number;
  maxGapMs?: number;
}

// The first event of each of these types opens a new visible stage.
const STAGE_ENTRY_TYPES = new Set([
  "plan_ready",
  "researcher_started",
  "synthesis_token",
  "report_complete",
]);

export function computeReplaySchedule(
  events: readonly ScheduledEvent[],
  opts: ScheduleOptions = {},
): number[] {
  const {
    targetTotalMs = 20000,
    stageMinDwellMs = 900,
    synthMinStepMs = 14,
    maxGapMs = 1200,
  } = opts;
  if (events.length === 0) return [];

  // 1. raw clamped gaps
  const raw = events.map((ev, i) => {
    if (i === 0) return 0;
    const gap = ev.t_ms - events[i - 1].t_ms;
    return gap < 0 ? 0 : Math.min(gap, maxGapMs);
  });

  // 2. fall back to even spacing when there is no usable spread
  const rawTotal = raw.reduce((a, b) => a + b, 0);
  if (rawTotal === 0) {
    return events.map((_, i) => (i === 0 ? 0 : targetTotalMs / events.length));
  }

  // 3. scale to the target total
  const scale = targetTotalMs / rawTotal;

  // 4. apply per-stage dwell and synthesis-cadence floors
  const seenStageEntry = new Set<string>();
  return events.map((ev, i) => {
    if (i === 0) return 0;
    let delay = raw[i] * scale;
    if (ev.type === "synthesis_token") delay = Math.max(delay, synthMinStepMs);
    if (STAGE_ENTRY_TYPES.has(ev.type) && !seenStageEntry.has(ev.type)) {
      seenStageEntry.add(ev.type);
      delay = Math.max(delay, stageMinDwellMs);
    }
    return delay;
  });
}
