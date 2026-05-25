export interface PipelineRun {
  id: number;
  mode: "auto" | "manual";
  video_route: "hyperframes" | "ltx";
  status: "pending" | "processing" | "review" | "done" | "failed";
  current_stage: number | null;
  time_range: string;
  max_articles: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  created_at: string;
}

export interface NewsSource {
  id: number;
  name: string;
  type: "rss" | "api" | "search" | "scrape";
  url: string;
  category: string;
  language: string;
  priority: number;
  enabled: boolean;
  tier: string;
  config_json: string | null;
  created_at: string;
}

export type StageNumber = 1 | 2 | 3 | 4 | 5 | 6;

export const STAGE_LABELS: Record<StageNumber, string> = {
  1: "获取和处理",
  2: "文案和分镜",
  3: "素材生成",
  4: "校验和调整",
  5: "合成与输出",
  6: "发布",
};
