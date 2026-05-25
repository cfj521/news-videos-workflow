import { Link } from "react-router-dom";
import type { PipelineRun } from "../types";
import { StageIndicator } from "./StageIndicator";

const STATUS_COLORS: Record<string, string> = {
  pending: "text-gray-400",
  processing: "text-blue-400",
  review: "text-yellow-400",
  done: "text-green-400",
  failed: "text-red-400",
};

export function RunCard({ run }: { run: PipelineRun }) {
  return (
    <Link
      to={`/runs/${run.id}`}
      className="block border border-gray-800 rounded-lg p-4 hover:border-gray-600 transition-colors"
    >
      <div className="flex justify-between items-start mb-3">
        <div>
          <span className="text-sm text-gray-500">#{run.id}</span>
          <span
            className={`ml-2 text-sm font-medium ${STATUS_COLORS[run.status] ?? ""}`}
          >
            {run.status}
          </span>
        </div>
        <span className="text-xs text-gray-500">
          {new Date(run.created_at).toLocaleString("zh-CN")}
        </span>
      </div>
      <StageIndicator currentStage={run.current_stage} status={run.status} />
      <div className="mt-3 flex gap-3 text-xs text-gray-500">
        <span>{run.mode}</span>
        <span>{run.video_route}</span>
        <span>{run.time_range}</span>
        <span>{run.max_articles} articles</span>
      </div>
      {run.error_message && (
        <p className="mt-2 text-xs text-red-400 truncate">{run.error_message}</p>
      )}
    </Link>
  );
}
