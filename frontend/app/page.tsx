import type { Metadata } from "next";

import { LandingPage } from "@/features/landing/landing-page";

export const metadata: Metadata = {
  title: { absolute: "CodeWalk Agent — Your Codebase. Understood by AI." },
  description:
    "An AI-powered coding environment for understanding, analyzing, debugging, and improving software projects.",
};

export default function HomePage() {
  return <LandingPage />;
}
