"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";

import { createSupabaseBrowser } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const supabase = createSupabaseBrowser();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function signInWithGoogle() {
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    if (error) setError(error.message);
  }

  async function signInWithMagicLink(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    setPending(false);
    if (error) setError(error.message);
    else setSentTo(email);
  }

  return (
    <main className="mx-auto max-w-md p-8 pt-20">
      <h1 className="font-mono text-2xl tracking-tight">Sign in to ARA</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Required to run reports and keep your history.
      </p>

      <div className="mt-8 space-y-4">
        <Button onClick={signInWithGoogle} className="w-full" variant="default">
          Continue with Google
        </Button>

        <div className="text-muted-foreground py-2 text-center font-mono text-[10px] uppercase tracking-widest">
          or
        </div>

        <form onSubmit={signInWithMagicLink} className="space-y-3">
          <Input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={pending || sentTo !== null}
          />
          <Button type="submit" disabled={pending || sentTo !== null} className="w-full" variant="secondary">
            {pending ? "Sending…" : sentTo ? `Magic link sent to ${sentTo}` : "Email me a magic link"}
          </Button>
        </form>

        {error && <p className="text-destructive text-sm">{error}</p>}
      </div>
    </main>
  );
}
