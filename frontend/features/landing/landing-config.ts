/** Landing page constants shared by server and client components (no "use client" here). */

export const LANDING_SECTIONS = [
  { id: "home", label: "Home" },
  { id: "features", label: "Features" },
  { id: "how-it-works", label: "How It Works" },
  { id: "ai", label: "AI" },
  { id: "faq", label: "FAQ" },
] as const;

/** The landing page scrolls inside this element (the root layout keeps <body> fixed). */
export const SCROLLER_ID = "landing-scroll";
