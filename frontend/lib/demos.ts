import type { ResearchEvent } from "@/lib/events";
import manifest from "@/public/demos/manifest.json";

export interface DemoManifestEntry {
  slug: string;
  title: string;
  question: string;
  model: string;
  created_at: string;
  n_events: number;
}

export interface DemoEvent {
  t_ms: number;
  event: ResearchEvent;
}

export interface DemoFile {
  slug: string;
  title: string;
  question: string;
  model: string;
  created_at: string;
  events: DemoEvent[];
}

// Static import — bundled at build time, so the gallery renders with no
// network call and no backend.
export const demoManifest = manifest as DemoManifestEntry[];

// The event payloads can be large; fetch them on demand from /public.
export async function loadDemoEvents(slug: string): Promise<DemoFile> {
  const res = await fetch(`/demos/${slug}.json`, { cache: "force-cache" });
  if (!res.ok) throw new Error(`demo ${slug} not found`);
  return (await res.json()) as DemoFile;
}
