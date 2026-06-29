"use client";

import { demoManifest } from "@/lib/demos";
import { DemoCard } from "@/components/demo-card";

export function GallerySnapshot() {
  const items = demoManifest.slice(0, 3);
  if (items.length === 0) return null;
  return (
    <div>
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
        Sample reports
      </h2>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.map((entry) => (
          <DemoCard key={entry.slug} entry={entry} />
        ))}
      </div>
    </div>
  );
}
