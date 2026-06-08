import { useState, useRef, useCallback } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import { btnPrimary, TYPE_CHIP, cardCls, chipCls, sectionTitleCls, toggleCls, toggleThumbCls } from "../styles";
import { AddSourceDialog } from "../components/AddSourceDialog";
import { EditSourceDialog } from "../components/EditSourceDialog";
import { PlusIcon } from "../components/icons";
import { DeleteIconButton } from "../components/DeleteIconButton";
import { type NewsSource, isAihotSource } from "../types";

// ── Sort helpers ────────────────────────────────────────

type SortKey = "name" | "type" | "category" | "language" | "priority";
type SortDir = "asc" | "desc";

function sortSources(sources: NewsSource[], key: SortKey, dir: SortDir): NewsSource[] {
  const sorted = [...sources];
  sorted.sort((a, b) => {
    // Pinned items always on top
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    const av = a[key], bv = b[key];
    if (typeof av === "number" && typeof bv === "number") return dir === "asc" ? av - bv : bv - av;
    return dir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
  });
  return sorted;
}

// ── Drag & drop ─────────────────────────────────────────

function useDragReorder(items: NewsSource[], onReorder: (ids: string[], priorityMap: Record<string, number>) => void) {
  const dragIdx = useRef<number | null>(null);
  const [overIdx, setOverIdx] = useState<number | null>(null);

  const onDragStart = useCallback((idx: number) => { dragIdx.current = idx; }, []);

  const onDragOver = useCallback((e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setOverIdx(idx);
  }, []);

  const onDrop = useCallback((dropIdx: number) => {
    const fromIdx = dragIdx.current;
    dragIdx.current = null;
    setOverIdx(null);
    if (fromIdx === null || fromIdx === dropIdx) return;

    const reordered = [...items];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(dropIdx, 0, moved);

    const priorityMap: Record<string, number> = {};
    reordered.forEach((s, i) => { priorityMap[s.id] = i + 1; });
    onReorder(reordered.map((s) => s.id), priorityMap);
  }, [items, onReorder]);

  const onDragEnd = useCallback(() => { dragIdx.current = null; setOverIdx(null); }, []);

  return { overIdx, onDragStart, onDragOver, onDrop, onDragEnd };
}

// ── Config preview ──────────────────────────────────────

