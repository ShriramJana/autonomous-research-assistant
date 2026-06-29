"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";

import type { ResearchStreamState } from "@/hooks/use-research-stream";

export function CostMeter({
  cumulativeUsd,
  costByModel,
}: {
  cumulativeUsd: ResearchStreamState["cumulativeCostUsd"];
  costByModel: ResearchStreamState["costByModel"];
}) {
  const [expanded, setExpanded] = useState(false);
  const entries = Object.entries(costByModel);

  return (
    <div className="bg-card flex flex-col rounded-lg p-5">
      <div className="flex items-end justify-between gap-3">
        <div className="flex flex-col">
          <span className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-widest">
            Cumulative usage
          </span>
          <span className="text-foreground mt-1 font-mono text-2xl font-semibold tracking-tight">
            ${cumulativeUsd.toFixed(4)}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? "Hide breakdown" : "Show breakdown"}
          className="text-muted-foreground/60 hover:text-foreground transition-colors"
        >
          <ChevronDown
            className={`h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`}
            strokeWidth={1.75}
          />
        </button>
      </div>
      {expanded ? (
        entries.length === 0 ? (
          <p className="text-muted-foreground/60 mt-4 font-mono text-xs">
            No calls yet.
          </p>
        ) : (
          <table className="mt-4 w-full">
            <thead>
              <tr className="text-muted-foreground/60 text-left font-mono text-[10px] uppercase tracking-wider">
                <th className="py-1 font-normal">Model</th>
                <th className="py-1 text-right font-normal">In</th>
                <th className="py-1 text-right font-normal">Out</th>
                <th className="py-1 text-right font-normal">USD</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([model, u]) => (
                <tr key={model} className="border-border/40 border-t">
                  <td className="max-w-32 truncate py-1.5 pr-2 font-mono text-[11px]">
                    {model}
                  </td>
                  <td className="py-1.5 text-right font-mono text-[11px]">
                    {u.inputTokens}
                  </td>
                  <td className="py-1.5 text-right font-mono text-[11px]">
                    {u.outputTokens}
                  </td>
                  <td className="py-1.5 text-right font-mono text-[11px]">
                    {u.priced ? `$${u.usd.toFixed(4)}` : "n/a"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : null}
      <p className="text-muted-foreground/40 mt-3 font-mono text-[10px]">
        Estimated from list prices.
      </p>
    </div>
  );
}
