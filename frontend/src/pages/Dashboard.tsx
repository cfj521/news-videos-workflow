import { useState, useEffect, useRef, useCallback, createContext, useContext } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, type ScriptData, type TimelineData, type AppSettings, type PublishResultRec, type ScoringData } from "../api/client";
import {
  btnPrimary, btnSecondary, btnCompact, btnIcon, cardCls, chipCls, STATUS_CHIP,
  sectionTitleCls, inputCls, labelCls, errorTextCls,
  btnApprove, btnDelete, btnDeleteIcon,
  dialogOverlayCls, dialogPanelCls,
} from "../styles";
import { Select } from "../components/Select";
import { CreateRunDialog } from "../components/CreateRunDialog";
import { SourceSummary } from "../components/SourceSummary";
import { IconButton } from "../components/IconButton";
import { DeleteIconButton } from "../components/DeleteIconButton";
import { PencilIcon, PlusIcon, ImportIcon, RefreshIcon, SparklesIcon, WandIcon } from "../components/icons";
import { useToast } from "../components/Toast";
import type { PipelineRun } from "../types";
import { STAGE_LABELS, VISIBLE_STAGES, BACKEND_STAGE_MAP, PLATFORM_LABELS } from "../types";

// SSE 事件分发：RunWorkspace 开一条 EventSource，子面板从 context 读取就绪标记，无需各自轮询/连流
const RunEventsContext = createContext<{ sceneTick: Record<number, number>; publishTick: number }>({ sceneTick: {}, publishTick: 0 });

const STATUS_LABEL: Record<string, string> = {
  pending: "等待中",
  processing: "处理中",
  review: "审核中",
  done: "完成",
  failed: "失败",
  cancelled: "已终止",
};

// ─── Resolution presets ─────────────────────────────────

const RES_PRESETS = [
  { value: "720x1280", label: "720x1280  竖屏 HD" },
  { value: "1280x720", label: "1280x720  横屏 HD" },
  { value: "1024x1024", label: "1024x1024  方形" },
  { value: "1080x1920", label: "1080x1920  竖屏 FHD" },
  { value: "1920x1080", label: "1920x1080  横屏 FHD" },
];

// ─── PresetInput (editable dropdown) ────────────────────

function PresetInput({ value, onChange, onCommit, presets, className }: {
  value: string;
  onChange: (v: string) => void;
  onCommit?: (v: string) => void;
  presets: { value: string; label: string }[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className={`relative ${className ?? ""}`} ref={ref}>
      <div className="flex">
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onBlur={(e) => onCommit?.(e.target.value)}
          className={`${inputCls} !rounded-r-none !border-r-0 text-xs`}
        />
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="px-2 rounded-r-lg border border-white/[0.08] bg-white/[0.04] text-white/60 hover:text-white/76 hover:bg-white/[0.06] transition text-[10px]"
        >
          ▾
        </button>
      </div>
      {open && (
        <div className="absolute z-30 top-full left-0 right-0 mt-1 rounded-lg bg-[var(--color-surface-raised)] border border-white/[0.08] shadow-xl overflow-hidden py-1">
          {presets.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => { onChange(p.value); onCommit?.(p.value); setOpen(false); }}
              className={`w-full px-3 py-1.5 text-left text-xs transition hover:bg-white/[0.06] ${
                value === p.value ? "text-blue-300 bg-white/[0.04]" : "text-white/85"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Stepper ────────────────────────────────────────────

function Stepper({ run, onSelect, activeStage, locked = false }: { run: PipelineRun; onSelect: (s: number) => void; activeStage: number; locked?: boolean }) {
  const selected: number[] = (() => { try { return JSON.parse(run.selected_stages); } catch { return []; } })();

  const audioOnly = run.video_route === "audio";
  const stages = audioOnly ? VISIBLE_STAGES.filter((s) => s !== 4) : VISIBLE_STAGES;
  const labelOf = (s: number) => (audioOnly && s === 2 ? "脚本/语音生成" : STAGE_LABELS[s]);

  const statusOf = (vs: number) => {
    const bs = BACKEND_STAGE_MAP[vs];
    if (!bs.some((s) => selected.includes(s))) return "skipped";
    if (run.status === "done") return "done";
    const cs = run.current_stage ?? 0;
    if (bs.includes(cs)) {
      if (run.status === "review") return "review";
      if (run.status === "processing") return "processing";
      if (run.status === "failed") return "failed";
    }
    if (cs > Math.max(...bs)) return "done";
    return "pending";
  };

  const dotCls: Record<string, string> = {
    done: "bg-emerald-400", processing: "bg-blue-400 animate-pulse-soft", review: "bg-amber-400",
    failed: "bg-red-400", pending: "bg-white/[0.15]", skipped: "bg-white/[0.06]",
  };

  return (
    <div className="flex items-center gap-1 mb-6">
      {stages.map((s, i) => {
        const ss = statusOf(s);
        const isActive = s === activeStage;
        // 锁定（自动模式进行中）时，尚未到达的阶段不可点击查看
        const clickable = ss !== "skipped" && !(locked && ss === "pending");
        return (
          <div key={s} className="flex items-center flex-1">
            <button
              onClick={() => clickable && onSelect(s)}
              className={`flex items-center gap-2 px-3 py-2 rounded-lg transition w-full ${
                isActive ? "bg-white/[0.06] border border-white/[0.1]" : "hover:bg-white/[0.03] border border-transparent"
              } ${!clickable ? "opacity-30 cursor-default" : "cursor-pointer"}`}
            >
              <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${dotCls[ss]}`} />
              <span className="text-xs text-white/85 truncate">{labelOf(s)}</span>
            </button>
            {i < stages.length - 1 && <div className="w-4 h-px bg-white/[0.08] shrink-0" />}
          </div>
        );
      })}
    </div>
  );
}

// ─── S1: 搜索整理 ──────────────────────────────────────

type ArticleRec = Record<string, unknown> & { title?: string; content?: string; summary?: string; source?: string; url?: string; score_final?: number; score_reason?: string };

