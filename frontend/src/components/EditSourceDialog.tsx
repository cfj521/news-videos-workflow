import { useState } from "react";
import { api } from "../api/client";
import { inputCls, labelCls, btnPrimary, btnSecondary, btnDanger, dialogOverlayCls, dialogPanelCls, errorTextCls } from "../styles";
import { Select } from "./Select";
import type { NewsSource } from "../types";

interface Props {
  source: NewsSource;
  onUpdated: () => void;
  onClose: () => void;
}

const needsApiKey = (t: string) => t === "search" || t === "api";

function extractApiKey(json: string | null): string {
  if (!json) return "";
  try { return (JSON.parse(json) as Record<string, unknown>).api_key as string ?? ""; } catch { return ""; }
}

export function EditSourceDialog({ source, onUpdated, onClose }: Props) {
  const [name, setName] = useState(source.name);
  const [type, setType] = useState(source.type as string);
  const [url, setUrl] = useState(source.url);
  const [category, setCategory] = useState(source.category);
  const [language, setLanguage] = useState(source.language);
  const [priority, setPriority] = useState(source.priority);
  const [apiKey, setApiKey] = useState(extractApiKey(source.config_json));
  const [configJson, setConfigJson] = useState(source.config_json ?? "");
  const [showAdvanced, setShowAdvanced] = useState(Boolean(source.config_json?.trim()));
  const [loading, setLoading] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [error, setError] = useState("");

  const buildConfigJson = () => {
    let cfg: Record<string, unknown> = {};
    if (configJson.trim()) {
      try { cfg = JSON.parse(configJson); } catch { return configJson; }
    }
    if (apiKey.trim()) cfg.api_key = apiKey.trim();
    else delete cfg.api_key;
    return Object.keys(cfg).length > 0 ? JSON.stringify(cfg) : null;
  };

  const handleSubmit = async () => {
    if (!name.trim() || !url.trim()) { setError("名称和 URL 为必填项"); return; }
    if (configJson.trim()) {
      try { JSON.parse(configJson); } catch { setError("配置 JSON 格式无效"); return; }
    }
    setError("");
    setLoading(true);
    try {
      await api.sources.update(source.id, { name, type: type as "rss" | "api" | "search" | "scrape", url, category, language, priority, config_json: buildConfigJson() });
      onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "更新信息源失败");
    } finally { setLoading(false); }
  };

  const handleDisable = async () => {
    setDisabling(true);
    try { await api.sources.update(source.id, { enabled: false }); onUpdated(); }
    catch (e) { setError(e instanceof Error ? e.message : "禁用信息源失败"); }
    finally { setDisabling(false); setConfirmDisable(false); }
  };

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-1">
          编辑信息源
          <span className="ml-2 text-sm text-white/25 font-normal font-mono">#{source.id}</span>
        </h2>
        {!source.enabled && (
          <span className="text-xs text-white/25 italic">该信息源已禁用</span>
        )}
        <div className="mt-4" />

        <label className={labelCls}>名称</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} className={`${inputCls} mb-4`} />

        <label className={labelCls}>类型</label>
        <Select value={type} onChange={setType} className="mb-4" options={[
          { value: "rss", label: "RSS" },
          { value: "api", label: "API" },
          { value: "search", label: "Search" },
          { value: "scrape", label: "Scrape" },
        ]} />

        <label className={labelCls}>URL</label>
        <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} className={`${inputCls} mb-4`} />

        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className={labelCls}>分类</label>
            <Select value={category} onChange={setCategory} options={[
              { value: "tech", label: "科技" },
              { value: "ai", label: "AI" },
              { value: "general", label: "综合" },
            ]} />
          </div>
          <div>
            <label className={labelCls}>语言</label>
            <Select value={language} onChange={setLanguage} options={[
              { value: "zh", label: "中文 (zh)" },
              { value: "en", label: "English (en)" },
            ]} />
          </div>
        </div>

        <label className={labelCls}>优先级 (1-10)</label>
        <input type="number" value={priority} onChange={(e) => setPriority(Number(e.target.value))} min={1} max={10} className={`${inputCls} mb-4`} />

        {needsApiKey(type) && (
          <>
            <label className={labelCls}>API Key</label>
            <input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="sk-... / tvly-... / BSA..." className={`${inputCls} mb-4 font-mono text-[13px]`} />
          </>
        )}

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-white/30 hover:text-white/50 mb-2 flex items-center gap-1.5 transition"
        >
          <svg className={`w-3 h-3 transition-transform ${showAdvanced ? "rotate-90" : ""}`} viewBox="0 0 16 16" fill="currentColor">
            <path d="M6.5 3.5l5 4.5-5 4.5V3.5z" />
          </svg>
          高级配置 (JSON)
        </button>
        {showAdvanced && (
          <textarea
            value={configJson}
            onChange={(e) => setConfigJson(e.target.value)}
            rows={4}
            placeholder='{"key": "value"}'
            className={`${inputCls} mb-4 font-mono text-xs`}
          />
        )}

        {error && <p className={`${errorTextCls} mb-4`}>{error}</p>}

        <div className="flex justify-between items-center mt-2">
          <div>
            {source.enabled ? (
              confirmDisable ? (
                <div className="flex items-center gap-2">
                  <span className={`text-xs ${errorTextCls}`}>确认禁用此信息源？</span>
                  <button
                    onClick={handleDisable}
                    disabled={disabling}
                    className="px-3 py-1 text-xs rounded-lg bg-red-500/15 text-red-300 hover:bg-red-500/25 transition disabled:opacity-50"
                  >
                    {disabling ? "..." : "确认"}
                  </button>
                  <button onClick={() => setConfirmDisable(false)} className="px-2 py-1 text-xs text-white/30 hover:text-white/50 transition">
                    取消
                  </button>
                </div>
              ) : (
                <button onClick={() => setConfirmDisable(true)} className={btnDanger}>
                  禁用信息源
                </button>
              )
            ) : null}
          </div>
          <div className="flex gap-3">
            <button onClick={onClose} className={btnSecondary}>取消</button>
            <button onClick={handleSubmit} disabled={loading} className={btnPrimary}>
              {loading ? "保存中..." : "保存"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
