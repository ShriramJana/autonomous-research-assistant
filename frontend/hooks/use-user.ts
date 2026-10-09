"use client";

import { useEffect, useState } from "react";

import { fetchMode } from "@/hooks/use-mode";
import { createSupabaseBrowser } from "@/lib/supabase/client";

export interface AppUser {
  id: string;
  email?: string;
}

export const LOCAL_USER: AppUser = {
  id: "00000000-0000-4000-8000-000000000001",
  email: "local@ara",
};

export function useUser(): { user: AppUser | null; loading: boolean } {
  const [user, setUser] = useState<AppUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let unsubscribe = () => {};
    let cancelled = false;
    fetchMode().then((mode) => {
      if (cancelled) return;
      if (mode === "local") {
        setUser(LOCAL_USER);
        setLoading(false);
        return;
      }
      const supabase = createSupabaseBrowser();
      supabase.auth.getUser().then(({ data }) => {
        if (cancelled) return;
        setUser(data.user ? { id: data.user.id, email: data.user.email } : null);
        setLoading(false);
      });
      const { data } = supabase.auth.onAuthStateChange((_event, session) => {
        setUser(session?.user ? { id: session.user.id, email: session.user.email } : null);
      });
      unsubscribe = () => data.subscription.unsubscribe();
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return { user, loading };
}
