"use client";

import { CircleUser, LogOut, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useUser } from "@/hooks/use-user";
import { createSupabaseBrowser } from "@/lib/supabase/client";

const NAV_LINKS = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/gallery", label: "Gallery", match: (p: string) => p === "/gallery" },
  { href: "/#history", label: "History", match: () => false },
  { href: "/settings", label: "Settings", match: (p: string) => p === "/settings" },
] as const;

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useUser();
  const isDashboard = pathname === "/";

  const onExecuteClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (isDashboard) {
      const el = document.getElementById("question") as HTMLTextAreaElement | null;
      el?.focus();
      window.history.replaceState(null, "", "/#question");
    } else {
      router.push("/#question");
    }
  };

  async function signOut() {
    const supabase = createSupabaseBrowser();
    await supabase.auth.signOut();
    router.push("/");
  }

  return (
    <header className="bg-background sticky top-0 z-50 flex h-14 w-full items-center justify-between border-b border-white/[0.06] px-6 print:hidden">
      <div className="flex items-center gap-8">
        <Link href="/" className="text-primary font-mono text-xl font-bold tracking-tighter transition-opacity hover:opacity-80">
          ARA
        </Link>
        <nav className="hidden gap-6 md:flex">
          {NAV_LINKS.map((link) => {
            const active = link.match(pathname);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={
                  active
                    ? "text-primary border-primary border-b-2 pb-1 font-mono text-xs uppercase tracking-wider opacity-90"
                    : "text-muted-foreground hover:text-primary/80 font-mono text-xs uppercase tracking-wider transition-colors"
                }
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <Popover>
          <PopoverTrigger
            aria-label="Account"
            className="text-muted-foreground hover:text-primary/80 hidden transition-colors md:inline-flex"
          >
            <CircleUser className="h-5 w-5" strokeWidth={1.5} />
          </PopoverTrigger>
          <PopoverContent align="end" className="w-56">
            {user ? (
              <>
                <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
                  Signed in as
                </p>
                <p className="truncate px-2 pb-2 text-sm">{user.email}</p>
                <Link
                  href="/settings"
                  className="block rounded px-2 py-1.5 text-sm hover:bg-accent"
                >
                  Settings
                </Link>
                <button
                  type="button"
                  onClick={signOut}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                >
                  <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
                  Sign out
                </button>
              </>
            ) : (
              <>
                <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
                  Account
                </p>
                <Link
                  href="/login"
                  className="block rounded px-2 py-1.5 text-sm hover:bg-accent"
                >
                  Sign in
                </Link>
              </>
            )}
          </PopoverContent>
        </Popover>
        <button
          type="button"
          onClick={onExecuteClick}
          className="bg-primary-container text-on-primary-container hover:bg-primary-container/90 inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 font-mono text-xs font-bold uppercase tracking-wider transition-all"
        >
          Execute Task
          <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
      </div>
    </header>
  );
}
