import { ReportPageActions } from "@/components/report-page-actions";

export default async function ReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ reportId: string }>;
  searchParams: Promise<{ t?: string }>;
}) {
  const { reportId } = await params;
  const { t } = await searchParams;
  return <ReportPageActions reportId={reportId} shareToken={t} />;
}
