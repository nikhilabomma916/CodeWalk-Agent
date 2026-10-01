import type { Metadata } from "next";
import { Suspense } from "react";

import { HistoryPage } from "@/features/history/history-page";

export const metadata: Metadata = { title: "History" };

export default function HistoryRoute() {
  return (
    <Suspense>
      <HistoryPage />
    </Suspense>
  );
}
