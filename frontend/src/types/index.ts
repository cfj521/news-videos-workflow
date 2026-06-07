export interface PipelineRun {
  id: number;
  mode: "auto" | "manual";
  video_route: "hyperframes" | "comfyui" | "audio";
  status: "pending" | "processing" | "review" | "done" | "failed";
  current_stage: number | null;
  time_range: string;
  max_articles: number;
  selected_stages: string;
  publish_platforms: string;
  progress_detail: string | null;
  preview_path: string | null;
  output_path: string | null;
  resolution: string | null;
  language: string | null;
  source_ids: string | null;
  aihot_config: string | null;
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

/** 判断信息源是否为 AI HOT 聚合源（与后端 _resolve_collector_type 的判断一致）。 */
export function isAihotSource(s: NewsSource): boolean {
  if (s.config_json) {
    try { if ((JSON.parse(s.config_json) as { provider?: string }).provider === "aihot") return true; } catch { /* ignore */ }
  }
  return s.url.includes("aihot.virxact.com");
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

export const VIDEO_ROUTE_LABELS: Record<string, string> = {
  hyperframes: "Hyperframes",
  comfyui: "ComfyUI",
  audio: "纯语音",
};

export interface PublishTarget {
  id: number;
  name: string;
  platform: "youtube" | "instagram" | "bilibili" | "douyin" | "kuaishou" | "ximalaya" | "xiaoyuzhou" | "netease_music" | "apple_podcasts";
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

// ── 各平台配置字段定义（发布管理表单 + 账号可用性校验共用）──
// required=true 的字段为「必要信息」：全部填齐，该账号才算可用（可在新建任务里选）。
export interface FieldDef {
  key: string;
  label: string;
  required?: boolean;
  secret?: boolean;
  placeholder?: string;
}

export const PLATFORM_FIELDS: Record<string, FieldDef[]> = {
  youtube: [
    { key: "client_id", label: "Client ID", required: true, placeholder: "xxxxx.apps.googleusercontent.com" },
    { key: "client_secret", label: "Client Secret", required: true, secret: true, placeholder: "GOCSPX-..." },
    { key: "refresh_token", label: "Refresh Token", required: true, secret: true },
  ],
  instagram: [
    { key: "user_id", label: "User ID", required: true, placeholder: "Instagram 商业账号 ID" },
    { key: "access_token", label: "Access Token", required: true, secret: true },
    { key: "file_host_url", label: "视频公开 URL", required: true, placeholder: "https://your-cdn.com/video.mp4" },
  ],
  bilibili: [
    { key: "sessdata", label: "SESSDATA（必填）", required: true, secret: true },
    { key: "bili_jct", label: "bili_jct（必填·CSRF）", required: true, secret: true },
    { key: "dede_user_id", label: "DedeUserID（强烈建议·UID）", placeholder: "上传者 UID" },
    { key: "buvid3", label: "buvid3（建议·设备指纹）", secret: true },
    { key: "buvid4", label: "buvid4（建议·新版指纹）", secret: true },
    { key: "ac_time_value", label: "ac_time_value（可选·续期）", secret: true },
    { key: "tid", label: "分区 ID", placeholder: "17 (科技>数码)" },
  ],
  douyin: [
    { key: "method", label: "接入方式", placeholder: "api / playwright" },
    { key: "client_key", label: "Client Key", required: true },
    { key: "client_secret", label: "Client Secret", required: true, secret: true },
    { key: "access_token", label: "Access Token", required: true, secret: true },
  ],
  kuaishou: [
    { key: "method", label: "接入方式", placeholder: "api / playwright" },
    { key: "app_id", label: "App ID", required: true },
    { key: "app_secret", label: "App Secret", required: true, secret: true },
    { key: "access_token", label: "Access Token", required: true, secret: true },
  ],
  ximalaya: [
    { key: "access_token", label: "Access Token", required: true, secret: true },
  ],
  xiaoyuzhou: [
    { key: "cookie", label: "Cookie", required: true, secret: true },
  ],
  netease_music: [
    { key: "cookie", label: "Cookie", required: true, secret: true },
  ],
  apple_podcasts: [
    { key: "rss_url", label: "RSS URL", required: true, placeholder: "https://feeds.example.com/podcast.xml" },
  ],
};

/** 账号必要凭证是否齐全（required 字段全部有非空值）→ 决定账号是否可用。 */
export function isTargetReady(platform: string, configJson: string | null): boolean {
  const fields = PLATFORM_FIELDS[platform];
  if (!fields) return false;
  let cfg: Record<string, unknown> = {};
  try {
    cfg = configJson ? JSON.parse(configJson) : {};
  } catch {
    return false;
  }
  return fields
    .filter((f) => f.required)
    .every((f) => {
      const v = cfg[f.key];
      return typeof v === "string" ? v.trim() !== "" : Boolean(v);
    });
}

export const BACKEND_STAGE_MAP: Record<number, number[]> = {
  1: [1],
  2: [2, 3],
  4: [4],
  5: [5],
  6: [6],
};
