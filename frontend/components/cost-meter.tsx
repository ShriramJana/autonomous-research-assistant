"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ResearchStreamState } from "@/hooks/use-research-stream";

export function CostMeter({
  cumulativeUsd,
  costByModel,
}: {
  cumulativeUsd: ResearchStreamState["cumulativeCostUsd"];
  costByModel: ResearchStreamState["costByModel"];
}) {
  const entries = Object.entries(costByModel);
  return (
    <Popover>
      <PopoverTrigger className="hover:bg-accent hover:text-accent-foreground rounded-md border px-2.5 py-1.5 font-mono text-xs transition-colors">
        ${cumulativeUsd.toFixed(4)}
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 text-xs">
        <p className="text-muted-foreground mb-2 uppercase tracking-wider">API cost</p>
        {entries.length === 0 ? (
          <p className="text-muted-foreground">No calls yet.</p>
        ) : (
          <table className="w-full">
            <thead>
              <tr className="text-muted-foreground text-left">
                <th className="py-1 font-normal">Model</th>
                <th className="py-1 text-right font-normal">In</th>
                <th className="py-1 text-right font-normal">Out</th>
                <th className="py-1 text-right font-normal">USD</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([model, u]) => (
                <tr key={model} className="border-t">
                  <td className="max-w-32 truncate py-1 pr-2 font-mono">{model}</td>
                  <td className="py-1 text-right font-mono">{u.inputTokens}</td>
                  <td className="py-1 text-right font-mono">{u.outputTokens}</td>
                  <td className="py-1 text-right font-mono">${u.usd.toFixed(4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-muted-foreground mt-2 text-[10px]">
          Estimated from list prices — real billing may vary.
        </p>
      </PopoverContent>
    </Popover>
  );
}
