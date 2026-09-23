import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
        },
      },
    },
  );
  // Refresh the session, but never let a slow/unreachable Supabase Auth server
  // hang the middleware — Vercel kills it at ~25s with MIDDLEWARE_INVOCATION_TIMEOUT,
  // which would 504 the entire site. Cap the call and degrade to "logged out".
  try {
    await Promise.race([
      supabase.auth.getUser(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("auth timeout")), 5000),
      ),
    ]);
  } catch {
    // Session couldn't be refreshed; continue unauthenticated rather than 504.
  }
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
