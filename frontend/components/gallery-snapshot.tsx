"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { apiGet } from "@/lib/api";
import type { ReportSummary } from "@/hooks/use-reports";

export function GallerySnapshot() {
  const [items, setItems] = useState<ReportSummary[]>([]);
  useEffect(() => {
    apiGet<ReportSummary[]>("/api/gallery")
      .then((rows) => setItems(rows.slice(0, 3)))
      .catch(() => setItems([]));
  }, []);
  if (items.length === 0) return null;
  return (
    <div>
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
        Sample reports
      </h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {items.map((r) => (
          <Link
            key={r.id}
            href={`/r/${r.id}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-4 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
