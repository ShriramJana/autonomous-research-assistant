"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useHistory } from "@/hooks/use-history";

export function HistoryList() {
  const { items, clear } = useHistory();
  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 className="text-muted-foreground font-mono text-xs uppercase tracking-wider">
          Recent research
        </h2>
        <Button
          variant="ghost"
          size="sm"
          onClick={clear}
          className="text-muted-foreground hover:text-foreground h-auto px-2 py-1 text-xs"
        >
          Clear
        </Button>
      </div>
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <Link key={item.reportId} href={`/r/${item.reportId}`} className="block">
            <Card className="hover:border-primary/40 transition-colors">
              <CardContent className="flex flex-col gap-1 py-3">
                <div className="flex items-start justify-between gap-3">
                  <p className="line-clamp-2 text-sm font-medium leading-snug">
                    {item.question}
                  </p>
                  <span className="text-muted-foreground shrink-0 whitespace-nowrap text-xs">
                    {formatRelativeTime(item.createdAt)}
                  </span>
                </div>
                {item.executiveSummary ? (
                  <p className="text-muted-foreground line-clamp-2 text-xs">
                    {item.executiveSummary}
                  </p>
                ) : null}
                {item.status === "running" ? (
                  <p className="text-primary text-xs">Running…</p>
                ) : null}
                {item.status === "error" ? (
                  <p className="text-destructive text-xs">Failed</p>
                ) : null}
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
      <p className="text-muted-foreground text-[10px]">
        Stored in this browser only. Clearing your browser data will remove history.
      </p>
    </div>
  );
}

function formatRelativeTime(ms: number): string {
  const delta = Date.now() - ms;
  const mins = Math.floor(delta / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
