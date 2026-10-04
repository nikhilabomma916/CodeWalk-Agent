import { SCROLLER_ID } from "./landing-config";
import { LandingNav } from "./landing-nav";
import styles from "./landing.module.css";
import {
  Architecture,
  AskSection,
  ContextFlow,
  Faq,
  Features,
  FinalCta,
  Footer,
  Hero,
  HowItWorks,
  HumanControl,
  ProblemSection,
  ProjectIntelligence,
  WorkspaceShowcase,
} from "./sections";

/**
 * The public landing page at "/". A presentation of the product: every preview is static markup in the
 * app's own design tokens (both themes), and every call to action leads into the real application.
 */
export function LandingPage() {
  return (
    // The root layout keeps <body> fixed (the workspace is a full-height app), so the page scrolls here.
    <div
      id={SCROLLER_ID}
      className={`h-dvh overflow-x-hidden overflow-y-auto bg-app text-fg ${styles.scroller}`}
    >
      <a
        href="#main"
        className="sr-only z-50 rounded bg-surface px-3 py-2 text-sm text-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <LandingNav />
      <main id="main">
        <Hero />
        <ProblemSection />
        <ContextFlow />
        <Features />
        <HowItWorks />
        <ProjectIntelligence />
        <HumanControl />
        <AskSection />
        <WorkspaceShowcase />
        <Architecture />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </div>
  );
}
