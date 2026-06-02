"use client";

import Link from "next/link";

import { BackgroundShapes } from "@/components/background-shapes";
import { GallerySnapshot } from "@/components/gallery-snapshot";
import { HistoryList } from "@/components/history-list";
import { ResearchForm } from "@/components/research-form";
import { useUser } from "@/hooks/use-user";

export default function Home() {
  const { user, loading } = useUser();
  if (loading) return null;

  if (!user) {
    return (
      <div className="relative flex flex-1 flex-col overflow-hidden">
        <BackgroundShapes />
        <main className="relative z-10 mx-auto flex w-full max-w-3xl flex-grow flex-col px-6 py-16">
          <h1 className="text-foreground font-mono text-3xl tracking-tight md:text-4xl">
            Autonomous Research Assistant
          </h1>
          <p className="text-muted-foreground mt-3">
            Ask anything. ARA plans, researches the web, and synthesizes a cited report — in seconds.
          </p>
          <div className="mt-8">
            <Link
              href="/login"
              className="bg-primary text-primary-foreground inline-flex items-center rounded-md px-5 py-2 font-mono text-sm font-semibold"
            >
              Sign in to get started
            </Link>
          </div>
          <div className="mt-16">
            <GallerySnapshot />
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <BackgroundShapes />
      <main className="relative z-10 mx-auto flex w-full max-w-4xl flex-grow flex-col px-6 py-12 md:py-24">
        <section className="mb-20 w-full space-y-12">
          <div className="space-y-2 text-left">
            <p className="text-primary font-mono text-[0.6875rem] uppercase tracking-[0.2em]">
              ARA
            </p>
            <h1 className="text-foreground text-4xl font-extrabold tracking-tight md:text-5xl">
              Ask a research question.
            </h1>
          </div>
          <ResearchForm />
        </section>
        <HistoryList />
      </main>
    </div>
  );
}
