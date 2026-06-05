import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { api, type AppSettings, type AuthUser, type ProviderCreds } from "../api/client";
import { useToast } from "../components/Toast";
import { Select } from "../components/Select";
import { PasswordInput } from "../components/PasswordInput";
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
  z_image: {
    steps: { min: 4, max: 20, desc: "采样步数，z_image turbo 蒸馏，8–9 步即可（默认 9）" },
    cfg: { min: 1, max: 5, desc: "提示词遵循强度，turbo 建议 1.0（默认 1.0）" },
  },
  qwen: {
    steps: { min: 10, max: 40, desc: "采样步数，越大越精细越慢（默认 20）" },
    cfg: { min: 1, max: 6, desc: "提示词遵循强度（默认 2.5）" },
  },
};
const VIDEO_PARAM_META: Record<string, ParamMeta> = {
  wan5b: {
    steps: { min: 10, max: 50, desc: "采样步数，越大越精细越慢（默认 30）" },
    cfg: { min: 1, max: 10, desc: "提示词遵循强度，越大越贴提示词（默认 5.0）" },
  },
  wan14b: {
    steps: { min: 10, max: 40, desc: "采样步数（默认 20）；高/低噪切换点自动取步数一半" },
    cfg: { min: 1, max: 10, desc: "提示词遵循强度（默认 3.5）" },
  },
  wan14b_lightx2v: {
    note: "加速 LoRA 固定 4 步、cfg≈1.0，步数与 cfg 均不可调。追求质量请改用 Wan2.2 14B。",
  },
  ltx: {
    cfg: { min: 1, max: 5, desc: "提示词遵循强度（默认 1.0）" },
    note: "蒸馏模型步数固定（约 4 步），无法调整。",
  },
};

const TTS_PRESETS: Record<string, ProviderPreset> = {
  "edge-tts": { label: "Edge TTS", baseUrl: "", models: [], needsKey: false },
  "openai-tts": { label: "OpenAI TTS", baseUrl: "https://api.openai.com/v1", models: ["gpt-4o-mini-tts", "tts-1-hd", "tts-1"], needsKey: true },
  "dashscope-tts": { label: "阿里云 CosyVoice", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["cosyvoice-v2", "cosyvoice-v1"], needsKey: true },
  "azure-speech": { label: "Azure Speech", baseUrl: "https://{region}.tts.speech.microsoft.com", models: [], needsKey: true },
};

const VOICES: Record<string, { label: string; value: string }[]> = {
  "edge-tts": [
    { value: "zh-CN-XiaoxiaoNeural", label: "晓晓 (女)" },
    { value: "zh-CN-YunxiNeural", label: "云希 (男)" },
    { value: "zh-CN-XiaohanNeural", label: "晓涵 (女)" },
    { value: "zh-CN-YunyangNeural", label: "云扬 (男·播报)" },
    { value: "en-US-JennyNeural", label: "Jenny (Female)" },
    { value: "en-US-GuyNeural", label: "Guy (Male)" },
    { value: "en-US-AriaNeural", label: "Aria (Female)" },
  ],
  "openai-tts": [
    { value: "alloy", label: "Alloy" }, { value: "echo", label: "Echo" },
    { value: "fable", label: "Fable" }, { value: "onyx", label: "Onyx" },
    { value: "nova", label: "Nova" }, { value: "shimmer", label: "Shimmer" },
  ],
  "dashscope-tts": [
    { value: "longxiaochun", label: "龙小淳 (女·温柔)" },
    { value: "longxiaoxia", label: "龙小夏 (女·热情)" },
    { value: "longyue", label: "龙悦 (女·播报)" },
    { value: "longcheng", label: "龙城 (男·磁性)" },
    { value: "longjielidou", label: "龙杰力豆 (男·活力)" },
    { value: "longshu", label: "龙书 (男·沉稳)" },
  ],
  "azure-speech": [
    { value: "zh-CN-XiaoxiaoNeural", label: "晓晓 (女)" },
    { value: "zh-CN-YunxiNeural", label: "云希 (男)" },
    { value: "en-US-JennyNeural", label: "Jenny (Female)" },
    { value: "en-US-GuyNeural", label: "Guy (Male)" },
  ],
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
        {desc && <p className="text-xs text-white/30 mt-0.5">{desc}</p>}
      </div>
      {children}
    </section>
  );
}

