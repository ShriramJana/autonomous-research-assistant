"use client";

import Link from "next/link";
import { ChevronRight, FileText } from "lucide-react";

import { useHistory } from "@/hooks/use-history";
import type { HistoryItem } from "@/lib/history";

export function HistoryList() {
  const { items, clear } = useHistory();
  if (items.length === 0) return null;

  return (
    <section className="w-full" id="history">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-muted-foreground font-mono text-xs uppercase tracking-widest">
          Recent reports
        </h2>
        <button
          type="button"
          onClick={clear}
          className="text-muted-foreground hover:text-primary font-mono text-[10px] uppercase tracking-wider transition-colors"
        >
          Clear history
        </button>
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <HistoryRow key={item.reportId} item={item} />
        ))}
      </div>
      <p className="text-muted-foreground/60 mt-6 font-mono text-[10px] tracking-wider">
        Stored in this browser only.
      </p>
    </section>
  );
}

function HistoryRow({ item }: { item: HistoryItem }) {
  const status = statusFor(item);
  return (
    <Link
      href={`/r/${item.reportId}`}
      className="hover:bg-card group flex flex-col items-stretch justify-between rounded-lg px-6 py-4 transition-all duration-150 md:flex-row md:items-center"
    >
      <div className="flex items-center gap-4">
        <FileText
          className="text-muted-foreground/60 group-hover:text-primary h-5 w-5 transition-colors"
          strokeWidth={1.5}
        />
        <div className="space-y-0.5">
          <p className="text-foreground group-hover:text-primary line-clamp-2 font-medium leading-snug transition-colors">
            {item.question}
          </p>
          <p className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-tight">
            {formatTimestamp(item.createdAt)}
          </p>
        </div>
      </div>
      <div className="mt-2 flex items-center gap-6 md:mt-0">
        <StatusBadge status={status} />
        <ChevronRight
          className="text-muted-foreground/40 h-4 w-4"
          strokeWidth={1.5}
        />
      </div>
    </Link>
  );
}

type HistoryStatus = "synthesized" | "running" | "failed" | "archive";

function statusFor(item: HistoryItem): HistoryStatus {
  if (item.status === "running") return "running";
  if (item.status === "error") return "failed";
  return "synthesized";
}

function StatusBadge({ status }: { status: HistoryStatus }) {
  if (status === "running") {
    return (
      <div className="flex items-center gap-2">
        <span className="bg-primary h-1.5 w-1.5 animate-pulse rounded-full" />
        <span className="text-primary font-mono text-[10px] uppercase tracking-widest">
          Researching
        </span>
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="flex items-center gap-2">
        <span className="bg-destructive h-1.5 w-1.5 rounded-full" />
        <span className="text-destructive font-mono text-[10px] uppercase tracking-widest">
          Failed
        </span>
      </div>
    );
  }
  if (status === "archive") {
    return (
      <div className="bg-secondary text-muted-foreground flex items-center gap-2 rounded px-2 py-0.5">
        <span className="font-mono text-[10px] uppercase tracking-widest">
          Archive
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <span className="bg-primary h-1.5 w-1.5 rounded-full" />
      <span className="text-primary font-mono text-[10px] uppercase tracking-widest">
        Synthesized
      </span>
    </div>
  );
}

function formatTimestamp(ms: number): string {
  const date = new Date(ms);
  const offsetMin = -date.getTimezoneOffset();
  const sign = offsetMin >= 0 ? "+" : "-";
  const offsetHours = String(Math.abs(Math.floor(offsetMin / 60))).padStart(
    2,
    "0",
  );
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `[TIMESTAMP_UTC${sign}${offsetHours}] ${yyyy}-${mm}-${dd} ${hh}:${min}`;
}
