import { useParams } from "react-router-dom";
import useSWR from "swr";
import { api } from "../api/client";
import { StageIndicator } from "../components/StageIndicator";
import { STAGE_LABELS, type PipelineRun, type StageNumber } from "../types";

export function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);
  const { data: run, mutate } = useSWR<PipelineRun>(`run-${runId}`, () =>
    api.runs.get(runId), { refreshInterval: 3000 }
  );

  const handleResume = async () => {
    await api.runs.resume(runId);
    mutate();
  };

  if (!run) return <div className="text-gray-500">Loading...</div>;

  const stages: StageNumber[] = [1, 2, 3, 4, 5, 6];

  return (
    <div className="max-w-4xl">
      <div className="flex items-center gap-4 mb-6">
        <h1 className="text-2xl font-bold">Run #{run.id}</h1>
        <span className="px-3 py-1 rounded-full text-sm bg-gray-800">
          {run.status}
        </span>
      </div>
      <div className="mb-6">
        <StageIndicator currentStage={run.current_stage} status={run.status} />
      </div>
      <div className="grid grid-cols-2 gap-4 mb-6 text-sm">
        {[
          ["Mode", run.mode],
          ["Video Route", run.video_route],
          ["Time Range", run.time_range],
          ["Max Articles", String(run.max_articles)],
        ].map(([label, value]) => (
          <div key={label} className="bg-gray-900 rounded-lg p-4">
            <div className="text-gray-500 mb-1">{label}</div>
            <div>{value}</div>
          </div>
        ))}
      </div>
      {run.status === "review" && (
        <div className="bg-yellow-900/20 border border-yellow-700 rounded-lg p-4 mb-6">
          <div className="flex justify-between items-center">
            <div>
              <h3 className="font-medium text-yellow-300">
                Waiting for Review
              </h3>
              <p className="text-sm text-yellow-400/70 mt-1">
                Stage {run.current_stage}:{" "}
                {run.current_stage
                  ? STAGE_LABELS[run.current_stage as StageNumber]
                  : ""}
              </p>
            </div>
            <button
              onClick={handleResume}
              className="px-4 py-2 bg-yellow-600 hover:bg-yellow-500 rounded text-sm font-medium"
            >
              Approve &amp; Continue
            </button>
          </div>
        </div>
      )}
      {run.error_message && (
        <div className="bg-red-900/20 border border-red-700 rounded-lg p-4 mb-6">
          <h3 className="font-medium text-red-300">Error</h3>
          <p className="text-sm text-red-400 mt-1">{run.error_message}</p>
        </div>
      )}
      <h2 className="text-lg font-semibold mb-3">Stages</h2>
      <div className="space-y-2">
        {stages.map((s) => {
          let stageStatus = "pending";
          if (run.status === "done") stageStatus = "done";
          else if (s === run.current_stage && run.status === "review")
            stageStatus = "review";
          else if (s === run.current_stage && run.status === "processing")
            stageStatus = "processing";
          else if (s < (run.current_stage ?? 0)) stageStatus = "done";

          const statusColors: Record<string, string> = {
            done: "border-green-800 bg-green-900/10",
            processing: "border-blue-800 bg-blue-900/10",
            review: "border-yellow-800 bg-yellow-900/10",
            pending: "border-gray-800",
          };

          return (
            <div
              key={s}
              className={`border rounded-lg p-3 flex justify-between items-center ${statusColors[stageStatus]}`}
            >
              <div className="flex items-center gap-3">
                <span className="text-gray-500 text-sm w-6">S{s}</span>
                <span className="text-sm">{STAGE_LABELS[s]}</span>
              </div>
              <span className="text-xs text-gray-500">{stageStatus}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
