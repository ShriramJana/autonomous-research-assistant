// Typed client for GET /api/config.

import type { Depth } from "@/hooks/use-depth";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ModelsConfig {
  planner: string;
  researcher: string;
  synthesizer: string;
}

export interface DepthPresetConfig {
  max_sub_queries: number;
  max_iterations: number;
}

export interface Config {
  models: ModelsConfig;
  depth_presets: Record<Depth, DepthPresetConfig>;
}

export async function fetchConfig(): Promise<Config> {
  const res = await fetch(`${BASE}/api/config`, {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`Failed to load config (${res.status})`);
  }
  return (await res.json()) as Config;
}
