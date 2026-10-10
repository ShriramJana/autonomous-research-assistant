import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy policy | ARA",
  description: "What ARA stores, who processes it, and how to delete it.",
};

const LAST_UPDATED = "October 10, 2026";
const CONTACT_EMAIL = "shriram.j.iyengar@gmail.com";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-mono text-base tracking-tight text-foreground">{title}</h2>
      <div className="text-muted-foreground space-y-3 text-sm leading-relaxed">{children}</div>
    </section>
  );
}

export default function PrivacyPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <h1 className="font-mono text-2xl tracking-tight">Privacy policy</h1>
      <p className="text-muted-foreground mt-2 font-mono text-xs">Last updated {LAST_UPDATED}</p>

      <p className="text-muted-foreground mt-6 text-sm leading-relaxed">
        ARA (Autonomous Research Assistant) is a portfolio project operated by LLMTechno. This page
        explains, in plain terms, what the hosted version at ara.llmtechno.com stores, which services
        process it, and how you can delete it. If you run ARA on your own machine in local mode, nothing
        described here leaves your computer.
      </p>

      <div className="mt-10 space-y-10">
        <Section title="What we collect">
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <span className="text-foreground">Account details.</span> When you sign in with Google or
              a magic link we receive your email address and, from Google, your name and profile
              picture. We use these only to identify your account.
            </li>
            <li>
              <span className="text-foreground">Research data.</span> The questions you submit, the
              generated research plan, the findings and sources gathered for each sub-question, the
              final report, the stream of progress events, an estimated cost, and timestamps.
            </li>
            <li>
              <span className="text-foreground">API keys you choose to save.</span> Provider keys you
              enter in Settings (Anthropic, OpenAI-compatible, Tavily) are encrypted before they are
              stored and are never displayed back to you. They are used only to run your reports.
            </li>
            <li>
              <span className="text-foreground">Technical logs.</span> Our hosting providers keep standard
              request logs (IP address, browser user agent, time of request) for a limited period.
            </li>
          </ul>
          <p>
            We do not run advertising, analytics trackers, or fingerprinting. We do not sell or rent any
            of this data.
          </p>
        </Section>

        <Section title="How we use it">
          <p>
            To run your research reports, show them in your History, enforce fair-use limits on the free
            tier, and diagnose problems when something breaks. That is the full list.
          </p>
        </Section>

        <Section title="Services that process your data">
          <p>Running a report involves these third parties, each only for the purpose listed:</p>
          <ul className="list-disc space-y-2 pl-5">
            <li>
              <span className="text-foreground">Supabase</span> hosts the sign-in system and the database
              where accounts, reports, and encrypted keys are stored.
            </li>
            <li>
              <span className="text-foreground">Vercel</span> serves the web interface.{" "}
              <span className="text-foreground">Google Cloud Run</span> runs the backend.
            </li>
            <li>
              <span className="text-foreground">Google</span> handles sign-in when you choose
              &ldquo;Continue with Google&rdquo;. We request only your basic profile (email, name,
              picture) and never access your Gmail, Drive, or other Google data.
            </li>
            <li>
              <span className="text-foreground">The model provider you configure</span> (Anthropic,
              OpenAI, or an OpenAI-compatible endpoint) receives your question and the sub-questions and
              search results derived from it, under your own API key and that provider&rsquo;s terms.
            </li>
            <li>
              <span className="text-foreground">Tavily</span> receives the web-search queries the
              researchers generate, when web browsing is enabled for a run.
            </li>
          </ul>
        </Section>

        <Section title="Who can see your reports">
          <p>
            Your reports are private to your account. They become visible to others only if you create a
            share link, in which case anyone holding that link can read that one report until you revoke
            it. The sample reports in the gallery were published deliberately by the operator.
          </p>
          <p>
            The operator administers the database and could technically access stored data, including
            your questions and reports. In practice that access is used only to operate, debug, and secure
            the service. Nobody reads your reports as a matter of course. Saved API keys are encrypted at
            rest with a key held on the server, and the application never returns them, even to you.
          </p>
        </Section>

        <Section title="Cookies">
          <p>
            Signing in sets session cookies from Supabase Auth so you stay logged in between visits. There
            are no advertising or tracking cookies.
          </p>
        </Section>

        <Section title="Retention and deletion">
          <ul className="list-disc space-y-2 pl-5">
            <li>Reports stay until you delete them from your History page.</li>
            <li>Saved API keys can be removed at any time from Settings.</li>
            <li>
              To delete your account and everything attached to it, email{" "}
              <a href={`mailto:${CONTACT_EMAIL}`} className="text-foreground underline underline-offset-4">
                {CONTACT_EMAIL}
              </a>{" "}
              from the address you signed in with. Deleting the account removes your reports and keys.
            </li>
          </ul>
        </Section>

        <Section title="Changes">
          <p>
            If this policy changes, the date at the top is updated. Material changes will be noted on the
            home page.
          </p>
        </Section>

        <Section title="Contact">
          <p>
            Questions about this policy or your data:{" "}
            <a href={`mailto:${CONTACT_EMAIL}`} className="text-foreground underline underline-offset-4">
              {CONTACT_EMAIL}
            </a>
            . The source code is public on{" "}
            <a
              href="https://github.com/ShriramJana/autonomous-research-assistant"
              target="_blank"
              rel="noreferrer"
              className="text-foreground underline underline-offset-4"
            >
              GitHub
            </a>
            .
          </p>
        </Section>
      </div>

      <p className="mt-12">
        <Link href="/" className="text-muted-foreground hover:text-foreground font-mono text-xs">
          ← Back to ARA
        </Link>
      </p>
    </main>
  );
}
