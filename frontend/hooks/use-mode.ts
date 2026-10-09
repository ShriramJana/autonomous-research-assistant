"use client";

import { useEffect, useState } from "react";

import { fetchConfig, type Mode } from "@/lib/config";

let modePromise: Promise<Mode> | null = null;

/** Resolves once per page load; falls back to "hosted" if the backend is unreachable. */
export function fetchMode(): Promise<Mode> {
  modePromise ??= fetchConfig()
    .then((c) => c.mode)
    .catch(() => "hosted" as const);
  return modePromise;
}

export function useMode(): { mode: Mode | null; loading: boolean } {
  const [mode, setMode] = useState<Mode | null>(null);
  useEffect(() => {
    let cancelled = false;
    fetchMode().then((m) => {
      if (!cancelled) setMode(m);
    });
    return () => {
      cancelled = true;
    };
  }, []);
  return { mode, loading: mode === null };
}
