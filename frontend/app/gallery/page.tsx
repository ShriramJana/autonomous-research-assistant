import { demoManifest } from "@/lib/demos";
import { DemoCard } from "@/components/demo-card";

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
        {items.map((entry) => (
          <DemoCard key={entry.slug} entry={entry} />
        ))}
      </div>
    </main>
  );
}
