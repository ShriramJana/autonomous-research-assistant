import { ResearchLive } from "@/components/research-live";

export default async function ReportPage({
  params,
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  return <ResearchLive reportId={reportId} />;
}