function ArticleDialog({ initial, onSave, onClose }: { initial: ArticleRec | null; onSave: (a: ArticleRec) => void; onClose: () => void; }) {
  const [title, setTitle] = useState(String(initial?.title ?? ""));
  const [content, setContent] = useState(String(initial?.content ?? ""));
  const [summary, setSummary] = useState(String(initial?.summary ?? ""));
  const [source, setSource] = useState(String(initial?.source ?? ""));
  const [url, setUrl] = useState(String(initial?.url ?? ""));
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[760px] max-w-[92vw]`}>
        <h2 className="text-lg font-semibold mb-4">{initial ? "编辑文章" : "添加文章"}</h2>
        <label className={labelCls}>标题</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} className={`${inputCls} mb-3`} />
        <label className={labelCls}>正文</label>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={16} className={`${inputCls} mb-3 text-[13px]`} />
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div><label className={labelCls}>来源</label><input value={source} onChange={(e) => setSource(e.target.value)} className={inputCls} /></div>
          <div><label className={labelCls}>原文链接</label><input value={url} onChange={(e) => setUrl(e.target.value)} className={inputCls} /></div>
        </div>
        <label className={labelCls}>摘要</label>
        <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={4} className={`${inputCls} mb-4 text-[13px]`} />
        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnCompact}>取消</button>
          <button onClick={() => onSave({ ...(initial ?? {}), title, content, summary, source, url })} className={btnPrimary}>保存</button>
        </div>
      </div>
    </div>
  );
}

function ImportArticleDialog({ runId, onDone, onClose }: { runId: number; onDone: () => void; onClose: () => void; }) {
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const { showToast } = useToast();
  const doFile = async (f: File) => {
    setLoading(true);
    try { await api.runs.importArticleFile(runId, f); showToast("已导入", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "导入失败", "error"); }
    finally { setLoading(false); }
  };
  const doUrl = async () => {
    if (!url.trim()) return;
    setLoading(true);
    try { await api.runs.importArticleUrl(runId, url.trim()); showToast("已导入", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "导入失败", "error"); }
    finally { setLoading(false); }
  };
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-4">导入文章</h2>
        <label className={labelCls}>上传文件（.docx / .pdf / .md / .txt）</label>
        <input type="file" accept=".docx,.pdf,.md,.txt" disabled={loading}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) doFile(f); }}
          className="mb-1 block w-full text-sm text-white/85" />
        <p className="text-[11px] text-white/52 mb-4">PDF 走视觉模型解析，可能较慢</p>
        <label className={labelCls}>或粘贴网页 URL</label>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." className={`${inputCls} mb-4`} />
        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnCompact}>关闭</button>
          <button onClick={doUrl} disabled={loading} className={`${btnPrimary} min-w-[96px]`}>导入</button>
        </div>
        {loading && <p className="text-xs text-white/66 mt-2">处理中...</p>}
      </div>
    </div>
  );
}

function S1Panel({ runId, run }: { runId: number; run: PipelineRun }) {
  const { data: articles, mutate } = useSWR<ArticleRec[]>(`articles-${runId}`, () => api.runs.articles(runId) as Promise<ArticleRec[]>);
  const { data: scoring } = useSWR<ScoringData>(`scoring-${runId}`, () => api.runs.scoring(runId).catch(() => null as unknown as ScoringData));
  const [rerolling, setRerolling] = useState(false);
  const [confirmReroll, setConfirmReroll] = useState(false);
  const [editing, setEditing] = useState<{ idx: number; rec: ArticleRec } | null>(null);
  const [adding, setAdding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [scoringOpen, setScoringOpen] = useState(false);
  const { showToast } = useToast();

  // AI HOT 采集模式从 run.aihot_config 判断（权威来源）：
  // daily 禁用重新采集；weekly 语义是「重新总结」；items/普通源是「重新采集/reroll」
  const aihotMethod = (() => { try { return run.aihot_config ? (JSON.parse(run.aihot_config) as { method?: string }).method ?? "" : ""; } catch { return ""; } })();
  const isDaily = aihotMethod === "daily";
  const isWeekly = aihotMethod === "weekly";
  const rerollLabel = isWeekly ? "重新总结" : "重新采集";

  const save = async (list: ArticleRec[]): Promise<boolean> => {
    try { await api.runs.saveArticles(runId, list); mutate(); return true; }
    catch (e) { showToast(e instanceof Error ? e.message : "保存失败", "error"); return false; }
  };

  const handleReroll = async () => {
    setRerolling(true);
    try {
      await api.runs.rerollArticles(runId);
      showToast(isWeekly ? "重新总结中..." : "重新采集中...", "success");
      setConfirmReroll(false);
      setTimeout(() => { mutate(); setRerolling(false); }, 5000);
    } catch { showToast("采集失败", "error"); setRerolling(false); }
  };

  const list = articles ?? [];

  const onSaveArticle = async (rec: ArticleRec) => {
    const next = [...list];
    if (editing) next[editing.idx] = rec; else next.push(rec);
    if (await save(next)) { setEditing(null); setAdding(false); }
  };
  const onDelete = async (idx: number) => { await save(list.filter((_, i) => i !== idx)); };

  if (!articles) return <p className="text-white/60 text-sm">加载中...</p>;

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <span className="text-sm text-white/66">{list.length} 篇文章</span>
        <div className="flex gap-1.5">
          <IconButton onClick={() => setImporting(true)} title="导入文章"><ImportIcon /></IconButton>
          <IconButton onClick={() => setAdding(true)} title="添加文章" variant="primary"><PlusIcon /></IconButton>
          <IconButton onClick={() => setConfirmReroll(true)} disabled={rerolling || isDaily}
            title={isDaily ? "日报无需重新采集（同一份当日日报）" : (rerolling ? (isWeekly ? "总结中..." : "采集中...") : rerollLabel)}>
            <RefreshIcon className={rerolling ? "animate-spin" : ""} />
          </IconButton>
        </div>
      </div>
      {list.length === 0 && <p className="text-white/60 text-sm">暂无文章，点「导入」或「添加文章」</p>}
      <div className="space-y-2">
        {list.map((a, i) => {
          const mainLink = String(a.aggregator_url ?? a.url ?? "");
          return (
            <div key={i} className={`${cardCls} p-4`}>
              <div className="flex justify-between items-start gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <button onClick={() => setEditing({ idx: i, rec: a })} title="点击编辑"
                      className="block text-left text-sm text-white/96 font-medium hover:text-blue-300 transition truncate min-w-0">{String(a.title ?? "")}</button>
                    {typeof a.score_final === "number" && (
                      <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-mono font-medium bg-blue-500/15 text-blue-300 border border-blue-400/20" title={a.score_reason ?? "评分"}>
                        {a.score_final.toFixed(2)}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-white/52 mt-1">{String(a.source ?? "")}</div>
                  {mainLink ? <a href={mainLink} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                    className="inline-block max-w-full truncate text-[11px] text-blue-300/80 hover:text-blue-300 transition mt-0.5">↗ {mainLink}</a> : null}
                  {a.summary ? <p className="text-xs text-white/66 mt-2 leading-relaxed">{String(a.summary)}</p> : null}
                </div>
                <div className="flex gap-1 shrink-0">
                  <IconButton onClick={() => setEditing({ idx: i, rec: a })} title="编辑文章"><PencilIcon /></IconButton>
                  <DeleteIconButton onClick={() => onDelete(i)} title="删除文章" />
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {/* 评分明细折叠区块 */}
      <div className="mt-4">
        <button
          type="button"
          onClick={() => setScoringOpen((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-white/60 hover:text-white/85 transition select-none"
        >
          <span className={`transition-transform ${scoringOpen ? "rotate-90" : ""}`}>▶</span>
          <span>评分明细</span>
          {scoring?.candidates && scoring.candidates.length > 0 && (
            <span className="text-white/40">· {scoring.candidates.length} 条候选</span>
          )}
          {scoring?.pool !== undefined && (
            <span className="text-white/40">· 池 {scoring.pool}</span>
          )}
          {scoring?.min_score !== undefined && (
            <span className="text-white/40">· 门槛 {scoring.min_score.toFixed(2)}</span>
          )}
        </button>
        {scoringOpen && (
          <div className="mt-2 space-y-2">
            {(!scoring?.candidates || scoring.candidates.length === 0) ? (
              <p className="text-xs text-white/52 pl-1">暂无评分数据</p>
            ) : (
              [...scoring.candidates].sort((a, b) => b.final - a.final).map((c, idx) => (
                <div key={idx} className={`${cardCls} p-3 ${c.selected ? "border-blue-500/30" : ""}`}>
                  <div className="flex items-start gap-2">
                    {/* 最终分徽标 */}
                    <span className={`shrink-0 inline-flex items-center justify-center min-w-[3rem] px-1.5 py-0.5 rounded text-[11px] font-mono font-semibold ${c.selected ? "bg-blue-500/20 text-blue-300 border border-blue-400/30" : "bg-white/[0.06] text-white/70 border border-white/[0.08]"}`}>
                      {c.final.toFixed(2)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="text-xs text-white/90 font-medium truncate">{c.title}</span>
                        {c.selected && (
                          <span className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/20">✓ 已选</span>
                        )}
                      </div>
                      <div className="text-[11px] text-white/52 mt-0.5">{c.source}</div>
                      {/* 4 个分项小条 */}
                      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1.5">
                        <span className="text-[10px] text-white/52 font-mono">LLM: {c.llm !== null ? c.llm.toFixed(2) : "—"}</span>
                        <span className="text-[10px] text-white/52 font-mono">来源: {c.source_w.toFixed(2)}</span>
                        <span className="text-[10px] text-white/52 font-mono">新鲜: {c.recency.toFixed(2)}</span>
                        <span className="text-[10px] text-white/52 font-mono">关键词: {c.keyword.toFixed(2)}</span>
                        <span className="text-[10px] text-white/52 font-mono">规则: {c.rule.toFixed(2)}</span>
                      </div>
                      {c.reason && (
                        <p className="text-[11px] text-white/60 mt-1 leading-relaxed">{c.reason}</p>
                      )}
                      {c.tags && c.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {c.tags.map((tag, ti) => (
                            <span key={ti} className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-white/[0.05] text-white/52 border border-white/[0.06]">{tag}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <p className="text-[11px] text-white/52 mt-3">编辑文章后，到"脚本/图片"标签点【重生成脚本】以应用。</p>

      {(adding || editing) && (
        <ArticleDialog initial={editing?.rec ?? null} onSave={onSaveArticle} onClose={() => { setAdding(false); setEditing(null); }} />
      )}
      {importing && <ImportArticleDialog runId={runId} onDone={() => { setImporting(false); mutate(); }} onClose={() => setImporting(false)} />}

      {confirmReroll && (
        <div className={dialogOverlayCls} onClick={() => { if (!rerolling) setConfirmReroll(false); }}>
          <div className={`${dialogPanelCls} w-[420px]`} onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold mb-2">{rerollLabel}</h2>
            <p className="text-sm text-white/76 mb-3 leading-relaxed">{isWeekly
              ? <>将重新 AI 总结上周日报，<span className="text-amber-300/80">覆盖现有周报结果</span>。</>
              : <>将按当前信息源重新采集，<span className="text-amber-300/80">覆盖现有文章列表</span>。</>}</p>
            <SourceSummary run={run} />
            <div className="flex gap-3 justify-end mt-5">
              <button onClick={() => setConfirmReroll(false)} disabled={rerolling} className={btnSecondary}>取消</button>
              <button onClick={handleReroll} disabled={rerolling} className={btnPrimary}>{rerolling ? (isWeekly ? "总结中..." : "采集中...") : `确认${rerollLabel}`}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── S2: 脚本/图片生成 ─────────────────────────────────

function AddSceneDialog({ runId, groupId, onDone, onClose }: { runId: number; groupId: number; onDone: () => void; onClose: () => void; }) {
  const [requirement, setRequirement] = useState("");
  const [loading, setLoading] = useState(false);
  const { showToast } = useToast();
  const submit = async () => {
    setLoading(true);
    try { await api.runs.addScene(runId, groupId, requirement); showToast("已新增分镜", "success"); onDone(); }
    catch (e) { showToast(e instanceof Error ? e.message : "新增失败", "error"); }
    finally { setLoading(false); }
  };
  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[480px]`}>
        <h2 className="text-lg font-semibold mb-3">新增分镜</h2>
        <label className={labelCls}>这个分镜想讲什么（选填）</label>
        <textarea value={requirement} onChange={(e) => setRequirement(e.target.value)} rows={3} className={`${inputCls} mb-4 text-[13px]`} placeholder="例如：强调它对开发者的影响" />
        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnCompact}>取消</button>
          <button onClick={submit} disabled={loading} className={btnPrimary}>{loading ? "生成中..." : "生成"}</button>
        </div>
      </div>
    </div>
  );
}

