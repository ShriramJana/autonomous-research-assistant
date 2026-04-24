"use client";

import { CircleUser, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

const NAV_LINKS = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  {
    href: "/#history",
    label: "History",
    match: () => false,
  },
  {
    href: "/settings",
    label: "Settings",
    match: (p: string) => p === "/settings",
  },
] as const;

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
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
            <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
              Account
            </p>
            <button
              type="button"
              disabled
              className="text-muted-foreground/60 flex w-full cursor-not-allowed items-center justify-between rounded px-2 py-1.5 text-left text-sm"
            >
              <span>Sign in</span>
              <span className="font-mono text-[10px] uppercase tracking-wider">
                Soon
              </span>
            </button>
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
