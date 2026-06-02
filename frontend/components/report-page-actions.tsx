"use client";

import { useEffect, useState } from "react";

import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { useUser } from "@/hooks/use-user";
import { ResearchLive } from "@/components/research-live";

interface ReportDetail {
  id: string;
  status: "running" | "completed" | "error";
  is_sample: boolean;
}

export function ReportPageActions({
  reportId,
  shareToken,
}: {
  reportId: string;
  shareToken?: string;
}) {
  const { user } = useUser();
  const isAdmin =
    typeof process !== "undefined" &&
    user?.id === process.env.NEXT_PUBLIC_ADMIN_USER_ID;
  const [report, setReport] = useState<ReportDetail | null>(null);
  const [replayMode, setReplayMode] = useState(false);

  useEffect(() => {
    const q = shareToken ? `?t=${shareToken}` : "";
    apiGet<ReportDetail>(`/api/reports/${reportId}${q}`)
      .then(setReport)
      .catch(() => setReport(null));
  }, [reportId, shareToken]);

  async function togglePromote() {
    if (!report) return;
    if (report.is_sample) {
      await apiDelete(`/api/reports/${reportId}/promote`);
    } else {
      await apiPost(`/api/reports/${reportId}/promote`, {});
    }
    setReport({ ...report, is_sample: !report.is_sample });
  }

  if (replayMode) {
    const url = `/api/reports/${reportId}/replay${shareToken ? `?t=${shareToken}` : ""}`;
    return <ResearchLive streamUrl={url} />;
  }

  return (
    <>
      <ResearchLive reportId={reportId} shareToken={shareToken} />
      {report && (
        <div className="mx-auto flex max-w-4xl gap-3 px-6 pb-12">
          {report.is_sample && (
            <button
              type="button"
              onClick={() => setReplayMode(true)}
              className="bg-primary text-primary-foreground inline-flex items-center gap-2 rounded-md px-4 py-2 font-mono text-sm"
            >
              ▶ Replay how this report was built
            </button>
          )}
          {isAdmin && report.status === "completed" && (
            <button
              type="button"
              onClick={() => void togglePromote()}
              className="bg-card hover:bg-accent rounded-md px-4 py-2 font-mono text-xs uppercase tracking-wider"
            >
              {report.is_sample ? "Remove from gallery" : "Promote to gallery"}
            </button>
          )}
        </div>
      )}
    </>
  );
}