function ConfigPreview({ json }: { json: string | null }) {
  const [expanded, setExpanded] = useState(false);
  if (!json) return <span className="text-white/46 text-xs">--</span>;

  let parsed: unknown;
  try { parsed = JSON.parse(json); } catch { parsed = json; }
  const preview = json.slice(0, 35) + (json.length > 35 ? "..." : "");

  return (
    <div>
      <button
        onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
        className="text-xs text-white/60 hover:text-white/76 flex items-center gap-1.5 transition"
      >
        <svg className={`w-3 h-3 transition-transform ${expanded ? "rotate-90" : ""}`} viewBox="0 0 16 16" fill="currentColor">
          <path d="M6.5 3.5l5 4.5-5 4.5V3.5z" />
        </svg>
        <span className="font-mono">{preview}</span>
      </button>
      {expanded && (
        <pre className={`mt-2 text-xs ${cardCls} p-3 text-white/76 font-mono overflow-x-auto max-w-xs`}>
          {JSON.stringify(parsed, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Sort header ─────────────────────────────────────────

function SortTh({ label, sortKey, currentKey, currentDir, onSort }: {
  label: string; sortKey: SortKey; currentKey: SortKey; currentDir: SortDir; onSort: (k: SortKey) => void;
}) {
  const active = currentKey === sortKey;
  return (
    <th
      className={`text-left px-4 py-3 ${sectionTitleCls} whitespace-nowrap cursor-pointer select-none hover:text-white/85 transition`}
      onClick={() => onSort(sortKey)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {active && (
          <svg className={`w-3 h-3 ${currentDir === "desc" ? "rotate-180" : ""}`} viewBox="0 0 16 16" fill="currentColor">
            <path d="M8 4l4 6H4z" />
          </svg>
        )}
      </span>
    </th>
  );
}

// ── Page ────────────────────────────────────────────────

export function SourcesPage() {
  const { data: sources, mutate } = useSWR<NewsSource[]>("sources", api.sources.list);
  const [showAdd, setShowAdd] = useState(false);
  const [editSource, setEditSource] = useState<NewsSource | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("priority");
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  };

  const sorted = sources ? sortSources(sources, sortKey, sortDir) : [];

  const customSources = sorted.filter((s) => !isAihotSource(s));
  const customIds = (sources ?? []).filter((s) => !isAihotSource(s)).map((s) => s.id);

  const toggleSource = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    const enabling = !source.enabled;
    // 乐观更新缓存：立即翻转该行，不等接口
    mutate((prev) => prev?.map((s) =>
      s.id === source.id ? { ...s, enabled: enabling } : s
    ), { revalidate: false });
    try {
      await api.sources.update(source.id, { enabled: enabling });
    } catch {
      mutate(); // 失败重新拉取纠正
    }
  };

  const deleteSource = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    if (!window.confirm(`确认删除信息源「${source.name}」？此操作不可恢复。`)) return;
    mutate((prev) => prev?.filter((s) => s.id !== source.id), { revalidate: false }); // 乐观移除
    try {
      await api.sources.remove(source.id);
    } catch {
      mutate(); // 失败重拉纠正
    }
  };

  const togglePin = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    if (!source.pinned) {
      const pinnedCount = sources?.filter((s) => s.pinned).length ?? 0;
      if (pinnedCount >= 3) return;
    }
    mutate((prev) => prev?.map((s) => s.id === source.id ? { ...s, pinned: !s.pinned } : s), { revalidate: false });
    try {
      await api.sources.update(source.id, { pinned: !source.pinned });
    } catch {
      mutate();
    }
  };

  // 批量开关所有自定义源
  const allCustomEnabled = customSources.length > 0 && customSources.every((s) => s.enabled);
  const toggleAllCustom = async () => {
    if (!customIds.length) return;
    const enabling = !allCustomEnabled;
    mutate((prev) => prev?.map((s) =>
      isAihotSource(s) ? s : { ...s, enabled: enabling }
    ), { revalidate: false });
    try {
      await api.sources.batch({ ids: customIds, enabled: enabling });
    } catch {
      mutate(); // 失败重新拉取纠正
    }
  };

  const handleReorder = async (ids: string[], priorityMap: Record<string, number>) => {
    await api.sources.batch({ ids, priority_map: priorityMap });
    mutate();
  };

  const { overIdx, onDragStart, onDragOver, onDrop, onDragEnd } = useDragReorder(customSources, handleReorder);

  const pinnedCount = sources?.filter((s) => s.pinned).length ?? 0;

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <h1 className="text-2xl font-bold tracking-tight">信息源管理</h1>
        <button onClick={() => setShowAdd(true)} className={btnPrimary} title="添加信息源" aria-label="添加信息源">
          <PlusIcon />
        </button>
      </div>
      <p className="text-xs text-white/46 mb-5">启用 = 作为新建任务的可选信息源；具体某次任务使用哪些，在「新建任务」窗口里选择。</p>

      <div className={`${cardCls} overflow-hidden`}>
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-white/[0.03]">
              <th className={`w-8 px-2 py-3 ${sectionTitleCls}`} />
              <SortTh label="名称" sortKey="name" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
              <SortTh label="类型" sortKey="type" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
              <SortTh label="分类" sortKey="category" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
              <SortTh label="语言" sortKey="language" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
              <SortTh label="优先级" sortKey="priority" currentKey={sortKey} currentDir={sortDir} onSort={handleSort} />
              <th className={`text-left px-4 py-3 ${sectionTitleCls} whitespace-nowrap`}>配置</th>
              <th className={`px-4 py-3 ${sectionTitleCls} whitespace-nowrap`}>
                <div className="flex items-center justify-end gap-1.5">
                  <button onClick={toggleAllCustom} className={toggleCls(allCustomEnabled)} title="全部启用/禁用">
                    <span className={toggleThumbCls(allCustomEnabled)} />
                  </button>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            {customSources.map((source, idx) => (
              <tr
                key={source.id}
                draggable
                onDragStart={() => onDragStart(idx)}
                onDragOver={(e) => onDragOver(e, idx)}
                onDrop={() => onDrop(idx)}
                onDragEnd={onDragEnd}
                onClick={() => setEditSource(source)}
                className={`border-t border-white/[0.04] hover:bg-white/[0.03] cursor-pointer transition ${
                  overIdx === idx ? "border-t-2 !border-t-blue-500/50" : ""
                } ${source.pinned ? "bg-white/[0.02]" : ""}`}
              >
                <td className="w-8 px-2 py-3 text-center">
                  <button
                    onClick={(e) => togglePin(e, source)}
                    title={source.pinned ? "取消置顶" : pinnedCount >= 3 ? "置顶已满 (最多3条)" : "置顶"}
                    className={`p-1.5 rounded transition ${source.pinned ? "text-amber-400 hover:text-amber-300" : "text-white/42 hover:text-white/60 hover:bg-white/[0.04]"} ${!source.pinned && pinnedCount >= 3 ? "opacity-30 cursor-not-allowed" : ""}`}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <line x1="4" y1="3" x2="20" y2="3" />
                      <line x1="12" y1="21" x2="12" y2="7" />
                      <polyline points="6 13 12 7 18 13" />
                    </svg>
                  </button>
                </td>
                <td className="px-4 py-3">
                  <div>
                    <div className="font-medium text-white/96">{source.name}</div>
                    <div className="text-xs text-white/46 truncate max-w-xs mt-0.5">{source.url}</div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`${chipCls} ${TYPE_CHIP[source.type] ?? "bg-white/[0.06] text-white/66"}`}>
                    {source.type}
                  </span>
                </td>
                <td className="px-4 py-3 text-white/66">{source.category}</td>
                <td className="px-4 py-3 text-white/66">{source.language}</td>
                <td className="px-4 py-3 text-white/66">{source.priority}</td>
                <td className="px-4 py-3"><ConfigPreview json={source.config_json} /></td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-end gap-2.5">
                    <button onClick={(e) => toggleSource(e, source)} className={toggleCls(source.enabled)}>
                      <span className={toggleThumbCls(source.enabled)} />
                    </button>
                    <DeleteIconButton onClick={(e) => deleteSource(e, source)} title="删除信息源" />
                  </div>
                </td>
              </tr>
            ))}
            {customSources.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-16 text-center">
                  <p className="text-white/60 text-sm">暂无信息源</p>
                  <p className="text-white/46 text-xs mt-1">点击上方按钮添加</p>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <AddSourceDialog
          onCreated={() => { setShowAdd(false); mutate(); }}
          onClose={() => setShowAdd(false)}
        />
      )}
      {editSource && (
        <EditSourceDialog
          source={editSource}
          onUpdated={() => { setEditSource(null); mutate(); }}
          onClose={() => setEditSource(null)}
        />
      )}
    </div>
  );
}
