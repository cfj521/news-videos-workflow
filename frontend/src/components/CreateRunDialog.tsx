import { useState } from "react";
import useSWR from "swr";
import { api, type AppSettings } from "../api/client";
import { inputCls, labelCls, btnPrimary, btnSecondary, dialogOverlayCls, dialogPanelCls, selectCls } from "../styles";
import { Select } from "./Select";
import { MultiSelect } from "./MultiSelect";
import { STAGE_LABELS, VISIBLE_STAGES, PLATFORM_LABELS, PLATFORM_MEDIA, isTargetReady, isAihotSource, SCAN_LOGIN_PLATFORMS } from "../types";
import { formatScheduleSummary, composeRunAt, decomposeRunAt } from "../lib/schedule";
import type { Schedule } from "../types";
import { payloadToDialogState, type DialogInit } from "../lib/runConfig";

interface Props {
  onCreated: () => void;
  onClose: () => void;
  schedule?: boolean;          // true = 计划模式
  onScheduled?: () => void;    // 新建/编辑成功回调
  edit?: Schedule;             // 存在 = 编辑模式（隐含 schedule 行为）
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
  { value: "720x1280", ar: "9:16", label: "720×1280 · 9:16 竖屏" },
  { value: "1280x720", ar: "16:9", label: "1280×720 · 16:9 横屏" },
  { value: "1024x1024", ar: "1:1", label: "1024×1024 · 1:1 方形" },
  { value: "1080x1920", ar: "9:16", label: "1080×1920 · 9:16 竖屏" },
  { value: "1920x1080", ar: "16:9", label: "1920×1080 · 16:9 横屏" },
];

const AIHOT_CATEGORIES = [
  { value: "", label: "全部分类" },
  { value: "ai-models", label: "模型" },
  { value: "ai-products", label: "产品" },
  { value: "industry", label: "行业" },
  { value: "paper", label: "论文" },
  { value: "tip", label: "技巧" },
];

