import type { NewsSource, PipelineRun, PublishTarget, Schedule, RunCreatePayload } from "../types";

const BASE = "/api";
const TOKEN_KEY = "nv_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

/** 登录失效时触发，由 App 监听以回到登录页。 */
export function onUnauthorized(handler: () => void) {
  window.addEventListener("nv-unauthorized", handler);
  return () => window.removeEventListener("nv-unauthorized", handler);
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken();
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: authHeaders(init?.headers),
  });
  if (res.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("nv-unauthorized"));
    throw new Error("未登录或登录已失效");
  }
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    throw new Error(`API error: ${res.status} ${detail ?? res.statusText}`);
  }
  return res.json();
}

export interface ProviderModels { text: string[]; image: string[]; vision: string[]; tts: string[] }
export interface ProviderCreds { base_url: string; api_key: string; max_output_tokens: number; models: ProviderModels; auth_mode?: string }

export interface OpenAIAuthStatus {
  logged_in: boolean;
  email?: string;
  plan?: string;
  expires_at?: string;
}

export interface ScoringCandidate {
  title: string;
  source: string;
  final: number;
  llm: number | null;
  source_w: number;
  recency: number;
  keyword: number;
  rule: number;
  reason: string;
  tags: string[];
  llm_ran: boolean;
  selected: boolean;
}

export interface ScoringData {
  pool?: number;
  n?: number;
  k?: number;
  min_score?: number;
  source_type?: string;
  candidates: ScoringCandidate[];
}

export interface AppSettings {
  // 供应商参数库：各供应商的连接凭证；当前用哪个由 pipeline 选型决定
  providers: Record<string, ProviderCreds>;
  collectors: { tavily_key: string; brave_key: string; serper_key: string };
  pipeline: {
    default_time_range: string; default_max_articles: number; default_video_route: string;
    default_language: string; dedup_lookback: string; resolution: string; max_images: number;
    summary_provider: string; summary_model: string; summary_max_length: number;
    script_provider: string; script_model: string;
    image_provider: string; image_model: string;
    vision_provider: string; vision_model: string;
    tts_provider: string; tts_model: string; tts_voice: string;
    video_model: string; video_fps: number;
  };
  storage: { work_dir: string; output_dir: string };
  hyperframes: { fps: string; scene_gap_ms: number; transition: string; subtitle_font_size: number; subtitle_max_lines: number; subtitle_bottom_px: number };
  comfyui: { server_url: string; default_negative: string; wake: { enabled: boolean; mac: string; broadcast: string; port: number; ready_timeout: number; poll_interval: number }; image_params: Record<string, { steps: number; cfg: number }>; video_params: Record<string, { steps: number; cfg: number }> };
  overlay: {
    enabled: boolean;
    font_file: string;
    font_size_ratio: number;
    color: string;
    bg_opacity: number;
    margin_ratio: number;
  };
  // 生效预设镜像（后端按 prompt_presets[active] 注入；前端只读不直接编辑）
  prompts: Record<string, string>;
  // 提示词预设库（存 prompts.yaml）：active 选中下标 + 固定 5 个预设
  prompt_presets: { active: number; presets: { name: string; values: Record<string, string> }[] };
}

export interface ScriptData {
  title: string;
  description: string;
  tags: string[];
  groups?: { id: number; title: string; source_index: number }[];
  scenes: { id: number; group_id?: number; group_title?: string; narration: string; image_prompt: string; motion_prompt?: string; duration_hint?: number }[];
}

export interface TimelineData {
  entries: { scene_id: number; start_ms: number; end_ms: number; image_path: string; audio_path: string; audio_duration_ms: number; subtitle_text: string }[];
  total_duration_ms: number;
}

export interface ArticleData {
  title: string;
  url: string;
  aggregator_url?: string;
  source: string;
  content?: string;
  summary?: string;
  score_final?: number;
  score_reason?: string;
}

export interface PublishResultRec {
  platform: string;
  status: string;
  url?: string | null;
  error_message?: string | null;
  target_name?: string | null;
}