function Field({ label, desc, children }: { label: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] gap-4 items-start">
      <label className="text-sm text-white/40 pt-2 select-none">
        {label}
        {desc && <span className="block text-xs text-white/25 mt-0.5 font-normal">{desc}</span>}
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
        <Field label="采样步数" desc={`${meta.steps.desc}；可设 ${meta.steps.min}–${meta.steps.max}`}>
          <input type="number" value={params.steps} min={meta.steps.min} max={meta.steps.max}
            onChange={(e) => onChange({ steps: Number(e.target.value) })} className={inputCls} />
        </Field>
      )}
      {meta.cfg && (
        <Field label="CFG" desc={`${meta.cfg.desc}；可设 ${meta.cfg.min}–${meta.cfg.max}`}>
          <input type="number" step={0.5} value={params.cfg} min={meta.cfg.min} max={meta.cfg.max}
            onChange={(e) => onChange({ cfg: Number(e.target.value) })} className={inputCls} />
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

function ModelInput({ value, onChange, suggestions }: {
  value: string; onChange: (v: string) => void; suggestions: string[];
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
    <div className="relative" ref={ref}>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => suggestions.length > 0 && setOpen(true)}
        placeholder="输入模型 ID"
        className={monoInputCls}
      />
      {open && suggestions.length > 0 && (
        <div className="absolute z-20 mt-1.5 w-full rounded-lg border border-white/[0.08] bg-[var(--color-surface-raised)] shadow-xl overflow-hidden max-h-60 overflow-y-auto">
          {suggestions.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { onChange(m); setOpen(false); }}
              className={cx(
                "w-full text-left px-3 py-2 text-[13px] font-mono transition",
                m === value ? "bg-blue-500/15 text-blue-300" : "text-white/60 hover:bg-white/[0.06] hover:text-white/80",
              )}
            >
              {m}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

// 横铺 tab 按钮条（供应商 / workflow 选择共用）
function TabStrip({ tabs, active, onSelect }: {
  tabs: { key: string; label: string }[]; active: string; onSelect: (k: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 mb-5">
      {tabs.map((t) => (
        <button key={t.key} type="button" onClick={() => onSelect(t.key)}
          className={`px-2.5 py-1 text-xs rounded-md transition ${active === t.key ? "bg-blue-500/15 text-blue-300 border border-blue-400/30" : "bg-white/[0.03] text-white/45 border border-white/[0.06] hover:text-white/70"}`}>
          {t.label}
        </button>
      ))}
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
            <span key={m} className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-white/[0.06] text-xs text-white/70 font-mono">
              {m}
              <button onClick={() => onChange(models.filter((x) => x !== m))} className="text-white/30 hover:text-red-300">×</button>
            </span>
          ))}
          {models.length === 0 && <span className="text-xs text-white/25">暂无，下方添加模型名</span>}
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

// 流水线选型一行：供应商下拉 + 模型输入（候选来自该供应商对应类型的模型列表）
function PurposeSelect({ label, desc, providerKeys, provider, model, modelOptions, onProvider, onModel }: {
  label: string; desc?: string; providerKeys: string[];
  provider: string; model: string; modelOptions: string[];
  onProvider: (v: string) => void; onModel: (v: string) => void;
}) {
  const provOptions = providerKeys.map((k) => ({ value: k, label: PROVIDER_LABELS[k] ?? k }));
  return (
    <Field label={label} desc={desc}>
      <div className="grid grid-cols-2 gap-2">
        <Select value={provider} onChange={onProvider} options={provOptions} />
        <ModelInput value={model} onChange={onModel} suggestions={modelOptions} />
      </div>
    </Field>
  );
}

const EMPTY_SETTINGS: AppSettings = {
  providers: {
    claude: { base_url: "https://api.anthropic.com", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    openai: { base_url: "https://api.openai.com/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    dashscope: { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    "openai-tts": { base_url: "https://api.openai.com/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    "dashscope-tts": { base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
    "azure-speech": { base_url: "", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } },
  },
  collectors: { tavily_key: "", brave_key: "", serper_key: "" },
  youtube: { client_id: "", client_secret: "" },
  pipeline: {
    default_time_range: "7d", default_max_articles: 5, default_video_route: "comfyui",
    default_language: "zh", dedup_lookback: "30d", resolution: "1080x1920",
    summary_provider: "openai", summary_model: "gpt-5", summary_max_length: 150,
    script_provider: "claude", script_model: "claude-sonnet-4-6",
    image_provider: "comfyui", image_model: "z_image",
    vision_provider: "openai", vision_model: "gpt-4o",
    tts_provider: "edge-tts", tts_voice: "zh-CN-XiaoxiaoNeural",
    video_model: "wan5b", video_fps: 24,
  },
  storage: { work_dir: "", output_dir: "" },
  video: { fps: "30", scene_gap_ms: 500, transition: "crossfade", subtitle_font_size: 48, subtitle_max_lines: 2 },
  comfyui: { server_url: "http://127.0.0.1:8188", default_negative: "模糊, 丑陋, 变形, 低质量, 水印", image_params: { z_image: { steps: 9, cfg: 1.0 }, qwen: { steps: 20, cfg: 2.5 } }, video_params: { wan5b: { steps: 30, cfg: 5.0 }, wan14b: { steps: 20, cfg: 3.5 }, wan14b_lightx2v: { steps: 4, cfg: 1.0 }, ltx: { steps: 4, cfg: 1.0 } } },
  prompts: {},
};

// 模型配置页：供应商横铺 tab（仅配 base_url + api_key；当前用哪个在流水线页选）
const PROVIDER_TABS: { key: string; label: string }[] = [
  { key: "claude", label: "Anthropic Claude" },
  { key: "openai", label: "OpenAI" },
  { key: "dashscope", label: "阿里云 DashScope" },
  { key: "openai-tts", label: "OpenAI TTS" },
  { key: "dashscope-tts", label: "阿里云 CosyVoice" },
  { key: "azure-speech", label: "Azure Speech" },
];
const PRESET_PROVIDER_KEYS = PROVIDER_TABS.map((t) => t.key);
const PROVIDER_LABELS: Record<string, string> = Object.fromEntries(PROVIDER_TABS.map((t) => [t.key, t.label]));

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
                  <span className="text-sm text-white/80">{u.username}</span>
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
  const [newProvider, setNewProvider] = useState("");
  const [imgWf, setImgWf] = useState<string>("z_image");
  const [vidWf, setVidWf] = useState<string>("wan5b");
  const { showToast } = useToast();

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
  // 文本/图片/视觉用途的可选供应商：排除纯 TTS 供应商
  const llmProviderKeys = allProviderKeys.filter((k) => !["openai-tts", "dashscope-tts", "azure-speech"].includes(k));
  const modelsOf = (p: string, t: "text" | "image" | "vision" | "tts") => settings.providers[p]?.models?.[t] ?? [];
  const addProvider = () => {
    const name = newProvider.trim();
    if (!name || settings.providers[name]) { setNewProvider(""); return; }
    patchProvider(name, { base_url: "", api_key: "" });
    setNewProvider("");
  };

  // 渲染一个「类型分组」：组内供应商 chip + 选中后配凭证（按供应商共享）与该类型模型列表
  const renderModelGroup = (type: "text" | "image" | "vision" | "tts", label: string, presetKeys: string[]) => {
    const keys = [...presetKeys, ...customKeys];
    const sel = (modelSel[type] && keys.includes(modelSel[type])) ? modelSel[type] : keys[0];
    const creds = settings.providers[sel] ?? { base_url: "", api_key: "", max_output_tokens: 65535, models: { text: [], image: [], vision: [], tts: [] } };
    const cm = creds.models ?? { text: [], image: [], vision: [], tts: [] };
    const isCustom = !PRESET_PROVIDER_KEYS.includes(sel);
    return (
      <Section key={type} title={label} desc="选供应商后配置其接口/Key 与该类型的模型列表（接口/Key 按供应商共享）">
        <TabStrip tabs={keys.map((k) => ({ key: k, label: PROVIDER_LABELS[k] ?? k }))} active={sel} onSelect={(k) => setModelSel((s) => ({ ...s, [type]: k }))} />
        <Field label="接口地址">
          <input value={creds.base_url} onChange={(e) => patchProvider(sel, { base_url: e.target.value })} placeholder="https://api.example.com/v1" className={monoInputCls} />
        </Field>
        <SecretField label="API Key" value={creds.api_key} onChange={(v) => patchProvider(sel, { api_key: v })} />
        {type !== "tts" && (
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
      </Section>
    );
  };

  const handleSave = async () => {
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
        <p className="text-white/30 text-sm">无法连接后端服务</p>
        <p className="text-white/20 text-xs mt-1">请先启动 API 服务: uvicorn app.main:app --reload</p>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-12">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold tracking-tight">设置</h1>
        {activeTab !== "users" && (
          <button onClick={handleSave} disabled={!dirty} className={`${btnPrimary} ${dirty ? "" : "opacity-40 cursor-default"}`}>
            保存
          </button>
        )}
      </div>

      <div className="flex flex-wrap gap-2 border-b border-white/10 pb-2">
        {([["pipeline", "流水线配置"], ["models", "模型配置"], ["comfyui", "ComfyUI 参数"], ["prompts", "提示词配置"], ["users", "用户管理"]] as const).map(([k, label]) => (
          <button key={k} onClick={() => setActiveTab(k)}
            className={`px-3 py-1.5 text-sm rounded-md transition ${activeTab === k ? "bg-white/10 text-white" : "text-white/40 hover:text-white/70"}`}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === "models" && (<>
        <div className="flex gap-2">
          <input value={newProvider} onChange={(e) => setNewProvider(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addProvider(); }}
            placeholder="添加自定义供应商，如 deepseek / siliconflow（加后在各分组的供应商里出现）" className={inputCls} />
          <button onClick={addProvider} className={btnPrimary}>+ 添加供应商</button>
        </div>
        {renderModelGroup("text", "文本模型", ["claude", "openai", "dashscope"])}
        {renderModelGroup("image", "图片模型", ["openai", "dashscope"])}
        {renderModelGroup("vision", "多模态模型", ["openai", "dashscope"])}
        {renderModelGroup("tts", "TTS 模型", ["openai-tts", "dashscope-tts", "azure-speech"])}
        <p className="text-xs text-white/30 pl-1">提示：接口地址/API Key 按供应商共享（任一分组里改即全局生效）；Edge TTS 免费无需配置；ComfyUI 在「ComfyUI 参数」页配。点 API Key 眼睛图标看完整内容。</p>
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
        <Field label="分辨率" desc="图片与视频共用">
          <Select value={settings.pipeline.resolution} onChange={(v) => patch("pipeline", { resolution: v })} options={[
            { value: "1080x1920", label: "1080×1920 竖屏" }, { value: "1920x1080", label: "1920×1080 横屏" },
            { value: "1080x1080", label: "1080×1080 方形" }, { value: "720x1280", label: "720×1280 竖屏HD" }, { value: "1280x720", label: "1280×720 横屏HD" },
          ]} />
        </Field>
        <PurposeSelect label="文章总结模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.summary_provider} model={settings.pipeline.summary_model}
          modelOptions={modelsOf(settings.pipeline.summary_provider, "text")}
          onProvider={(v) => patch("pipeline", { summary_provider: v })} onModel={(v) => patch("pipeline", { summary_model: v })} />
        <PurposeSelect label="文案脚本模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.script_provider} model={settings.pipeline.script_model}
          modelOptions={modelsOf(settings.pipeline.script_provider, "text")}
          onProvider={(v) => patch("pipeline", { script_provider: v })} onModel={(v) => patch("pipeline", { script_model: v })} />
        <PurposeSelect label="图片生成模型" providerKeys={["comfyui", ...llmProviderKeys]} desc="comfyui 时为图片 workflow"
          provider={settings.pipeline.image_provider} model={settings.pipeline.image_model}
          modelOptions={settings.pipeline.image_provider === "comfyui" ? ["z_image", "qwen"] : modelsOf(settings.pipeline.image_provider, "image")}
          onProvider={(v) => patch("pipeline", { image_provider: v })} onModel={(v) => patch("pipeline", { image_model: v })} />
        <PurposeSelect label="文档解析模型" providerKeys={llmProviderKeys}
          provider={settings.pipeline.vision_provider} model={settings.pipeline.vision_model}
          modelOptions={modelsOf(settings.pipeline.vision_provider, "vision")}
          onProvider={(v) => patch("pipeline", { vision_provider: v })} onModel={(v) => patch("pipeline", { vision_model: v })} />
        <Field label="语音生成模型"
          desc={settings.pipeline.default_language === "en" && !settings.pipeline.tts_voice.startsWith("en") ? "⚠ 当前语言为英文，建议选英文音色（en-US-*）" : "供应商 + 音色"}>
          <div className="grid grid-cols-2 gap-2">
            <Select value={settings.pipeline.tts_provider} onChange={(v) => patch("pipeline", { tts_provider: v })}
              options={Object.keys(TTS_PRESETS).map((k) => ({ value: k, label: TTS_PRESETS[k].label }))} />
            {(VOICES[settings.pipeline.tts_provider]?.length ?? 0) > 0 ? (
              <Select value={settings.pipeline.tts_voice} onChange={(v) => patch("pipeline", { tts_voice: v })} options={VOICES[settings.pipeline.tts_provider]} />
            ) : (
              <input value={settings.pipeline.tts_voice} onChange={(e) => patch("pipeline", { tts_voice: e.target.value })} placeholder="音色 ID" className={inputCls} />
            )}
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
            { value: "wan5b", label: "Wan2.2 5B (默认/快)" }, { value: "wan14b", label: "Wan2.2 14B (质量)" },
            { value: "wan14b_lightx2v", label: "Wan2.2 14B Lightx2v (4步快)" }, { value: "ltx", label: "LTX 2.3" },
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
          <Select value={settings.video.fps} onChange={(v) => patch("video", { fps: v })} options={[
            { value: "24", label: "24" }, { value: "25", label: "25" }, { value: "30", label: "30" },
          ]} />
        </Field>
        <Field label="场景间隔">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.video.scene_gap_ms} onChange={(e) => patch("video", { scene_gap_ms: Number(e.target.value) })} min={0} max={2000} step={100} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-16 text-right">{settings.video.scene_gap_ms}ms</span>
          </div>
        </Field>
        <Field label="转场效果">
          <Select value={settings.video.transition} onChange={(v) => patch("video", { transition: v })} options={[
            { value: "crossfade", label: "交叉淡入淡出" }, { value: "fade", label: "淡入淡出" },
            { value: "slide", label: "滑动" }, { value: "cut", label: "直接切换（无转场）" },
          ]} />
        </Field>
        <Field label="字幕字号" desc="按渲染分辨率计的像素值，过小会看不清">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.video.subtitle_font_size} onChange={(e) => patch("video", { subtitle_font_size: Number(e.target.value) })} min={24} max={96} step={2} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-16 text-right">{settings.video.subtitle_font_size}px</span>
          </div>
        </Field>
        <Field label="字幕最多行数" desc="超长旁白会按此上限自动切分成多条短字幕">
          <Select value={String(settings.video.subtitle_max_lines)} onChange={(v) => patch("video", { subtitle_max_lines: Number(v) })} options={[
            { value: "1", label: "1 行" }, { value: "2", label: "2 行" }, { value: "3", label: "3 行" },
          ]} />
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
            <input value={settings.comfyui.server_url} onChange={(e) => patch("comfyui", { server_url: e.target.value })} className={monoInputCls} />
          </Field>
          <Field label="默认负向提示词" desc="图片与视频生成共用，描述不想要的画面元素">
            <input value={settings.comfyui.default_negative} onChange={(e) => patch("comfyui", { default_negative: e.target.value })} placeholder="模糊, 丑陋, 变形, 低质量, 水印" className={inputCls} />
          </Field>
        </Section>

        <Section title="图片 workflow 参数" desc="选「图片生成模型 = ComfyUI」时生效；横铺切换各 workflow 配置参数。">
          <TabStrip tabs={[{ key: "z_image", label: "z_image turbo" }, { key: "qwen", label: "Qwen-Image" }]} active={imgWf} onSelect={setImgWf} />
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
            { key: "wan5b", label: "Wan2.2 5B" }, { key: "wan14b", label: "Wan2.2 14B" },
            { key: "wan14b_lightx2v", label: "14B Lightx2v" }, { key: "ltx", label: "LTX 2.3" },
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

      {activeTab === "prompts" && (<>
      <Section title="提示词" desc="流水线各步骤的 AI 提示词；中文/英文各一套（任务语言决定用哪套），留空回退内置默认。改后点上方「保存」。">
        {promptDefs && Object.entries(promptDefs).map(([key, def], idx) => {
          const rows = [0, 1, 6].includes(idx) ? 14 : 7;
          const ta = "w-full bg-white/[0.03] border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-white/80 font-mono leading-relaxed resize-y focus:outline-none focus:border-blue-400/40";
          return (
            <div key={key} className="mb-5">
              <label className="text-sm text-white/70">{def.label}<span className="text-white/30 text-xs ml-2">{def.desc}</span></label>
              <div className="grid grid-cols-2 gap-3 mt-1.5">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-white/40">中文</span>
                    <button onClick={() => patch("prompts", { [key]: def.default })} className="text-xs text-white/30 hover:text-white/60">恢复默认</button>
                  </div>
                  <textarea value={settings.prompts?.[key] || def.default} onChange={(e) => patch("prompts", { [key]: e.target.value })} rows={rows} className={ta} />
                </div>
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-white/40">English</span>
                    <button onClick={() => patch("prompts", { [`${key}_en`]: def.default_en })} className="text-xs text-white/30 hover:text-white/60">恢复默认</button>
                  </div>
                  <textarea value={settings.prompts?.[`${key}_en`] || def.default_en} onChange={(e) => patch("prompts", { [`${key}_en`]: e.target.value })} rows={rows} className={ta} />
                </div>
              </div>
            </div>
          );
        })}
      </Section>
      </>)}

      {activeTab === "users" && <UsersTab />}

      {activeTab !== "users" && (
        <p className="text-xs text-white/20 text-center pt-2">
          设置保存在 config.yaml
        </p>
      )}
    </div>
  );
}
