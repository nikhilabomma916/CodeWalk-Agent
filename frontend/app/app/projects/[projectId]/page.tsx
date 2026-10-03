import type { Metadata } from "next";

import { ProjectDetailPage } from "@/features/projects/project-detail-page";

export const metadata: Metadata = { title: "Project" };

export default async function ProjectRoute({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <ProjectDetailPage key={projectId} projectId={projectId} />;
}
