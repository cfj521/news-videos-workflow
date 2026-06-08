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
  if (freq === "monthly") return d.getDate() >= 29 ? `每月月末 ${time}` : `每月 ${d.getDate()} 号 ${time}`;
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${date} ${time}（单次）`;
}

export type ScheduleTimeParts = {
  onceAt: string;            // datetime-local 串 "YYYY-MM-DDTHH:mm"（仅 once 用）
  tod: string;              // "HH:mm"（daily/weekly/monthly 用）
  weekday: number;          // 0=周一..6=周日（weekly 用）
  monthDay: number | "last"; // 1..28 或 "last"=月末（monthly 用）
};

/** 控件值 → 合法 run_at（naive 本地串）。日期部分对周期任务只是载体（后端只读时/分/周几/号）。 */
export function composeRunAt(freq: ScheduleFreq, p: ScheduleTimeParts): string {
  if (freq === "once") return p.onceAt;
  if (freq === "daily") return `2000-01-01T${p.tod}`;
  if (freq === "weekly") return `2024-01-0${p.weekday + 1}T${p.tod}`;  // 2024-01-01 是周一
  // monthly：12 月有 31 天，可承载 1..31；"last" 用 31 承载，后端据 day>=29 映射为 last
  const dd = p.monthDay === "last" ? "31" : String(p.monthDay).padStart(2, "0");
  return `2024-12-${dd}T${p.tod}`;
}

/** run_at → 控件值（编辑预填）。不相关字段给默认。 */
export function decomposeRunAt(freq: ScheduleFreq, runAt: string): ScheduleTimeParts {
  const base: ScheduleTimeParts = { onceAt: "", tod: "", weekday: 0, monthDay: 1 };
  if (freq === "once") return { ...base, onceAt: runAt.slice(0, 16) };
  const tod = runAt.slice(11, 16);
  if (freq === "daily") return { ...base, tod };
  const d = new Date(runAt);
  if (freq === "weekly") return { ...base, tod, weekday: (d.getDay() + 6) % 7 };
  const day = d.getDate();
  return { ...base, tod, monthDay: day >= 29 ? "last" : day };
}
