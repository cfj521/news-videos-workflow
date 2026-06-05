import { useState, useRef, useCallback, useEffect } from "react";
import useSWR, { type KeyedMutator } from "swr";
import { api } from "../api/client";
import { btnPrimary, TYPE_CHIP, cardCls, chipCls, sectionTitleCls, toggleCls, toggleThumbCls, segItem } from "../styles";
import { AddSourceDialog } from "../components/AddSourceDialog";
import { EditSourceDialog } from "../components/EditSourceDialog";
import { Select } from "../components/Select";
import { type NewsSource, isAihotSource } from "../types";

// ── Sort helpers ────────────────────────────────────────

type SortKey = "name" | "type" | "category" | "language" | "priority";
type SortDir = "asc" | "desc";

// ── AI HOT helpers ──────────────────────────────────────

function parseConfig(json: string | null): Record<string, unknown> {
  if (!json) return {};
  try { return JSON.parse(json) as Record<string, unknown>; } catch { return {}; }
}

const AIHOT_CATEGORIES = [
  { value: "", label: "全部分类" },
  { value: "ai-models", label: "模型" },
  { value: "ai-products", label: "产品" },
  { value: "industry", label: "行业" },
  { value: "paper", label: "论文" },
  { value: "tip", label: "技巧" },
];

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

