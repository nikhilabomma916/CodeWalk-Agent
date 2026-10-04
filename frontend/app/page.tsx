import type { Metadata } from "next";

import { LandingPage } from "@/features/landing/landing-page";

const TITLE = "CodeWalk Agent — Your Codebase. Understood by AI.";
const DESCRIPTION =
  "An AI-powered coding environment for understanding, analyzing, debugging, and improving software projects.";

export const metadata: Metadata = {
  title: { absolute: TITLE },
  description: DESCRIPTION,
  openGraph: {
    type: "website",
    siteName: "CodeWalk Agent",
    title: TITLE,
    description: DESCRIPTION,
  },
  twitter: { card: "summary", title: TITLE, description: DESCRIPTION },
};

export default function HomePage() {
  return <LandingPage />;
}
