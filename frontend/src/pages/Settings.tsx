import { useState, useEffect, useRef, useLayoutEffect, useCallback } from "react";
import useSWR from "swr";
import { api, type AppSettings, type AuthUser, type ProviderCreds, type OpenAIAuthStatus } from "../api/client";
import { useToast } from "../components/Toast";
import { Select } from "../components/Select";
import { PasswordInput } from "../components/PasswordInput";
import { IconButton } from "../components/IconButton";
import { EraserIcon } from "../components/icons";
import {
  inputCls as _inputCls,
  monoInputCls as _monoInputCls,
  btnPrimary,
  btnConfirm,
  btnDeleteCompact,
  btnAdd,
  sectionTitleCls,
  cx,
} from "../styles";

// ---------------------------------------------------------------------------
// Provider presets — auto-fill URL + latest models
// ---------------------------------------------------------------------------

interface ProviderPreset {
  label: string;
  baseUrl: string;
  models: string[];
  needsKey?: boolean;
}

// 每种 workflow 可调的生成参数 + 范围/说明。无 steps/cfg 字段表示该项锁死，note 给出原因。
type ParamMeta = {
  steps?: { min: number; max: number; desc: string };
  cfg?: { min: number; max: number; desc: string };
  note?: string;
};
// ComfyUI 图片 workflow 的可调参数（均为单 KSampler）。
const IMAGE_PARAM_META: Record<string, ParamMeta> = {
  "z_image_turbo": {
    steps: { min: 4, max: 20, desc: "采样步数，z_image turbo 蒸馏，8–9 步即可（默认 9）" },
    cfg: { min: 1, max: 5, desc: "提示词遵循强度，turbo 建议 1.0（默认 1.0）" },
  },
  "qwen_image": {
    steps: { min: 10, max: 40, desc: "采样步数，越大越精细越慢（默认 20）" },
    cfg: { min: 1, max: 6, desc: "提示词遵循强度（默认 2.5）" },
  },
};
const VIDEO_PARAM_META: Record<string, ParamMeta> = {
  "wan2.2_5b": {
    steps: { min: 10, max: 50, desc: "采样步数，越大越精细越慢（默认 30）" },
    cfg: { min: 1, max: 10, desc: "提示词遵循强度，越大越贴提示词（默认 5.0）" },
  },
  "wan2.2_14b": {
    steps: { min: 10, max: 40, desc: "采样步数（默认 20）；高/低噪切换点自动取步数一半" },
    cfg: { min: 1, max: 10, desc: "提示词遵循强度（默认 3.5）" },
  },
  "wan2.2_14b_lightx2v": {
    note: "加速 LoRA 固定 4 步、cfg≈1.0，步数与 cfg 均不可调。追求质量请改用 wan2.2_14b。",
  },
  "ltx_2.3": {
    cfg: { min: 1, max: 5, desc: "提示词遵循强度（默认 1.0）" },
    note: "蒸馏模型步数固定（约 4 步），无法调整。",
  },
};

