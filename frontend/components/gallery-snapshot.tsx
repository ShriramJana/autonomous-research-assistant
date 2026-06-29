"use client";

import Link from "next/link";

import { demoManifest } from "@/lib/demos";

export function GallerySnapshot() {
  const items = demoManifest.slice(0, 3);
  if (items.length === 0) return null;
  return (
    <div>
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
        Sample reports
      </h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {items.map((r) => (
          <Link
            key={r.slug}
            href={`/demo/${r.slug}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-4 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
