"use client";

import type { Depth } from "@/hooks/use-depth";
import { createSupabaseBrowser } from "@/lib/supabase/client";

// All API calls are same-origin via the Next.js /api/:path* rewrite (see
// frontend/next.config.ts). Going cross-origin would break cookie-based auth
// for EventSource, so we keep every call site on relative paths.

export interface ApiError extends Error {
  status: number;
  body: unknown;
}

async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const supabase = createSupabaseBrowser();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const headers = new Headers(init.headers);
  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`);
  }
  return fetch(input, { ...init, headers, credentials: "include" });
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await authedFetch(path, { method: "GET" });
  return throwOrJson<T>(res);
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const res = await authedFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...extraHeaders },
    body: JSON.stringify(body),
  });
  return throwOrJson<T>(res);
}

export async function apiPut(path: string, body: unknown): Promise<void> {
  const res = await authedFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwOrJson(res);
}

export async function apiDelete(path: string): Promise<void> {
  const res = await authedFetch(path, { method: "DELETE" });
  if (!res.ok) await throwOrJson(res);
}

async function throwOrJson<T>(res: Response): Promise<T> {
  if (res.ok) {
    if (res.status === 204) return undefined as unknown as T;
    return (await res.json()) as T;
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = await res.text();
  }
  const err = new Error(`API ${res.status}`) as ApiError;
  err.status = res.status;
  err.body = body;
  throw err;
}

// --- Legacy helpers kept for the existing research form -------------------

export interface CreateResearchResponse {
  report_id: string;
}

export interface CreateResearchOptions {
  depth?: Depth;
  browseWeb?: boolean;
}

export async function createResearch(
  question: string,
  options: CreateResearchOptions = {},
): Promise<CreateResearchResponse> {
  const body: Record<string, unknown> = { question };
  if (options.depth) body.depth = options.depth;
  if (typeof options.browseWeb === "boolean") body.browse_web = options.browseWeb;
  return apiPost<CreateResearchResponse>("/api/research", body);
}
