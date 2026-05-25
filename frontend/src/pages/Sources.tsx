import useSWR from "swr";
import { api } from "../api/client";
import type { NewsSource } from "../types";

const TYPE_COLORS: Record<string, string> = {
  rss: "bg-green-900 text-green-300",
  api: "bg-blue-900 text-blue-300",
  search: "bg-purple-900 text-purple-300",
  scrape: "bg-orange-900 text-orange-300",
};

export function SourcesPage() {
  const { data: sources, mutate } = useSWR<NewsSource[]>(
    "sources",
    api.sources.list
  );

  const toggleSource = async (source: NewsSource) => {
    await api.sources.update(source.id, { enabled: !source.enabled });
    mutate();
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">News Sources</h1>
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
                Enabled
              </th>
            </tr>
          </thead>
          <tbody>
            {sources?.map((source) => (
              <tr
                key={source.id}
                className="border-t border-gray-800 hover:bg-gray-900/50"
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
                  <button
                    onClick={() => toggleSource(source)}
                    className={`w-10 h-5 rounded-full relative transition-colors ${source.enabled ? "bg-green-600" : "bg-gray-700"}`}
                  >
                    <span
                      className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${source.enabled ? "left-5" : "left-0.5"}`}
                    />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
