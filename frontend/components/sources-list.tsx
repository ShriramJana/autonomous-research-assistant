"use client";

import type { Source } from "@/lib/types";

export function SourcesList({ citations }: { citations: Source[] }) {
  if (citations.length === 0) return null;

  return (
    <section className="border-border/60 mt-10 border-t pt-6">
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-wider">
        Sources
      </h2>
      <ol className="flex flex-col gap-3">
        {citations.map((src, i) => (
          <li key={src.id} className="flex gap-3 text-sm">
            <span className="text-muted-foreground w-7 shrink-0 font-mono text-xs leading-5">
              [{i + 1}]
            </span>
            <div className="flex min-w-0 flex-col">
              <a
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary font-medium hover:underline"
              >
                {src.title}
              </a>
              <span className="text-muted-foreground break-all text-xs">
                {src.url}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
