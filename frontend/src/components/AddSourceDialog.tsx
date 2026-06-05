import { useState } from "react";
import { api } from "../api/client";
import { inputCls, labelCls, btnPrimary, btnSecondary, dialogOverlayCls, dialogPanelCls, errorTextCls } from "../styles";
import { Select } from "./Select";
import { PasswordInput } from "./PasswordInput";

interface Props {
  onCreated: () => void;
  onClose: () => void;
}

const needsApiKey = (t: string) => t === "search" || t === "api";

export function AddSourceDialog({ onCreated, onClose }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState("rss");
  const [url, setUrl] = useState("");
  const [category, setCategory] = useState("general");
  const [language, setLanguage] = useState("zh");
  const [priority, setPriority] = useState(5);
  const [apiKey, setApiKey] = useState("");
  const [configJson, setConfigJson] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const buildConfigJson = () => {
    let cfg: Record<string, unknown> = {};
    if (configJson.trim()) {
      try { cfg = JSON.parse(configJson); } catch { return configJson; }
    }
    if (apiKey.trim()) cfg.api_key = apiKey.trim();
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
      await api.sources.create({ name, type: type as "rss" | "api" | "search" | "scrape", url, category, language, priority, enabled: true, tier: "standard", config_json: buildConfigJson() });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建信息源失败");
    } finally { setLoading(false); }
  };

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-5">添加信息源</h2>

        <label className={labelCls}>名称</label>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 TechCrunch RSS" className={`${inputCls} mb-4`} />

        <label className={labelCls}>类型</label>
        <Select value={type} onChange={setType} className="mb-4" options={[
          { value: "rss", label: "RSS" },
          { value: "api", label: "API" },
          { value: "search", label: "Search" },
          { value: "scrape", label: "Scrape" },
        ]} />

        <label className={labelCls}>URL</label>
        <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." className={`${inputCls} mb-4`} />

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
            <div className="mb-4">
              <PasswordInput value={apiKey} onChange={setApiKey} placeholder="sk-... / tvly-... / BSA..." className={`${inputCls} font-mono text-[13px]`} />
            </div>
          </>
        )}

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-white/60 hover:text-white/76 mb-2 flex items-center gap-1.5 transition"
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

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className={btnSecondary}>取消</button>
          <button onClick={handleSubmit} disabled={loading} className={btnPrimary}>
            {loading ? "添加中..." : "添加信息源"}
          </button>
        </div>
      </div>
    </div>
  );
}
