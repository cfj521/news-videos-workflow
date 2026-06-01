import type { NewsSource, PipelineRun, PublishTarget } from "../types";

const BASE = "/api";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface AppSettings {
  text: { provider: string; base_url: string; model: string; api_key: string };
  image: { provider: string; base_url: string; model: string; api_key: string };
  vision: { provider: string; base_url: string; model: string; api_key: string };
  tts: { provider: string; base_url: string; api_key: string; model: string; voice: string; speed: number };
  summary: { enabled: boolean; provider: string; base_url: string; model: string; api_key: string; max_length: number };
  collectors: { tavily_key: string; brave_key: string; serper_key: string };
  youtube: { client_id: string; client_secret: string };
  pipeline: { default_time_range: string; default_max_articles: number; default_video_route: string; default_language: string; dedup_lookback: string };
  storage: { work_dir: string; output_dir: string };
  video: { resolution: string; aspect_ratio: string; fps: string; scene_gap_ms: number; transition: string };
  ltx: { model_dir: string; checkpoint: string; upsampler: string; distilled_lora: string; lora_strength: number; gemma_dir: string; inference_steps: number; cfg_scale: number; stg_scale: number; fps: number; use_fp8: boolean };
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
      aspect_ratio?: string;
    }) =>
      fetchJSON<PipelineRun>("/pipeline/runs", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    resume: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}/resume`, {
        method: "POST",
      }),
    remove: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}`, {
        method: "DELETE",
      }),
    logs: (id: number) => fetchJSON<{ lines: string[] }>(`/pipeline/runs/${id}/logs`),
    script: (id: number) => fetchJSON<ScriptData>(`/pipeline/runs/${id}/script`),
    timeline: (id: number) => fetchJSON<TimelineData>(`/pipeline/runs/${id}/timeline`),
    articles: (id: number) => fetchJSON<ArticleData[]>(`/pipeline/runs/${id}/articles`),
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
      const res = await fetch(`/api/pipeline/runs/${runId}/articles/import/file`, { method: "POST", body: fd });
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
    assetUrl: (runId: number, filename: string) => `${BASE}/pipeline/runs/${runId}/assets/${filename}`,
    previewHtmlUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/preview-html`,
    videoUrl: (runId: number) => `${BASE}/pipeline/runs/${runId}/video`,
  },
  sources: {
    list: () => fetchJSON<NewsSource[]>("/sources/"),
    create: (body: Partial<NewsSource>) =>
      fetchJSON<NewsSource>("/sources/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: Partial<NewsSource>) =>
      fetchJSON<NewsSource>(`/sources/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    batch: (body: { ids: number[]; enabled?: boolean; pinned?: boolean; priority_map?: Record<number, number> }) =>
      fetchJSON<NewsSource[]>("/sources/batch", {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },
  publishers: {
    list: () => fetchJSON<PublishTarget[]>("/publishers/"),
    create: (body: Partial<PublishTarget>) =>
      fetchJSON<PublishTarget>("/publishers/", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: number, body: Partial<PublishTarget>) =>
      fetchJSON<PublishTarget>(`/publishers/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    remove: (id: number) =>
      fetchJSON<{ status: string }>(`/publishers/${id}`, { method: "DELETE" }),
  },
  settings: {
    get: () => fetchJSON<AppSettings>("/settings/"),
    save: (body: Partial<AppSettings>) =>
      fetchJSON<AppSettings>("/settings/", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },
};
