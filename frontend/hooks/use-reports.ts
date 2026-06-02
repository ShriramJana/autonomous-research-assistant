"use client";

import { useCallback, useEffect, useState } from "react";

import { apiDelete, apiGet } from "@/lib/api";

export interface ReportSummary {
  id: string;
  question: string;
  status: "running" | "completed" | "error";
  depth: "quick" | "standard" | "deep";
  used_byok: boolean;
  is_sample: boolean;
  cost_usd: number | null;
  created_at: string;
  completed_at: string | null;
}

export function useReports() {
  const [items, setItems] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setItems(await apiGet<ReportSummary[]>("/api/reports"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial fetch on mount; subsequent updates flow through `refresh`/`remove`.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const remove = useCallback(async (id: string) => {
    await apiDelete(`/api/reports/${id}`);
    setItems((prev) => prev.filter((r) => r.id !== id));
  }, []);

  return { items, loading, error, refresh, remove };
}
