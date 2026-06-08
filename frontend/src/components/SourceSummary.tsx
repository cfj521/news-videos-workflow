import useSWR from "swr";
import { api } from "../api/client";
import type { PipelineRun } from "../types";

const METHOD_LABEL: Record<string, string> = { items: "动态聚合", daily: "每日日报", weekly: "每周周报" };

/**
 * 按本次 run 的实际信息源展示摘要：
 * - 有 aihot_config → AI HOT 模式，展示方法标签
 * - 有 source_ids → 列出对应信息源名称
 * - 都没有 → 默认 Hacker News
 */
export function SourceSummary({ run }: { run: PipelineRun }) {
  const { data: sources } = useSWR("sources", api.sources.list);
  const aihot = run.aihot_config
    ? (() => { try { return JSON.parse(run.aihot_config) as { method?: string }; } catch { return null; } })()
    : null;
  const ids: string[] = run.source_ids
    ? (() => { try { return JSON.parse(run.source_ids) as string[]; } catch { return []; } })()
    : [];
  const names = (sources ?? []).filter((s) => ids.includes(s.id)).map((s) => s.name);

  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 text-xs leading-relaxed">
      <span className="text-white/66">信息源：</span>
      {aihot ? (
        <span className="text-blue-300">AI HOT · {METHOD_LABEL[aihot.method ?? "items"] ?? "动态聚合"}</span>
      ) : names.length > 0 ? (
        <span className="text-white/92">{names.join("、")}</span>
      ) : (
        <span className="text-amber-300/80">默认 Hacker News</span>
      )}
    </div>
  );
}
