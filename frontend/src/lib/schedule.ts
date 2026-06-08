import type { ScheduleFreq } from "../types";

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 把「freq + 锚点 run_at」格式化为人类可读的规则摘要。run_at 为本地 naive ISO 串。 */
export function formatScheduleSummary(freq: ScheduleFreq, runAt: string): string {
  const d = new Date(runAt);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const time = `${hh}:${mm}`;
  if (freq === "daily") return `每天 ${time}`;
  if (freq === "weekly") return `每${WEEKDAYS[d.getDay()]} ${time}`;
  if (freq === "monthly") return `每月 ${d.getDate()} 号 ${time}`;
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${date} ${time}（单次）`;
}
