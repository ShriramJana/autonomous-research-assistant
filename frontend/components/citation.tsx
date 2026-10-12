"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Badge } from "@/components/ui/badge";
import { sourceMeta } from "@/lib/sources";
import type { Source } from "@/lib/types";

export function Citation({ number, source }: { number: number; source: Source | undefined }) {
  return (
    <Popover>
      <PopoverTrigger
        className="text-primary hover:text-primary/80 cursor-pointer select-none align-super px-0.5 text-[0.75em] font-medium"
        aria-label={source ? `Citation ${number}: ${source.title}` : `Citation ${number}`}
      >
        [{number}]
      </PopoverTrigger>
      <PopoverContent className="w-80 text-sm" sideOffset={6}>
        {source ? (
          <div className="flex flex-col gap-2">
            <p className="font-medium leading-tight">{source.title}</p>
            {source.kind === "scholarly" ? (
              <p className="text-muted-foreground font-mono text-[10px] tracking-tight">
                <Badge variant="outline" className="mr-2 font-mono text-[9px] uppercase tracking-wider">
                  paper
                </Badge>
                {sourceMeta(source)}
              </p>
            ) : null}
            <a
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary truncate break-all text-xs underline"
            >
              {source.url}
            </a>
          </div>
        ) : (
          <p className="text-muted-foreground text-xs">Source unavailable</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
