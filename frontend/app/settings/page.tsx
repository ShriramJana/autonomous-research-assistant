"use client";

import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { type Config, fetchConfig } from "@/lib/config";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; config: Config }
  | { kind: "error"; message: string };

export default function SettingsPage() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchConfig()
      .then((config) => {
        if (!cancelled) setState({ kind: "ready", config });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : "unknown error",
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 py-12 md:py-16">
      <header className="mb-10 flex flex-col gap-2">
        <p className="text-primary font-mono text-[0.6875rem] uppercase tracking-[0.2em]">
          Settings
        </p>
        <h1 className="text-foreground text-3xl font-extrabold tracking-tight md:text-4xl">
          Runtime configuration
        </h1>
        <p className="text-muted-foreground text-sm">
          Read-only view of which models ARA is routing to and what each depth
          preset actually does.
        </p>
      </header>

      {state.kind === "error" ? (
        <p className="text-muted-foreground font-mono text-xs">
          Config unavailable — backend may be offline. ({state.message})
        </p>
      ) : null}

      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Active models
        </h2>
        <div className="bg-card flex flex-col overflow-hidden rounded-lg">
          {state.kind === "loading" ? (
            <>
              <ModelSkeletonRow />
              <ModelSkeletonRow />
              <ModelSkeletonRow />
            </>
          ) : state.kind === "ready" ? (
            <>
              <ModelRow role="Planner" model={state.config.models.planner} />
              <ModelRow
                role="Researcher"
                model={state.config.models.researcher}
              />
              <ModelRow
                role="Synthesizer"
                model={state.config.models.synthesizer}
              />
            </>
          ) : null}
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Depth presets
        </h2>
        <div className="bg-card overflow-hidden rounded-lg">
          <table className="w-full">
            <thead>
              <tr className="text-muted-foreground/60 border-border/40 border-b text-left font-mono text-[10px] uppercase tracking-widest">
                <th className="px-5 py-3 font-normal">Preset</th>
                <th className="px-5 py-3 text-right font-normal">
                  Sub-queries
                </th>
                <th className="px-5 py-3 text-right font-normal">
                  Iterations
                </th>
              </tr>
            </thead>
            <tbody>
              {state.kind === "ready" ? (
                (["quick", "standard", "deep"] as const).map((preset) => {
                  const p = state.config.depth_presets[preset];
                  return (
                    <tr
                      key={preset}
                      className="border-border/20 border-b last:border-b-0"
                    >
                      <td className="text-foreground px-5 py-3 text-sm font-medium capitalize">
                        {preset}
                      </td>
                      <td className="text-foreground px-5 py-3 text-right font-mono text-sm">
                        {p.max_sub_queries}
                      </td>
                      <td className="text-foreground px-5 py-3 text-right font-mono text-sm">
                        {p.max_iterations}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <>
                  <DepthSkeletonRow />
                  <DepthSkeletonRow />
                  <DepthSkeletonRow />
                </>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <p className="text-muted-foreground/60 font-mono text-[10px] tracking-wider">
        Values are read at request time from the backend <code>.env</code>. To
        change them, edit the environment and restart the backend.
      </p>
    </main>
  );
}

function ModelRow({ role, model }: { role: string; model: string }) {
  return (
    <div className="border-border/20 flex items-center justify-between border-b px-5 py-4 last:border-b-0">
      <span className="text-muted-foreground/80 font-mono text-[11px] uppercase tracking-widest">
        {role}
      </span>
      <code className="text-foreground font-mono text-sm">{model}</code>
    </div>
  );
}

function ModelSkeletonRow() {
  return (
    <div className="border-border/20 flex items-center justify-between border-b px-5 py-4 last:border-b-0">
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-4 w-40" />
    </div>
  );
}

function DepthSkeletonRow() {
  return (
    <tr className="border-border/20 border-b last:border-b-0">
      <td className="px-5 py-3">
        <Skeleton className="h-4 w-16" />
      </td>
      <td className="px-5 py-3 text-right">
        <Skeleton className="ml-auto h-4 w-6" />
      </td>
      <td className="px-5 py-3 text-right">
        <Skeleton className="ml-auto h-4 w-6" />
      </td>
    </tr>
  );
}
