import useSWR from "swr";
import { api } from "../api/client";
import { isAihotSource } from "../types";

/**
 * 当前启用信息源的只读摘要，口径与后端采集一致：
 * 有启用的 AI HOT 源即只用 AI HOT（互斥），否则列出自定义源，都没有则回退默认 Hacker News。
 */
export function SourceSummary() {
  const { data: sources } = useSWR("sources", api.sources.list);
  const enabled = (sources ?? []).filter((s) => s.enabled);
  const aihot = enabled.find(isAihotSource);
  const method = (() => {
    if (!aihot) return "";
    try { return (JSON.parse(aihot.config_json ?? "{}") as { method?: string }).method ?? "items"; }
    catch { return "items"; }
  })();
  const customNames = enabled.filter((s) => !isAihotSource(s)).map((s) => s.name);

  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 text-xs leading-relaxed">
      <span className="text-white/40">信息源：</span>
      {sources === undefined ? (
        <span className="text-white/30">加载中…</span>
      ) : aihot ? (
        <span className="text-blue-300">{aihot.name} · {method === "daily" ? "每日日报" : "动态聚合"}</span>
      ) : customNames.length > 0 ? (
        <span className="text-white/70">{customNames.join("、")}</span>
      ) : (
        <span className="text-amber-300/80">未启用任何信息源，将使用默认 Hacker News</span>
      )}
    </div>
  );
}
