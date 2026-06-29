import Link from "next/link";
import { ArrowRight } from "lucide-react";

import type { DemoManifestEntry } from "@/lib/demos";

export function DemoCard({ entry }: { entry: DemoManifestEntry }) {
  const meta: string[] = [];
  if (entry.model) meta.push(entry.model.replace(/^claude-/, ""));
  if (typeof entry.n_sources === "number") meta.push(`${entry.n_sources} sources`);
  if (typeof entry.n_sub_queries === "number") meta.push(`${entry.n_sub_queries} sub-queries`);
  if (typeof entry.cost_usd === "number" && entry.cost_usd > 0) {
    meta.push(`~$${entry.cost_usd.toFixed(2)}`);
  }

  return (
    <Link
      href={`/demo/${entry.slug}`}
      className="group bg-card hover:bg-card/80 border-border/40 flex flex-col gap-3 rounded-lg border p-5 transition-colors"
    >
      <p className="text-foreground font-medium leading-snug">{entry.question}</p>
      {entry.summary ? (
        <p className="text-muted-foreground/80 line-clamp-2 text-sm leading-snug">
          {entry.summary}
        </p>
      ) : null}
      <div className="mt-auto flex items-center justify-between gap-2 pt-2">
        <span className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-wider">
          {meta.join(" · ")}
        </span>
        <span className="text-muted-foreground/60 group-hover:text-foreground inline-flex shrink-0 items-center gap-1 font-mono text-[10px] uppercase tracking-wider transition-colors">
          Watch replay
          <ArrowRight className="h-3 w-3" strokeWidth={1.75} />
        </span>
      </div>
    </Link>
  );
}
