import type { Metadata } from "next";
import { Suspense } from "react";

import { CodingPage } from "@/features/workspace/coding-page";

export const metadata: Metadata = { title: "Coding" };

export default function CodingRoute() {
  return (
    <Suspense>
      <CodingPage />
    </Suspense>
  );
}
