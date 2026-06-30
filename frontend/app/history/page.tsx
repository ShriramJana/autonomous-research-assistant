"use client";

import Link from "next/link";

import { HistoryList } from "@/components/history-list";
import { useUser } from "@/hooks/use-user";

export default function HistoryPage() {
  const { user, loading } = useUser();

  if (loading) return null;

  if (!user) {
    return (
      <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 py-12 md:py-16">
        <p className="text-muted-foreground text-sm">
          Please{" "}
          <Link href="/login?next=/history" className="text-primary underline">
            sign in
          </Link>{" "}
          to view your research history.
        </p>
      </main>
    );
  }

  return (
    <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 py-12 md:py-16">
      <header className="mb-8 flex flex-col gap-2">
        <p className="text-primary font-mono text-[0.6875rem] uppercase tracking-[0.2em]">
          History
        </p>
        <p className="text-muted-foreground text-sm">
          Every report you&apos;ve run, newest first.
        </p>
      </header>
      <HistoryList emptyHint />
    </main>
  );
}
