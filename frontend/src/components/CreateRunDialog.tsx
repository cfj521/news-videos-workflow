import { useState } from "react";
import useSWR from "swr";
import { api, type AppSettings } from "../api/client";
import { inputCls, labelCls, btnPrimary, btnSecondary, dialogOverlayCls, dialogPanelCls, selectCls } from "../styles";
import { Select } from "./Select";
import { MultiSelect } from "./MultiSelect";
import { SourceSummary } from "./SourceSummary";
import { STAGE_LABELS, VISIBLE_STAGES, PLATFORM_LABELS, PLATFORM_MEDIA, isTargetReady, isAihotSource } from "../types";

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

// 分辨率预设（图片与视频共用）；选中时同时确定画面比例
const RES_PRESETS_DLG = [
  { value: "1080x1920", ar: "9:16", label: "1080×1920 · 9:16 竖屏" },
  { value: "1920x1080", ar: "16:9", label: "1920×1080 · 16:9 横屏" },
  { value: "1024x1024", ar: "1:1", label: "1024×1024 · 1:1 方形" },
  { value: "720x1280", ar: "9:16", label: "720×1280 · 9:16 竖屏" },
];

export function CreateRunDialog({ onCreated, onClose }: Props) {
  const [mode, setMode] = useState("auto");
  const [timeRange, setTimeRange] = useState("7d");
  const [maxArticles, setMaxArticles] = useState(5);
  const [autoCollect, setAutoCollect] = useState(true);
  const [videoRoute, setVideoRoute] = useState("hyperframes");
  const [selectedVisual, setSelectedVisual] = useState<Set<number>>(new Set([1, 2, 4, 5, 6]));
  // null = 用户尚未手动改动 → 默认全选所有可用账号；非 null = 用户的具体选择
  const [targetIds, setTargetIds] = useState<Set<string> | null>(null);
  const [loading, setLoading] = useState(false);
  const [resolution, setResolution] = useState("");
  const [language, setLanguage] = useState("");
  const [maxImages, setMaxImages] = useState<number | null>(null);  // null = 用流水线配置默认

  const { data: settings } = useSWR<AppSettings>("settings", api.settings.get);
  // 默认值取自流水线配置；用户可在此覆盖
  const effRes = resolution || settings?.pipeline?.resolution || "1080x1920";
  const effLang = language || settings?.pipeline?.default_language || "zh";
  const effMaxImages = maxImages ?? settings?.pipeline?.max_images ?? 10;
  // 新建任务默认 hyperframes；用户可在弹窗内切换
  const effVideoRoute = videoRoute || settings?.pipeline?.default_video_route || "comfyui";
  const resOptions = (RES_PRESETS_DLG.some((o) => o.value === effRes)
    ? RES_PRESETS_DLG
    : [{ value: effRes, label: effRes }, ...RES_PRESETS_DLG]
  ).map((o) => ({ value: o.value, label: o.label }));

  const { data: sources } = useSWR("sources", api.sources.list);
  const { data: publishTargets } = useSWR("publishers", api.publishers.list);
  const enabledSources = (sources ?? []).filter((s) => s.enabled);
  // 后端互斥：只要有启用的 AI HOT 源，就只走 AI HOT 组
  const aihotSource = enabledSources.find(isAihotSource);
  const aihotMethod = (() => {
    if (!aihotSource) return "";
    try { return (JSON.parse(aihotSource.config_json ?? "{}") as { method?: string }).method ?? "items"; }
    catch { return "items"; }
  })();
  // 日报/周报模式忽略时间范围与文章数；动态(items)模式两者仍生效
  const isAihotDigest = aihotMethod === "daily" || aihotMethod === "weekly";

  const audioOnly = effVideoRoute === "audio";
  const excludedMedia = audioOnly ? "video" : "audio";
  // 可选发布账号：启用 + 必要凭证齐全（isTargetReady）+ 媒体类型与当前路线匹配
  const availableTargets = (publishTargets ?? []).filter(
    (t) => t.enabled && isTargetReady(t.platform, t.config_json) && PLATFORM_MEDIA[t.platform] !== excludedMedia
  );
  const targetOptions = availableTargets.map((t) => ({
    value: String(t.id), label: t.name, hint: PLATFORM_LABELS[t.platform] ?? t.platform,
  }));
  const dialogStages = audioOnly ? VISIBLE_STAGES.filter((s) => s !== 4) : VISIBLE_STAGES;
  const stageLabel = (s: number) => (audioOnly && s === 2 ? "脚本/语音生成" : STAGE_LABELS[s]);

  // 把 audio 路线的约束在读取时应用，避免用 effect 同步 state（React 推荐做法）
  const effectiveVisual = audioOnly && selectedVisual.has(4)
    ? new Set([...selectedVisual].filter((s) => s !== 4))
    : selectedVisual;
  // targetIds 为 null（用户未手动改动）时默认全选所有可用账号；否则用其选择并过滤掉已不可用的
  const availableIdSet = new Set(availableTargets.map((t) => String(t.id)));
  const effectiveTargetIds = targetIds === null
    ? new Set(availableIdSet)
    : new Set([...targetIds].filter((id) => availableIdSet.has(id)));

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

  const toggleTarget = (id: string) => {
    setTargetIds((prev) => {
      // 首次手动操作前，以「全选可用账号」为基准再 toggle
      const base = prev ?? new Set(availableTargets.map((t) => String(t.id)));
      const next = new Set(base);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    setLoading(true);
    try {
      await api.runs.create({
        mode,
        video_route: effVideoRoute,
        time_range: timeRange,
        max_articles: maxArticles,
        selected_stages: toBackendStages(effectiveVisual),
        publish_platforms: Array.from(effectiveTargetIds),
        resolution: effRes,
        language: effLang,
        max_images: effMaxImages,
        auto_collect: autoCollect,
      });
      onCreated();
    } finally { setLoading(false); }
  };

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[500px]`}>
        <h2 className="text-lg font-semibold mb-4">新建任务</h2>

        <div className="mb-5"><SourceSummary /></div>

        <label className={labelCls}>执行阶段</label>
        <div className="rounded-lg border border-white/[0.06] mb-4 overflow-hidden">
          {dialogStages.map((s) => (
            <label
              key={s}
              className="flex items-center gap-3 px-3 py-2.5 hover:bg-white/[0.03] cursor-pointer border-b border-white/[0.04] last:border-0 transition"
            >
              <input
                type="checkbox"
                checked={effectiveVisual.has(s)}
                onChange={() => toggleStage(s)}
                className="w-3.5 h-3.5 rounded accent-blue-500"
              />
              <span className="text-xs text-white/52 font-mono w-5">S{s}</span>
              <span className="text-sm text-white/92 flex-1">{stageLabel(s)}</span>
            </label>
          ))}
        </div>

        {effectiveVisual.has(6) && (
          <div className="mb-4">
            <label className={labelCls}>发布账号</label>
            <MultiSelect
              values={[...effectiveTargetIds]}
              onToggle={toggleTarget}
              options={targetOptions}
              placeholder="选择发布账号..."
              emptyHint="暂无可用发布账号，请先到「发布管理」添加"
            />
          </div>
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
            <Select value={effVideoRoute} onChange={setVideoRoute} options={[
              { value: "hyperframes", label: "Hyperframes" },
              { value: "comfyui", label: "ComfyUI" },
              { value: "audio", label: "纯语音" },
            ]} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className={labelCls}>分辨率（图片与视频共用）</label>
            <Select value={effRes} onChange={setResolution} options={resOptions} />
          </div>
          <div>
            <label className={labelCls}>语言</label>
            <Select value={effLang} onChange={setLanguage} options={[
              { value: "zh", label: "中文" }, { value: "en", label: "English" },
            ]} />
          </div>
          <div>
            <label className={labelCls}>最多图片数（0=不限制）</label>
            <input type="number" value={effMaxImages} onChange={(e) => setMaxImages(Number(e.target.value))} min={0} max={100} className={inputCls} />
            <p className="text-[11px] text-white/40 mt-1">超过则生图前 AI 重规划，合并零碎/短文章到同一张图</p>
          </div>
        </div>
        {effLang === "en" && (
          <p className="text-xs text-amber-300/70 -mt-2 mb-4">英文模式：脚本/字幕用英文、图片倾向西方面孔与场景；TTS 音色请在「设置 → 流水线配置」选英文音色（en-US-*）。</p>
        )}

        <div className="mb-4">
          <label className={labelCls}>采集方式</label>
          {mode === "auto" ? (
            <div className={`${selectCls} flex items-center justify-between opacity-50 cursor-not-allowed`}>
              <span className="text-white/96">自动采集</span>
            </div>
          ) : (
            <Select value={autoCollect ? "auto" : "manual"} onChange={(v) => setAutoCollect(v === "auto")} options={[
              { value: "auto", label: "自动采集" },
              { value: "manual", label: "不采集（人工导入）" },
            ]} />
          )}
        </div>

        {autoCollect && !isAihotDigest && (
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
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0} className={btnPrimary}>
            {loading ? "创建中..." : "创建"}
          </button>
        </div>
      </div>
    </div>
  );
}
