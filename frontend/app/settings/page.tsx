"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet } from "@/lib/api";
import { createSupabaseBrowser } from "@/lib/supabase/client";
import { useUser } from "@/hooks/use-user";
import { type Config, fetchConfig } from "@/lib/config";
import {
  type ActiveProvider,
  type CredentialsState,
  deleteAnthropicKey,
  deleteOpenAIConfig,
  getCredentials,
  putAnthropicKey,
  putOpenAIConfig,
  setActiveProvider,
} from "@/lib/credentials";

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
  tavily_cap_reached: boolean;
}

export default function SettingsPage() {
  const router = useRouter();
  const { user, loading } = useUser();

  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [quota, setQuota] = useState<Quota | null>(null);
  const [quotaError, setQuotaError] = useState<string | null>(null);

  // Credentials state
  const [creds, setCreds] = useState<CredentialsState | null>(null);
  const [credsError, setCredsError] = useState<string | null>(null);

  // Anthropic key form
  const [anthropicKeyInput, setAnthropicKeyInput] = useState("");
  const [anthropicSaving, setAnthropicSaving] = useState(false);

  // OpenAI config form
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState("");
  const [openaiModel, setOpenaiModel] = useState("");
  const [openaiKeyInput, setOpenaiKeyInput] = useState("");
  const [openaiSaving, setOpenaiSaving] = useState(false);

  // Active provider
  const [providerSaving, setProviderSaving] = useState(false);

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

  const loadCredentials = () => {
    let cancelled = false;
    getCredentials()
      .then((c) => {
        if (!cancelled) {
          setCreds(c);
          setCredsError(null);
          // Echo stored base_url/model into fields if configured and fields are empty
          if (c.openai.configured) {
            if (c.openai.base_url) setOpenaiBaseUrl((prev) => prev || c.openai.base_url!);
            if (c.openai.model) setOpenaiModel((prev) => prev || c.openai.model!);
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setCredsError(err instanceof Error ? err.message : "unknown error");
      });
    return () => {
      cancelled = true;
    };
  };

  useEffect(() => {
    if (!user) return;
    const cancel = loadCredentials();
    return cancel;
  }, [user]); // loadCredentials is a stable local fn; only re-run when user changes

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

  const onSaveAnthropicKey = async () => {
    const trimmed = anthropicKeyInput.trim();
    if (!trimmed) return;
    setAnthropicSaving(true);
    try {
      await putAnthropicKey(trimmed);
      setAnthropicKeyInput("");
      loadCredentials();
    } finally {
      setAnthropicSaving(false);
    }
  };

  const onClearAnthropicKey = async () => {
    setAnthropicSaving(true);
    try {
      await deleteAnthropicKey();
      loadCredentials();
    } finally {
      setAnthropicSaving(false);
    }
  };

  const onSaveOpenAI = async () => {
    const baseUrl = openaiBaseUrl.trim();
    const model = openaiModel.trim();
    const key = openaiKeyInput.trim();
    if (!baseUrl || !model || !key) return;
    setOpenaiSaving(true);
    try {
      await putOpenAIConfig({ baseUrl, model, key });
      setOpenaiKeyInput("");
      loadCredentials();
    } finally {
      setOpenaiSaving(false);
    }
  };

  const onClearOpenAI = async () => {
    setOpenaiSaving(true);
    try {
      await deleteOpenAIConfig();
      setOpenaiBaseUrl("");
      setOpenaiModel("");
      setOpenaiKeyInput("");
      loadCredentials();
    } finally {
      setOpenaiSaving(false);
    }
  };

  const onSetActiveProvider = async (provider: ActiveProvider) => {
    setProviderSaving(true);
    try {
      await setActiveProvider(provider);
      loadCredentials();
    } finally {
      setProviderSaving(false);
    }
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
          Manage your API credentials, track free-tier usage, and configure
          which provider ARA uses.
        </p>
      </header>

      {/* Active Provider */}
      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Active provider
        </h2>
        <div className="bg-card flex flex-col gap-3 rounded-lg p-5">
          {credsError ? (
            <p className="text-muted-foreground font-mono text-xs">
              Credentials unavailable — backend may be offline. ({credsError})
            </p>
          ) : creds === null ? (
            <Skeleton className="h-4 w-64" />
          ) : (
            <>
              <div className="flex flex-col gap-2 sm:flex-row sm:gap-4">
                <ProviderRadio
                  label="Free (ARA-hosted)"
                  value="free"
                  current={creds.active_provider}
                  disabled={providerSaving}
                  alwaysEnabled
                  onChange={onSetActiveProvider}
                />
                <ProviderRadio
                  label="Anthropic (your key)"
                  value="anthropic"
                  current={creds.active_provider}
                  disabled={providerSaving || !creds.anthropic_configured}
                  alwaysEnabled={false}
                  onChange={onSetActiveProvider}
                />
                <ProviderRadio
                  label="OpenAI-compat (your key)"
                  value="openai"
                  current={creds.active_provider}
                  disabled={providerSaving || !creds.openai.configured}
                  alwaysEnabled={false}
                  onChange={onSetActiveProvider}
                />
              </div>
              <p className="text-muted-foreground/70 font-mono text-[10px] tracking-wider">
                Anthropic key → built-in web search (recommended, better
                results). OpenAI-compat providers use Tavily for web search.
              </p>
              {quota?.tavily_cap_reached ? (
                <p className="text-destructive font-mono text-[10px] tracking-wider">
                  Tavily monthly cap reached — OpenAI-compat web search is
                  paused until next month.
                </p>
              ) : null}
            </>
          )}
        </div>
      </section>

      {/* Anthropic key */}
      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          Anthropic API key
        </h2>
        <div className="bg-card flex flex-col gap-3 rounded-lg p-5">
          {creds?.anthropic_configured ? (
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <code className="text-foreground font-mono text-sm">
                sk-ant-•••• (encrypted on server)
              </code>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void onClearAnthropicKey()}
                disabled={anthropicSaving}
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
                value={anthropicKeyInput}
                onChange={(e) => setAnthropicKeyInput(e.target.value)}
                className="flex-1 font-mono"
                autoComplete="off"
              />
              <Button
                size="sm"
                onClick={() => void onSaveAnthropicKey()}
                disabled={!anthropicKeyInput.trim() || anthropicSaving}
                className="font-mono text-xs uppercase tracking-wider"
              >
                Save
              </Button>
            </div>
          )}
          <p className="text-muted-foreground/70 font-mono text-[10px] tracking-wider">
            Stored encrypted on the server. Never returned. Enables native
            Anthropic web search.
          </p>
        </div>
      </section>

      {/* OpenAI-compatible config */}
      <section className="mb-8">
        <h2 className="text-muted-foreground/60 mb-3 font-mono text-[10px] uppercase tracking-widest">
          OpenAI-compatible provider
        </h2>
        <div className="bg-card flex flex-col gap-4 rounded-lg p-5">
          {credsError ? null : creds === null ? (
            <Skeleton className="h-4 w-64" />
          ) : (
            <>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-muted-foreground/80 font-mono text-[10px] uppercase tracking-wider">
                    Base URL
                  </label>
                  <Input
                    type="url"
                    placeholder="https://api.openai.com/v1"
                    value={openaiBaseUrl}
                    onChange={(e) => setOpenaiBaseUrl(e.target.value)}
                    className="font-mono"
                    autoComplete="off"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-muted-foreground/80 font-mono text-[10px] uppercase tracking-wider">
                    Model
                  </label>
                  <Input
                    type="text"
                    placeholder="gpt-4o"
                    value={openaiModel}
                    onChange={(e) => setOpenaiModel(e.target.value)}
                    className="font-mono"
                    autoComplete="off"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-muted-foreground/80 font-mono text-[10px] uppercase tracking-wider">
                    API key
                  </label>
                  <Input
                    type="password"
                    placeholder={
                      creds.openai.configured ? "•••• (enter new key to update)" : "sk-…"
                    }
                    value={openaiKeyInput}
                    onChange={(e) => setOpenaiKeyInput(e.target.value)}
                    className="font-mono"
                    autoComplete="off"
                  />
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  onClick={() => void onSaveOpenAI()}
                  disabled={
                    !openaiBaseUrl.trim() ||
                    !openaiModel.trim() ||
                    !openaiKeyInput.trim() ||
                    openaiSaving
                  }
                  className="font-mono text-xs uppercase tracking-wider"
                >
                  Save
                </Button>
                {creds.openai.configured ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void onClearOpenAI()}
                    disabled={openaiSaving}
                    className="font-mono text-xs uppercase tracking-wider"
                  >
                    Clear
                  </Button>
                ) : null}
              </div>
              <p className="text-muted-foreground/70 font-mono text-[10px] tracking-wider">
                Key stored encrypted on server. Never returned. Base URL and
                model are echoed back when configured.
              </p>
            </>
          )}
        </div>
      </section>

      {/* Free tier quota */}
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

      {/* Active models */}
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

      {/* Depth presets */}
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

      {/* Account */}
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

function ProviderRadio({
  label,
  value,
  current,
  disabled,
  alwaysEnabled,
  onChange,
}: {
  label: string;
  value: ActiveProvider;
  current: ActiveProvider;
  disabled: boolean;
  alwaysEnabled: boolean;
  onChange: (v: ActiveProvider) => void;
}) {
  const isSelected = current === value;
  const isDisabled = disabled && !alwaysEnabled ? true : disabled;
  return (
    <label
      className={`flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors ${
        isSelected
          ? "border-primary bg-primary/5 text-foreground"
          : "border-border text-muted-foreground hover:border-primary/50"
      } ${isDisabled ? "cursor-not-allowed opacity-50" : ""}`}
    >
      <input
        type="radio"
        name="active-provider"
        value={value}
        checked={isSelected}
        disabled={isDisabled}
        onChange={() => onChange(value)}
        className="accent-primary"
      />
      <span className="font-mono text-[11px] uppercase tracking-wider">
        {label}
      </span>
    </label>
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
