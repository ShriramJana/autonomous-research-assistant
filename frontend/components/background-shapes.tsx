// Cognitive Terminal ambient backdrop.
// A faint dot grid (the "data lattice") plus two very low-opacity blue
// radial glows that drift slowly. No competing colors, no drop shadows —
// depth comes from tonal layering of the surfaces above.
// Reduced-motion is respected by the @media rule in globals.css.

export function BackgroundShapes() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 z-0 overflow-hidden"
    >
      <div
        className="absolute inset-0 opacity-[0.12]"
        style={{
          backgroundImage:
            "radial-gradient(circle at 1px 1px, currentColor 1px, transparent 0)",
          backgroundSize: "32px 32px",
          color: "#434654",
        }}
      />
      <div className="ara-glow ara-glow-1" />
      <div className="ara-glow ara-glow-2" />
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 60%, var(--background) 100%)",
        }}
      />
    </div>
  );
}
