"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Globe, Layers, Zap } from "lucide-react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { createResearch } from "@/lib/api";
import { addHistoryItem } from "@/lib/history";
import { useBrowseWeb } from "@/hooks/use-browse-web";
import { type Depth, useDepth } from "@/hooks/use-depth";

const DEPTH_OPTIONS: Array<{
  value: Depth;
  label: string;
  detail: string;
}> = [
  { value: "quick", label: "Quick", detail: "3 sub-queries · 2 iterations" },
  { value: "standard", label: "Standard", detail: "5 sub-queries · 3 iterations" },
  { value: "deep", label: "Deep", detail: "7 sub-queries · 5 iterations" },
];

const depthLabel = (d: Depth) =>
  DEPTH_OPTIONS.find((o) => o.value === d)?.label ?? "Standard";

export function ResearchForm({
  initialQuestion = "",
  compact = false,
}: {
  initialQuestion?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [question, setQuestion] = useState(initialQuestion);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [depthOpen, setDepthOpen] = useState(false);
  const { depth, setDepth } = useDepth();
  const { browseWeb, toggleBrowseWeb } = useBrowseWeb();

  useEffect(() => {
    const focusOnHash = () => {
      if (window.location.hash === "#question") {
        textareaRef.current?.focus({ preventScroll: false });
      }
    };
    focusOnHash();
    window.addEventListener("hashchange", focusOnHash);
    return () => window.removeEventListener("hashchange", focusOnHash);
  }, []);

  const submit = async () => {
    if (!question.trim() || submitting) return;
    setError(null);
    setSubmitting(true);
    try {
      const trimmed = question.trim();
      const { report_id } = await createResearch(trimmed, { depth, browseWeb });
      addHistoryItem({
        reportId: report_id,
        question: trimmed,
        createdAt: Date.now(),
        status: "running",
      });
      router.push(`/r/${report_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setSubmitting(false);
    }
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void submit();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void submit();
    }
  };

  const minHeight = compact ? "min-h-[96px]" : "min-h-[160px]";

  return (
    <form onSubmit={onSubmit} className="w-full">
      <div className="bg-secondary focus-within:ring-border group relative rounded-xl p-1 transition-all duration-300 focus-within:ring-1">
        <textarea
          ref={textareaRef}
          id="question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={submitting}
          placeholder="Deep dive into the competitive landscape of renewable energy storage systems in 2024…"
          className={`text-foreground placeholder:text-muted-foreground/50 font-sans w-full resize-none border-none bg-transparent p-6 text-lg outline-none focus:ring-0 ${minHeight}`}
        />
        <div className="flex items-center justify-between border-t border-white/[0.04] px-6 py-4">
          <div className="flex gap-4">
            <Popover open={depthOpen} onOpenChange={setDepthOpen}>
              <PopoverTrigger
                className="text-muted-foreground hover:text-foreground flex items-center gap-2 transition-colors"
                aria-label={`Depth: ${depthLabel(depth)}`}
              >
                <Layers className="h-3.5 w-3.5" strokeWidth={1.75} />
                <span className="font-mono text-[10px] uppercase tracking-wider">
                  Depth · {depthLabel(depth)}
                </span>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-64 p-1.5">
                <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
                  Research depth
                </p>
                {DEPTH_OPTIONS.map((opt) => {
                  const active = opt.value === depth;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => {
                        setDepth(opt.value);
                        setDepthOpen(false);
                      }}
                      className={
                        active
                          ? "bg-accent text-foreground flex w-full items-center justify-between rounded px-2 py-1.5 text-left"
                          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground flex w-full items-center justify-between rounded px-2 py-1.5 text-left transition-colors"
                      }
                    >
                      <div className="flex flex-col">
                        <span className="text-sm font-medium">{opt.label}</span>
                        <span className="text-muted-foreground/70 font-mono text-[10px] tracking-tight">
                          {opt.detail}
                        </span>
                      </div>
                      {active ? (
                        <Check
                          className="text-primary h-3.5 w-3.5"
                          strokeWidth={2.5}
                        />
                      ) : null}
                    </button>
                  );
                })}
              </PopoverContent>
            </Popover>
            <button
              type="button"
              onClick={toggleBrowseWeb}
              aria-pressed={browseWeb}
              title={
                browseWeb
                  ? "Web search enabled — click to disable"
                  : "Web search disabled — click to enable"
              }
              className={
                browseWeb
                  ? "text-primary hover:text-primary/80 flex items-center gap-2 transition-colors"
                  : "text-muted-foreground/50 hover:text-foreground flex items-center gap-2 transition-colors"
              }
            >
              <Globe className="h-3.5 w-3.5" strokeWidth={1.75} />
              <span className="font-mono text-[10px] uppercase tracking-wider">
                Browse Web · {browseWeb ? "On" : "Off"}
              </span>
            </button>
          </div>
          <button
            type="submit"
            disabled={!question.trim() || submitting}
            className="from-primary to-primary-container text-primary-foreground shadow-primary/10 inline-flex items-center gap-2 rounded-md bg-gradient-to-r px-8 py-2 text-sm font-bold shadow-lg transition-all hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <span className="font-mono text-xs tracking-tight">
              {submitting ? "STARTING…" : "EXECUTE"}
            </span>
            {!submitting ? (
              <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
            ) : null}
          </button>
        </div>
      </div>
      {error ? (
        <p className="text-destructive mt-3 px-2 font-mono text-xs">
          {error}
        </p>
      ) : null}
    </form>
  );
}
