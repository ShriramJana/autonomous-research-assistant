"use client";

import { Bell, CircleUser, Wallet, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/#history", label: "History" },
  { href: "/#settings", label: "Settings" },
] as const;

export function TopNav() {
  const pathname = usePathname();
  const isDashboard = pathname === "/";

  return (
    <header className="bg-background sticky top-0 z-50 flex h-14 w-full items-center justify-between border-b border-white/[0.06] px-6 print:hidden">
      <div className="flex items-center gap-8">
        <Link
          href="/"
          className="text-primary font-mono text-xl font-bold tracking-tighter transition-opacity hover:opacity-80"
        >
          ARA
        </Link>
        <nav className="hidden gap-6 md:flex">
          {NAV_LINKS.map((link) => {
            const active = link.href === "/" ? isDashboard : false;
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
        <div className="hidden items-center gap-3 md:flex">
          <button
            type="button"
            aria-label="Cost overview"
            title="Cost overview"
            className="text-muted-foreground hover:text-primary/80 transition-colors"
          >
            <Wallet className="h-5 w-5" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            aria-label="Notifications"
            title="Notifications"
            className="text-muted-foreground hover:text-primary/80 transition-colors"
          >
            <Bell className="h-5 w-5" strokeWidth={1.5} />
          </button>
          <button
            type="button"
            aria-label="Account"
            title="Account"
            className="text-muted-foreground hover:text-primary/80 transition-colors"
          >
            <CircleUser className="h-5 w-5" strokeWidth={1.5} />
          </button>
        </div>
        <Link
          href="/"
          className="bg-primary-container text-on-primary-container hover:bg-primary-container/90 inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 font-mono text-xs font-bold uppercase tracking-wider transition-all"
        >
          Execute Task
          <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
        </Link>
      </div>
    </header>
  );
}