export const api = {
  runs: {
    list: () => fetchJSON<PipelineRun[]>("/pipeline/runs"),
    get: (id: number) => fetchJSON<PipelineRun>(`/pipeline/runs/${id}`),
    create: (body: {
      mode?: string;
      video_route?: string;
      time_range?: string;
      max_articles?: number;
      selected_stages?: number[];
      publish_platforms?: string[];
      auto_collect?: boolean;
      resolution?: string;
      language?: string;
      max_images?: number;
      source_ids?: string[];
      aihot_config?: { method: string; category?: string; report_date?: string; week_start?: string };
    }) =>
      fetchJSON<PipelineRun>("/pipeline/runs", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: { resolution?: string }) =>
      fetchJSON<PipelineRun>(`/pipeline/runs/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    resume: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}/resume`, {
        method: "POST",
      }),
    stop: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}/stop`, {
        method: "POST",
      }),
    remove: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}`, {
        method: "DELETE",
      }),
    ttsPreview: async (body: { provider: string; model: string; voice: string }): Promise<Blob> => {
      const res = await fetch(`${BASE}/pipeline/tts/preview`, {
        method: "POST", headers: authHeaders(), body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail;
        throw new Error(detail ?? `试听失败: ${res.status}`);
      }
      return res.blob();
    },
    logs: (id: number) => fetchJSON<{ lines: string[] }>(`/pipeline/runs/${id}/logs`),
    script: (id: number) => fetchJSON<ScriptData>(`/pipeline/runs/${id}/script`),
    timeline: (id: number) => fetchJSON<TimelineData>(`/pipeline/runs/${id}/timeline`),
    articles: (id: number) => fetchJSON<ArticleData[]>(`/pipeline/runs/${id}/articles`),
    scoring: (id: number) => fetchJSON<ScoringData>(`/pipeline/runs/${id}/scoring`),
    regenAudio: (runId: number, sceneId: number, narration: string) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/scenes/${sceneId}/audio`, {
        method: "POST",
        body: JSON.stringify({ narration }),
      }),
    regenImage: (runId: number, sceneId: number, imagePrompt: string, size?: string) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/scenes/${sceneId}/image`, {
        method: "POST",
        body: JSON.stringify({ image_prompt: imagePrompt, ...(size ? { size } : {}) }),
      }),
    regenScript: (runId: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/regen-script`, {
        method: "POST",
      }),
    addScene: (runId: number, groupId: number, requirement: string) =>
      fetchJSON(`/pipeline/runs/${runId}/scenes`, { method: "POST", body: JSON.stringify({ group_id: groupId, requirement }) }),
    deleteScene: (runId: number, sceneId: number) =>
      fetchJSON(`/pipeline/runs/${runId}/scenes/${sceneId}`, { method: "DELETE" }),
    regenPrompt: (runId: number, sceneId: number, narration: string) =>
      fetchJSON<{ status: string; image_prompt: string }>(`/pipeline/runs/${runId}/scenes/${sceneId}/regen-prompt`, {
        method: "POST",
        body: JSON.stringify({ narration }),
      }),
    rerollArticles: (runId: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/reroll-articles`, {
        method: "POST",
      }),
    saveArticles: (runId: number, items: unknown[]) =>
      fetchJSON(`/pipeline/runs/${runId}/articles`, { method: "PUT", body: JSON.stringify(items) }),
    importArticleUrl: (runId: number, url: string) =>
      fetchJSON(`/pipeline/runs/${runId}/articles/import/url`, { method: "POST", body: JSON.stringify({ url }) }),
    importArticleFile: async (runId: number, file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const token = getToken();
      const res = await fetch(`/api/pipeline/runs/${runId}/articles/import/file`, {
        method: "POST",
        body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        const detail = (await res.json().catch(() => ({}))).detail;
        throw new Error(`API error: ${res.status} ${detail ?? res.statusText}`);
      }
      return res.json();
    },
    triggerRender: (runId: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/render`, {
        method: "POST",
      }),
    triggerPublish: (runId: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${runId}/publish`, {
        method: "POST",
      }),
    publishResults: (runId: number) =>
      fetchJSON<PublishResultRec[]>(`/pipeline/runs/${runId}/publish-results`),
    assetUrl: (runId: number, filename: string) => `${BASE}/pipeline/runs/${runId}/assets/${filename}`,
    eventsUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/events`,
    previewHtmlUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/preview-html`,
    videoUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/video`,
    subtitlesUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/subtitles`,
    subtitlesVttUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/subtitles.vtt`,
  },
  sources: {
    list: () => fetchJSON<NewsSource[]>("/sources/"),
    aihotWeeks: () => fetchJSON<{ week_start: string; week_end: string; days: number }[]>("/sources/aihot/weeks"),
    aihotDays: () => fetchJSON<{ date: string }[]>("/sources/aihot/days"),
    create: (body: Partial<NewsSource>) =>
      fetchJSON<NewsSource>("/sources/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: string, body: Partial<NewsSource>) =>
      fetchJSON<NewsSource>(`/sources/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    batch: (body: { ids: string[]; enabled?: boolean; pinned?: boolean; priority_map?: Record<string, number> }) =>
      fetchJSON<NewsSource[]>("/sources/batch", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      fetchJSON<void>(`/sources/${id}`, { method: "DELETE" }),
  },
  publishers: {
    list: () => fetchJSON<PublishTarget[]>("/publishers/"),
    create: (body: Partial<PublishTarget>) =>
      fetchJSON<PublishTarget>("/publishers/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: string, body: Partial<PublishTarget>) =>
      fetchJSON<PublishTarget>(`/publishers/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    remove: (id: string) =>
      fetchJSON<{ status: string }>(`/publishers/${id}`, { method: "DELETE" }),
    /** 启动扫码登录流程（按 平台 + 账号内部标识），返回会话 ID。保存前即可调用。 */
    loginStart: (platform: string, account: string) =>
      fetchJSON<{ sid: string }>("/publishers/login/start", {
        method: "POST",
        body: JSON.stringify({ platform, account }),
      }),
    /** 轮询登录状态 */
    loginPoll: (sid: string) =>
      fetchJSON<{ status: string; qr_base64?: string; error?: string }>(
        `/publishers/login/status?sid=${encodeURIComponent(sid)}`
      ),
    /** 查询账号当前登录状态 */
    loginStatus: (slug: string) =>
      fetchJSON<{ logged_in: boolean; detail?: string }>(`/publishers/${slug}/login-status`),
  },
  settings: {
    get: () => fetchJSON<AppSettings>("/settings/"),
    save: (body: Partial<AppSettings>) =>
      fetchJSON<AppSettings>("/settings/", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    promptDefaults: () => fetchJSON<Record<string, { label: string; desc: string; default: string; default_en: string }>>("/settings/prompts/defaults"),
    comfyuiHealth: (url: string) =>
      fetchJSON<{ ok: boolean; url: string; detail?: string; error?: string }>(`/settings/comfyui/health?url=${encodeURIComponent(url)}`),
  },
  schedules: {
    list: () => fetchJSON<Schedule[]>("/schedules/"),
    create: (body: { name: string; freq: string; run_at: string; payload: RunCreatePayload }) =>
      fetchJSON<Schedule>("/schedules/", { method: "POST", body: JSON.stringify(body) }),
    toggle: (slug: string, enabled: boolean) =>
      fetchJSON<Schedule>(`/schedules/${slug}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    update: (slug: string, body: { name?: string; freq?: string; run_at?: string; payload?: RunCreatePayload }) =>
      fetchJSON<Schedule>(`/schedules/${slug}`, { method: "PATCH", body: JSON.stringify(body) }),
    remove: (slug: string) =>
      fetchJSON<{ status: string }>(`/schedules/${slug}`, { method: "DELETE" }),
    runNow: (slug: string) =>
      fetchJSON<{ status: string }>(`/schedules/${slug}/run-now`, { method: "POST" }),
  },
  auth: {
    login: (username: string, password: string) =>
      fetchJSON<{ token: string; username: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    me: () => fetchJSON<{ username: string }>("/auth/me"),
    changePassword: (oldPassword: string, newPassword: string) =>
      fetchJSON<{ status: string }>("/auth/password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
      }),
    users: () => fetchJSON<AuthUser[]>("/auth/users"),
    createUser: (username: string, password: string) =>
      fetchJSON<AuthUser>("/auth/users", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      }),
    resetPassword: (id: number, newPassword: string) =>
      fetchJSON<{ status: string }>(`/auth/users/${id}/password`, {
        method: "POST",
        body: JSON.stringify({ new_password: newPassword }),
      }),
    deleteUser: (id: number) =>
      fetchJSON<{ status: string }>(`/auth/users/${id}`, { method: "DELETE" }),
    openaiLoginStart: () =>
      fetchJSON<{ authorize_url: string; state: string }>("/auth/openai/login/start", { method: "POST" }),
    openaiLoginStatus: (state: string) =>
      fetchJSON<{ status: "pending" | "success" | "error"; error?: string }>(`/auth/openai/login/status?state=${encodeURIComponent(state)}`),
    openaiStatus: () =>
      fetchJSON<OpenAIAuthStatus>("/auth/openai/status"),
    openaiLogout: () =>
      fetchJSON<{ status: string }>("/auth/openai/logout", { method: "POST" }),
  },
};

export interface AuthUser {
  id: number;
  username: string;
  created_at: string;
}
