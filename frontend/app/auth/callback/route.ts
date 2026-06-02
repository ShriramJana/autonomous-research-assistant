import { NextResponse } from "next/server";

import { createSupabaseServer } from "@/lib/supabase/server";

/**
 * Guard against open-redirect: only accept `next` values that name a path on
 * THIS origin. Reject absolute URLs (`https://evil.com`), protocol-relative
 * URLs (`//evil.com`, which some browsers/specs treat as origin-relative to
 * the current scheme), and anything that doesn't start with `/`.
 */
function safeNext(value: string | null): string {
  if (!value) return "/";
  if (!value.startsWith("/")) return "/";
  if (value.startsWith("//")) return "/"; // network-path reference
  return value;
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = safeNext(url.searchParams.get("next"));

  if (code) {
    const supabase = await createSupabaseServer();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      return NextResponse.redirect(
        new URL(`/login?error=${encodeURIComponent(error.message)}`, url.origin),
      );
    }
  }
  return NextResponse.redirect(new URL(next, url.origin));
}