// 语音供应商（与文本/图片对齐，共用 key）：edge-tts 免费、openai、dashscope
const TTS_PRESETS: Record<string, ProviderPreset> = {
  "edge-tts": { label: "微软 Edge TTS", baseUrl: "", models: [], needsKey: false },
  "openai": { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"], needsKey: true },
  "dashscope": { label: "阿里云 DashScope", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen3-tts-flash"], needsKey: true },
};

// 音色按「供应商 + 模型」区分（dashscope 的 qwen-tts 与 cosyvoice 音色完全不同）。value = API 实际音色参数。
type Voice = { value: string; label: string };
const VOICES_EDGE: Voice[] = [
  { value: "zh-CN-XiaoxiaoNeural", label: "晓晓 (女)" },
  { value: "zh-CN-YunxiNeural", label: "云希 (男)" },
  { value: "zh-CN-XiaohanNeural", label: "晓涵 (女)" },
  { value: "zh-CN-YunyangNeural", label: "云扬 (男·播报)" },
  { value: "en-US-JennyNeural", label: "Jenny (Female)" },
  { value: "en-US-GuyNeural", label: "Guy (Male)" },
  { value: "en-US-AriaNeural", label: "Aria (Female)" },
];
const VOICES_OPENAI: Voice[] = [
  { value: "alloy", label: "Alloy" }, { value: "ash", label: "Ash" }, { value: "coral", label: "Coral" },
  { value: "echo", label: "Echo" }, { value: "fable", label: "Fable" }, { value: "nova", label: "Nova" },
  { value: "onyx", label: "Onyx" }, { value: "sage", label: "Sage" }, { value: "shimmer", label: "Shimmer" },
];
const VOICES_QWEN: Voice[] = [
  { value: "Cherry", label: "芊悦·阳光自然女" }, { value: "Ryan", label: "甜茶·美剧张力男" },
  { value: "Marcus", label: "秦川·陕北汉子" }, { value: "Seren", label: "小婉·舒缓女声" },
  { value: "EldricSage", label: "沧明子·沧桑老者" }, { value: "Ethan", label: "晨煦·北方口音男" },
  { value: "Katerina", label: "卡捷琳娜·御姐深情女" }, { value: "Roy", label: "阿杰·闽南哥仔" },
  { value: "Dylan", label: "晓东·北京少年" }, { value: "Dolce", label: "多尔切·慵懒大叔" },
  { value: "Nofish", label: "不吃鱼·南方口音男" }, { value: "Elias", label: "墨讲师·学术讲师" },
  { value: "Andre", label: "安德雷·葡萄牙男声" }, { value: "Kiki", label: "阿清·甜美港妹(粤)" },
  { value: "Sohee", label: "素熙·温柔欧尼" }, { value: "Jennifer", label: "詹妮弗·美剧大女主" },
  { value: "Li", label: "老李·南京大叔" }, { value: "Chelsie", label: "千雪·乖巧柔弱" },
  { value: "Sunny", label: "晴儿·甜飒川妹" },
];
const VOICES_COSYVOICE: Voice[] = [
  { value: "longanhuan_v3", label: "龙安欢·欢脱元气女" }, { value: "longyingtao_v3", label: "龙应桃·温柔淡定女" },
  { value: "loongtomoka_v3", label: "Tomoka·日语女" }, { value: "longyan_v3", label: "龙颜温·暖春风女" },
  { value: "longyichen_v3", label: "龙逸尘·洒脱活力男" }, { value: "longdaiyu_v3", label: "龙黛玉·娇率才女" },
  { value: "longanyang_v3", label: "龙安洋·阳光大男孩" }, { value: "longsanshu_v3", label: "龙三叔·沉稳质感男" },
  { value: "longyuan_v3", label: "龙媛温·暖治愈女" }, { value: "longjielidou_v3", label: "龙杰力豆·阳光顽皮男" },
  { value: "longhuhu_v3", label: "龙呼呼·天真烂漫女童" }, { value: "longlaoyi_v3", label: "龙老姨·烟火从容阿姨" },
  { value: "loongdavid_v3", label: "David·美式英文男" }, { value: "longyingxiao_v3", label: "龙应笑·清甜推销女" },
  { value: "longling_v3", label: "龙铃·稚气呆板女" }, { value: "longanxuan_v3", label: "龙安宣·经典直播女" },
  { value: "longanli_v3", label: "龙安莉·利落从容女" }, { value: "longwanjun_v3", label: "龙婉君·细腻柔声女" },
  { value: "longyue_v3", label: "龙悦温·暖磁性女" }, { value: "longxiaoxia_v3", label: "龙小夏·沉稳权威女" },
];
// 按 供应商+模型 取音色列表
const voicesFor = (provider: string, model: string): Voice[] => {
  if (provider === "openai") return VOICES_OPENAI;
  if (provider === "edge-tts") return VOICES_EDGE;
  if (provider === "dashscope") return model.startsWith("cosyvoice") ? VOICES_COSYVOICE : VOICES_QWEN;
  return [];
};

// ---------------------------------------------------------------------------
// Shared UI components
// ---------------------------------------------------------------------------

const inputCls = _inputCls;
const monoInputCls = _monoInputCls;

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-6 space-y-5">
      <div>
        <h3 className={sectionTitleCls}>{title}</h3>
        {desc && <p className="text-xs text-white/60 mt-0.5">{desc}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, desc, children, center }: { label: string; desc?: string; children: React.ReactNode; center?: boolean }) {
  return (
    <div className={`grid grid-cols-[11rem_1fr] gap-4 ${center ? "items-center" : "items-start"}`}>
      <label className={`text-sm text-white/66 select-none ${center ? "" : "pt-2"}`}>
        {label}
        {desc && <span className="block text-xs text-white/52 mt-0.5 font-normal">{desc}</span>}
      </label>
      <div>{children}</div>
    </div>
  );
}

// 按 ParamMeta 渲染某 workflow 的 steps/cfg 输入与锁定说明；图片、视频两区共用。
function ParamFields({ meta, params, onChange }: {
  meta: ParamMeta;
  params: { steps: number; cfg: number };
  onChange: (next: Partial<{ steps: number; cfg: number }>) => void;
}) {
  return (
    <>
      {meta.steps && (
        <Field label="采样步数" center>
          <div className="flex items-center gap-3">
            <div className="w-24 shrink-0">
              <input type="number" value={params.steps} min={meta.steps.min} max={meta.steps.max}
                onChange={(e) => onChange({ steps: Number(e.target.value) })} className={inputCls} />
            </div>
            <span className="text-xs text-white/60 leading-snug">{meta.steps.desc}；范围 {meta.steps.min}–{meta.steps.max}</span>
          </div>
        </Field>
      )}
      {meta.cfg && (
        <Field label="CFG" center>
          <div className="flex items-center gap-3">
            <div className="w-24 shrink-0">
              <input type="number" step={0.5} value={params.cfg} min={meta.cfg.min} max={meta.cfg.max}
                onChange={(e) => onChange({ cfg: Number(e.target.value) })} className={inputCls} />
            </div>
            <span className="text-xs text-white/60 leading-snug">{meta.cfg.desc}；范围 {meta.cfg.min}–{meta.cfg.max}</span>
          </div>
        </Field>
      )}
      {meta.note && <p className="text-xs text-amber-300/60 pl-1">{meta.note}</p>}
    </>
  );
}

function SecretField({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <Field label={label}>
      <PasswordInput value={value} onChange={onChange} placeholder={placeholder ?? "sk-..."} className={monoInputCls} />
    </Field>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// 横铺 tab 按钮条（供应商 / workflow 选择共用）；className 可覆盖默认底部间距
function TabStrip({ tabs, active, onSelect, className }: {
  tabs: { key: string; label: string }[]; active: string; onSelect: (k: string) => void; className?: string;
}) {
  return (
    <div className={`flex flex-wrap gap-1.5 ${className ?? "mb-5"}`}>
      {tabs.map((t) => (
        <button key={t.key} type="button" onClick={() => onSelect(t.key)}
          className={`px-2.5 py-1 text-xs rounded-md transition ${active === t.key ? "bg-blue-500/15 text-blue-300 border border-blue-400/30" : "bg-white/[0.03] text-white/70 border border-white/[0.06] hover:text-white/92"}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

// 一条提示词（中文+英文两框）：值=预设自身内容（空则显示为空框），内置默认作为 placeholder 灰显提示。
// 高度自适应：空值时按 placeholder 撑高，保证默认提示词也能完整可见；两框取较大值保持等高；+6px 消除滚动条。
function PromptRow({ label, desc, zhValue, enValue, zhPlaceholder, enPlaceholder, onZh, onEn }: {
  label: string; desc: string; zhValue: string; enValue: string;
  zhPlaceholder: string; enPlaceholder: string;
  onZh: (v: string) => void; onEn: (v: string) => void;
}) {
  const zhRef = useRef<HTMLTextAreaElement | null>(null);
  const enRef = useRef<HTMLTextAreaElement | null>(null);
  const maxPx = 600;
  useLayoutEffect(() => {
    const a = zhRef.current, b = enRef.current;
    if (!a || !b) return;
    // 测高时：空值临时按 placeholder 撑开（placeholder 本身不计入 scrollHeight），测完还原受控空值
    const measure = (el: HTMLTextAreaElement) => {
      const empty = !el.value;
      if (empty) el.value = el.placeholder;
      el.style.height = "auto";
      const h = el.scrollHeight;
      if (empty) el.value = "";
      return h;
    };
    const h = Math.min(Math.max(measure(a), measure(b)) + 6, maxPx); // +6 抵消边框/亚像素，消滚动条
    a.style.height = `${h}px`; b.style.height = `${h}px`;
  }, [zhValue, enValue, zhPlaceholder, enPlaceholder]);
  const ta = "w-full bg-white/[0.03] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/96 font-mono leading-relaxed resize-y focus:outline-none focus:border-blue-400/40 placeholder:text-white/35";
  const badge = "inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium";
  return (
    <div className="mb-5">
      <label className="text-sm text-white/92">{label}<span className="text-white/60 text-xs ml-2">{desc}</span></label>
      <div className="grid grid-cols-2 gap-3 mt-1.5">
        <div>
          <div className="flex items-center mb-1">
            <span className={`${badge} bg-blue-500/15 text-blue-300`}>中文</span>
          </div>
          <textarea ref={zhRef} value={zhValue} placeholder={zhPlaceholder} onChange={(e) => onZh(e.target.value)} className={ta} style={{ maxHeight: maxPx }} />
        </div>
        <div>
          <div className="flex items-center mb-1">
            <span className={`${badge} bg-violet-500/15 text-violet-300`}>English</span>
          </div>
          <textarea ref={enRef} value={enValue} placeholder={enPlaceholder} onChange={(e) => onEn(e.target.value)} className={ta} style={{ maxHeight: maxPx }} />
        </div>
      </div>
    </div>
  );
}

// 提示词预设切换条：5 个 chip（单击切换、双击重命名）+ 右侧清空（橡皮擦，二次确认，仅清空当前预设内容）。
function PresetBar({ presets, active, onSwitch, onRename, onClear }: {
  presets: { name: string; values: Record<string, string> }[];
  active: number;
  onSwitch: (i: number) => void;
  onRename: (i: number, name: string) => void;
  onClear: () => void;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [editWidth, setEditWidth] = useState<number>(0);  // 重命名输入框宽度 = 被双击 chip 的实际宽度
  const [confirming, setConfirming] = useState(false);
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const beginRename = (i: number, width: number) => {
    setEditing(i);
    setDraft(presets[i]?.name || `预设 ${i + 1}`);
    setEditWidth(width);
  };
  const commitRename = () => {
    if (editing === null) return;
    onRename(editing, draft.trim() || `预设 ${editing + 1}`);
    setEditing(null);
  };
  const clickClear = () => {
    if (confirming) {
      if (confirmTimer.current) clearTimeout(confirmTimer.current);
      setConfirming(false);
      onClear();
    } else {
      setConfirming(true);
      confirmTimer.current = setTimeout(() => setConfirming(false), 3000);  // 3 秒内未再次点击则取消
    }
  };

  return (
    <div className="flex items-center gap-2 mt-3">
      <div className="flex flex-wrap gap-1.5">
        {presets.map((p, i) => (
          editing === i ? (
            <input key={i} autoFocus value={draft}
              style={{ width: editWidth, boxSizing: "border-box" }}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setEditing(null); }}
              className="px-3 py-1 text-xs rounded-md bg-white/[0.06] text-white border border-blue-400/50 focus:outline-none" />
          ) : (
            <button key={i} onClick={() => onSwitch(i)} onDoubleClick={(e) => beginRename(i, e.currentTarget.offsetWidth)}
              title="单击切换 · 双击重命名"
              className={`min-w-[88px] px-3 py-1 text-xs rounded-md border transition ${
                i === active
                  ? "bg-blue-500/20 text-white/92 border-blue-400/40 font-medium"
                  : "bg-white/[0.04] text-white/70 border-white/[0.08] hover:text-white/92"
              }`}>
              {p.name || `预设 ${i + 1}`}
            </button>
          )
        ))}
      </div>
      <div className="ml-auto">
        <IconButton onClick={clickClear} title={confirming ? "再次点击确认清空当前预设" : "清空当前预设内容"}
          className={`p-1.5 ${confirming ? "text-red-300 bg-red-500/15 rounded-md" : ""}`}>
          <EraserIcon size={16} />
        </IconButton>
      </div>
    </div>
  );
}

// ComfyUI 地址输入 + 右侧「测试连接」：探测 {url}/system_stats，绿/红状态指示。测的是输入框当前值（含未保存）。
function ComfyuiHealthField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [state, setState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [msg, setMsg] = useState("");
  const test = async () => {
    setState("testing"); setMsg("");
    try {
      const r = await api.settings.comfyuiHealth(value);
      if (r.ok) { setState("ok"); setMsg(r.detail || "在线"); }
      else { setState("fail"); setMsg(r.error || "不可达"); }
    } catch (e) {
      setState("fail"); setMsg(e instanceof Error ? e.message : "请求失败");
    }
  };
  return (
    <div>
      <div className="flex gap-2 items-center">
        <input value={value} onChange={(e) => { onChange(e.target.value); setState("idle"); }} className={`${monoInputCls} flex-1`} />
        <button onClick={test} disabled={state === "testing" || !value.trim()}
          className={cx("shrink-0 px-3 py-2 text-xs rounded-md bg-white/[0.05] text-white/78 border border-white/[0.08] hover:text-white/96 transition",
            (state === "testing" || !value.trim()) && "opacity-40 cursor-default")}>
          {state === "testing" ? "测试中…" : "测试连接"}
        </button>
      </div>
      {(state === "ok" || state === "fail") && (
        <p className={cx("text-xs mt-1.5 flex items-center gap-1.5", state === "ok" ? "text-emerald-300" : "text-red-300")}>
          <span className={cx("inline-block w-2 h-2 rounded-full shrink-0", state === "ok" ? "bg-emerald-400" : "bg-red-400")} />
          <span className="break-all">{state === "ok" ? `已连接 · ${msg}` : `连接失败：${msg}`}</span>
        </p>
      )}
    </div>
  );
}

// 分组内「添加自定义供应商」一行：自带输入态，加后回调父级（小一号按钮）
function AddProviderInline({ onAdd }: { onAdd: (name: string) => void }) {
  const [v, setV] = useState("");
  const add = () => { const n = v.trim(); if (n) onAdd(n); setV(""); };
  return (
    <div className="flex gap-2 mb-4">
      <input value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }}
        placeholder="自定义供应商名，如 deepseek / siliconflow" className={inputCls} />
      <button onClick={add} className="shrink-0 px-2.5 py-1 text-xs rounded-md bg-white/[0.05] text-white/78 border border-white/[0.08] hover:text-white/96 transition">
        + 添加供应商
      </button>
    </div>
  );
}

// 模型名列表编辑：tag 形式增删，回车/＋ 添加
function ModelListEditor({ label, models, onChange }: {
  label: string; models: string[]; onChange: (m: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const add = () => {
    const v = input.trim();
    if (v && !models.includes(v)) onChange([...models, v]);
    setInput("");
  };
  return (
    <Field label={label}>
      <div className="space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {models.map((m) => (
            <span key={m} className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-white/[0.06] text-sm text-white/92 font-mono">
              {m}
              <button onClick={() => onChange(models.filter((x) => x !== m))} className="text-white/60 hover:text-red-300">×</button>
            </span>
          ))}
          {models.length === 0 && <span className="text-xs text-white/52">暂无，下方添加模型名</span>}
        </div>
        <div className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") add(); }}
            placeholder="模型名，回车添加" className={inputCls} />
          <button onClick={add} className={btnPrimary}>+</button>
        </div>
      </div>
    </Field>
  );
}

// 流水线选型一行：供应商下拉 + 模型下拉（均不可编辑；模型候选来自该供应商对应类型的模型列表，
// 在「模型配置」页维护。切换供应商时由父级把模型重置为新供应商的首个模型）
function PurposeSelect({ label, desc, providerKeys, provider, model, modelOptions, modelLabels, onProvider, onModel }: {
  label: string; desc?: string; providerKeys: string[];
  provider: string; model: string; modelOptions: string[]; modelLabels?: Record<string, string>;
  onProvider: (v: string) => void; onModel: (v: string) => void;
}) {
  const provOptions = providerKeys.map((k) => ({ value: k, label: PROVIDER_LABELS[k] ?? k }));
  // 当前模型若不在候选列表也并入，避免下拉显示空白
  const names = model && !modelOptions.includes(model) ? [model, ...modelOptions] : modelOptions;
  const modelOpts = names.length ? names.map((m) => ({ value: m, label: modelLabels?.[m] ?? m })) : [{ value: "", label: "无可选模型，去「模型配置」添加" }];
  return (
    <Field label={label} desc={desc}>
      <div className="grid grid-cols-2 gap-2">
        <Select value={provider} onChange={onProvider} options={provOptions} />
        <Select value={model} onChange={onModel} options={modelOpts} />
      </div>
    </Field>
  );
}

const EMPTY_SETTINGS: AppSettings = {
  providers: {
    openai: { base_url: "https://api.openai.com/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    dashscope: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    "edge-tts": { base_url: "", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
  },
  collectors: { tavily_key: "", brave_key: "", serper_key: "" },
  pipeline: {
    default_time_range: "7d", default_max_articles: 5, default_video_route: "comfyui",
    default_language: "zh", dedup_lookback: "30d", resolution: "1080x1920", max_images: 10,
    summary_provider: "openai", summary_model: "gpt-5", summary_max_length: 150,
    script_provider: "openai", script_model: "gpt-5.5",
    image_provider: "comfyui", image_model: "z_image_turbo",
    vision_provider: "openai", vision_model: "gpt-4o",
    tts_provider: "edge-tts", tts_model: "", tts_voice: "zh-CN-XiaoxiaoNeural",
    video_model: "wan2.2_5b", video_fps: 24,
  },
  storage: { work_dir: "", output_dir: "" },
  hyperframes: { fps: "30", scene_gap_ms: 500, transition: "crossfade", subtitle_font_size: 48, subtitle_max_lines: 2, subtitle_bottom_px: 80 },
  comfyui: { server_url: "http://127.0.0.1:8188", default_negative: "模糊, 丑陋, 变形, 低质量, 水印", wake: { enabled: false, mac: "", broadcast: "255.255.255.255", port: 9, ready_timeout: 180, poll_interval: 3 }, image_params: { "z_image_turbo": { steps: 9, cfg: 1.0 }, "qwen_image": { steps: 20, cfg: 2.5 } }, video_params: { "wan2.2_5b": { steps: 30, cfg: 5.0 }, "wan2.2_14b": { steps: 20, cfg: 3.5 }, "wan2.2_14b_lightx2v": { steps: 4, cfg: 1.0 }, "ltx_2.3": { steps: 4, cfg: 1.0 } } },
  overlay: { enabled: true, font_file: "C:/Windows/Fonts/msyh.ttc", font_size_ratio: 0.035, color: "#FFFFFF", bg_opacity: 0.45, margin_ratio: 0.03 },
  cover: { enabled: false, image: "", title_template: "{period}AI资讯", subtitle: "", narration: "", font_size: 72 },
  prompts: {},
  prompt_presets: { active: 0, presets: [] },
};

// 模型配置页：供应商横铺 tab（仅配 base_url + api_key；当前用哪个在流水线页选）
const PROVIDER_TABS: { key: string; label: string }[] = [
  { key: "openai", label: "OpenAI" },
  { key: "dashscope", label: "阿里云 DashScope" },
  { key: "edge-tts", label: "微软 Edge TTS" },
];
const PRESET_PROVIDER_KEYS = PROVIDER_TABS.map((t) => t.key);
const PROVIDER_LABELS: Record<string, string> = { ...Object.fromEntries(PROVIDER_TABS.map((t) => [t.key, t.label])), comfyui: "ComfyUI" };

// ---------------------------------------------------------------------------
// OpenAI 订阅登录面板（仅在 auth_mode === "subscription" 时渲染）
// ---------------------------------------------------------------------------

function OpenAILoginPanel() {
  const { showToast } = useToast();
  const [status, setStatus] = useState<OpenAIAuthStatus | null>(null);
  const [loading, setLoading] = useState(false);         // 拉取状态 / 登录操作 loading
  const [polling, setPolling] = useState(false);          // 正在轮询登录结果
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setPolling(false);
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.auth.openaiStatus();
      setStatus(s);
    } catch {
      // 不显示 toast，静默处理
    }
  }, []);

  // 挂载时拉取一次状态
  useEffect(() => {
    fetchStatus();
    return () => stopPoll();
  }, [fetchStatus, stopPoll]);

  const handleLogin = async () => {
    if (loading || polling) return;
    setLoading(true);
    try {
      const { authorize_url, state } = await api.auth.openaiLoginStart();
      window.open(authorize_url, "_blank");
      setLoading(false);
      setPolling(true);
      let tries = 0;
      pollTimerRef.current = setInterval(async () => {
        tries++;
        if (tries > 150) { stopPoll(); showToast("登录超时，请重试", "error"); return; }
        try {
          const r = await api.auth.openaiLoginStatus(state);
          if (r.status === "success") {
            stopPoll();
            await fetchStatus();
            showToast("ChatGPT 登录成功", "success");
          } else if (r.status === "error") {
            stopPoll();
            showToast(r.error ?? "登录失败，请重试", "error");
          }
          // pending：继续轮询
        } catch {
          // 网络抖动，继续轮询
        }
      }, 2000);
    } catch (e) {
      setLoading(false);
      showToast(e instanceof Error ? e.message : "启动登录失败", "error");
    }
  };

  const handleLogout = async () => {
    setLoading(true);
    try {
      await api.auth.openaiLogout();
      await fetchStatus();
      showToast("已退出 ChatGPT 登录", "success");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "退出失败", "error");
    } finally {
      setLoading(false);
    }
  };

  const formatExpiry = (s?: string) => {
    if (!s) return "—";
    const d = new Date(s);
    return isNaN(d.getTime()) ? s : d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
  };

  return (
    <div className="space-y-3">
      {status === null ? (
        <p className="text-sm text-white/52">正在检查登录状态…</p>
      ) : status.logged_in ? (
        <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.06] px-4 py-3 space-y-2">
          <p className="text-sm text-emerald-300 font-medium">已登录 ChatGPT</p>
          <div className="grid grid-cols-[6rem_1fr] gap-y-1 text-sm">
            <span className="text-white/52">邮箱</span><span className="text-white/92">{status.email ?? "—"}</span>
            <span className="text-white/52">套餐</span><span className="text-white/92">{status.plan ?? "—"}</span>
            <span className="text-white/52">到期时间</span><span className="text-white/92">{formatExpiry(status.expires_at)}</span>
          </div>
          <button onClick={handleLogout} disabled={loading}
            className="mt-1 px-3 py-1.5 text-xs rounded-md bg-white/[0.06] text-white/78 border border-white/[0.08] hover:text-white/96 hover:bg-white/[0.1] transition disabled:opacity-50">
            {loading ? "处理中…" : "退出登录"}
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button onClick={handleLogin} disabled={loading || polling}
            className="shrink-0 px-4 py-1.5 text-sm rounded-md bg-blue-500/15 text-blue-300 border border-blue-400/30 hover:bg-blue-500/25 transition disabled:opacity-50">
            {loading ? "跳转中…" : polling ? "等待授权回调…" : "登录 ChatGPT"}
          </button>
          {polling && (
            <span className="shrink-0 text-xs text-white/52">浏览器窗口完成授权后自动更新</span>
          )}
          <p className="text-xs text-amber-300/60 leading-snug">
            订阅模式仅支持 文案/生图/解析，不支持语音(TTS)；生图固定用 gpt-5.5。
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 用户管理 tab
// ---------------------------------------------------------------------------

function UsersTab() {
  const { showToast } = useToast();
  const { data: me } = useSWR("auth-me", api.auth.me);
  const { data: users, mutate } = useSWR<AuthUser[]>("auth-users", api.auth.users);

  // 修改自己的密码
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");

  // 新增用户
  const [newName, setNewName] = useState("");
  const [newUserPw, setNewUserPw] = useState("");

  // 重置某用户密码（行内展开）
  const [resetId, setResetId] = useState<number | null>(null);
  const [resetPw, setResetPw] = useState("");

  const changeOwnPassword = async () => {
    if (!oldPw || !newPw) return;
    if (newPw !== confirmPw) { showToast("两次输入的新密码不一致", "error"); return; }
    try {
      await api.auth.changePassword(oldPw, newPw);
      setOldPw(""); setNewPw(""); setConfirmPw("");
      showToast("密码已修改", "success");
    } catch {
      showToast("修改失败，请检查原密码", "error");
    }
  };

  const addUser = async () => {
    if (!newName.trim() || !newUserPw) return;
    try {
      await api.auth.createUser(newName.trim(), newUserPw);
      setNewName(""); setNewUserPw("");
      mutate();
      showToast("用户已添加", "success");
    } catch {
      showToast("添加失败，用户名可能已存在", "error");
    }
  };

  const resetUserPassword = async (id: number) => {
    if (!resetPw) return;
    try {
      await api.auth.resetPassword(id, resetPw);
      setResetId(null); setResetPw("");
      showToast("密码已重置", "success");
    } catch {
      showToast("重置失败", "error");
    }
  };

  const removeUser = async (u: AuthUser) => {
    if (!window.confirm(`确认删除用户「${u.username}」？`)) return;
    try {
      await api.auth.deleteUser(u.id);
      mutate();
      showToast("用户已删除", "success");
    } catch {
      showToast("删除失败", "error");
    }
  };

  return (
    <>
      <Section title="修改密码" desc="修改当前登录账号的密码">
        <Field label="原密码">
          <PasswordInput value={oldPw} onChange={setOldPw} placeholder="原密码" autoComplete="current-password" className={inputCls} />
        </Field>
        <Field label="新密码">
          <PasswordInput value={newPw} onChange={setNewPw} placeholder="新密码" autoComplete="new-password" className={inputCls} />
        </Field>
        <Field label="确认新密码">
          <PasswordInput value={confirmPw} onChange={setConfirmPw} placeholder="再次输入新密码" autoComplete="new-password" className={inputCls} />
        </Field>
        <div className="flex justify-end">
          <button onClick={changeOwnPassword} disabled={!oldPw || !newPw} className={cx(btnConfirm, (!oldPw || !newPw) && "opacity-40 cursor-default")}>
            修改密码
          </button>
        </div>
      </Section>

      <Section title="用户列表" desc="管理可登录系统的账号">
        <div className="space-y-2">
          {(users ?? []).map((u) => (
            <div key={u.id} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-4 py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm text-white/96">{u.username}</span>
                  {me?.username === u.username && (
                    <span className="text-[11px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300">当前</span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => { setResetId(resetId === u.id ? null : u.id); setResetPw(""); }} className={btnAdd}>
                    重置密码
                  </button>
                  <button onClick={() => removeUser(u)} disabled={me?.username === u.username} className={btnDeleteCompact}>
                    删除
                  </button>
                </div>
              </div>
              {resetId === u.id && (
                <div className="flex items-center gap-2 mt-3">
                  <PasswordInput value={resetPw} onChange={setResetPw} placeholder={`为 ${u.username} 设置新密码`} autoComplete="new-password" className={inputCls} />
                  <button onClick={() => resetUserPassword(u.id)} disabled={!resetPw} className={cx(btnConfirm, !resetPw && "opacity-40 cursor-default")}>
                    确认
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>

      <Section title="新增用户" desc="创建新的登录账号">
        <Field label="用户名">
          <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="用户名" className={inputCls} />
        </Field>
        <Field label="密码">
          <PasswordInput value={newUserPw} onChange={setNewUserPw} placeholder="密码" autoComplete="new-password" className={inputCls} />
        </Field>
        <div className="flex justify-end">
          <button onClick={addUser} disabled={!newName.trim() || !newUserPw} className={cx(btnConfirm, (!newName.trim() || !newUserPw) && "opacity-40 cursor-default")}>
            添加用户
          </button>
        </div>
      </Section>
    </>
  );
}

export function SettingsPage() {
  const { data: remote, error: loadError, mutate } = useSWR("settings", api.settings.get);
  const { data: promptDefs } = useSWR("prompt-defaults", api.settings.promptDefaults);
  const [settings, setSettings] = useState<AppSettings>(EMPTY_SETTINGS);
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<"pipeline" | "models" | "comfyui" | "prompts" | "users">("pipeline");
  const [modelSel, setModelSel] = useState<Record<string, string>>({});  // 每个类型分组当前选中的供应商
  const [imgWf, setImgWf] = useState<string>("z_image_turbo");
  const [vidWf, setVidWf] = useState<string>("wan2.2_5b");
  // 封面图上传时间戳（防缓存刷新缩略图）
  const [coverImgTs, setCoverImgTs] = useState(0);
  // 仅两态：idle / playing；合成中并入 playing（统一显示停止图标）
  const [ttsState, setTtsState] = useState<"idle" | "playing">("idle");
  const ttsAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsUrlRef = useRef<string>("");
  const ttsGenRef = useRef(0);  // 合成代次：停止时自增，丢弃在途的合成结果
  const { showToast } = useToast();

  const stopTtsPreview = () => {
    ttsGenRef.current++;  // 作废在途合成
    const a = ttsAudioRef.current;
    if (a) { a.pause(); a.currentTime = 0; }
    if (ttsUrlRef.current) { URL.revokeObjectURL(ttsUrlRef.current); ttsUrlRef.current = ""; }
    ttsAudioRef.current = null;
    setTtsState("idle");
  };

  // 试听：用当前选型合成示例并播放。idle 点击开始；playing（含合成中）再点即停止
  const playTtsPreview = async () => {
    if (ttsState === "playing") { stopTtsPreview(); return; }  // 进行中：停止
    const p = settings.pipeline;
    const gen = ++ttsGenRef.current;
    setTtsState("playing");  // 合成中并入播放态：立即切到停止图标
    try {
      const blob = await api.runs.ttsPreview({ provider: p.tts_provider, model: p.tts_model, voice: p.tts_voice });
      if (gen !== ttsGenRef.current) return;  // 已被停止：丢弃结果
      const url = URL.createObjectURL(blob);
      ttsUrlRef.current = url;
      const audio = new Audio(url);
      ttsAudioRef.current = audio;
      audio.onended = stopTtsPreview;
      audio.onerror = stopTtsPreview;
      await audio.play();
    } catch (e) {
      if (gen !== ttsGenRef.current) return;  // 已停止：不报错
      showToast(e instanceof Error ? e.message : "试听失败", "error");
      stopTtsPreview();
    }
  };

  useEffect(() => {
    if (remote) {
      setSettings(remote);
      setDirty(false);
    }
  }, [remote]);

  const patch = <G extends keyof AppSettings>(group: G, p: Partial<AppSettings[G]>) => {
    setSettings((prev) => ({ ...prev, [group]: { ...prev[group], ...p } }));
    setDirty(true);
  };

  const patchProvider = (name: string, p: Partial<ProviderCreds>) => {
    setSettings((prev) => ({
      ...prev,
      providers: { ...prev.providers, [name]: { ...(prev.providers[name] ?? { base_url: "", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } }), ...p } },
    }));
    setDirty(true);
  };

  // 用户自定义供应商（出现在各分组的供应商 chip + 流水线选型）
  const customKeys = Object.keys(settings.providers).filter((k) => !PRESET_PROVIDER_KEYS.includes(k));
  const allProviderKeys = [...PRESET_PROVIDER_KEYS, ...customKeys];
  // 文本/图片/视觉用途的可选供应商：排除纯语音供应商（edge-tts）
  const llmProviderKeys = allProviderKeys.filter((k) => k !== "edge-tts");
  const modelsOf = (p: string, t: "text" | "image" | "vision" | "tts") => settings.providers[p]?.models?.[t] ?? [];
  // 新增自定义供应商（供分组内的「添加供应商」一行调用）
  const addProviderByName = (name: string) => {
    if (settings.providers[name]) return;
    patchProvider(name, { base_url: "", api_key: "" });
  };

  // 渲染一个「类型分组」：组内供应商 chip + 添加供应商一行 + 选中后配凭证（按供应商共享）与该类型模型列表
  const renderModelGroup = (type: "text" | "image" | "vision" | "tts", label: string, presetKeys: string[]) => {
    const keys = [...presetKeys, ...customKeys];
    const sel = (modelSel[type] && keys.includes(modelSel[type])) ? modelSel[type] : keys[0];
    const creds = settings.providers[sel] ?? { base_url: "", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } };
    const cm = creds.models ?? { text: [], image: [], vision: [], tts: [] };
    const isCustom = !PRESET_PROVIDER_KEYS.includes(sel);
    return (
      <Section key={type} title={label} desc="选供应商后配置其接口/Key 与该类型的模型列表（接口/Key 按供应商共享）">
        <TabStrip tabs={keys.map((k) => ({ key: k, label: PROVIDER_LABELS[k] ?? k }))} active={sel} onSelect={(k) => setModelSel((s) => ({ ...s, [type]: k }))} className="mb-2.5" />
        <AddProviderInline onAdd={(name) => { addProviderByName(name); setModelSel((s) => ({ ...s, [type]: name })); }} />
        {sel === "edge-tts" ? (
          <p className="text-sm text-white/52">微软 Edge TTS 免费，无需接口/Key/模型；音色在「流水线配置」选择。</p>
        ) : (<>
        {/* OpenAI 鉴权模式切换 */}
        {sel === "openai" && (
          <Field label="鉴权方式" center>
            <div className="flex gap-1.5">
              {(["api_key", "subscription"] as const).map((mode) => {
                const active = (creds.auth_mode ?? "api_key") === mode;
                return (
                  <button key={mode} type="button"
                    onClick={() => patchProvider("openai", { auth_mode: mode })}
                    className={`px-2.5 py-1 text-xs rounded-md transition border ${active ? "bg-blue-500/15 text-blue-300 border-blue-400/30" : "bg-white/[0.03] text-white/70 border-white/[0.06] hover:text-white/92"}`}>
                    {mode === "api_key" ? "API Key" : "订阅登录"}
                  </button>
                );
              })}
            </div>
          </Field>
        )}
        {/* 接口地址：api_key 模式下显示；订阅模式不需要（走 OAuth token）*/}
        {(sel !== "openai" || (creds.auth_mode ?? "api_key") === "api_key") && (
          <Field label="接口地址">
            <input value={creds.base_url} onChange={(e) => patchProvider(sel, { base_url: e.target.value })} placeholder="https://api.example.com/v1" className={monoInputCls} />
          </Field>
        )}
        {/* API Key：api_key 模式下显示；订阅模式改为显示登录 UI */}
        {sel === "openai" && (creds.auth_mode ?? "api_key") === "subscription" ? (
          <Field label="ChatGPT 账号">
            <OpenAILoginPanel />
          </Field>
        ) : (
          <SecretField label="API Key" value={creds.api_key} onChange={(v) => patchProvider(sel, { api_key: v })} />
        )}
        {(type === "text" || type === "vision") && (
          <Field label="输出 tokens" desc="单次生成 token 上限">
            <input type="number" value={creds.max_output_tokens} min={256} max={200000} step={1024}
              onChange={(e) => patchProvider(sel, { max_output_tokens: Number(e.target.value) })} className={inputCls} />
          </Field>
        )}
        <ModelListEditor label={`${label}名`} models={cm[type] ?? []} onChange={(l) => patchProvider(sel, { models: { ...cm, [type]: l } })} />
        {isCustom && (
          <button
            onClick={() => {
              setSettings((prev) => { const p = { ...prev.providers }; delete p[sel]; return { ...prev, providers: p }; });
              setDirty(true);
              setModelSel((s) => ({ ...s, [type]: presetKeys[0] }));
            }}
            className="text-xs text-red-300/70 hover:text-red-300"
          >删除自定义供应商「{sel}」</button>
        )}
        </>)}
      </Section>
    );
  };

  const handleSave = async () => {
    // openai 选了订阅登录但未登录成功时拦截，避免存下「订阅却无凭证」的坏配置
    if ((settings.providers.openai?.auth_mode ?? "api_key") === "subscription") {
      try {
        const st = await api.auth.openaiStatus();
        if (!st.logged_in) {
          showToast("OpenAI 选择了订阅登录但尚未登录，请先登录 ChatGPT 再保存", "error");
          return;
        }
      } catch {
        showToast("无法确认 ChatGPT 登录状态，请先完成登录再保存", "error");
        return;
      }
    }
    try {
      const updated = await api.settings.save(settings);
      mutate(updated, false);
      setDirty(false);
      showToast("设置已保存至 config.yaml", "success");
    } catch {
      showToast("保存设置失败", "error");
    }
  };

  if (loadError) {
    return (
      <div className="py-20 text-center">
        <p className="text-white/60 text-sm">无法连接后端服务</p>
        <p className="text-white/46 text-xs mt-1">请先启动 API 服务: uvicorn app.main:app --reload</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-12">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold tracking-tight">设置</h1>
        {/* 用户管理无保存动作，但按钮始终占位（invisible）以保持头部高度一致，避免切 tab 上下抖动 */}
        <button onClick={handleSave} disabled={!dirty}
          className={`${btnPrimary} ${activeTab === "users" ? "invisible" : dirty ? "" : "opacity-40 cursor-default"}`}>
          保存
        </button>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-white/10 pb-2">
        {([["pipeline", "流水线配置"], ["models", "模型配置"], ["comfyui", "ComfyUI 参数"], ["prompts", "提示词配置"], ["users", "用户管理"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setActiveTab(k)}
            className={`px-3 py-1.5 text-sm rounded-md transition ${activeTab === k ? "bg-white/10 text-white" : "text-white/66 hover:text-white/92"}`}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === "models" && (<>
        {renderModelGroup("text", "文本模型", ["openai", "dashscope"])}
        {renderModelGroup("image", "图片模型", ["openai", "dashscope"])}
        {renderModelGroup("vision", "多模态模型", ["openai", "dashscope"])}
        {renderModelGroup("tts", "语音生成模型", ["openai", "dashscope", "edge-tts"])}
        <p className="text-xs text-white/60 pl-1">提示：接口地址/API Key 按供应商共享（任一分组里改即全局生效）；Edge TTS 免费无需配置；ComfyUI 在「ComfyUI 参数」页配。点 API Key 眼睛图标看完整内容。</p>
      </>)}

      {activeTab === "pipeline" && (<>
      <Section title="流水线默认值" desc="创建任务窗口与 run 从这里读取默认值。模型选型即「当前用哪个供应商+模型」。">
        <Field label="时间范围">
          <Select value={settings.pipeline.default_time_range} onChange={(v) => patch("pipeline", { default_time_range: v })} options={[
            { value: "1d", label: "最近 1 天" }, { value: "3d", label: "最近 3 天" }, { value: "7d", label: "最近 7 天" }, { value: "15d", label: "最近 15 天" }, { value: "1m", label: "最近 1 个月" },
          ]} />
        </Field>
        <Field label="最大文章数">
          <input type="number" value={settings.pipeline.default_max_articles} onChange={(e) => patch("pipeline", { default_max_articles: Number(e.target.value) })} min={1} max={50} className={inputCls} />
        </Field>
        <Field label="最多图片数" desc="0=不限制；超过则生图前 AI 重规划分镜，合并零碎/短文章到同一张图">
          <input type="number" value={settings.pipeline.max_images} onChange={(e) => patch("pipeline", { max_images: Number(e.target.value) })} min={0} max={100} className={inputCls} />
        </Field>
        <Field label="分辨率" desc="图片与视频共用">
          <Select value={settings.pipeline.resolution} onChange={(v) => patch("pipeline", { resolution: v })} options={[
            { value: "720x1280", label: "720×1280 竖屏HD" }, { value: "1280x720", label: "1280×720 横屏HD" },
            { value: "1024x1024", label: "1024×1024 方形" },
            { value: "1080x1920", label: "1080×1920 竖屏" }, { value: "1920x1080", label: "1920×1080 横屏" },
          ]} />
        </Field>
        <PurposeSelect label="文章总结模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.summary_provider} model={settings.pipeline.summary_model}
          modelOptions={modelsOf(settings.pipeline.summary_provider, "text")}
          onProvider={(v) => patch("pipeline", { summary_provider: v, summary_model: modelsOf(v, "text")[0] ?? "" })} onModel={(v) => patch("pipeline", { summary_model: v })} />
        <PurposeSelect label="文案脚本模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.script_provider} model={settings.pipeline.script_model}
          modelOptions={modelsOf(settings.pipeline.script_provider, "text")}
          onProvider={(v) => patch("pipeline", { script_provider: v, script_model: modelsOf(v, "text")[0] ?? "" })} onModel={(v) => patch("pipeline", { script_model: v })} />
        <PurposeSelect label="图片生成模型" providerKeys={["comfyui", ...llmProviderKeys]} desc="comfyui 时为图片 workflow"
          provider={settings.pipeline.image_provider} model={settings.pipeline.image_model}
          modelOptions={settings.pipeline.image_provider === "comfyui" ? ["z_image_turbo", "qwen_image"] : modelsOf(settings.pipeline.image_provider, "image")}
          onProvider={(v) => patch("pipeline", { image_provider: v, image_model: (v === "comfyui" ? "z_image_turbo" : modelsOf(v, "image")[0]) ?? "" })} onModel={(v) => patch("pipeline", { image_model: v })} />
        <PurposeSelect label="文档解析模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.vision_provider} model={settings.pipeline.vision_model}
          modelOptions={modelsOf(settings.pipeline.vision_provider, "vision")}
          onProvider={(v) => patch("pipeline", { vision_provider: v, vision_model: modelsOf(v, "vision")[0] ?? "" })} onModel={(v) => patch("pipeline", { vision_model: v })} />
        <Field label="语音生成模型"
          desc={settings.pipeline.default_language === "en" && !settings.pipeline.tts_voice.startsWith("en") ? "⚠ 当前语言为英文，建议选英文音色（en-US-*）" : "供应商 + 模型 + 音色"}>
          <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-center">
            <Select value={settings.pipeline.tts_provider}
              onChange={(v) => {
                stopTtsPreview();
                const ttsModels = settings.providers[v]?.models?.tts ?? [];
                const model = ttsModels[0] ?? "";
                const voices = voicesFor(v, model);
                patch("pipeline", { tts_provider: v, tts_model: model, tts_voice: voices[0]?.value ?? settings.pipeline.tts_voice });
              }}
              options={Object.keys(TTS_PRESETS).map((k) => ({ value: k, label: TTS_PRESETS[k].label }))} />
            {settings.pipeline.tts_provider === "edge-tts" ? (
              <div className={`${inputCls} flex items-center text-white/40`}>无需模型</div>
            ) : (
              <Select value={settings.pipeline.tts_model}
                onChange={(v) => { stopTtsPreview(); const vs = voicesFor(settings.pipeline.tts_provider, v); patch("pipeline", { tts_model: v, tts_voice: vs[0]?.value ?? settings.pipeline.tts_voice }); }}
                options={(settings.providers[settings.pipeline.tts_provider]?.models?.tts ?? []).map((m) => ({ value: m, label: m }))} />
            )}
            {(() => {
              const vs = voicesFor(settings.pipeline.tts_provider, settings.pipeline.tts_model);
              return vs.length > 0 ? (
                <Select value={settings.pipeline.tts_voice} onChange={(v) => { stopTtsPreview(); patch("pipeline", { tts_voice: v }); }} options={vs} />
              ) : (
                <input value={settings.pipeline.tts_voice} onChange={(e) => patch("pipeline", { tts_voice: e.target.value })} placeholder="音色 ID" className={inputCls} />
              );
            })()}
            <button onClick={playTtsPreview} title={ttsState === "playing" ? "停止" : "试听"} aria-label={ttsState === "playing" ? "停止" : "试听"}
              className="shrink-0 inline-flex items-center justify-center px-3 py-2 rounded-md bg-white/[0.06] text-white/70 border border-white/[0.08] hover:bg-white/[0.1] transition">
              {ttsState === "playing" ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><rect x="5" y="5" width="14" height="14" rx="1.5" /></svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M6 4l15 8-15 8V4z" /></svg>
              )}
            </button>
          </div>
        </Field>
        <Field label="视频路线">
          <Select value={settings.pipeline.default_video_route} onChange={(v) => patch("pipeline", { default_video_route: v })} options={[
            { value: "hyperframes", label: "Hyperframes" }, { value: "comfyui", label: "ComfyUI" }, { value: "audio", label: "纯语音" },
          ]} />
        </Field>
        <Field label="语言">
          <Select value={settings.pipeline.default_language} onChange={(v) => patch("pipeline", { default_language: v })} options={[
            { value: "zh", label: "中文" }, { value: "en", label: "English" },
          ]} />
        </Field>
      </Section>

      <Section title="ComfyUI（视频）" desc="视频路线为 ComfyUI 时生效；workflow 的 steps/cfg 在「ComfyUI 参数」页调整">
        <Field label="视频模型">
          <Select value={settings.pipeline.video_model} onChange={(v) => patch("pipeline", { video_model: v })} options={[
            { value: "wan2.2_5b", label: "wan2.2_5b" }, { value: "wan2.2_14b", label: "wan2.2_14b" },
            { value: "wan2.2_14b_lightx2v", label: "wan2.2_14b_lightx2v" }, { value: "ltx_2.3", label: "ltx_2.3" },
          ]} />
        </Field>
        <Field label="帧率">
          <Select value={String(settings.pipeline.video_fps)} onChange={(v) => patch("pipeline", { video_fps: Number(v) })} options={[
            { value: "16", label: "16" }, { value: "24", label: "24" }, { value: "25", label: "25" },
          ]} />
        </Field>
      </Section>

      <Section title="Hyperframes 配置">
        <Field label="帧率">
          <Select value={settings.hyperframes.fps} onChange={(v) => patch("hyperframes", { fps: v })} options={[
            { value: "24", label: "24" }, { value: "25", label: "25" }, { value: "30", label: "30" },
          ]} />
        </Field>
        <Field label="场景间隔">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.hyperframes.scene_gap_ms} onChange={(e) => patch("hyperframes", { scene_gap_ms: Number(e.target.value) })} min={0} max={2000} step={100} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/76 tabular-nums w-16 text-right">{settings.hyperframes.scene_gap_ms}ms</span>
          </div>
        </Field>
        <Field label="转场效果">
          <Select value={settings.hyperframes.transition} onChange={(v) => patch("hyperframes", { transition: v })} options={[
            { value: "crossfade", label: "交叉淡入淡出" }, { value: "fade", label: "淡入淡出" },
            { value: "slide", label: "滑动" }, { value: "cut", label: "直接切换（无转场）" },
          ]} />
        </Field>
        <Field label="字幕字号" desc="按渲染分辨率计的像素值，过小会看不清">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.hyperframes.subtitle_font_size} onChange={(e) => patch("hyperframes", { subtitle_font_size: Number(e.target.value) })} min={24} max={96} step={2} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/76 tabular-nums w-16 text-right">{settings.hyperframes.subtitle_font_size}px</span>
          </div>
        </Field>
        <Field label="字幕距底部" desc="按渲染分辨率计的像素值，越大字幕越靠上">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.hyperframes.subtitle_bottom_px} onChange={(e) => patch("hyperframes", { subtitle_bottom_px: Number(e.target.value) })} min={0} max={400} step={10} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/76 tabular-nums w-16 text-right">{settings.hyperframes.subtitle_bottom_px}px</span>
          </div>
        </Field>
        <Field label="字幕最多行数" desc="超长旁白会按此上限自动切分成多条短字幕">
          <Select value={String(settings.hyperframes.subtitle_max_lines)} onChange={(v) => patch("hyperframes", { subtitle_max_lines: Number(v) })} options={[
            { value: "1", label: "1 行" }, { value: "2", label: "2 行" }, { value: "3", label: "3 行" },
          ]} />
        </Field>
      </Section>

      <Section title="画面标题" desc="在合成视频的每张画面上烧录标题文字；需后端有可用的 CJK 字体（见依赖要求）才会生效。">
        <Field label="画面标题烧录" center>
          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" checked={settings.overlay.enabled}
              onChange={(e) => patch("overlay", { enabled: e.target.checked })}
              className="w-4 h-4 accent-blue-500 rounded" />
            <span className="text-sm text-white/76">{settings.overlay.enabled ? "已开启" : "已关闭"}</span>
          </label>
        </Field>
        <Field label="字号比例" desc="相对于画面高度的比例（0.01–0.15），如 0.045 = 4.5%">
          <div className="flex items-center gap-3">
            <input type="number" value={settings.overlay.font_size_ratio} min={0.01} max={0.15} step={0.005}
              onChange={(e) => patch("overlay", { font_size_ratio: Number(e.target.value) })} className={inputCls} />
            <span className="text-xs text-white/60">{(settings.overlay.font_size_ratio * 100).toFixed(1)}%</span>
          </div>
        </Field>
        <Field label="文字颜色" desc="十六进制颜色值，如 #FFFFFF">
          <div className="flex items-center gap-2">
            <input type="color" value={settings.overlay.color}
              onChange={(e) => patch("overlay", { color: e.target.value })}
              className="w-9 h-8 rounded cursor-pointer border border-white/[0.08] bg-transparent" />
            <input value={settings.overlay.color} onChange={(e) => patch("overlay", { color: e.target.value })}
              placeholder="#FFFFFF" className={`${inputCls} w-32`} />
          </div>
        </Field>
        <Field label="背景不透明度" desc="文字底部半透明背景，0=无背景，1=全不透明">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.overlay.bg_opacity} min={0} max={1} step={0.05}
              onChange={(e) => patch("overlay", { bg_opacity: Number(e.target.value) })} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/76 tabular-nums w-12 text-right">{settings.overlay.bg_opacity.toFixed(2)}</span>
          </div>
        </Field>
        <Field label="边距比例" desc="相对于画面高度的上下边距比例（0–0.1）">
          <div className="flex items-center gap-3">
            <input type="number" value={settings.overlay.margin_ratio} min={0} max={0.1} step={0.005}
              onChange={(e) => patch("overlay", { margin_ratio: Number(e.target.value) })} className={inputCls} />
            <span className="text-xs text-white/60">{(settings.overlay.margin_ratio * 100).toFixed(1)}%</span>
          </div>
        </Field>
      </Section>

      <Section title="视频封面" desc="封面统一用 hyperframes 渲染；comfyui 视频路线会把封面片段自动拼接到成片开头。纯音频路线不出封面。">
        <Field label="封面功能" center>
          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" checked={settings.cover.enabled}
              onChange={(e) => patch("cover", { enabled: e.target.checked })}
              className="w-4 h-4 accent-blue-500 rounded" />
            <span className="text-sm text-white/76">{settings.cover.enabled ? "已开启" : "已关闭"}</span>
          </label>
        </Field>
        <Field label="封面图">
          <div className="flex flex-col gap-2">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <span className="px-3 py-1.5 text-xs rounded-lg border border-white/[0.08] bg-white/[0.04] text-white/76 hover:bg-white/[0.08] hover:text-white/92 transition cursor-pointer">上传图片</span>
              <input type="file" accept="image/*" className="hidden"
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  if (!file) return;
                  try {
                    const res = await api.settings.uploadCoverImage(file);
                    patch("cover", { image: (res as { path: string }).path });
                    setCoverImgTs(Date.now());
                    showToast("封面图已上传", "success");
                  } catch (err) {
                    showToast(err instanceof Error ? err.message : "上传失败", "error");
                  }
                }} />
            </label>
            {settings.cover.image && (
              <img
                src={`${api.settings.coverImageUrl()}?t=${coverImgTs}`}
                alt="封面预览"
                className="w-32 h-auto rounded-lg border border-white/[0.08] object-cover"
              />
            )}
          </div>
        </Field>
        <Field label="标题模板" desc="变量：{period} {days} {date}">
          <input value={settings.cover.title_template}
            onChange={(e) => patch("cover", { title_template: e.target.value })}
            placeholder="{period}AI资讯" className={inputCls} />
        </Field>
        <Field label="副标题">
          <input value={settings.cover.subtitle}
            onChange={(e) => patch("cover", { subtitle: e.target.value })}
            placeholder="留空则无副标题" className={inputCls} />
        </Field>
        <Field label="旁白" desc="空则封面无配音">
          <textarea value={settings.cover.narration}
            onChange={(e) => patch("cover", { narration: e.target.value })}
            placeholder="封面旁白文字，留空则无配音" rows={3}
            className={`${inputCls} resize-none w-full`} />
        </Field>
        <Field label="标题字号" desc="按渲染分辨率计的像素值">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.cover.font_size} min={24} max={160} step={4}
              onChange={(e) => patch("cover", { font_size: Number(e.target.value) })} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/76 tabular-nums w-16 text-right">{settings.cover.font_size}px</span>
          </div>
        </Field>
      </Section>

      <Section title="存储目录" desc="任务半成品与成品的存放位置">
        <Field label="工作目录">
          <input value={settings.storage.work_dir} onChange={(e) => patch("storage", { work_dir: e.target.value })} placeholder="留空使用默认 data/runs；每个任务一个子目录" className={monoInputCls} />
        </Field>
        <Field label="成品输出目录">
          <input value={settings.storage.output_dir} onChange={(e) => patch("storage", { output_dir: e.target.value })} placeholder="留空不额外导出；渲染完成后复制成品到此，如 D:\视频成品" className={monoInputCls} />
        </Field>
      </Section>

      </>)}

      {activeTab === "comfyui" && (<>
        <Section title="ComfyUI 连接" desc="本地 ComfyUI 服务，图片与视频生成共用。需 ComfyUI 运行中。">
          <Field label="ComfyUI 地址">
            <ComfyuiHealthField value={settings.comfyui.server_url} onChange={(v) => patch("comfyui", { server_url: v })} />
          </Field>
          <Field label="默认负向提示词" desc="图片与视频生成共用，描述不想要的画面元素">
            <input value={settings.comfyui.default_negative} onChange={(e) => patch("comfyui", { default_negative: e.target.value })} placeholder="模糊, 丑陋, 变形, 低质量, 水印" className={inputCls} />
          </Field>
          <Field label="远程唤醒(WoL)" desc="app 在无 GPU 机、ComfyUI 在另一台机器（平时休眠）时启用：用到前若不可达先发魔术包唤醒并等就绪，超时报错停止" center>
            <label className="inline-flex items-center gap-2 cursor-pointer select-none">
              <input type="checkbox" checked={settings.comfyui.wake.enabled}
                onChange={(e) => patch("comfyui", { wake: { ...settings.comfyui.wake, enabled: e.target.checked } })}
                className="w-4 h-4 accent-blue-500 rounded" />
              <span className="text-sm text-white/76">{settings.comfyui.wake.enabled ? "已开启" : "已关闭"}</span>
            </label>
          </Field>
          {settings.comfyui.wake.enabled && (<>
            <Field label="目标机 MAC" desc="ComfyUI 所在机的网卡物理地址">
              <input value={settings.comfyui.wake.mac} onChange={(e) => patch("comfyui", { wake: { ...settings.comfyui.wake, mac: e.target.value } })}
                placeholder="AA:BB:CC:DD:EE:FF" className={monoInputCls} />
            </Field>
            <Field label="子网广播地址" desc="与该机同一网段的广播地址，发包机须同段">
              <input value={settings.comfyui.wake.broadcast} onChange={(e) => patch("comfyui", { wake: { ...settings.comfyui.wake, broadcast: e.target.value } })}
                placeholder="192.168.1.255" className={monoInputCls} />
            </Field>
            <Field label="就绪超时(秒)" desc="唤醒后等 ComfyUI 就绪的最长时间，含冷启 + 载模型">
              <input type="number" value={settings.comfyui.wake.ready_timeout} min={10} max={600} step={10}
                onChange={(e) => patch("comfyui", { wake: { ...settings.comfyui.wake, ready_timeout: Number(e.target.value) } })} className={inputCls} />
            </Field>
          </>)}
        </Section>

        <Section title="图片 workflow 参数" desc="选「图片生成模型 = ComfyUI」时生效；横铺切换各 workflow 配置参数。">
          <TabStrip tabs={[{ key: "z_image_turbo", label: "z_image_turbo" }, { key: "qwen_image", label: "qwen_image" }]} active={imgWf} onSelect={setImgWf} />
          {(() => {
            const meta = IMAGE_PARAM_META[imgWf];
            if (!meta) return null;
            const p = settings.comfyui.image_params[imgWf] ?? { steps: 0, cfg: 0 };
            return <ParamFields meta={meta} params={p}
              onChange={(next) => patch("comfyui", { image_params: { ...settings.comfyui.image_params, [imgWf]: { ...p, ...next } } })} />;
          })()}
        </Section>

        <Section title="视频 workflow 参数" desc="ComfyUI 图生视频（i2v）；横铺切换各 workflow 配置参数。当前用哪个在「流水线配置」选。">
          <TabStrip tabs={[
            { key: "wan2.2_5b", label: "wan2.2_5b" }, { key: "wan2.2_14b", label: "wan2.2_14b" },
            { key: "wan2.2_14b_lightx2v", label: "wan2.2_14b_lightx2v" }, { key: "ltx_2.3", label: "ltx_2.3" },
          ]} active={vidWf} onSelect={setVidWf} />
          {(() => {
            const meta = VIDEO_PARAM_META[vidWf];
            if (!meta) return null;
            const p = settings.comfyui.video_params[vidWf] ?? { steps: 0, cfg: 0 };
            return <ParamFields meta={meta} params={p}
              onChange={(next) => patch("comfyui", { video_params: { ...settings.comfyui.video_params, [vidWf]: { ...p, ...next } } })} />;
          })()}
        </Section>
      </>)}

      {activeTab === "prompts" && (() => {
        const pp = settings.prompt_presets;
        const presets = pp?.presets ?? [];
        const active = Math.min(Math.max(pp?.active ?? 0, 0), Math.max(presets.length - 1, 0));
        const cur = presets[active]?.values ?? {};
        const setActiveValues = (next: Record<string, string>) =>
          patch("prompt_presets", { presets: presets.map((p, i) => (i === active ? { ...p, values: next } : p)) });
        const onField = (k: string, v: string) => setActiveValues({ ...cur, [k]: v });
        return (
          <div className="space-y-4">
            <div>
              <h3 className={sectionTitleCls}>提示词预设</h3>
              {presets.length > 0 && (
                <PresetBar presets={presets} active={active}
                  onSwitch={(i) => patch("prompt_presets", { active: i })}
                  onRename={(i, name) => patch("prompt_presets", { presets: presets.map((p, j) => (j === i ? { ...p, name } : p)) })}
                  onClear={() => setActiveValues({})} />
              )}
            </div>
            <section className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-6 space-y-5">
              {promptDefs && Object.entries(promptDefs).map(([key, def]) => (
                <PromptRow key={key} label={def.label} desc={def.desc}
                  zhValue={cur[key] ?? ""}
                  enValue={cur[`${key}_en`] ?? ""}
                  zhPlaceholder={def.default}
                  enPlaceholder={def.default_en}
                  onZh={(v) => onField(key, v)}
                  onEn={(v) => onField(`${key}_en`, v)} />
              ))}
            </section>
          </div>
        );
      })()}

      {activeTab === "users" && <UsersTab />}
    </div>
  );
}
