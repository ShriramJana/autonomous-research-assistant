import { BackgroundShapes } from "@/components/background-shapes";
import { HistoryList } from "@/components/history-list";
import { ResearchForm } from "@/components/research-form";

export default function Home() {
  return (
    <div className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden p-6">
      <BackgroundShapes />
      <div className="relative z-10 mx-auto flex w-full max-w-2xl flex-col gap-10 py-12">
        <section className="flex flex-col gap-2">
          <p className="text-muted-foreground font-mono text-xs uppercase tracking-wider">
            Autonomous Research Assistant
          </p>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Ask a research question.
          </h1>
          <p className="text-muted-foreground text-sm">
            A planner decomposes your question into sub-queries, researchers run them
            in parallel with live web search, and a synthesizer streams a cited report
            back in real time.
          </p>
        </section>
        <ResearchForm />
        <HistoryList />
      </div>
    </div>
  );
}