function S2Panel({ runId, run, audioOnly }: { runId: number; run: PipelineRun; audioOnly: boolean }) {
  const { data: script, mutate: mutateScript } = useSWR<ScriptData>(`script-${runId}`, () => api.runs.script(runId).catch(() => null as unknown as ScriptData));
  const { data: timeline, mutate: mutateTimeline } = useSWR<TimelineData>(`timeline-${runId}`, () => api.runs.timeline(runId).catch(() => null as unknown as TimelineData));
  const [imgSize, setImgSize] = useState("");
  const [addGroup, setAddGroup] = useState<number | null>(null);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [regenning, setRegenning] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const { sceneTick } = useContext(RunEventsContext); // 素材就绪由 RunWorkspace 的 SSE 统一分发
  const { showToast } = useToast();
  const { mutate: globalMutate } = useSWRConfig();
  // 图片生成尺寸 = 任务级分辨率（建任务时已必填）
  useEffect(() => { if (!imgSize) setImgSize(run.resolution || ""); }, [run.resolution, imgSize]);
  // 在图片阶段改分辨率会回写 run.resolution，成为后续各阶段（渲染/合成）的权威值。
  // 仅在选预设/输入失焦时回写，并校验 WxH 格式，避免逐字符写入无效中间值
  const handleImgSizeCommit = async (v: string) => {
    if (!/^\d+x\d+$/.test(v) || v === run.resolution) return;
    try {
      await api.runs.update(runId, { resolution: v });
      globalMutate(`run-${runId}`);
    } catch { showToast("更新分辨率失败", "error"); }
  };
  // 事件驱动刷新（替代固定计时器盲刷）：流水线每推进一个阶段或状态变化时——这些变更
  // 由父组件每 2s 轮询 run 感知到——重新拉取脚本/时间轴，并给图片/音频 URL 换一次
  // cache-bust，使新生成的素材显示出来。即「生成完成」这一事件发生时才执行一次。
  // 阶段/状态变化时重取脚本/时间轴并整体换一次 cache-bust（进入 S2/S4 等场景）
  useEffect(() => {
    mutateScript();
    mutateTimeline();
    setRefreshTick(Date.now());
  }, [run.current_stage, run.status, mutateScript, mutateTimeline]);

  const handleRegenScript = async () => {
    setRegenning(true);
    try {
      await api.runs.regenScript(runId);
      showToast("脚本已重新生成", "success");
      setConfirmRegen(false);
      mutateScript();
    } catch (e) { showToast(e instanceof Error ? e.message : "重新生成失败", "error"); }
    finally { setRegenning(false); }
  };

  if (!script) return <p className="text-white/60 text-sm">暂无脚本</p>;

  const scenes = script.scenes ?? [];
  const order: number[] = [];
  const byGroup = new Map<number, typeof scenes>();
  for (const sc of scenes) {
    const gid = sc.group_id ?? 0;
    if (!byGroup.has(gid)) { byGroup.set(gid, []); order.push(gid); }
    byGroup.get(gid)!.push(sc);
  }
  const groupTitle = (gid: number) => script.groups?.find((g) => g.id === gid)?.title ?? byGroup.get(gid)?.[0]?.group_title ?? "分镜";

  const onDelete = async (sceneId: number) => {
    try { await api.runs.deleteScene(runId, sceneId); mutateScript(); }
    catch (e) { showToast(e instanceof Error ? e.message : "删除失败", "error"); }
  };

  return (
    <div>
      <div className="flex justify-between items-start mb-4 gap-4">
        <div className="flex-1 min-w-0">
          <h3 className="text-base font-medium truncate">{script.title}</h3>
          <p className="text-xs text-white/60 mt-0.5">{script.description}</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!audioOnly && (
            <>
              <label className="text-[11px] text-white/60 whitespace-nowrap">图片尺寸</label>
              <PresetInput value={imgSize} onChange={setImgSize} onCommit={handleImgSizeCommit} presets={RES_PRESETS} className="w-40" />
            </>
          )}
          <IconButton onClick={() => setConfirmRegen(true)} disabled={regenning}
            title={regenning ? "生成中..." : "重新生成脚本（覆盖所有分镜）"}>
            <WandIcon className={regenning ? "animate-pulse" : ""} />
          </IconButton>
        </div>
      </div>

      {order.map((gid) => {
        const groupScenes = byGroup.get(gid)!;
        return (
          <div key={gid} className="mb-5">
            <div className="flex items-center justify-between mb-2">
              <h4 className={sectionTitleCls}>{groupTitle(gid)}</h4>
              <IconButton onClick={() => setAddGroup(gid)} title="新增分镜" variant="primary"><PlusIcon /></IconButton>
            </div>
            <div className="space-y-3">
              {groupScenes.map((scene) => {
                const entry = timeline?.entries?.find((e) => e.scene_id === scene.id);
                const durS = entry ? ((entry.end_ms - entry.start_ms) / 1000).toFixed(1) : null;
                return (
                  <SceneEditor key={scene.id} runId={runId} scene={scene} durationS={durS} mutateScript={mutateScript} imgSize={imgSize}
                    refreshTick={sceneTick[scene.id] || refreshTick} onDelete={() => onDelete(scene.id)} canDelete={groupScenes.length > 1} audioOnly={audioOnly} />
                );
              })}
            </div>
          </div>
        );
      })}

      {addGroup !== null && (
        <AddSceneDialog runId={runId} groupId={addGroup} onDone={() => { setAddGroup(null); mutateScript(); }} onClose={() => setAddGroup(null)} />
      )}

      {confirmRegen && (
        <div className={dialogOverlayCls} onClick={() => { if (!regenning) setConfirmRegen(false); }}>
          <div className={`${dialogPanelCls} w-[420px]`} onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold mb-2">重新生成脚本</h2>
            <p className="text-sm text-white/76 mb-5 leading-relaxed">将根据当前文章列表重新生成整个脚本，<span className="text-amber-300/80">会覆盖所有分镜及手工编辑</span>，不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setConfirmRegen(false)} disabled={regenning} className={btnSecondary}>取消</button>
              <button onClick={handleRegenScript} disabled={regenning} className={btnPrimary}>{regenning ? "生成中..." : "确认重新生成"}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function SceneEditor({ runId, scene, durationS, mutateScript, imgSize, refreshTick = 0, onDelete, canDelete, audioOnly }: {
  runId: number; scene: ScriptData["scenes"][0]; durationS: string | null; mutateScript: () => void; imgSize: string; refreshTick?: number; onDelete?: () => void; canDelete?: boolean; audioOnly?: boolean;
}) {
  const [narration, setNarration] = useState(scene.narration);
  const [prompt, setPrompt] = useState(scene.image_prompt);
  const { showToast } = useToast();

  useEffect(() => { setNarration(scene.narration); setPrompt(scene.image_prompt); }, [scene.narration, scene.image_prompt]);

  const sid = scene.id;
  const imgSrc = api.runs.assetUrl(runId, `scene_${String(sid).padStart(2, "0")}_image.png`);
  const audioSrc = api.runs.assetUrl(runId, `scene_${String(sid).padStart(2, "0")}_audio.mp3`);

  const [regenAudioLoading, setRegenAudioLoading] = useState(false);
  const [regenImgLoading, setRegenImgLoading] = useState(false);
  const [regenPromptLoading, setRegenPromptLoading] = useState(false);
  const [audioTs, setAudioTs] = useState(0);
  const [imgTs, setImgTs] = useState(0);
  const [confirmDel, setConfirmDel] = useState(false);
  const [zoom, setZoom] = useState(false);
  const [imgBroken, setImgBroken] = useState(false); // 图片未生成/加载失败 → 用占位图、禁止放大
  const imgUrl = (imgTs || refreshTick) ? `${imgSrc}?t=${imgTs || refreshTick}` : imgSrc;
  useEffect(() => { setImgBroken(false); }, [imgUrl]); // 换图后重置有效性
  const arMatch = /^(\d+)x(\d+)$/.exec(imgSize || "");
  const placeholderAspect = arMatch ? `${arMatch[1]} / ${arMatch[2]}` : "9 / 16"; // 占位图按分辨率比例，避免布局跳动

  // 放大预览：Esc 关闭
  useEffect(() => {
    if (!zoom) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setZoom(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoom]);

  const handleRegenAudio = async () => {
    setRegenAudioLoading(true);
    try { await api.runs.regenAudio(runId, sid, narration); setAudioTs(Date.now()); showToast("音频已重新生成", "success"); mutateScript(); }
    catch { showToast("音频生成失败", "error"); }
    finally { setRegenAudioLoading(false); }
  };

  const handleRegenImage = async () => {
    setRegenImgLoading(true);
    try { await api.runs.regenImage(runId, sid, prompt, imgSize || undefined); setImgTs(Date.now()); showToast("图片已重新生成", "success"); mutateScript(); }
    catch { showToast("图片生成失败", "error"); }
    finally { setRegenImgLoading(false); }
  };

  const handleRegenPrompt = async () => {
    setRegenPromptLoading(true);
    try {
      const res = await api.runs.regenPrompt(runId, sid, narration);
      setPrompt(res.image_prompt);
      showToast("提示词已重新生成", "success");
      mutateScript();
    } catch { showToast("提示词生成失败", "error"); }
    finally { setRegenPromptLoading(false); }
  };

  return (
    <div className={`${cardCls} p-4`}>
      <div className="flex gap-4">
        <div className="w-[260px] shrink-0 flex flex-col">
          {!audioOnly && (
            <>
              {/* 隐藏的真实图：仍在后台加载，成功则显示、失败则换占位图（无文字提示） */}
              <img
                src={imgUrl}
                className={`w-full rounded-lg bg-white/[0.02] transition ${imgBroken ? "hidden" : "cursor-zoom-in hover:opacity-90"}`}
                title="点击放大预览"
                onClick={() => { if (!imgBroken) setZoom(true); }}
                onError={() => setImgBroken(true)}
                onLoad={() => setImgBroken(false)}
              />
              {imgBroken && (
                <div className="w-full rounded-lg bg-white/[0.04] border border-white/[0.06] flex items-center justify-center"
                     style={{ aspectRatio: placeholderAspect }}>
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                       strokeLinecap="round" strokeLinejoin="round" className="text-white/20">
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                    <circle cx="9" cy="9" r="2" />
                    <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" />
                  </svg>
                </div>
              )}
            </>
          )}
          <audio controls src={(audioTs || refreshTick) ? `${audioSrc}?t=${audioTs || refreshTick}` : audioSrc} className={`w-full ${audioOnly ? "" : "mt-auto pt-2"}`} />
        </div>
        <div className="flex-1 space-y-3 min-w-0">
          <div className="flex justify-between items-center">
            <span className="text-xs text-white/60 font-mono">场景 {sid}</span>
            {durationS && <span className="text-xs text-white/52 font-mono">{durationS}s</span>}
            {onDelete && (
              <DeleteIconButton onClick={() => setConfirmDel(true)} title="删除分镜" />
            )}
          </div>

          <div>
            <div className="flex justify-between items-center mb-1">
              <span className="text-[11px] text-white/60">旁白</span>
              <IconButton onClick={handleRegenAudio} disabled={regenAudioLoading}
                title={regenAudioLoading ? "生成中..." : "重新配音"} className="p-1">
                <WandIcon size={14} className={regenAudioLoading ? "animate-pulse" : ""} />
              </IconButton>
            </div>
            <textarea value={narration} onChange={(e) => setNarration(e.target.value)} rows={6} className={`${inputCls} text-[13px]`} />
          </div>

          {!audioOnly && (
            <div>
              <div className="flex justify-between items-center mb-1">
                <span className="text-[11px] text-white/60">图片提示词</span>
                <div className="flex items-center gap-0.5">
                  <IconButton onClick={handleRegenPrompt} disabled={regenPromptLoading}
                    title={regenPromptLoading ? "生成中..." : "重新生成提示词"} className="p-1">
                    <SparklesIcon size={14} className={regenPromptLoading ? "animate-pulse" : ""} />
                  </IconButton>
                  <IconButton onClick={handleRegenImage} disabled={regenImgLoading}
                    title={regenImgLoading ? "生成中..." : "重新生成图片"} className="p-1">
                    <WandIcon size={14} className={regenImgLoading ? "animate-pulse" : ""} />
                  </IconButton>
                </div>
              </div>
              <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={5} className={`${inputCls} text-[13px] text-white/76 resize-y`} />
            </div>
          )}
        </div>
      </div>

      {confirmDel && (
        <div className={dialogOverlayCls} onClick={() => setConfirmDel(false)}>
          <div className={`${dialogPanelCls} w-[400px]`} onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold mb-2">删除分镜 {sid}</h2>
            <p className="text-sm text-white/76 mb-5 leading-relaxed">
              {canDelete
                ? "确认删除此分镜？不可恢复。"
                : <>这是该文章分组的最后一个分镜，<span className="text-amber-300/80">删除后将连带移除该组对应的文章</span>，不可恢复。</>}
            </p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setConfirmDel(false)} className={btnSecondary}>取消</button>
              <button onClick={() => { onDelete?.(); setConfirmDel(false); }} className={btnDelete}>
                {canDelete ? "删除" : "删除分镜及文章"}
              </button>
            </div>
          </div>
        </div>
      )}

      {zoom && !audioOnly && !imgBroken && (
        <div className={`${dialogOverlayCls} cursor-zoom-out p-8`} onClick={() => setZoom(false)}>
          <img src={imgUrl} className="max-w-[92vw] max-h-[92vh] rounded-lg shadow-2xl object-contain" onClick={(e) => e.stopPropagation()} />
          <button onClick={() => setZoom(false)} className="absolute top-5 right-6 text-white/85 hover:text-white text-3xl leading-none" title="关闭（Esc）">×</button>
        </div>
      )}
    </div>
  );
}

// ─── Playback icons ─────────────────────────────────────

const IconPlay = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
    <path d="M6 4l15 8-15 8V4z" />
  </svg>
);

const IconPause = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
    <rect x="5" y="3" width="4" height="18" rx="1" />
    <rect x="15" y="3" width="4" height="18" rx="1" />
  </svg>
);

