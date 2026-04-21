"use client";

import { useCallback, useEffect, useState } from "react";
import { clearHistory, loadHistory, type HistoryItem } from "@/lib/history";

export function useHistory(): {
  items: HistoryItem[];
  clear: () => void;
  refresh: () => void;
} {
  // SSR-safe: loadHistory() returns [] on the server and the real list
  // on the client. React 19 is fine with this since history isn't
  // rendered during SSR for our routes.
  const [items, setItems] = useState<HistoryItem[]>(() => loadHistory());

  const refresh = useCallback(() => {
    setItems(loadHistory());
  }, []);

  useEffect(() => {
    // Refresh when the tab regains focus — picks up updates made in
    // another tab (e.g. a report that completed in /r/{id}).
    const onFocus = () => refresh();
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key.startsWith("ara.history")) refresh();
    };
    window.addEventListener("focus", onFocus);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("storage", onStorage);
    };
  }, [refresh]);

  const clear = useCallback(() => {
    clearHistory();
    refresh();
  }, [refresh]);

  return { items, clear, refresh };
}
