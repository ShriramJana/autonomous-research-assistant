"use client";

import { BackgroundShapes } from "@/components/background-shapes";
import { HistoryList } from "@/components/history-list";
import { LandingPage } from "@/components/landing-page";
import { ResearchForm } from "@/components/research-form";
import { useUser } from "@/hooks/use-user";

export default function Home() {
  const { user, loading } = useUser();
  if (loading) return null;

  if (!user) {
    return <LandingPage />;
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
