import { useState } from "react";
import { api } from "../api/client";
import type { NewsSource } from "../types";

interface Props {
  source: NewsSource;
  onUpdated: () => void;
  onClose: () => void;
}

const inputCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";
const selectCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";
const labelCls = "block text-sm text-gray-400 mb-1";

export function EditSourceDialog({ source, onUpdated, onClose }: Props) {
  const [name, setName] = useState(source.name);
  const [type, setType] = useState<"rss" | "api" | "search" | "scrape">(
    source.type
  );
  const [url, setUrl] = useState(source.url);
  const [category, setCategory] = useState(source.category);
  const [language, setLanguage] = useState(source.language);
  const [priority, setPriority] = useState(source.priority);
  const [configJson, setConfigJson] = useState(source.config_json ?? "");
  const [showAdvanced, setShowAdvanced] = useState(
    Boolean(source.config_json?.trim())
  );
  const [loading, setLoading] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!name.trim() || !url.trim()) {
      setError("Name and URL are required.");
      return;
    }
    if (configJson.trim()) {
      try {
        JSON.parse(configJson);
      } catch {
        setError("Config JSON is not valid JSON.");
        return;
      }
    }
    setError("");
    setLoading(true);
    try {
      await api.sources.update(source.id, {
        name,
        type,
        url,
        category,
        language,
        priority,
        config_json: configJson.trim() || null,
      });
      onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update source.");
    } finally {
      setLoading(false);
    }
  };

  const handleDisable = async () => {
    setDisabling(true);
    try {
      await api.sources.update(source.id, { enabled: false });
      onUpdated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disable source.");
    } finally {
      setDisabling(false);
      setConfirmDisable(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-[480px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold mb-4">
          Edit Source
          <span className="ml-2 text-sm text-gray-500 font-normal">
            #{source.id}
          </span>
        </h2>

        <label className={labelCls}>Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={`${inputCls} mb-3`}
        />

        <label className={labelCls}>Type</label>
        <select
          value={type}
          onChange={(e) => setType(e.target.value as typeof type)}
          className={`${selectCls} mb-3`}
        >
          <option value="rss">RSS</option>
          <option value="api">API</option>
          <option value="search">Search</option>
          <option value="scrape">Scrape</option>
        </select>

        <label className={labelCls}>URL</label>
        <input
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className={`${inputCls} mb-3`}
        />

        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className={labelCls}>Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className={selectCls}
            >
              <option value="tech">Tech</option>
              <option value="ai">AI</option>
              <option value="general">General</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className={selectCls}
            >
              <option value="zh">Chinese (zh)</option>
              <option value="en">English (en)</option>
            </select>
          </div>
        </div>

        <label className={labelCls}>Priority (1–10)</label>
        <input
          type="number"
          value={priority}
          onChange={(e) => setPriority(Number(e.target.value))}
          min={1}
          max={10}
          className={`${inputCls} mb-3`}
        />

        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-gray-500 hover:text-gray-300 mb-2 flex items-center gap-1"
        >
          <span>{showAdvanced ? "▾" : "▸"}</span>
          Advanced Config (JSON)
        </button>
        {showAdvanced && (
          <textarea
            value={configJson}
            onChange={(e) => setConfigJson(e.target.value)}
            rows={4}
            placeholder='{"key": "value"}'
            className={`${inputCls} mb-3 font-mono text-xs`}
          />
        )}

        {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

        <div className="flex justify-between items-center mt-2">
          {/* Disable / Delete section */}
          <div>
            {source.enabled ? (
              confirmDisable ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs text-red-400">Disable this source?</span>
                  <button
                    onClick={handleDisable}
                    disabled={disabling}
                    className="px-3 py-1 text-xs bg-red-700 hover:bg-red-600 rounded disabled:opacity-50"
                  >
                    {disabling ? "Disabling..." : "Confirm"}
                  </button>
                  <button
                    onClick={() => setConfirmDisable(false)}
                    className="px-3 py-1 text-xs text-gray-400 hover:text-white"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => setConfirmDisable(true)}
                  className="px-3 py-1 text-xs bg-red-900/60 border border-red-700 text-red-400 hover:bg-red-800 rounded"
                >
                  Disable Source
                </button>
              )
            ) : (
              <span className="text-xs text-gray-500 italic">
                Source is disabled
              </span>
            )}
          </div>

          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-400 hover:text-white"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 rounded font-medium disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
