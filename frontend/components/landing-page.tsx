import Link from "next/link";
import {
  FileText,
  Eye,
  KeyRound,
  SlidersHorizontal,
  DollarSign,
  LayoutGrid,
  ArrowRight,
} from "lucide-react";

import { PipelineGraph } from "@/components/pipeline-graph";
import { DemoCard } from "@/components/demo-card";
import { demoManifest } from "@/lib/demos";

/* ═══════════════════════════════════════════════════════════
   1. HERO
   ═══════════════════════════════════════════════════════════ */
function Hero() {
  return (
    <section className="flex flex-col items-center gap-10 py-20 text-center md:py-28">
      {/* Eyebrow pill */}
      <div className="inline-flex items-center rounded-full border border-border/50 bg-muted px-3 py-1">
        <span className="font-mono text-[0.6rem] uppercase tracking-widest text-muted-foreground">
          Autonomous Research Assistant
        </span>
      </div>

      {/* Headline */}
      <h1 className="max-w-3xl text-4xl font-extrabold tracking-tight text-foreground md:text-5xl lg:text-6xl">
        From a question to a{" "}
        <span className="bg-gradient-to-r from-primary to-primary-container bg-clip-text text-transparent">
          cited report
        </span>{" "}
        — in minutes.
      </h1>

      {/* Subhead */}
      <p className="max-w-2xl text-lg text-muted-foreground">
        ARA plans your research, runs a team of AI agents across the live web,
        and writes one report where every fact is traceable to its source.
      </p>

      {/* CTAs */}
      <div className="flex flex-col gap-3 sm:flex-row">
        <Link
          href="/login"
          className="from-primary to-primary-container text-primary-foreground inline-flex items-center gap-2 rounded-md bg-gradient-to-r px-7 py-3 font-mono text-sm font-bold shadow-lg shadow-primary/10 transition-opacity hover:opacity-90"
        >
          Get started
          <ArrowRight className="h-4 w-4" strokeWidth={2} />
        </Link>
        <Link
          href="/gallery"
          className="border-border/50 text-foreground hover:bg-muted inline-flex items-center gap-2 rounded-md border bg-transparent px-7 py-3 font-mono text-sm font-semibold transition-colors"
        >
          Watch a live demo
        </Link>
      </div>

      {/* Pipeline diagram */}
      <div className="w-full max-w-4xl">
        <PipelineGraph />
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════
   2. HOW IT WORKS
   ═══════════════════════════════════════════════════════════ */
const STEPS = [
  {
    num: "01",
    title: "Plan",
    body: "ARA breaks your question into a focused set of sub-questions.",
  },
  {
    num: "02",
    title: "Research",
    body: "Parallel agents search the live web, gather facts, and track every source.",
  },
  {
    num: "03",
    title: "Synthesize",
    body: "Findings are composed into one report — every claim annotated with a citation to its source.",
  },
] as const;

function HowItWorks() {
  return (
    <section className="border-border/30 border-y py-20">
      <div className="mb-14 text-center">
        <h2 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          The autonomous workflow
        </h2>
        <p className="text-muted-foreground mt-3">
          Three phases of deep reasoning, orchestrated automatically.
        </p>
      </div>
      <div className="relative flex flex-col gap-10 md:flex-row md:justify-center md:gap-8">
        {/* Connecting line on desktop */}
        <div className="from-border/0 via-border/50 to-border/0 pointer-events-none absolute top-5 hidden h-px w-full bg-gradient-to-r md:block" />
        {STEPS.map((step) => (
          <div key={step.num} className="relative flex flex-col gap-3 md:max-w-[260px]">
            <div className="bg-card border-border/40 flex h-10 w-10 items-center justify-center rounded-md border">
              <span className="text-primary font-mono text-xs font-semibold">
                {step.num}
              </span>
            </div>
            <h3 className="text-foreground text-lg font-semibold">{step.title}</h3>
            <p className="text-muted-foreground text-sm leading-relaxed">{step.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════
   3. FEATURES
   ═══════════════════════════════════════════════════════════ */
const FEATURES = [
  {
    Icon: FileText,
    title: "Cited by source",
    body: "Every claim links to the source it came from, so you can verify each one yourself.",
  },
  {
    Icon: Eye,
    title: "Watch it think",
    body: "Watch each stage stream live — sub-questions planned, the web searched, findings synthesized.",
  },
  {
    Icon: KeyRound,
    title: "Bring your own key",
    body: "Run on your own Anthropic or OpenAI key. You choose the model and control the cost.",
  },
  {
    Icon: SlidersHorizontal,
    title: "Adjustable depth",
    body: "Quick, standard, or deep — control how many sub-questions and research iterations each run uses.",
  },
  {
    Icon: DollarSign,
    title: "Transparent cost",
    body: "A live token and cost meter on every run. You pay your provider directly — ARA takes no cut.",
  },
  {
    Icon: LayoutGrid,
    title: "Free demo gallery",
    body: "Watch real, pre-recorded research runs across several topics — no sign-up needed.",
  },
] as const;

function Features() {
  return (
    <section className="py-20">
      <div className="mb-14 text-center">
        <h2 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          Built for transparency and trust
        </h2>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map(({ Icon, title, body }) => (
          <div
            key={title}
            className="bg-card border-border/40 flex flex-col gap-3 rounded-lg border p-5"
          >
            <div className="bg-primary/10 inline-flex w-fit rounded-md p-2">
              <Icon className="text-primary h-4 w-4" strokeWidth={1.75} />
            </div>
            <h3 className="text-foreground text-sm font-semibold">{title}</h3>
            <p className="text-muted-foreground text-sm leading-relaxed">{body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════
   4. SEE IT IN ACTION (real demos)
   ═══════════════════════════════════════════════════════════ */
function DemoSection() {
  const demos = demoManifest.slice(0, 3);
  return (
    <section className="border-border/30 border-t py-20">
      <div className="mb-10 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <h2 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
          See it in action
        </h2>
        <Link
          href="/gallery"
          className="text-primary font-mono text-sm hover:underline"
        >
          View all samples →
        </Link>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        {demos.map((entry) => (
          <DemoCard key={entry.slug} entry={entry} />
        ))}
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════
   5. CTA BAND
   ═══════════════════════════════════════════════════════════ */
function CtaBand() {
  return (
    <section className="border-border/30 border-t py-20 text-center">
      {/* Powered-by chips */}
      <div className="mb-8 flex items-center justify-center gap-3">
        <span className="text-muted-foreground font-mono text-xs uppercase tracking-widest">
          Powered by
        </span>
        {["Anthropic", "OpenAI"].map((name) => (
          <span
            key={name}
            className="border-border/50 text-muted-foreground font-mono text-xs rounded-md border px-2.5 py-1"
          >
            {name}
          </span>
        ))}
      </div>

      <h2 className="text-3xl font-bold tracking-tight text-foreground md:text-4xl">
        Ask your first research question.
      </h2>
      <p className="text-muted-foreground mx-auto mt-4 max-w-lg text-base">
        Free to explore the demo gallery — bring your own Anthropic or OpenAI
        key to run live research. No credit card.
      </p>
      <div className="mt-8">
        <Link
          href="/login"
          className="from-primary to-primary-container text-primary-foreground inline-flex items-center gap-2 rounded-md bg-gradient-to-r px-8 py-3 font-mono text-sm font-bold shadow-lg shadow-primary/10 transition-opacity hover:opacity-90"
        >
          Get started
          <ArrowRight className="h-4 w-4" strokeWidth={2} />
        </Link>
      </div>
    </section>
  );
}

/* ═══════════════════════════════════════════════════════════
   6. FOOTER (landing-only)
   ═══════════════════════════════════════════════════════════ */
function LandingFooter() {
  return (
    <footer className="border-border/30 border-t py-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Left: wordmark + copyright */}
        <div className="flex flex-col gap-1">
          <span className="font-mono text-sm font-bold text-foreground">ARA</span>
          <span className="text-muted-foreground font-mono text-xs">
            © 2026 ARA — built by LLMTechno.
          </span>
        </div>

        {/* Right: links */}
        <nav className="flex gap-5" aria-label="Footer navigation">
          <a
            href="https://github.com/ShriramJana/autonomous-research-assistant"
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground font-mono text-xs transition-colors"
          >
            GitHub
          </a>
          <Link
            href="/gallery"
            className="text-muted-foreground hover:text-foreground font-mono text-xs transition-colors"
          >
            Gallery
          </Link>
          <Link
            href="/login"
            className="text-muted-foreground hover:text-foreground font-mono text-xs transition-colors"
          >
            Sign in
          </Link>
        </nav>
      </div>
    </footer>
  );
}

/* ═══════════════════════════════════════════════════════════
   Root export
   ═══════════════════════════════════════════════════════════ */
export function LandingPage() {
  return (
    <div className="mx-auto w-full max-w-6xl px-6">
      <Hero />
      <HowItWorks />
      <Features />
      <DemoSection />
      <CtaBand />
      <LandingFooter />
    </div>
  );
}
