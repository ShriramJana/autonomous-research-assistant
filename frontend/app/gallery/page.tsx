import Link from "next/link";

import type { ReportSummary } from "@/hooks/use-reports";

export const dynamic = "force-dynamic";

async function fetchGallery(): Promise<ReportSummary[]> {
  const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
  const res = await fetch(`${backend}/api/gallery`, { cache: "no-store" });
  if (!res.ok) return [];
  return (await res.json()) as ReportSummary[];
}

export default async function GalleryPage() {
  const items = await fetchGallery();
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-mono text-2xl tracking-tight">Sample gallery</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Curated runs showing what ARA does end-to-end.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.length === 0 && (
          <p className="text-muted-foreground col-span-3 font-mono text-xs">
            Gallery is empty.
          </p>
        )}
        {items.map((r) => (
          <Link
            key={r.id}
            href={`/r/${r.id}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-5 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
            <p className="text-muted-foreground/60 mt-3 font-mono text-[10px] uppercase tracking-wider">
              View report
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
