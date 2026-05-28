import { useState, useEffect } from "react";
import { api } from "../api/client";
import { inputCls, labelCls, btnPrimary, btnSecondary, dialogOverlayCls, dialogPanelCls, selectCls } from "../styles";
import { Select } from "./Select";
import { STAGE_LABELS, VISIBLE_STAGES } from "../types";
import { PLATFORM_LABELS, PLATFORM_MEDIA } from "../types";

interface Props {
  onCreated: () => void;
  onClose: () => void;
}

const VISUAL_DEPS: Record<number, number[]> = { 2: [1], 4: [1, 2], 5: [1, 2, 4], 6: [1, 2, 4, 5] };

function toBackendStages(visual: Set<number>): number[] {
  const backend: number[] = [];
  for (const vs of visual) {
    if (vs === 2) { backend.push(2, 3); }
    else { backend.push(vs); }
  }
  return [...new Set(backend)].sort();
}

const ALL_PLATFORMS = Object.keys(PLATFORM_MEDIA).map((k) => ({ value: k, label: PLATFORM_LABELS[k] ?? k }));

export function CreateRunDialog({ onCreated, onClose }: Props) {
  const [mode, setMode] = useState("auto");
  const [timeRange, setTimeRange] = useState("7d");
  const [maxArticles, setMaxArticles] = useState(5);
  const [autoCollect, setAutoCollect] = useState(true);
  const [videoRoute, setVideoRoute] = useState("hyperframes");
  const [selectedVisual, setSelectedVisual] = useState<Set<number>>(new Set([1, 2, 4, 5]));
  const [platforms, setPlatforms] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);

  const audioOnly = videoRoute === "audio";
  const platformOptions = audioOnly
    ? ALL_PLATFORMS.filter((p) => PLATFORM_MEDIA[p.value] !== "video")
    : ALL_PLATFORMS.filter((p) => PLATFORM_MEDIA[p.value] !== "audio");

  useEffect(() => {
    if (audioOnly) setSelectedVisual((prev) => {
      if (!prev.has(4)) return prev;
      const next = new Set(prev); next.delete(4); return next;
    });
  }, [audioOnly]);

  useEffect(() => {
    setPlatforms((prev) => {
      const allowed = new Set(platformOptions.map((p) => p.value));
      const next = new Set([...prev].filter((p) => allowed.has(p)));
      return next.size === prev.size ? prev : next;
    });
  }, [audioOnly]);

  const toggleStage = (s: number) => {
    setSelectedVisual((prev) => {
      const next = new Set(prev);
      if (next.has(s)) {
        next.delete(s);
        for (const [dep, requires] of Object.entries(VISUAL_DEPS)) {
          if (requires.includes(s)) next.delete(Number(dep));
        }
      } else {
        next.add(s);
        const deps = VISUAL_DEPS[s] ?? [];
        for (const d of deps) next.add(d);
      }
      return next;
    });
  };

  const togglePlatform = (p: string) => {
    setPlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      if (next.size > 0) {
        setSelectedVisual(new Set(VISIBLE_STAGES));
      }
      return next;
    });
  };

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await api.runs.create({
        mode,
        video_route: videoRoute,
        time_range: timeRange,
        max_articles: maxArticles,
        selected_stages: toBackendStages(selectedVisual),
        publish_platforms: Array.from(platforms),
        auto_collect: autoCollect,
      });
      onCreated();
    } finally { setLoading(false); }
  };

  const dialogStages = audioOnly ? VISIBLE_STAGES.filter((s) => s !== 4) : VISIBLE_STAGES;
  const stageLabel = (s: number) => (audioOnly && s === 2 ? "脚本/语音生成" : STAGE_LABELS[s]);

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[500px]`}>
        <h2 className="text-lg font-semibold mb-5">新建任务</h2>

        <label className={labelCls}>执行阶段</label>
        <div className="rounded-lg border border-white/[0.06] mb-4 overflow-hidden">
          {dialogStages.map((s) => (
            <label
              key={s}
              className="flex items-center gap-3 px-3 py-2.5 hover:bg-white/[0.03] cursor-pointer border-b border-white/[0.04] last:border-0 transition"
            >
              <input
                type="checkbox"
                checked={selectedVisual.has(s)}
                onChange={() => toggleStage(s)}
                className="w-3.5 h-3.5 rounded accent-blue-500"
              />
              <span className="text-xs text-white/25 font-mono w-5">S{s}</span>
              <span className="text-sm text-white/70 flex-1">{stageLabel(s)}</span>
            </label>
          ))}
        </div>

        {selectedVisual.has(6) && (
          <>
            <label className={labelCls}>发布平台</label>
            <div className="flex gap-2 mb-4">
              {platformOptions.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => togglePlatform(p.value)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition border ${
                    platforms.has(p.value)
                      ? "bg-blue-500/15 border-blue-500/30 text-blue-300"
                      : "bg-white/[0.03] border-white/[0.06] text-white/40 hover:text-white/60"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className={labelCls}>运行模式</label>
            <Select value={mode} onChange={(v) => { setMode(v); if (v === "auto") setAutoCollect(true); }} options={[
              { value: "auto", label: "自动" },
              { value: "manual", label: "手动（逐步审核）" },
            ]} />
          </div>
          <div>
            <label className={labelCls}>音视频路线</label>
            <Select value={videoRoute} onChange={setVideoRoute} options={[
              { value: "hyperframes", label: "Hyperframes" },
              { value: "ltx", label: "LTX 2.3" },
              { value: "audio", label: "纯语音" },
            ]} />
          </div>
        </div>

        <div className="mb-4">
          <label className={labelCls}>采集方式</label>
          {mode === "auto" ? (
            <div className={`${selectCls} flex items-center justify-between opacity-50 cursor-not-allowed`}>
              <span className="text-white/90">自动采集</span>
            </div>
          ) : (
            <Select value={autoCollect ? "auto" : "manual"} onChange={(v) => setAutoCollect(v === "auto")} options={[
              { value: "auto", label: "自动采集" },
              { value: "manual", label: "不采集（人工导入）" },
            ]} />
          )}
        </div>

        {autoCollect && (
          <div className="grid grid-cols-2 gap-3 mb-5">
            <div>
              <label className={labelCls}>时间范围</label>
              <Select value={timeRange} onChange={setTimeRange} options={[
                { value: "1d", label: "最近 1 天" },
                { value: "3d", label: "最近 3 天" },
                { value: "7d", label: "最近 7 天" },
                { value: "15d", label: "最近 15 天" },
                { value: "1m", label: "最近 1 个月" },
              ]} />
            </div>
            <div>
              <label className={labelCls}>最大文章数</label>
              <input type="number" value={maxArticles} onChange={(e) => setMaxArticles(Number(e.target.value))} min={1} max={20} className={inputCls} />
            </div>
          </div>
        )}

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className={btnSecondary}>取消</button>
          <button onClick={handleSubmit} disabled={loading || selectedVisual.size === 0} className={btnPrimary}>
            {loading ? "创建中..." : "创建"}
          </button>
        </div>
      </div>
    </div>
  );
}
