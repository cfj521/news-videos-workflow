import { useState } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import { AddSourceDialog } from "../components/AddSourceDialog";
import { EditSourceDialog } from "../components/EditSourceDialog";
import type { NewsSource } from "../types";

const TYPE_COLORS: Record<string, string> = {
  rss: "bg-green-900 text-green-300",
  api: "bg-blue-900 text-blue-300",
  search: "bg-purple-900 text-purple-300",
  scrape: "bg-orange-900 text-orange-300",
};

function ConfigPreview({ json }: { json: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!json) return <span className="text-gray-600 text-xs">—</span>;

  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    parsed = json;
  }

  const preview = json.slice(0, 40) + (json.length > 40 ? "…" : "");

  return (
    <div>
      <button
        onClick={(e) => {
          e.stopPropagation();
          setExpanded((v) => !v);
        }}
        className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
      >
        <span>{expanded ? "▾" : "▸"}</span>
        <span className="font-mono">{preview}</span>
      </button>
      {expanded && (
        <pre className="mt-1 text-xs bg-gray-800 rounded p-2 text-gray-300 font-mono overflow-x-auto max-w-xs">
          {JSON.stringify(parsed, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function SourcesPage() {
  const { data: sources, mutate } = useSWR<NewsSource[]>(
    "sources",
    api.sources.list
  );
  const [showAdd, setShowAdd] = useState(false);
  const [editSource, setEditSource] = useState<NewsSource | null>(null);

  const toggleSource = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    await api.sources.update(source.id, { enabled: !source.enabled });
    mutate();
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">News Sources</h1>
        <button
          onClick={() => setShowAdd(true)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium"
        >
          + Add Source
        </button>
      </div>

      <div className="border border-gray-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-900">
            <tr>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Name
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Type
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Category
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Lang
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Priority
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Config
              </th>
              <th className="text-left px-4 py-3 text-gray-400 font-medium">
                Enabled
              </th>
            </tr>
          </thead>
          <tbody>
            {sources?.map((source) => (
              <tr
                key={source.id}
                onClick={() => setEditSource(source)}
                className="border-t border-gray-800 hover:bg-gray-900/50 cursor-pointer"
              >
                <td className="px-4 py-3">
                  <div className="font-medium">{source.name}</div>
                  <div className="text-xs text-gray-500 truncate max-w-xs">
                    {source.url}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${TYPE_COLORS[source.type] ?? "bg-gray-800"}`}
                  >
                    {source.type}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{source.category}</td>
                <td className="px-4 py-3 text-gray-400">{source.language}</td>
                <td className="px-4 py-3 text-gray-400">{source.priority}</td>
                <td className="px-4 py-3">
                  <ConfigPreview json={source.config_json} />
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={(e) => toggleSource(e, source)}
                    className={`w-10 h-5 rounded-full relative transition-colors ${source.enabled ? "bg-green-600" : "bg-gray-700"}`}
                  >
                    <span
                      className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${source.enabled ? "left-5" : "left-0.5"}`}
                    />
                  </button>
                </td>
              </tr>
            ))}
            {sources?.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-10 text-center text-gray-500"
                >
                  No sources yet. Add one to get started.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <AddSourceDialog
          onCreated={() => {
            setShowAdd(false);
            mutate();
          }}
          onClose={() => setShowAdd(false)}
        />
      )}

      {editSource && (
        <EditSourceDialog
          source={editSource}
          onUpdated={() => {
            setEditSource(null);
            mutate();
          }}
          onClose={() => setEditSource(null)}
        />
      )}
    </div>
  );
}
