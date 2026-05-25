import type { NewsSource, PipelineRun } from "../types";

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

export const api = {
  runs: {
    list: () => fetchJSON<PipelineRun[]>("/pipeline/runs"),
    get: (id: number) => fetchJSON<PipelineRun>(`/pipeline/runs/${id}`),
    create: (body: {
      mode?: string;
      video_route?: string;
      time_range?: string;
      max_articles?: number;
    }) =>
      fetchJSON<PipelineRun>("/pipeline/runs", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    resume: (id: number) =>
      fetchJSON<{ status: string }>(`/pipeline/runs/${id}/resume`, {
        method: "POST",
      }),
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
  },
};
