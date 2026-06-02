"use client";

import Link from "next/link";
import { ChevronRight, FileText, Trash2 } from "lucide-react";

import { useReports, type ReportSummary } from "@/hooks/use-reports";

export function HistoryList() {
  const { items, loading, error, remove } = useReports();

  if (loading) {
    return (
      <section className="w-full" id="history">
        <div className="text-muted-foreground/60 font-mono text-xs">Loading history…</div>
      </section>
    );
  }
  if (error) {
    return (
      <section className="w-full" id="history">
        <div className="text-destructive font-mono text-xs">History unavailable: {error}</div>
      </section>
    );
  }
  if (items.length === 0) return null;

  return (
    <section className="w-full" id="history">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-muted-foreground font-mono text-xs uppercase tracking-widest">
          Recent reports
        </h2>
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <HistoryRow
            key={item.id}
            item={item}
            onDelete={async () => {
              if (confirm("Delete this report?")) await remove(item.id);
            }}
          />
        ))}
      </div>
    </section>
  );
}

function HistoryRow({ item, onDelete }: { item: ReportSummary; onDelete: () => void }) {
  return (
    <div className="hover:bg-card group flex flex-col items-stretch justify-between rounded-lg px-6 py-4 transition-all duration-150 md:flex-row md:items-center">
      <Link href={`/r/${item.id}`} className="flex flex-1 items-center gap-4">
        <FileText
          className="text-muted-foreground/60 group-hover:text-primary h-5 w-5 transition-colors"
          strokeWidth={1.5}
        />
        <div className="space-y-0.5">
          <p className="text-foreground group-hover:text-primary line-clamp-2 font-medium leading-snug transition-colors">
            {item.question}
          </p>
          <p className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-tight">
            {formatTimestamp(item.created_at)} · {item.status}
          </p>
        </div>
      </Link>
      <div className="mt-2 flex items-center gap-3 md:mt-0">
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete report"
          className="text-muted-foreground/40 hover:text-destructive p-1 transition-colors"
        >
          <Trash2 className="h-4 w-4" strokeWidth={1.5} />
        </button>
        <ChevronRight className="text-muted-foreground/40 h-4 w-4" strokeWidth={1.5} />
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}