function OverlayIndicator({ playing }: { playing: boolean }) {
  const [visible, setVisible] = useState(false);
  const [icon, setIcon] = useState(playing);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const trigger = useCallback((isPlaying: boolean) => {
    setIcon(isPlaying);
    setVisible(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setVisible(false), 600);
  }, []);

  useEffect(() => { trigger(playing); }, [playing, trigger]);

  return (
    <div
      className={`absolute inset-0 flex items-center justify-center pointer-events-none z-10 transition-opacity duration-300 ${visible ? "opacity-100" : "opacity-0"}`}
    >
      <div className="w-16 h-16 rounded-full bg-black/50 backdrop-blur-sm flex items-center justify-center">
        {icon ? (
          <svg width="28" height="28" viewBox="0 0 24 24" fill="white" stroke="none">
            <rect x="5" y="3" width="4" height="18" rx="1" />
            <rect x="15" y="3" width="4" height="18" rx="1" />
          </svg>
        ) : (
          <svg width="28" height="28" viewBox="0 0 24 24" fill="white" stroke="none" className="ml-1">
            <path d="M6 4l15 8-15 8V4z" />
          </svg>
        )}
      </div>
    </div>
  );
}

// ─── Scrubber (draggable progress bar) ──────────────────

function Scrubber({ currentTime, totalDuration, onSeek, onScrubStart, onScrubEnd }: {
  currentTime: number;
  totalDuration: number;
  onSeek: (t: number) => void;
  onScrubStart: () => void;
  onScrubEnd: (t: number) => void;
}) {
  const dur = totalDuration || 1;
  const inputRef = useRef<HTMLInputElement>(null);
  const draggingRef = useRef(false);
  const [displayTime, setDisplayTime] = useState(0);

  useEffect(() => {
    if (!draggingRef.current && inputRef.current) {
      const v = Math.round((currentTime / dur) * 1000);
      inputRef.current.value = String(v);
      setDisplayTime(currentTime);
    }
  }, [currentTime, dur]);

  return (
    <div className="flex-1 flex items-center gap-2">
      <input
        ref={inputRef}
        type="range"
        min={0}
        max={1000}
        defaultValue={0}
        onPointerDown={() => { draggingRef.current = true; onScrubStart(); }}
        onPointerUp={() => {
          draggingRef.current = false;
          const v = Number(inputRef.current?.value ?? 0);
          const t = (v / 1000) * dur;
          setDisplayTime(t);
          onScrubEnd(t);
        }}
        onInput={(e) => {
          const v = Number((e.target as HTMLInputElement).value);
          const t = (v / 1000) * dur;
          setDisplayTime(t);
          onSeek(t);
        }}
        className="scrubber flex-1 h-6 cursor-pointer"
      />
      <span className="text-[11px] text-white/60 font-mono text-right shrink-0 select-none whitespace-nowrap">
        {displayTime.toFixed(1)}s/{totalDuration.toFixed(0)}s
      </span>
    </div>
  );
}

