// Typed client for GET /api/config.

import type { Depth } from "@/hooks/use-depth";

// Same-origin via the Next.js /api/:path* rewrite — see frontend/next.config.ts.

export interface ModelsConfig {
  planner: string;
  researcher: string;
  synthesizer: string;
}

export interface DepthPresetConfig {
  max_sub_queries: number;
  max_iterations: number;
}

export type Mode = "hosted" | "local";

export interface Config {
  mode: Mode;
  // Optional: a backend older than the frontend (Vercel deploys first) omits it.
  scholarly_catalogs?: string[];
  models: ModelsConfig;
  depth_presets: Record<Depth, DepthPresetConfig>;
}

export async function fetchConfig(): Promise<Config> {
  const res = await fetch("/api/config", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Failed to load config (${res.status})`);
  }
  return (await res.json()) as Config;
}
