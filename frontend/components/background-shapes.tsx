// Ambient backdrop for the landing page.
// Layer 1: a faint static dot grid — evokes a knowledge/data lattice.
// Layer 2: three large blurred gradient blobs drifting in slow cycles —
// the "thinking" ambient feel you see on most modern AI product pages.
// All CSS — no JS, no third-party libs. Animation respects
// prefers-reduced-motion via a @media rule in globals.css.

export function BackgroundShapes() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
    >
      {/* Dot grid */}
      <div
        className="absolute inset-0 opacity-[0.18]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
          backgroundSize: "28px 28px",
          color: "oklch(0.3 0 0)",
        }}
      />
      {/* Drifting blobs */}
      <div className="ara-blob ara-blob-1" />
      <div className="ara-blob ara-blob-2" />
      <div className="ara-blob ara-blob-3" />
      {/* Soft vignette — above blobs, below content — softens edges
           and keeps text contrast near the center. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 55%, var(--background) 100%)",
        }}
      />
    </div>
  );
}
