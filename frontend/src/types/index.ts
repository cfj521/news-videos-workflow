export interface PipelineRun {
  id: number;
  mode: "auto" | "manual";
  video_route: "hyperframes" | "ltx" | "audio";
  status: "pending" | "processing" | "review" | "done" | "failed";
  current_stage: number | null;
  time_range: string;
  max_articles: number;
  selected_stages: string;
  publish_platforms: string;
  progress_detail: string | null;
  preview_path: string | null;
  output_path: string | null;
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
  pinned: boolean;
  tier: string;
  config_json: string | null;
  created_at: string;
}

export type StageNumber = 1 | 2 | 3 | 4 | 5 | 6;

export const STAGE_LABELS: Record<number, string> = {
  1: "搜索整理",
  2: "脚本/图片生成",
  3: "素材生成",
  4: "预览",
  5: "合成渲染",
  6: "发布",
};

export const VISIBLE_STAGES = [1, 2, 4, 5, 6] as const;

export interface PublishTarget {
  id: number;
  name: string;
  platform: "youtube" | "instagram" | "bilibili" | "douyin" | "kuaishou";
  enabled: boolean;
  config_json: string | null;
  created_at: string;
}

export const PLATFORM_LABELS: Record<string, string> = {
  youtube: "YouTube",
  instagram: "Instagram Reels",
  bilibili: "Bilibili",
  douyin: "抖音",
  kuaishou: "快手",
  ximalaya: "喜马拉雅",
  xiaoyuzhou: "小宇宙",
  netease_music: "网易云音乐",
  apple_podcasts: "Apple Podcasts",
};

export type MediaType = "video" | "audio" | "both";

export const PLATFORM_MEDIA: Record<string, MediaType> = {
  youtube: "video",
  instagram: "video",
  bilibili: "both",
  douyin: "video",
  kuaishou: "video",
  ximalaya: "audio",
  xiaoyuzhou: "audio",
  netease_music: "audio",
  apple_podcasts: "audio",
};

export const BACKEND_STAGE_MAP: Record<number, number[]> = {
  1: [1],
  2: [2, 3],
  4: [4],
  5: [5],
  6: [6],
};
