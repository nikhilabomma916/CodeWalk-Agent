import type { Metadata } from "next";

import { UploadsPage } from "@/features/uploads/uploads-page";

export const metadata: Metadata = { title: "Uploads" };

export default function UploadsRoute() {
  return <UploadsPage />;
}
