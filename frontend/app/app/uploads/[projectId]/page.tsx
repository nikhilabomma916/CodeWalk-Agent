import type { Metadata } from "next";

import { UploadDetailPage } from "@/features/uploads/upload-detail-page";

export const metadata: Metadata = { title: "Upload" };

export default async function UploadRoute({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <UploadDetailPage key={projectId} projectId={projectId} />;
}
