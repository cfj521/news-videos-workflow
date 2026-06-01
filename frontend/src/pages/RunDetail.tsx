import { useParams } from "react-router-dom";
import useSWR from "swr";
import { api } from "../api/client";
import { STATUS_CHIP, cardCls, chipCls, sectionTitleCls, errorTextCls, btnPrimary, btnApprove } from "../styles";
import { StageIndicator } from "../components/StageIndicator";
import { STAGE_LABELS, VIDEO_ROUTE_LABELS, type PipelineRun, type StageNumber } from "../types";

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  review: "审核中",
  done: "完成",
  failed: "失败",
  skipped: "跳过",
};

export function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);
  const { data: run, mutate } = useSWR<PipelineRun>(`run-${runId}`, () =>
    api.runs.get(runId), { refreshInterval: 2000 },
  );

  const handleResume = async () => { await api.runs.resume(runId); mutate(); };

  if (!run) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-5 h-5 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
      </div>
    );
  }

  const stages: StageNumber[] = [1, 2, 3, 4, 5, 6];
  const selected: number[] = (() => { try { return JSON.parse(run.selected_stages); } catch { return []; } })();

  const stageStatusOf = (s: StageNumber) => {
    if (!selected.includes(s)) return "skipped";
    if (run.status === "done") return "done";
    if (s === run.current_stage && run.status === "review") return "review";
    if (s === run.current_stage && run.status === "processing") return "processing";
    if (s < (run.current_stage ?? 0)) return "done";
    if (run.status === "failed" && s === run.current_stage) return "failed";
    return "pending";
  };

  const stageStyle: Record<string, string> = {
    done: "border-emerald-500/20 bg-emerald-500/[0.04]",
    processing: "border-blue-500/20 bg-blue-500/[0.04]",
    review: "border-amber-500/20 bg-amber-500/[0.04]",
    failed: "border-red-500/20 bg-red-500/[0.04]",
    pending: "border-white/[0.06] bg-white/[0.02]",
    skipped: "border-white/[0.04] bg-transparent opacity-40",
  };

  const stageDot: Record<string, string> = {
    done: "bg-emerald-400",
    processing: "bg-blue-400 animate-pulse-soft",
    review: "bg-amber-400",
    failed: "bg-red-400",
    pending: "bg-white/[0.15]",
    skipped: "bg-white/[0.08]",
  };

  return (
    <div className="max-w-4xl">
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-bold tracking-tight">任务 #{run.id}</h1>
        <span className={`${chipCls} ${STATUS_CHIP[run.status] ?? ""}`}>{STATUS_LABEL[run.status] ?? run.status}</span>
      </div>

      <div className="mb-8">
        <StageIndicator currentStage={run.current_stage} status={run.status} />
      </div>

      {/* Progress detail */}
      {run.progress_detail && (
        <div className={`${cardCls} p-4 mb-6`}>
          <div className="text-sm text-white/70">{run.progress_detail}</div>
        </div>
      )}

      {/* Meta cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-8">
        {([
          ["运行模式", run.mode],
          ["音视频路线", VIDEO_ROUTE_LABELS[run.video_route] ?? run.video_route],
          ["时间范围", run.time_range],
          ["最大文章数", String(run.max_articles)],
        ] as const).map(([label, value]) => (
          <div key={label} className={`${cardCls} p-4`}>
            <div className={sectionTitleCls}>{label}</div>
            <div className="text-sm font-medium mt-1">{value}</div>
          </div>
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 mb-6">
        {run.status === "review" && (
          <button onClick={handleResume} className={btnApprove}>
            审核通过并继续
          </button>
        )}
        {run.preview_path && (
          <a href={`/api/pipeline/runs/${run.id}/preview`} target="_blank" rel="noreferrer" className={`${btnPrimary} inline-block no-underline`}>
            预览
          </a>
        )}
        {run.output_path && (
          <a href={`/api/pipeline/runs/${run.id}/video`} target="_blank" rel="noreferrer" className={`${btnPrimary} inline-block no-underline`}>
            下载视频
          </a>
        )}
      </div>

      {/* Error banner */}
      {run.error_message && (
        <div className="rounded-xl bg-red-500/[0.06] border border-red-500/20 p-5 mb-6">
          <h3 className="text-sm font-medium text-red-300">错误</h3>
          <p className={`text-xs mt-1 ${errorTextCls} opacity-70`}>{run.error_message}</p>
        </div>
      )}

      {/* Stage list */}
      <h2 className={`${sectionTitleCls} mb-3`}>执行阶段</h2>
      <div className="space-y-2">
        {stages.map((s) => {
          const ss = stageStatusOf(s);
          return (
            <div
              key={s}
              className={`border rounded-xl px-4 py-3 flex justify-between items-center transition ${stageStyle[ss]}`}
            >
              <div className="flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full ${stageDot[ss]}`} />
                <span className="text-xs text-white/25 font-mono w-6">S{s}</span>
                <span className="text-sm">{STAGE_LABELS[s]}</span>
              </div>
              <span className="text-xs text-white/30">{STATUS_LABEL[ss] ?? ss}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
