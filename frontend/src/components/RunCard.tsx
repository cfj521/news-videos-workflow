import { Link } from "react-router-dom";
import type { PipelineRun } from "../types";
import { STATUS_CHIP, cardCls, chipCls } from "../styles";
import { StageIndicator } from "./StageIndicator";

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  review: "审核中",
  done: "完成",
  failed: "失败",
};

export function RunCard({ run }: { run: PipelineRun }) {
  const stageCount = (() => { try { return JSON.parse(run.selected_stages).length; } catch { return 0; } })();

  return (
    <Link
      to={`/runs/${run.id}`}
      className={`group block ${cardCls} p-5 transition hover:bg-white/[0.05] hover:border-white/[0.1]`}
    >
      <div className="flex justify-between items-start mb-4">
        <div className="flex items-center gap-2.5">
          <span className="text-sm text-white/30 font-mono">#{run.id}</span>
          <span className={`${chipCls} ${STATUS_CHIP[run.status] ?? ""}`}>{STATUS_LABEL[run.status] ?? run.status}</span>
        </div>
        <span className="text-xs text-white/25">
          {new Date(run.created_at).toLocaleString("zh-CN")}
        </span>
      </div>
      <StageIndicator currentStage={run.current_stage} status={run.status} />
      {run.progress_detail && (
        <p className="mt-3 text-xs text-white/40">{run.progress_detail}</p>
      )}
      <div className="mt-3 flex gap-2 flex-wrap text-xs text-white/30">
        <span className="px-2 py-0.5 rounded bg-white/[0.04]">{run.mode}</span>
        <span className="px-2 py-0.5 rounded bg-white/[0.04]">{run.video_route}</span>
        <span className="px-2 py-0.5 rounded bg-white/[0.04]">{run.time_range}</span>
        <span className="px-2 py-0.5 rounded bg-white/[0.04]">{stageCount} 个阶段</span>
      </div>
      {run.error_message && (
        <p className="mt-3 text-xs text-red-400 truncate">{run.error_message}</p>
      )}
    </Link>
  );
}
