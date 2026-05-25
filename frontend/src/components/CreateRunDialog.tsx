import { useState } from "react";
import { api } from "../api/client";

interface Props {
  onCreated: () => void;
  onClose: () => void;
}

export function CreateRunDialog({ onCreated, onClose }: Props) {
  const [mode, setMode] = useState("manual");
  const [timeRange, setTimeRange] = useState("7d");
  const [maxArticles, setMaxArticles] = useState(5);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await api.runs.create({
        mode,
        video_route: "hyperframes",
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
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-96">
        <h2 className="text-lg font-semibold mb-4">New Pipeline Run</h2>
        <label className="block text-sm text-gray-400 mb-1">Mode</label>
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 mb-3 text-sm"
        >
          <option value="manual">Manual (with review)</option>
          <option value="auto">Auto (no review)</option>
        </select>
        <label className="block text-sm text-gray-400 mb-1">Time Range</label>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 mb-3 text-sm"
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
          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 mb-4 text-sm"
        />
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