export function CreateRunDialog({ onCreated, onClose, schedule = false, onScheduled, edit }: Props) {
  const isSchedule = schedule || !!edit;
  // 编辑模式：从存储 payload 反填弹窗 state（只在挂载时算一次）
  const [init] = useState<DialogInit | null>(() => (edit ? payloadToDialogState(edit.payload) : null));
  const [mode, setMode] = useState("auto");
  const [freq, setFreq] = useState<"once" | "daily" | "weekly" | "monthly">(edit?.freq ?? "once");
  // 执行时间分件：once 用 onceAt；其余用 tod(HH:mm)；weekly 用 weekday；monthly 用 monthDay
  const [tparts] = useState(() => (edit ? decomposeRunAt(edit.freq, edit.run_at) : null));
  const [onceAt, setOnceAt] = useState(tparts?.onceAt ?? "");
  const [tod, setTod] = useState(tparts?.tod ?? "");
  const [weekday, setWeekday] = useState<number>(tparts?.weekday ?? 0);
  const [monthDay, setMonthDay] = useState<number | "last">(tparts?.monthDay ?? 1);
  const [scheduleName, setScheduleName] = useState(edit?.name ?? "");
  const timeReady = freq === "once" ? !!onceAt : !!tod;
  const [timeRange, setTimeRange] = useState(init?.timeRange ?? "");
  const [maxArticles, setMaxArticles] = useState<number | null>(init?.maxArticles ?? null);
  const [autoCollect, setAutoCollect] = useState(init?.autoCollect ?? true);
  const [videoRoute, setVideoRoute] = useState(init?.videoRoute ?? "");
  const [selectedVisual, setSelectedVisual] = useState<Set<number>>(init?.selectedVisual ?? new Set([1, 2, 4, 5, 6]));
  // null = 用户尚未手动改动 → 默认全选所有可用账号；非 null = 用户的具体选择
  const [targetIds, setTargetIds] = useState<Set<string> | null>(init?.targetIds ?? null);
  // null = 用默认规则；非 null = 用户显式选择
  const [sourceIds, setSourceIds] = useState<Set<string> | null>(init?.sourceIds ?? null);
  const [loading, setLoading] = useState(false);
  const [resolution, setResolution] = useState(init?.resolution ?? "");
  const [language, setLanguage] = useState(init?.language ?? "");
  const [maxImages, setMaxImages] = useState<number | null>(init?.maxImages ?? null);  // null = 用流水线配置默认

  // 信息源模式：AI HOT 或 其他源
  const [sourceMode, setSourceMode] = useState<"aihot" | "custom">(init?.sourceMode ?? "aihot");
  const [aihotCfg, setAihotCfg] = useState<{ method: string; category?: string; report_date?: string; week_start?: string }>(init?.aihotCfg ?? { method: "items" });

  const { data: settings } = useSWR<AppSettings>("settings", api.settings.get);
  // 默认值取自流水线配置；用户可在此覆盖
  const effRes = resolution || settings?.pipeline?.resolution || "1080x1920";
  const effLang = language || settings?.pipeline?.default_language || "zh";
  const effMaxImages = maxImages ?? settings?.pipeline?.max_images ?? 10;
  // 默认取流水线配置 default_video_route；用户可在弹窗内切换
  const effVideoRoute = videoRoute || settings?.pipeline?.default_video_route || "comfyui";
  const effTimeRange = timeRange || settings?.pipeline?.default_time_range || "7d";
  const effMaxArticles = maxArticles ?? settings?.pipeline?.default_max_articles ?? 5;
  const resOptions = (RES_PRESETS_DLG.some((o) => o.value === effRes)
    ? RES_PRESETS_DLG
    : [{ value: effRes, label: effRes }, ...RES_PRESETS_DLG]
  ).map((o) => ({ value: o.value, label: o.label }));

  const { data: sources } = useSWR("sources", api.sources.list);
  const { data: publishTargets } = useSWR("publishers", api.publishers.list);
  // AI HOT 周报/日报数据（仅在对应模式时获取）
  const { data: weeks } = useSWR(sourceMode === "aihot" && aihotCfg.method === "weekly" ? "aihot-weeks" : null, api.sources.aihotWeeks);
  const { data: days } = useSWR(sourceMode === "aihot" && aihotCfg.method === "daily" ? "aihot-days" : null, api.sources.aihotDays);

  // 其他源：排除 aihot 源
  const availableSources = (sources ?? []).filter((s) => s.enabled && !isAihotSource(s));
  const availableSourceIdSet = new Set(availableSources.map((s) => s.id));
  const effectiveSourceIds = sourceIds === null
    ? new Set(availableSources.map((s) => s.id))
    : new Set([...sourceIds].filter((id) => availableSourceIdSet.has(id)));

  // 日报/周报模式忽略时间范围与文章数
  const isAihotDigest = sourceMode === "aihot" && (aihotCfg.method === "daily" || aihotCfg.method === "weekly");

  const audioOnly = effVideoRoute === "audio";
  const excludedMedia = audioOnly ? "video" : "audio";
  // 扫码登录平台（抖音/快手）账号是否可用取决于「是否已扫码登录」，需查 login-status（无配置字段可判）。
  const scanSlugs = (publishTargets ?? [])
    .filter((t) => t.enabled && SCAN_LOGIN_PLATFORMS.has(t.platform))
    .map((t) => String(t.id));
  const { data: loginMap } = useSWR(
    scanSlugs.length ? ["publisher-login-status", scanSlugs.join(",")] : null,
    async () => {
      const entries = await Promise.all(
        scanSlugs.map(async (slug) => [slug, (await api.publishers.loginStatus(slug)).logged_in] as const),
      );
      return Object.fromEntries(entries) as Record<string, boolean>;
    },
  );
  // 可选发布账号：启用 + 媒体类型匹配 + 凭证齐全（扫码平台改判「已登录」）
  const availableTargets = (publishTargets ?? []).filter((t) => {
    if (!t.enabled || PLATFORM_MEDIA[t.platform] === excludedMedia) return false;
    if (SCAN_LOGIN_PLATFORMS.has(t.platform)) return loginMap?.[String(t.id)] === true;
    return isTargetReady(t.platform, t.config_json);
  });
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

  const toggleSource = (id: string) => {
    setSourceIds((prev) => {
      const base = prev ?? new Set(availableSources.map((s) => s.id));
      const next = new Set(base);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allSourcesSelected = availableSources.length > 0 && availableSources.every((s) => effectiveSourceIds.has(s.id));
  const onSelectAllSources = (nextAll: boolean) => setSourceIds(nextAll ? null : new Set());

  const handleSubmit = async () => {
    setLoading(true);
    try {
      const runAt = composeRunAt(freq, { onceAt, tod, weekday, monthDay });
      const payload = {
        mode: isSchedule ? "auto" : mode,
        video_route: effVideoRoute,
        time_range: effTimeRange,
        max_articles: effMaxArticles,
        selected_stages: toBackendStages(effectiveVisual),
        publish_platforms: Array.from(effectiveTargetIds),
        resolution: effRes,
        language: effLang,
        max_images: effMaxImages,
        auto_collect: isSchedule ? true : autoCollect,
        ...(sourceMode === "aihot"
          ? { aihot_config: aihotCfg }
          : { source_ids: Array.from(effectiveSourceIds) }),
      };
      if (edit) {
        await api.schedules.update(edit.slug, {
          name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
          freq,
          run_at: runAt,                 // 直接提交 datetime-local 原始串，勿 toISOString
          payload,
        });
        onScheduled?.();
      } else if (isSchedule) {
        await api.schedules.create({
          name: scheduleName.trim() || formatScheduleSummary(freq, runAt),
          freq,
          run_at: runAt,
          payload,
        });
        onScheduled?.();
      } else {
        await api.runs.create(payload);
        onCreated();
      }
    } finally { setLoading(false); }
  };

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[720px]`}>
        <h2 className="text-lg font-semibold mb-4">{edit ? "编辑计划任务" : isSchedule ? "新建计划任务" : "新建任务"}</h2>

        {isSchedule && (
          <>
            <div className="mb-3">
              <label className={labelCls}>名称（可空，默认用规则摘要）</label>
              <input type="text" value={scheduleName} onChange={(e) => setScheduleName(e.target.value)}
                placeholder={timeReady ? formatScheduleSummary(freq, composeRunAt(freq, { onceAt, tod, weekday, monthDay })) : "如：每日AI日报"} className={inputCls} />
            </div>
            <div className="mb-5 rounded-lg border border-white/[0.06] p-3 grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>间隔</label>
                <Select value={freq} onChange={(v) => setFreq(v as typeof freq)} options={[
                  { value: "once", label: "单次" },
                  { value: "daily", label: "每日" },
                  { value: "weekly", label: "每周" },
                  { value: "monthly", label: "每月" },
                ]} />
              </div>
              <div>
                <label className={labelCls}>执行时间</label>
                {freq === "once" && (
                  <input type="datetime-local" value={onceAt} onChange={(e) => setOnceAt(e.target.value)} className={inputCls} />
                )}
                {freq === "daily" && (
                  <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
                )}
                {freq === "weekly" && (
                  <div className="flex gap-2">
                    <Select value={String(weekday)} onChange={(v) => setWeekday(Number(v))} className="min-w-[5.5rem]" options={[
                      { value: "0", label: "周一" }, { value: "1", label: "周二" }, { value: "2", label: "周三" },
                      { value: "3", label: "周四" }, { value: "4", label: "周五" }, { value: "5", label: "周六" }, { value: "6", label: "周日" },
                    ]} />
                    <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
                  </div>
                )}
                {freq === "monthly" && (
                  <div className="flex gap-2">
                    <Select value={typeof monthDay === "number" ? String(monthDay) : "last"}
                      onChange={(v) => setMonthDay(v === "last" ? "last" : Number(v))}
                      className="min-w-[5.5rem]"
                      options={[...Array.from({ length: 28 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} 日` })), { value: "last", label: "月末（最后一天）" }]} />
                    <input type="time" value={tod} onChange={(e) => setTod(e.target.value)} className={inputCls} />
                  </div>
                )}
              </div>
              <p className="col-span-2 text-[11px] text-white/40 leading-snug">
                {freq === "once"
                  ? "在所选时刻执行一次。"
                  : "按所选间隔在该时间重复执行。"}
                {freq === "monthly" && monthDay === "last" && " 每月最后一天执行（短月自动顺延，如 2 月跑 28/29 日）。"}
              </p>
            </div>
          </>
        )}

        <div className="flex gap-5">
          {/* 左列：信息源 → 发布账号 → 执行阶段 */}
          <div className="flex-1 min-w-0">
            <label className={labelCls}>信息源</label>
            <div className="flex gap-2 mb-3">
              {(["aihot", "custom"] as const).map((m) => (
                <button key={m} type="button" onClick={() => setSourceMode(m)}
                  className={`px-4 py-1.5 text-sm rounded-md border transition ${sourceMode === m ? "bg-blue-500/15 text-blue-300 border-blue-400/30" : "bg-white/[0.03] text-white/70 border-white/[0.06] hover:text-white/92"}`}>
                  {m === "aihot" ? "AI HOT" : "其他源"}
                </button>
              ))}
            </div>
            {sourceMode === "aihot" ? (
              <div className="mb-4">
                <div className="flex gap-1.5 mb-2">
                  {(["items", "daily", "weekly"] as const).map((m) => (
                    <button key={m} type="button" onClick={() => setAihotCfg({ method: m })}
                      className={`px-2.5 py-1 text-xs rounded-md border transition ${aihotCfg.method === m ? "bg-blue-500/15 text-blue-300 border-blue-400/30" : "bg-white/[0.03] text-white/70 border-white/[0.06]"}`}>
                      {m === "items" ? "动态" : m === "daily" ? "日报" : "周报"}
                    </button>
                  ))}
                </div>
                {aihotCfg.method === "items" && (
                  <Select value={aihotCfg.category ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, category: v }))} options={AIHOT_CATEGORIES} />
                )}
                {aihotCfg.method === "daily" && (
                  <Select value={aihotCfg.report_date ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, report_date: v }))}
                    options={[{ value: "", label: "自动（最新一期）" }, ...(days ?? []).map((d) => ({ value: d.date, label: d.date }))]} />
                )}
                {aihotCfg.method === "weekly" && (
                  <Select value={aihotCfg.week_start ?? ""} onChange={(v) => setAihotCfg((c) => ({ ...c, week_start: v }))}
                    options={[{ value: "", label: "自动（上一个完整自然周）" }, ...(weeks ?? []).map((w) => ({ value: w.week_start, label: `${w.week_start.slice(5)}~${w.week_end.slice(5)}（${w.days}天）` }))]} />
                )}
              </div>
            ) : (
              <div className="mb-4">
                {availableSources.length === 0 ? (
                  <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] px-3 py-2.5 text-xs text-amber-300/80">暂无可用信息源，请到「信息源管理」启用（将回退默认 Hacker News）</div>
                ) : (
                  <MultiSelect
                    variant="chips" searchable selectAll
                    allSelected={allSourcesSelected}
                    onSelectAll={onSelectAllSources}
                    values={[...effectiveSourceIds]}
                    onToggle={(v) => toggleSource(v)}
                    options={availableSources.map((s) => ({ value: String(s.id), label: s.name }))}
                    placeholder="选择信息源..."
                  />
                )}
              </div>
            )}

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

          </div>

          {/* 右列：运行模式·路线 → 图片数·文章数 → 分辨率 → 采集方式 → 语言·时间范围 */}
          <div className="flex-1 min-w-0">
            <div className="grid grid-cols-2 gap-3 mb-4">
              <div>
                <label className={labelCls}>运行模式</label>
                {isSchedule ? (
                  <div className={`${selectCls} flex items-center opacity-50 cursor-not-allowed`}>
                    <span className="text-white/96">自动</span>
                  </div>
                ) : (
                  <Select value={mode} onChange={(v) => { setMode(v); if (v === "auto") setAutoCollect(true); }} options={[
                    { value: "auto", label: "自动" },
                    { value: "manual", label: "手动（逐步审核）" },
                  ]} />
                )}
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
                <label className={labelCls}>最多图片数（0=不限制）</label>
                <input type="number" value={effMaxImages} onChange={(e) => setMaxImages(Number(e.target.value))} min={0} max={100} className={inputCls} />
                <p className="text-[11px] text-white/40 mt-1 leading-snug">超过则按评分裁掉低分内容到此数量</p>
              </div>
              <div>
                <label className={labelCls}>最大文章数</label>
                <input type="number" value={effMaxArticles} onChange={(e) => setMaxArticles(Number(e.target.value))} min={1} max={20} className={inputCls} />
                <p className="text-[11px] text-white/40 mt-1 leading-snug">评分后进入视频的内容条数上限</p>
              </div>
            </div>

            <div className="mb-4">
              <label className={labelCls}>分辨率（图片与视频共用）</label>
              <Select value={effRes} onChange={setResolution} options={resOptions} />
            </div>

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

            <div className="grid grid-cols-2 gap-3 mb-5">
              <div>
                <label className={labelCls}>语言</label>
                <Select value={effLang} onChange={setLanguage} options={[
                  { value: "zh", label: "中文" }, { value: "en", label: "English" },
                ]} />
                <p className="text-[11px] text-white/40 mt-1 leading-snug">
                  {effLang === "en"
                    ? "英文和西方面孔、场景，TTS 尽量选择英文音色"
                    : "中文和东方面孔、场景，TTS 必须选择中文音色"}
                </p>
              </div>
              {autoCollect && !isAihotDigest && (
                <div>
                  <label className={labelCls}>时间范围</label>
                  <Select value={effTimeRange} onChange={setTimeRange} options={[
                    { value: "1d", label: "最近 1 天" },
                    { value: "3d", label: "最近 3 天" },
                    { value: "7d", label: "最近 7 天" },
                    { value: "15d", label: "最近 15 天" },
                    { value: "1m", label: "最近 1 个月" },
                  ]} />
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className={btnSecondary}>取消</button>
          <button onClick={handleSubmit} disabled={loading || effectiveVisual.size === 0 || (isSchedule && !timeReady)} className={btnPrimary}>
            {loading ? "创建中..." : edit ? "保存修改" : isSchedule ? "创建计划" : "创建"}
          </button>
        </div>
      </div>
    </div>
  );
}
