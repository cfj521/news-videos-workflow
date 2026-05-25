import { useState } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import type { NewsSource } from "../types";

interface Props {
  onCreated: () => void;
  onClose: () => void;
}

const selectCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";
const inputCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";

export function CreateRunDialog({ onCreated, onClose }: Props) {
  const [mode, setMode] = useState("manual");
  const [timeRange, setTimeRange] = useState("7d");
  const [maxArticles, setMaxArticles] = useState(5);
  const [videoRoute, setVideoRoute] = useState<"hyperframes" | "ltx">(
    "hyperframes"
  );
  const [language, setLanguage] = useState<"zh" | "en">("zh");
  const [loading, setLoading] = useState(false);

  const { data: sources } = useSWR<NewsSource[]>("sources", api.sources.list);
  const enabledSources = sources?.filter((s) => s.enabled) ?? [];

  // Default: all enabled sources selected
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<number>>(
    () => new Set(enabledSources.map((s) => s.id))
  );

  // Sync selections when sources load
  const [syncedOnce, setSyncedOnce] = useState(false);
  if (enabledSources.length > 0 && !syncedOnce) {
    setSelectedSourceIds(new Set(enabledSources.map((s) => s.id)));
    setSyncedOnce(true);
  }

  const toggleSource = (id: number) => {
    setSelectedSourceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedSourceIds.size === enabledSources.length) {
      setSelectedSourceIds(new Set());
    } else {
      setSelectedSourceIds(new Set(enabledSources.map((s) => s.id)));
    }
  };

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await api.runs.create({
        mode,
        video_route: videoRoute,
        time_range: timeRange,
        max_articles: maxArticles,
      });
      onCreated();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-[460px] max-h-[90vh] overflow-y-auto">
        <h2 className="text-lg font-semibold mb-4">New Pipeline Run</h2>

        <label className="block text-sm text-gray-400 mb-1">Mode</label>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className={`${selectCls} mb-3`}
        >
          <option value="manual">Manual (with review)</option>
          <option value="auto">Auto (no review)</option>
        </select>

        <label className="block text-sm text-gray-400 mb-1">Video Route</label>
        <select
          value={videoRoute}
          onChange={(e) =>
            setVideoRoute(e.target.value as "hyperframes" | "ltx")
          }
          className={`${selectCls} mb-3`}
        >
          <option value="hyperframes">Hyperframes (MVP)</option>
          <option value="ltx">LTX 2.3</option>
        </select>

        <label className="block text-sm text-gray-400 mb-1">Language</label>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as "zh" | "en")}
          className={`${selectCls} mb-3`}
        >
          <option value="zh">Chinese (zh)</option>
          <option value="en">English (en)</option>
        </select>

        <label className="block text-sm text-gray-400 mb-1">Time Range</label>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value)}
          className={`${selectCls} mb-3`}
        >
          <option value="1d">Last 1 day</option>
          <option value="3d">Last 3 days</option>
          <option value="7d">Last 7 days</option>
          <option value="15d">Last 15 days</option>
          <option value="1m">Last month</option>
        </select>

        <label className="block text-sm text-gray-400 mb-1">Max Articles</label>
        <input
          type="number"
          value={maxArticles}
          onChange={(e) => setMaxArticles(Number(e.target.value))}
          min={1}
          max={20}
          className={`${inputCls} mb-3`}
        />

        {/* Source selection */}
        <div className="mb-4">
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm text-gray-400">Sources</label>
            {enabledSources.length > 0 && (
              <button
                type="button"
                onClick={toggleAll}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                {selectedSourceIds.size === enabledSources.length
                  ? "Deselect all"
                  : "Select all"}
              </button>
            )}
          </div>
          {enabledSources.length === 0 ? (
            <p className="text-xs text-gray-500 italic">
              No enabled sources. Add some in the Sources page.
            </p>
          ) : (
            <div className="border border-gray-700 rounded max-h-36 overflow-y-auto">
              {enabledSources.map((source) => (
                <label
                  key={source.id}
                  className="flex items-center gap-3 px-3 py-2 hover:bg-gray-800 cursor-pointer border-b border-gray-800 last:border-0"
                >
                  <input
                    type="checkbox"
                    checked={selectedSourceIds.has(source.id)}
                    onChange={() => toggleSource(source.id)}
                    className="w-4 h-4 rounded accent-blue-500"
                  />
                  <span className="text-sm text-gray-200 flex-1">
                    {source.name}
                  </span>
                  <span className="text-xs text-gray-500">{source.type}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="flex gap-3 justify-end">
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
            {loading ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
