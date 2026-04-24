"use client";

import type { Source } from "@/lib/types";

export function SourcesList({ citations }: { citations: Source[] }) {
  return (
    <section>
      <h2 className="text-muted-foreground mb-4 font-mono text-[10px] uppercase tracking-widest">
        Sources
      </h2>
      {citations.length === 0 ? (
        <p className="text-muted-foreground/60 font-mono text-xs">
          No sources yet.
        </p>
      ) : (
        <ol className="flex flex-col gap-3">
          {citations.map((src, i) => (
            <li key={src.id} className="flex gap-3 text-sm">
              <span className="text-muted-foreground w-7 shrink-0 font-mono text-[11px] leading-5">
                [{String(i + 1).padStart(2, "0")}]
              </span>
              <div className="flex min-w-0 flex-col">
                <a
                  href={src.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-foreground hover:text-primary line-clamp-2 text-sm font-medium leading-snug transition-colors"
                >
                  {src.title}
                </a>
                <span className="text-muted-foreground/60 mt-0.5 break-all font-mono text-[10px]">
                  {src.url}
                </span>
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