// ─── S4: 预览 ──────────────────────────────────────────

function S4Panel({ runId, run }: { runId: number; run: PipelineRun }) {
  const { data: settings } = useSWR<AppSettings>("settings", api.settings.get);
  const { data: timeline } = useSWR<TimelineData>(`timeline-${runId}`, () => api.runs.timeline(runId).catch(() => null as unknown as TimelineData));
  const { showToast } = useToast();
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const [transition, setTransition] = useState("");
  const [sceneGap, setSceneGap] = useState(500);
  const [fps, setFps] = useState("");
  const [subFont, setSubFont] = useState(48);
  const [subLines, setSubLines] = useState(2);
  const [inited, setInited] = useState(false);
  // 已应用到预览的参数快照（仅本地、不写全局配置）。null = 尚未覆盖，预览用落盘 timeline 默认渲染
  const [applied, setApplied] = useState<{ transition: string; sceneGap: number; fps: string; subFont: number; subLines: number } | null>(null);
  // 预览字幕显隐开关（仅控制预览；成片走外挂 SRT 本就不烧字幕）。默认显示
  const [showSubtitles, setShowSubtitles] = useState(true);

  // Playback state (synced via postMessage from iframe)
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [totalDuration, setTotalDuration] = useState(0);

  useEffect(() => {
    if (settings && !inited) {
      setTransition(settings.hyperframes.transition);
      setSceneGap(settings.hyperframes.scene_gap_ms);
      setFps(settings.hyperframes.fps);
      setSubFont(settings.hyperframes.subtitle_font_size);
      setSubLines(settings.hyperframes.subtitle_max_lines);
      setInited(true);
    }
  }, [settings, inited]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === "progress") {
        setCurrentTime(e.data.time ?? 0);
        setTotalDuration(e.data.duration ?? 0);
        setPlaying(!e.data.paused);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const postCmd = (cmd: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(cmd, "*");
  };

  const isHyperframes = run.video_route === "hyperframes";
  const settingsLabel = isHyperframes ? "hyperframes 设置" : "视频设置";

  // 基准 = 已应用快照（若有）否则全局配置；脏 = 当前控件与基准不同
  const base = applied ?? (settings ? {
    transition: settings.hyperframes.transition,
    sceneGap: settings.hyperframes.scene_gap_ms,
    fps: settings.hyperframes.fps,
    subFont: settings.hyperframes.subtitle_font_size,
    subLines: settings.hyperframes.subtitle_max_lines,
  } : null);
  const isDirty = !!base && (
    transition !== base.transition ||
    sceneGap !== base.sceneGap ||
    fps !== base.fps ||
    subFont !== base.subFont ||
    subLines !== base.subLines
  );

  // 重新生成预览：仅把当前参数应用到本次预览（query 覆盖，不写全局配置、不落盘）
  const handleRegenerate = () => {
    setApplied({ transition, sceneGap, fps, subFont, subLines });
    setIframeKey((k) => k + 1);
    setPlaying(false);
    showToast("已应用到预览（未改全局配置）", "success");
  };

  // 预览 URL：应用过则带 query 覆盖参数，让 get_preview_html 按本地值临时渲染
  const previewUrl = (() => {
    const baseUrl = api.runs.previewHtmlUrl(runId);
    if (!applied) return baseUrl;
    const q = new URLSearchParams({
      transition: applied.transition,
      scene_gap_ms: String(applied.sceneGap),
      subtitle_font_size: String(applied.subFont),
      subtitle_max_lines: String(applied.subLines),
    });
    return `${baseUrl}?${q.toString()}`;
  })();
  const previewContainerRef = useRef<HTMLDivElement>(null);
  const [isBrowserFs, setIsBrowserFs] = useState(false);
  const [isViewportFs, setIsViewportFs] = useState(false);
  const [iframeKey, setIframeKey] = useState(0);

  useEffect(() => {
    const handler = () => setIsBrowserFs(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  useEffect(() => {
    if (!isViewportFs) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") setIsViewportFs(false); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isViewportFs]);

  const toggleBrowserFs = () => {
    if (!previewContainerRef.current) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else previewContainerRef.current.requestFullscreen();
  };

  const isExpanded = isBrowserFs || isViewportFs;

  const [canvasW, canvasH] = (() => {
    const parts = (run.resolution || "1080x1920").split("x").map(Number);
    return parts.length === 2 && parts[0] > 0 && parts[1] > 0 ? parts : [1080, 1920];
  })();
  const CONTAINER_H = isExpanded ? window.innerHeight - 60 : 540;
  const scale = Math.min(CONTAINER_H / canvasH, 1);
  const scaledW = Math.round(canvasW * scale);
  const scaledH = Math.round(canvasH * scale);


  const previewCard = (
    <div
      ref={previewContainerRef}
      className={`${isViewportFs ? "" : cardCls} p-4 ${isExpanded ? "bg-black flex flex-col" : ""} ${isViewportFs ? "fixed inset-0 z-50" : ""}`}
    >
      <div className="flex justify-between items-center mb-3">
        <h4 className={sectionTitleCls}>
          {isHyperframes ? "Hyperframes HTML 预览" : "视频预览"}
        </h4>
      </div>
      <div
        className={`flex justify-center rounded-lg bg-black/40 overflow-hidden ${isExpanded ? "flex-1" : ""}`}
        style={isExpanded ? { padding: 8 } : { height: scaledH + 16, padding: 8 }}
      >
        <div
          className="relative rounded overflow-hidden shadow-2xl cursor-pointer"
          style={{ width: scaledW, height: scaledH }}
          onClick={() => {
            if (playing) { postCmd({ type: "pause" }); setPlaying(false); }
            else { postCmd({ type: "play" }); setPlaying(true); }
          }}
        >
          <iframe
            key={iframeKey}
            ref={iframeRef}
            src={previewUrl}
            title="预览"
            onLoad={() => postCmd({ type: "subtitles", show: showSubtitles })}
            className="absolute top-0 left-0 pointer-events-none"
            style={{
              width: canvasW,
              height: canvasH,
              border: "none",
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          />
          <OverlayIndicator playing={playing} />
        </div>
      </div>

      {/* Playback controls */}
      <div className="flex items-center gap-2 mt-3">
        <button
          onClick={() => {
            if (playing) { postCmd({ type: "pause" }); setPlaying(false); }
            else { postCmd({ type: "play" }); setPlaying(true); }
          }}
          className={btnIcon}
          title={playing ? "暂停" : "播放"}
        >
          {playing ? <IconPause /> : <IconPlay />}
        </button>
        <Scrubber
          currentTime={currentTime}
          totalDuration={totalDuration || (timeline?.total_duration_ms ? timeline.total_duration_ms / 1000 : 0)}
          onSeek={(t) => { postCmd({ type: "seek", time: t }); }}
          onScrubStart={() => { postCmd({ type: "pause" }); }}
          onScrubEnd={(t) => { postCmd({ type: "seek", time: t }); if (playing) postCmd({ type: "play" }); }}
        />

        {/* Viewport fullscreen */}
        <button onClick={() => setIsViewportFs((v) => !v)} className={btnIcon} title={isViewportFs ? "退出页面全屏" : "页面全屏"}>
          {isViewportFs ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="4 14 10 14 10 20" /><polyline points="20 10 14 10 14 4" />
              <line x1="14" y1="10" x2="21" y2="3" /><line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" />
              <line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" />
            </svg>
          )}
        </button>

        {/* Browser fullscreen */}
        <button onClick={toggleBrowserFs} className={btnIcon} title={isBrowserFs ? "退出浏览器全屏" : "浏览器全屏"}>
          {isBrowserFs ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3v3a2 2 0 0 1-2 2H3" /><path d="M21 8h-3a2 2 0 0 1-2-2V3" />
              <path d="M3 16h3a2 2 0 0 1 2 2v3" /><path d="M16 21v-3a2 2 0 0 1 2-2h3" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 3H5a2 2 0 0 0-2 2v3" /><path d="M21 8V5a2 2 0 0 0-2-2h-3" />
              <path d="M3 16v3a2 2 0 0 0 2 2h3" /><path d="M16 21h3a2 2 0 0 0 2-2v-3" />
            </svg>
          )}
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Preview player — renders as fixed overlay in viewport-fullscreen mode */}
      {isViewportFs ? (
        <>{previewCard}<div style={{ height: scaledH + 100 }} /></>
      ) : previewCard}

      {/* Editable settings */}
      <div className={`${cardCls} p-5`}>
        <div className="flex justify-between items-center mb-3">
          <h4 className={sectionTitleCls}>{settingsLabel}</h4>
          <div className="flex items-center gap-4">
            <button onClick={handleRegenerate} disabled={!isDirty} className={`${btnCompact} ${isDirty ? "!border-blue-500/30 !text-blue-300" : ""}`}>
              {"重新生成"}
            </button>
            <label className="inline-flex items-center gap-2 cursor-pointer select-none" title="仅控制预览显隐；成片走外挂 SRT，本就不烧字幕">
              <span className="text-sm text-white/76">显示字幕</span>
              <input type="checkbox" checked={showSubtitles}
                onChange={(e) => { setShowSubtitles(e.target.checked); postCmd({ type: "subtitles", show: e.target.checked }); }}
                className="w-4 h-4 accent-blue-500 rounded" />
            </label>
          </div>
        </div>

        {isHyperframes ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>分辨率</label>
              <div className="text-sm text-white/85 font-mono mt-2">{run.resolution || "—"}</div>
            </div>
            <div>
              <label className={labelCls}>转场效果</label>
              <Select value={transition} onChange={setTransition} options={[
                { value: "crossfade", label: "交叉淡入淡出" },
                { value: "fade", label: "淡入淡出" },
                { value: "slide", label: "滑动" },
                { value: "cut", label: "直接切换" },
              ]} />
            </div>
            <div>
              <label className={labelCls}>场景间隔</label>
              <div className="flex items-center gap-2 mt-1">
                <input type="range" min={0} max={2000} step={100} value={sceneGap} onChange={(e) => setSceneGap(Number(e.target.value))} className="flex-1 accent-blue-500" />
                <span className="text-xs text-white/66 w-14 text-right font-mono">{sceneGap}ms</span>
              </div>
            </div>
            <div>
              <label className={labelCls}>字幕字号</label>
              <div className="flex items-center gap-2 mt-1">
                <input type="range" min={24} max={96} step={2} value={subFont} onChange={(e) => setSubFont(Number(e.target.value))} className="flex-1 accent-blue-500" />
                <span className="text-xs text-white/66 w-14 text-right font-mono">{subFont}px</span>
              </div>
            </div>
            <div>
              <label className={labelCls}>字幕最多行数</label>
              <Select value={String(subLines)} onChange={(v) => setSubLines(Number(v))} options={[
                { value: "1", label: "1 行" },
                { value: "2", label: "2 行" },
                { value: "3", label: "3 行" },
              ]} />
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            <div>
              <label className={labelCls}>分辨率</label>
              <div className="text-sm text-white/85 font-mono mt-2">{run.resolution || "—"}</div>
            </div>
            <div>
              <label className={labelCls}>帧率</label>
              <input value={fps} onChange={(e) => setFps(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label className={labelCls}>场景间隔</label>
              <div className="flex items-center gap-2 mt-1">
                <input type="range" min={0} max={2000} step={100} value={sceneGap} onChange={(e) => setSceneGap(Number(e.target.value))} className="flex-1 accent-blue-500" />
                <span className="text-xs text-white/66 w-14 text-right font-mono">{sceneGap}ms</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Timeline */}
      {timeline && (
        <div className={`${cardCls} p-5`}>
          <h4 className={`${sectionTitleCls} mb-3`}>
            时间线 &mdash; {(timeline.total_duration_ms / 1000).toFixed(0)}s &middot; {timeline.entries.length} 个场景
          </h4>
          <div className="space-y-2">
            {timeline.entries.map((e) => (
              <div key={e.scene_id} className="flex items-center gap-3 text-xs">
                <span className="text-white/52 font-mono w-6">S{e.scene_id}</span>
                <div className="flex-1 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500/40 rounded-full" style={{ width: `${((e.end_ms - e.start_ms) / timeline.total_duration_ms) * 100}%` }} />
                </div>
                <span className="text-white/60 w-10 text-right">{((e.end_ms - e.start_ms) / 1000).toFixed(1)}s</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── S5: 合成渲染 ──────────────────────────────────────

function S5Panel({ runId, run }: { runId: number; run: PipelineRun }) {
  const [rendering, setRendering] = useState(false);
  const { showToast } = useToast();
  const audioOnly = run.video_route === "audio";
  const actionLabel = audioOnly ? "合成" : "渲染";

  const handleRender = async () => {
    setRendering(true);
    try { await api.runs.triggerRender(runId); showToast(`开始${actionLabel}...`, "success"); }
    catch { showToast(`${actionLabel}启动失败`, "error"); setRendering(false); }
  };

  // 重新渲染后完成时间变化 → cache-bust，确保播放器加载新成片而非旧缓存
  const mediaSrc = `${api.runs.videoUrl(runId)}?t=${encodeURIComponent(run.finished_at ?? "")}`;

  if (!run.output_path) {
    const isRendering = (run.current_stage === 5 && run.status === "processing") || rendering;
    return (
      <div className={`${cardCls} p-8 text-center`}>
        {isRendering ? (
          <div>
            <div className="text-white/66 text-sm mb-1">{actionLabel}中...</div>
            {run.progress_detail && <div className="text-xs text-white/52">{run.progress_detail}</div>}
          </div>
        ) : (
          <div>
            <p className="text-white/60 text-sm mb-4">{audioOnly ? "尚未合成音频" : "尚未渲染成片"}</p>
            <button onClick={handleRender} disabled={rendering} className={btnPrimary}>{audioOnly ? "合成音频" : "渲染成片"}</button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className={`${cardCls} p-5`}>
      {audioOnly ? (
        <audio controls className="w-full max-w-2xl mx-auto" src={mediaSrc} />
      ) : (
        <video controls className="w-full max-w-2xl mx-auto rounded-lg" src={mediaSrc} />
      )}
      <div className="flex justify-center gap-3 mt-4">
        <a href={api.runs.videoUrl(runId)} download className={btnPrimary}>{audioOnly ? "下载 MP3" : "下载 MP4"}</a>
        {!audioOnly && (
          <a href={api.runs.subtitlesUrl(runId)} download className={btnCompact}>下载字幕</a>
        )}
        <button onClick={handleRender} disabled={rendering} className={btnCompact}>
          {rendering ? `${actionLabel}中...` : `重新${actionLabel}`}
        </button>
      </div>
    </div>
  );
}

// ─── S6: 发布 ──────────────────────────────────────────

function S6Panel({ runId, run }: { runId: number; run: PipelineRun }) {
  const { data: targets } = useSWR("publishers", api.publishers.list);
  const { data: results, mutate: mutateResults } = useSWR<PublishResultRec[]>(
    `publish-results-${runId}`,
    () => api.runs.publishResults(runId).catch(() => [] as PublishResultRec[]),
    // SSE 的 publish 事件驱动刷新；仅保留低频兜底
    { refreshInterval: run.status === "processing" ? 20000 : 0 },
  );
  const [publishing, setPublishing] = useState(false);
  const { publishTick } = useContext(RunEventsContext);
  const { showToast } = useToast();

  // 发布状态变化（开始/完成）或收到 publish 事件时刷新结果
  useEffect(() => { mutateResults(); }, [run.status, run.finished_at, publishTick, mutateResults]);

  // publish_platforms 存的是发布账号 id
  const ids: string[] = (() => { try { return JSON.parse(run.publish_platforms); } catch { return []; } })();
  if (ids.length === 0) return <p className="text-white/60 text-sm">未选择发布账号</p>;
  const byId = new Map((targets ?? []).map((t) => [String(t.id), t]));
  const resultByName = new Map((results ?? []).map((r) => [r.target_name ?? r.platform, r]));
  const isPublishing = (run.current_stage === 6 && run.status === "processing") || publishing;
  const hasResults = (results ?? []).length > 0;
  const noOutput = !run.output_path;

  const handlePublish = async () => {
    setPublishing(true);
    try { await api.runs.triggerPublish(runId); showToast("开始发布...", "success"); mutateResults(); }
    catch (e) { showToast(e instanceof Error ? e.message : "发布启动失败", "error"); setPublishing(false); }
  };

  return (
    <div>
      <div className="space-y-2 mb-3">
        {ids.map((id) => {
          const t = byId.get(String(id));
          const name = t ? t.name : `账号 #${id}`;
          const r = resultByName.get(name);
          return (
            <div key={id} className={`${cardCls} p-4 flex justify-between items-center gap-3`}>
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-sm truncate">{name}</span>
                {t && (
                  <span className={`${chipCls} bg-white/[0.06] text-white/66`}>
                    {PLATFORM_LABELS[t.platform] ?? t.platform}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {r?.status === "success" ? (
                  <>
                    <span className={`${chipCls} bg-green-500/15 text-green-300`}>成功</span>
                    {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="text-xs text-blue-300 hover:underline">查看</a>}
                  </>
                ) : r ? (
                  <span className={`${chipCls} bg-red-500/15 text-red-300`} title={r.error_message ?? ""}>失败</span>
                ) : isPublishing ? (
                  <span className={`${chipCls} bg-white/[0.06] text-white/66`}>发布中...</span>
                ) : (
                  <span className={`${chipCls} bg-white/[0.06] text-white/66`}>等待中</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {(results ?? []).filter((r) => r.status !== "success" && r.error_message).map((r, i) => (
        <p key={i} className="text-xs text-red-300/70 mb-1 break-all">· {r.target_name ?? r.platform}：{r.error_message}</p>
      ))}

      <div className="flex justify-end mt-3">
        <button onClick={handlePublish} disabled={isPublishing || noOutput} className={btnPrimary}
          title={noOutput ? "尚无成片，请先完成渲染（S5）" : ""}>
          {isPublishing ? "发布中..." : hasResults ? "重新发布" : "发布"}
        </button>
      </div>
    </div>
  );
}

// ─── Stage router ──────────────────────────────────────

function StagePanel({ stage, runId, run }: { stage: number; runId: number; run: PipelineRun }) {
  switch (stage) {
    case 1: return <S1Panel runId={runId} run={run} />;
    case 2: return <S2Panel runId={runId} run={run} audioOnly={run.video_route === "audio"} />;
    case 4: return <S4Panel runId={runId} run={run} />;
    case 5: return <S5Panel runId={runId} run={run} />;
    case 6: return <S6Panel runId={runId} run={run} />;
    default: return null;
  }
}

// ─── Run Workspace ──────────────────────────────────────

function RunWorkspace({ run, mutateRuns }: { run: PipelineRun; mutateRuns: () => void }) {
  const { data: freshRun, mutate: mutateRun } = useSWR<PipelineRun>(`run-${run.id}`, () => api.runs.get(run.id), {
    // SSE 实时驱动；仅保留低频兜底，防代理偶发断流导致状态卡住
    refreshInterval: run.status === "processing" || run.status === "pending" ? 20000 : 0,
    fallbackData: run,
  });
  const r = freshRun ?? run;

  // 单一 EventSource：progress→刷新本 run/列表；asset→记场景就绪；publish→通知 S6 刷新
  const [sceneTick, setSceneTick] = useState<Record<number, number>>({});
  const [publishTick, setPublishTick] = useState(0);
  useEffect(() => {
    if (!(r.status === "processing" || r.status === "pending")) return;
    const es = new EventSource(api.runs.eventsUrl(run.id));
    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data) as { type?: string; scene?: number; status?: string };
        if (ev.type === "progress") { mutateRun(); mutateRuns(); }
        else if (ev.type === "asset" && typeof ev.scene === "number") setSceneTick((m) => ({ ...m, [ev.scene as number]: Date.now() }));
        else if (ev.type === "publish") setPublishTick(Date.now());
        else if (ev.type === "end") es.close();
      } catch { /* 忽略心跳 */ }
    };
    es.onerror = () => { /* 浏览器自动重连；run 结束由 effect 清理 */ };
    return () => es.close();
  }, [run.id, r.status, mutateRun, mutateRuns]);

  const mapToVisual = (cs: number | null): number => {
    if (!cs) return VISIBLE_STAGES[0];
    if (cs === 3) return 2;
    return (VISIBLE_STAGES as readonly number[]).includes(cs) ? cs : VISIBLE_STAGES[0];
  };

  const [activeStage, setActiveStage] = useState<number>(() => mapToVisual(r.current_stage));

  useEffect(() => {
    if (r.current_stage) setActiveStage(mapToVisual(r.current_stage));
  }, [r.current_stage]);

  const handleResume = async () => {
    await api.runs.resume(r.id);
    mutateRun();
    mutateRuns();
  };

  // 自动模式且流程进行中：各阶段面板只读、不可切到尚未到达的阶段（仅可回看已完成）
  const locked = r.mode === "auto" && (r.status === "processing" || r.status === "pending");

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold">任务 #{r.id}</span>
          <span className={`${chipCls} ${STATUS_CHIP[r.status] ?? ""}`}>{STATUS_LABEL[r.status] ?? r.status}</span>
          {r.progress_detail && <span className="text-xs text-white/60">{r.progress_detail}</span>}
        </div>
        {r.status === "review" && (
          <button onClick={handleResume} className={btnApprove}>
            审核通过并继续
          </button>
        )}
      </div>

      {r.error_message && (
        <div className="rounded-xl bg-red-500/[0.06] border border-red-500/20 p-4 mb-4">
          <p className={`text-xs ${errorTextCls}`}>{r.error_message}</p>
        </div>
      )}

      <Stepper run={r} onSelect={setActiveStage} activeStage={activeStage} locked={locked} />
      <RunEventsContext.Provider value={{ sceneTick, publishTick }}>
        <fieldset disabled={locked} className="min-w-0 border-0 p-0 m-0">
          <StagePanel stage={activeStage} runId={r.id} run={r} />
        </fieldset>
      </RunEventsContext.Provider>
    </div>
  );
}

// ─── Dashboard Page ─────────────────────────────────────

export function DashboardPage() {
  // 列表由展开任务的 SSE(progress)驱动 mutate；仅保留低频兜底覆盖新建/删除/断流
  const { data: runs, mutate } = useSWR<PipelineRun[]>("runs", api.runs.list, { refreshInterval: 15000 });
  const [showCreate, setShowCreate] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PipelineRun | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [pendingStop, setPendingStop] = useState<PipelineRun | null>(null);
  const [stopping, setStopping] = useState(false);
  const { showToast } = useToast();

  useEffect(() => {
    if (runs && runs.length > 0 && expandedId === null) {
      const active = runs.find((r) => r.status === "processing" || r.status === "review");
      if (active) setExpandedId(active.id);
      else setExpandedId(runs[0].id);
    }
  }, [runs, expandedId]);

  const confirmStop = async () => {
    if (!pendingStop) return;
    setStopping(true);
    try {
      await api.runs.stop(pendingStop.id);
      showToast("已请求终止", "success");
      mutate();
      setPendingStop(null);
    } catch {
      showToast("终止失败", "error");
    } finally {
      setStopping(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.runs.remove(pendingDelete.id);
      showToast("任务已删除", "success");
      if (expandedId === pendingDelete.id) setExpandedId(null);
      mutate();
      setPendingDelete(null);
    } catch {
      showToast("删除失败", "error");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">工作台</h1>
        <button onClick={() => setShowCreate(true)} className={btnPrimary}>+ 新建任务</button>
      </div>

      <div className="flex gap-2 mb-6 flex-wrap">
        {runs?.map((run) => {
          const d = new Date(run.created_at);
          const ts = `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
          return (
            <div
              key={run.id}
              onClick={() => setExpandedId(run.id)}
              className={`flex items-center gap-1.5 pl-1.5 pr-3 py-1.5 rounded-lg text-sm transition border cursor-pointer ${
                expandedId === run.id
                  ? "bg-white/[0.08] border-white/[0.12] text-white"
                  : "bg-white/[0.02] border-white/[0.06] text-white/66 hover:text-white/85 hover:bg-white/[0.04]"
              }`}
            >
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); setPendingDelete(run); }}
                disabled={run.status === "processing"}
                title={run.status === "processing" ? "任务正在运行，无法删除" : "删除此任务"}
                className={btnDeleteIcon}
              >
                ×
              </button>
              <span className="font-mono text-xs">#{run.id}</span>
              <span className="text-xs text-white/52">{ts}</span>
              <span className={`${chipCls} ${STATUS_CHIP[run.status] ?? ""} text-[10px]`}>{STATUS_LABEL[run.status] ?? run.status}</span>
              {run.status === "processing" && (
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); setPendingStop(run); }}
                  title="终止此任务"
                  aria-label="终止此任务"
                  className="ml-1 inline-flex items-center justify-center p-1 rounded text-red-300 bg-red-500/15 border border-red-500/25 hover:bg-red-500/25 transition"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                  </svg>
                </button>
              )}
            </div>
          );
        })}
        {(!runs || runs.length === 0) && (
          <p className="text-white/60 text-sm">暂无任务，点击上方按钮创建</p>
        )}
      </div>

      {expandedId && runs && runs.find((r) => r.id === expandedId) && (
        <RunWorkspace run={runs.find((r) => r.id === expandedId)!} mutateRuns={mutate} />
      )}

      {showCreate && (
        <CreateRunDialog
          onCreated={() => { setShowCreate(false); mutate(); }}
          onClose={() => setShowCreate(false)}
        />
      )}

      {pendingDelete && (
        <div className={dialogOverlayCls} onClick={() => { if (!deleting) setPendingDelete(null); }}>
          <div className={`${dialogPanelCls} w-[360px]`} onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold mb-2">删除任务 #{pendingDelete.id}</h2>
            <p className="text-sm text-white/76 mb-5 leading-relaxed">将一并删除该任务的所有文件，此操作不可恢复。</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setPendingDelete(null)} disabled={deleting} className={btnSecondary}>取消</button>
              <button onClick={confirmDelete} disabled={deleting} className={btnDelete}>
                {deleting ? "删除中..." : "删除"}
              </button>
            </div>
          </div>
        </div>
      )}

      {pendingStop && (
        <div className={dialogOverlayCls} onClick={() => { if (!stopping) setPendingStop(null); }}>
          <div className={`${dialogPanelCls} w-[360px]`} onClick={(e) => e.stopPropagation()}>
            <h2 className="text-lg font-semibold mb-2">终止任务 #{pendingStop.id}</h2>
            <p className="text-sm text-white/76 mb-5 leading-relaxed">正在进行的步骤会在当前操作完成后停止。</p>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setPendingStop(null)} disabled={stopping} className={btnSecondary}>取消</button>
              <button onClick={confirmStop} disabled={stopping} className={btnDelete}>
                {stopping ? "终止中..." : "终止"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
