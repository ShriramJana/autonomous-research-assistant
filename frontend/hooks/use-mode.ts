"use client";

import { useEffect, useState } from "react";

import { fetchConfig, type Mode } from "@/lib/config";

let modePromise: Promise<Mode> | null = null;

const CONFIG_TIMEOUT_MS = 1500;

/**
 * Resolves once per page load.
 * - `make local` sets NEXT_PUBLIC_ARA_MODE=local, so local mode resolves with
 *   no network call (and never waits on, or touches, Supabase).
 * - Otherwise /api/config is raced against a short timeout: the hosted backend
 *   is on Cloud Run with scale-to-zero (~18s cold start) and first paint must
 *   not block on it. Timeout or error falls back to "hosted".
 */
export function fetchMode(): Promise<Mode> {
  if (process.env.NEXT_PUBLIC_ARA_MODE === "local") return Promise.resolve("local");
  modePromise ??= Promise.race([
    fetchConfig().then((c) => c.mode),
    new Promise<Mode>((resolve) => setTimeout(() => resolve("hosted"), CONFIG_TIMEOUT_MS)),
  ]).catch(() => "hosted" as const);
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
