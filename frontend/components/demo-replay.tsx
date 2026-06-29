"use client";

import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ResearchLive } from "@/components/research-live";
import { useReplayFromJson } from "@/hooks/use-replay-from-json";
import { loadDemoEvents } from "@/lib/demos";
import type { DemoEvent } from "@/lib/demos";

export function DemoReplay({ slug }: { slug: string }) {
  const [events, setEvents] = useState<DemoEvent[] | null>(null);
  const [notFound, setNotFound] = useState(false);
  const { state, restart } = useReplayFromJson(events);

  useEffect(() => {
    let active = true;
    loadDemoEvents(slug)
      .then((file) => {
        if (active) setEvents(file.events);
      })
      .catch(() => {
        if (active) setNotFound(true);
      });
    return () => {
      active = false;
    };
  }, [slug]);

  if (notFound) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-24 text-center">
        <p className="text-muted-foreground font-mono text-sm">
          Demo &ldquo;{slug}&rdquo; not found.
        </p>
      </main>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-6 py-2 print:hidden">
        <span className="text-muted-foreground font-mono text-[10px] uppercase tracking-widest">
          Demo replay · no API key · runs in your browser
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={restart}
          className="text-muted-foreground hover:text-foreground font-mono text-xs uppercase tracking-wider"
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.75} />
          Replay
        </Button>
      </div>
      <ResearchLive state={state} />
    </div>
  );
}
