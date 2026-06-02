import { ResearchLive } from "@/components/research-live";

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ reportId: string }>;
  searchParams: Promise<{ t?: string }>;
}) {
  const { reportId } = await params;
  const { t } = await searchParams;
  return <ResearchLive reportId={reportId} shareToken={t} />;
}
