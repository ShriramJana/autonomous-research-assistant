import Link from "next/link";

import { demoManifest } from "@/lib/demos";

export default function GalleryPage() {
  const items = demoManifest;
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-mono text-2xl tracking-tight">Sample gallery</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Curated runs showing what ARA does end-to-end. Each one replays in your
        browser — no API key, no cost.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.length === 0 && (
          <p className="text-muted-foreground col-span-3 font-mono text-xs">
            Gallery is empty.
          </p>
        )}
        {items.map((r) => (
          <Link
            key={r.slug}
            href={`/demo/${r.slug}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-5 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
            <p className="text-muted-foreground/60 mt-3 font-mono text-[10px] uppercase tracking-wider">
              Watch replay
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
