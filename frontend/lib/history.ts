// Per-browser research history, persisted in localStorage.
// Intentionally client-side — v1 backend is in-memory, so server-side
// history would be discarded on restart anyway. Swap to a DB-backed
// store when auth + persistence land (see ARCHITECTURE.md).

export type HistoryStatus = "running" | "complete" | "error";

export interface HistoryItem {
  reportId: string;
  question: string;
  createdAt: number; // unix ms
  status: HistoryStatus;
  executiveSummary?: string;
}

const KEY = "ara.history.v1";
const MAX_ITEMS = 50;

export function loadHistory(): HistoryItem[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as HistoryItem[]) : [];
  } catch {
    return [];
  }
}

function save(items: HistoryItem[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
}

export function addHistoryItem(item: HistoryItem): void {
  // Newest first, dedup by reportId.
  const items = loadHistory().filter((i) => i.reportId !== item.reportId);
  save([item, ...items]);
}

export function updateHistoryItem(
  reportId: string,
  patch: Partial<Omit<HistoryItem, "reportId">>,
): void {
  const items = loadHistory();
  const idx = items.findIndex((i) => i.reportId === reportId);
  if (idx === -1) return;
  items[idx] = { ...items[idx], ...patch };
  save(items);
}

export function clearHistory(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}
