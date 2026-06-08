import type { RunCreatePayload } from "../types";
import { VISIBLE_STAGES } from "../types";

/** toBackendStages 的逆映射：后端阶段 → 可视阶段集合。
 *  后端 2/3 折回可视 2；其余落在 VISIBLE_STAGES 的原样保留。 */
export function backendStagesToVisual(backend: number[]): Set<number> {
  const visible = new Set<number>(VISIBLE_STAGES);
  const out = new Set<number>();
  for (const s of backend) {
    const v = s === 2 || s === 3 ? 2 : s;
    if (visible.has(v)) out.add(v);
  }
  return out;
}

export interface DialogInit {
  videoRoute: string;
  timeRange: string;
  maxArticles: number;
  autoCollect: boolean;
  resolution: string;
  language: string;
  maxImages: number | null;
  selectedVisual: Set<number>;
  targetIds: Set<string> | null;
  sourceMode: "aihot" | "custom";
  aihotCfg: { method: string; category?: string; report_date?: string; week_start?: string };
  sourceIds: Set<string> | null;
}

/** 把存储的 payload 反填为弹窗初始 state；缺省字段回退到与新建一致的默认。 */
export function payloadToDialogState(p: RunCreatePayload): DialogInit {
  const aihot = !!p.aihot_config;
  return {
    videoRoute: p.video_route ?? "hyperframes",
    timeRange: p.time_range ?? "7d",
    maxArticles: p.max_articles ?? 5,
    autoCollect: p.auto_collect ?? true,
    resolution: p.resolution ?? "",
    language: p.language ?? "",
    maxImages: p.max_images ?? null,
    selectedVisual: p.selected_stages ? backendStagesToVisual(p.selected_stages) : new Set([1, 2, 4, 5, 6]),
    targetIds: p.publish_platforms ? new Set(p.publish_platforms) : null,
    sourceMode: aihot ? "aihot" : "custom",
    aihotCfg: aihot ? p.aihot_config! : { method: "items" },
    sourceIds: aihot ? null : new Set(p.source_ids ?? []),
  };
}
