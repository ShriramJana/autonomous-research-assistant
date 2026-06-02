"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet } from "@/lib/api";
import {
  clearStoredApiKey,
  getStoredApiKey,
  setStoredApiKey,
} from "@/lib/api-key";
import { createSupabaseBrowser } from "@/lib/supabase/client";
import { useUser } from "@/hooks/use-user";
import { type Config, fetchConfig } from "@/lib/config";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; config: Config }
  | { kind: "error"; message: string };

interface Quota {
  used: number;
  limit: number;
  global_spend_usd: number;
  global_cap_usd: number;
  circuit_breaker_tripped: boolean;
}

export default function SettingsPage() {
  const router = useRouter();
  const { user, loading } = useUser();

  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [keyInput, setKeyInput] = useState("");
  const [storedKey, setStoredKey] = useState<string | null>(null);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [quotaError, setQuotaError] = useState<string | null>(null);

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

  useEffect(() => {
    // Read localStorage post-mount to avoid SSR/CSR hydration mismatch.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStoredKey(getStoredApiKey());
  }, []);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    apiGet<Quota>("/api/quota")
      .then((q) => {
        if (!cancelled) setQuota(q);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setQuotaError(err instanceof Error ? err.message : "unknown error");
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  const onSaveKey = () => {
    const trimmed = keyInput.trim();
    if (!trimmed) return;
    setStoredApiKey(trimmed);
    setStoredKey(trimmed);
    setKeyInput("");
  };

  const onClearKey = () => {
    clearStoredApiKey();
    setStoredKey(null);
  };

  const onSignOut = async () => {
    const supabase = createSupabaseBrowser();
    await supabase.auth.signOut();
    router.push("/");
  };

  if (loading) return null;

  if (!user) {
    return (
      <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 py-12 md:py-16">
        <p className="text-muted-foreground text-sm">
          Please{" "}
          <Link href="/login" className="text-primary underline">
            sign in
          </Link>{" "}
          to manage your settings.
        </p>
      </main>
    );
  }

  return (
    <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 py-12 md:py-16">
      <header className="mb-10 flex flex-col gap-2">
        <p className="text-primary font-mono text-[0.6875rem] uppercase tracking-[0.2em]">
          Settings
        </p>
        <h1 className="text-foreground text-3xl font-extrabold tracking-tight md:text-4xl">
          Account & runtime
        </h1>
        <p className="text-muted-foreground text-sm">
          Bring your own Anthropic key, track your free-tier usage, and view
          which models ARA is routing to.
        </p>
      </header>

      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Anthropic API key
        </h2>
        <div className="bg-card flex flex-col gap-3 rounded-lg p-5">
          {storedKey ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <code className="text-foreground font-mono text-sm">
                sk-ant-•••• (saved to this browser only)
              </code>
              <Button
                variant="outline"
                size="sm"
                onClick={onClearKey}
                className="font-mono text-xs uppercase tracking-wider"
              >
                Clear
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <Input
                type="password"
                placeholder="sk-ant-…"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                className="flex-1 font-mono"
              />
              <Button
                size="sm"
                onClick={onSaveKey}
                disabled={!keyInput.trim()}
                className="font-mono text-xs uppercase tracking-wider"
              >
                Save
              </Button>
            </div>
          )}
          <p className="text-muted-foreground/70 font-mono text-[10px] tracking-wider">
            Stored in this browser only. Sent per-request as{" "}
            <code>X-Anthropic-Key</code>.
          </p>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Free tier quota
        </h2>
        <div className="bg-card rounded-lg p-5">
          {quotaError ? (
            <p className="text-muted-foreground font-mono text-xs">
              Quota unavailable — backend may be offline. ({quotaError})
            </p>
          ) : quota === null ? (
            <Skeleton className="h-4 w-64" />
          ) : (
            <>
              <p className="text-foreground text-sm">
                <span className="font-mono font-medium">{quota.used}</span> of{" "}
                <span className="font-mono font-medium">{quota.limit}</span>{" "}
                free reports used this month
              </p>
              {quota.circuit_breaker_tripped ? (
                <p className="text-destructive mt-2 font-mono text-xs">
                  Free tier paused — global spend cap reached. Add your own API
                  key above to keep running reports.
                </p>
              ) : null}
            </>
          )}
        </div>
      </section>

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
          ) : (
            <p className="text-muted-foreground p-5 font-mono text-xs">
              Config unavailable — backend may be offline. ({state.message})
            </p>
          )}
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
        <p className="text-muted-foreground/60 mt-3 font-mono text-[10px] tracking-wider">
          Values are read at request time from the backend <code>.env</code>.
        </p>
      </section>

      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Account
        </h2>
        <div className="bg-card flex items-center justify-between rounded-lg p-5">
          <p className="text-muted-foreground text-sm">
            Signed in as{" "}
            <span className="text-foreground font-mono">{user.email}</span>
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void onSignOut()}
            className="font-mono text-xs uppercase tracking-wider"
          >
            Sign out
          </Button>
        </div>
      </section>
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
