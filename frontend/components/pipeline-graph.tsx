/**
 * PipelineGraph — CSS/SVG animated diagram of ARA's real pipeline.
 * No props required. Fully server-renderable; animation via CSS keyframes
 * in globals.css (guarded by prefers-reduced-motion).
 *
 * Layout (horizontal, stacks vertically on mobile):
 *   [Question] → (Planner) → (Researcher ×3, parallel) → (Synthesizer) → [Cited Report]
 */

export function PipelineGraph() {
  return (
    <div
      className="ara-pipeline select-none"
      aria-label="ARA pipeline: Question feeds Planner, which fans out to three parallel Researchers, which converge into Synthesizer, producing a Cited Report"
      role="img"
    >
      {/* Row layout: nodes + arrows in a flex row, stacks on mobile */}
      <div className="flex flex-col items-center gap-3 sm:flex-row sm:items-center sm:justify-center sm:gap-0">

        {/* ── Question node ── */}
        <div className="ara-pl-node ara-pl-endpoint">
          <span className="ara-pl-label">QUESTION</span>
          <span className="ara-pl-title">Your question</span>
        </div>

        {/* Arrow: Question → Planner */}
        <div className="ara-pl-arrow ara-pl-arrow-h">
          <div className="ara-pl-flow" />
        </div>

        {/* ── Planner node ── */}
        <div className="ara-pl-node ara-pl-stage ara-pl-planner">
          <span className="ara-pl-label">PLAN</span>
          <span className="ara-pl-title">Planner</span>
        </div>

        {/* ── Fan-out: Planner → 3 Researchers ── */}
        {/* On small screens this becomes a vertical column */}
        <div className="ara-pl-fanout">
          {/* Top connector line (visible only sm+) */}
          <div className="ara-pl-fanout-rail" />
          <div className="ara-pl-researchers">
            {[0, 1, 2].map((i) => (
              <div key={i} className="ara-pl-researcher-row">
                <div className="ara-pl-stub ara-pl-stub-left">
                  <div className="ara-pl-flow" style={{ animationDelay: `${i * 0.35}s` }} />
                </div>
                <div
                  className="ara-pl-node ara-pl-stage ara-pl-researcher"
                  style={{ animationDelay: `${i * 0.35}s` }}
                >
                  <span className="ara-pl-label">RESEARCH</span>
                  <span className="ara-pl-title">Researcher {i + 1}</span>
                </div>
                <div className="ara-pl-stub ara-pl-stub-right">
                  <div className="ara-pl-flow" style={{ animationDelay: `${i * 0.35}s` }} />
                </div>
              </div>
            ))}
          </div>
          <div className="ara-pl-fanout-rail ara-pl-fanout-rail-right" />
        </div>

        {/* ── Synthesizer node ── */}
        <div className="ara-pl-node ara-pl-stage ara-pl-synthesizer">
          <span className="ara-pl-label">SYNTHESIZE</span>
          <span className="ara-pl-title">Synthesizer</span>
        </div>

        {/* Arrow: Synthesizer → Report */}
        <div className="ara-pl-arrow ara-pl-arrow-h">
          <div className="ara-pl-flow" />
        </div>

        {/* ── Cited Report node ── */}
        <div className="ara-pl-node ara-pl-endpoint ara-pl-report">
          <span className="ara-pl-label">OUTPUT</span>
          <span className="ara-pl-title">Cited report</span>
          {/* Citation chips */}
          <div className="ara-pl-chips">
            <span className="ara-pl-chip">[1]</span>
            <span className="ara-pl-chip">[2]</span>
            <span className="ara-pl-chip">[3]</span>
          </div>
        </div>
      </div>
    </div>
  );
}