function useDragReorder(items: NewsSource[], onReorder: (ids: number[], priorityMap: Record<number, number>) => void) {
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

    const priorityMap: Record<number, number> = {};
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

// ── AI HOT Group Card ────────────────────────────────────

function AIHotGroupCard({ source, customIds, mutate }: {
  source: NewsSource;
  customIds: number[];
  mutate: KeyedMutator<NewsSource[]>;
}) {
  // 配置（method/category/week）本地乐观：只写自己，不影响其它行，不必动列表缓存
  const [cfg, setCfgState] = useState<Record<string, unknown>>(() => parseConfig(source.config_json));
  useEffect(() => { setCfgState(parseConfig(source.config_json)); }, [source.config_json]);
  const method = (cfg.method as string) ?? "items";
  const category = (cfg.category as string) ?? "";
  const weekStart = (cfg.week_start as string) ?? "";
  const { data: weeks } = useSWR(method === "weekly" ? "aihot-weeks" : null, api.sources.aihotWeeks);

  const setConfig = async (patch: Record<string, unknown>) => {
    const next = { ...cfg, ...patch };
    setCfgState(next); // 立即反馈；只写这一个配置，不重新拉取整张列表
    try {
      await api.sources.update(source.id, { config_json: JSON.stringify(next) });
    } catch {
      setCfgState(parseConfig(source.config_json)); // 失败回滚
    }
  };

  // AI HOT 与自定义组互斥：开 AI HOT → 关全部自定义；关 AI HOT → 开全部自定义（始终二选一）
  const toggleGroup = async () => {
    const next = !source.enabled;
    mutate((prev) => prev?.map((s) =>
      isAihotSource(s) ? { ...s, enabled: next } : { ...s, enabled: !next }
    ), { revalidate: false });
    try {
      if (customIds.length) await api.sources.batch({ ids: customIds, enabled: !next });
      await api.sources.update(source.id, { enabled: next });
    } catch {
      mutate(); // 失败重拉纠正
    }
  };

  return (
    <div className={`${cardCls} p-5 mb-4`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold">AI HOT 聚合</h2>
          <p className="text-xs text-white/60 mt-0.5">聚合精选 AI 资讯 · 启用后与自定义源互斥</p>
        </div>
        <button onClick={toggleGroup} className={toggleCls(source.enabled)}>
          <span className={toggleThumbCls(source.enabled)} />
        </button>
      </div>
      <div className="flex items-center gap-2 mb-3">
        {(["items", "daily", "weekly"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setConfig({ method: m })}
            className={`${segItem(method === m)} !px-5 !py-2.5 !text-sm`}
          >
            {m === "items" ? "动态" : m === "daily" ? "日报" : "周报"}
          </button>
        ))}
        {method === "items" && (
          <div className="w-48 ml-3">
            <Select value={category} onChange={(v) => setConfig({ category: v })} options={AIHOT_CATEGORIES} />
          </div>
        )}
        {method === "weekly" && (
          <div className="w-72 ml-3">
            <Select
              value={weekStart}
              onChange={(v) => setConfig({ week_start: v })}
              options={[
                { value: "", label: "自动（最近有数据的周）" },
                ...(weeks ?? []).map((w) => ({
                  value: w.week_start,
                  label: `${w.week_start.slice(5).replace("-", "/")}~${w.week_end.slice(5).replace("-", "/")}（${w.days}天）`,
                })),
              ]}
            />
          </div>
        )}
      </div>
    </div>
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

  const aihotSource = sources?.find(isAihotSource);
  const customSources = sorted.filter((s) => !isAihotSource(s));
  const customIds = (sources ?? []).filter((s) => !isAihotSource(s)).map((s) => s.id);

  const toggleSource = async (e: React.MouseEvent, source: NewsSource) => {
    e.stopPropagation();
    const enabling = !source.enabled;
    // 乐观更新缓存：立即翻转该行（启用自定义源时联动关 AI HOT），不等接口
    mutate((prev) => prev?.map((s) =>
      s.id === source.id ? { ...s, enabled: enabling }
      : (enabling && aihotSource && s.id === aihotSource.id) ? { ...s, enabled: false }
      : s), { revalidate: false });
    try {
      await api.sources.update(source.id, { enabled: enabling });
      if (enabling && aihotSource?.enabled) {
        await api.sources.update(aihotSource.id, { enabled: false });
      }
    } catch {
      mutate(); // 失败重新拉取纠正
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

  // 批量开关仅控制其他组（自定义源）；全部启用时关闭 AI HOT（互斥），关闭则不自动开启 AI HOT
  const allCustomEnabled = customSources.length > 0 && customSources.every((s) => s.enabled);
  const toggleAllCustom = async () => {
    if (!customIds.length) return;
    const enabling = !allCustomEnabled;
    // 互斥：自定义组整体翻转，AI HOT 取反（开自定义→关 AI HOT；关自定义→开 AI HOT）
    mutate((prev) => prev?.map((s) =>
      isAihotSource(s) ? { ...s, enabled: !enabling } : { ...s, enabled: enabling }
    ), { revalidate: false });
    try {
      await api.sources.batch({ ids: customIds, enabled: enabling });
      if (aihotSource) await api.sources.update(aihotSource.id, { enabled: !enabling });
    } catch {
      mutate(); // 失败重新拉取纠正
    }
  };

  const handleReorder = async (ids: number[], priorityMap: Record<number, number>) => {
    await api.sources.batch({ ids, priority_map: priorityMap });
    mutate();
  };

  const { overIdx, onDragStart, onDragOver, onDrop, onDragEnd } = useDragReorder(customSources, handleReorder);

  const pinnedCount = sources?.filter((s) => s.pinned).length ?? 0;

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">信息源管理</h1>
        <button onClick={() => setShowAdd(true)} className={btnPrimary}>
          + 添加信息源
        </button>
      </div>

      {aihotSource && (
        <AIHotGroupCard source={aihotSource} customIds={customIds} mutate={mutate} />
      )}

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
              <th className={`text-left px-4 py-3 ${sectionTitleCls} whitespace-nowrap`}>
                <div className="flex items-center gap-2">
                  <button onClick={toggleAllCustom} className={toggleCls(allCustomEnabled)} title="全部启用/禁用（启用将关闭 AI HOT，与之互斥）">
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
                  <button onClick={(e) => toggleSource(e, source)} className={toggleCls(source.enabled)}>
                    <span className={toggleThumbCls(source.enabled)} />
                  </button>
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
