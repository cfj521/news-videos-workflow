import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { api, type AppSettings } from "../api/client";
import { useToast } from "../components/Toast";
import { Select } from "../components/Select";
import {
  inputCls as _inputCls,
  monoInputCls as _monoInputCls,
  btnPrimary,
  btnCompact,
  sectionTitleCls,
  toggleCls,
  toggleThumbCls,
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

const TEXT_PRESETS: Record<string, ProviderPreset> = {
  claude: { label: "Anthropic Claude", baseUrl: "https://api.anthropic.com", models: ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"] },
  openai: { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o"] },
  dashscope: { label: "阿里云 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"] },
};

const IMAGE_PRESETS: Record<string, ProviderPreset> = {
  openai: { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-image-1", "dall-e-3"] },
  dashscope: { label: "阿里云 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["wanx-v1", "wanx2.1-t2i-turbo"] },
};

const TTS_PRESETS: Record<string, ProviderPreset> = {
  "edge-tts": { label: "Edge TTS", baseUrl: "", models: [], needsKey: false },
  "openai-tts": { label: "OpenAI TTS", baseUrl: "https://api.openai.com/v1", models: ["tts-1-hd", "tts-1"], needsKey: true },
  "dashscope-tts": { label: "阿里云 CosyVoice", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["cosyvoice-v1", "cosyvoice-v2"], needsKey: true },
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

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[11rem_1fr] gap-4 items-start">
      <label className="text-sm text-white/40 pt-2 select-none">{label}</label>
      <div>{children}</div>
    </div>
  );
}

function SecretField({ label, value, onChange, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <Field label={label}>
      <div className="flex gap-2">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? "sk-..."}
          className={`flex-1 ${monoInputCls}`}
        />
        <button type="button" onClick={() => setShow((v) => !v)} className={btnCompact}>
          {show ? "隐藏" : "显示"}
        </button>
      </div>
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
// Provider section
// ---------------------------------------------------------------------------

interface ProviderFieldValues {
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
}

function ProviderSection({ title, desc, presets, config, onChange }: {
  title: string; desc: string;
  presets: Record<string, ProviderPreset>;
  config: ProviderFieldValues;
  onChange: (patch: Partial<ProviderFieldValues>) => void;
}) {
  const isCustom = !(config.provider in presets);
  const preset = presets[config.provider];
  const models = preset?.models ?? [];
  const options = [
    ...Object.entries(presets).map(([k, v]) => ({ value: k, label: v.label })),
    { value: "__custom__", label: "自定义" },
  ];

  const handleProviderChange = (v: string) => {
    if (v === "__custom__") {
      onChange({ provider: "__custom__", base_url: "", model: "" });
    } else {
      const p = presets[v];
      if (p) onChange({ provider: v, base_url: p.baseUrl, model: p.models[0] ?? "" });
    }
  };

  return (
    <Section title={title} desc={desc}>
      <Field label="服务商">
        <Select value={isCustom ? "__custom__" : config.provider} onChange={handleProviderChange} options={options} />
      </Field>
      {isCustom && (
        <Field label="服务商名称">
          <input value={config.provider === "__custom__" ? "" : config.provider} onChange={(e) => onChange({ provider: e.target.value })} placeholder="例如 deepseek" className={inputCls} />
        </Field>
      )}
      <Field label="接口地址">
        <input value={config.base_url} onChange={(e) => onChange({ base_url: e.target.value })} placeholder={isCustom ? "https://api.example.com/v1" : "自动填充，可按需修改"} className={monoInputCls} />
      </Field>
      <Field label="模型">
        <ModelInput value={config.model} onChange={(v) => onChange({ model: v })} suggestions={models} />
      </Field>
      <SecretField label="API Key" value={config.api_key} onChange={(v) => onChange({ api_key: v })} />
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

const SUMMARY_PRESETS: Record<string, ProviderPreset> = {
  "": { label: "同文本模型", baseUrl: "", models: [] },
  openai: { label: "OpenAI", baseUrl: "https://api.openai.com/v1", models: ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"] },
  claude: { label: "Anthropic Claude", baseUrl: "https://api.anthropic.com", models: ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"] },
  dashscope: { label: "阿里云 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: ["qwen-turbo", "qwen-plus", "qwen-max"] },
};

const EMPTY_SETTINGS: AppSettings = {
  text: { provider: "claude", base_url: "https://api.anthropic.com", model: "claude-sonnet-4-6", api_key: "" },
  image: { provider: "openai", base_url: "https://api.openai.com/v1", model: "gpt-image-1", api_key: "" },
  tts: { provider: "edge-tts", base_url: "", api_key: "", model: "", voice: "zh-CN-XiaoxiaoNeural", speed: 1.0 },
  summary: { enabled: true, provider: "", base_url: "", model: "", api_key: "", max_length: 150 },
  collectors: { tavily_key: "", brave_key: "", serper_key: "" },
  youtube: { client_id: "", client_secret: "" },
  pipeline: { default_time_range: "7d", default_max_articles: 5, default_video_route: "hyperframes", default_language: "zh", dedup_lookback: "30d" },
  video: { resolution: "1080x1920", aspect_ratio: "9:16", fps: "30", scene_gap_ms: 500, transition: "crossfade" },
  ltx: { model_dir: "", checkpoint: "ltx-2.3-22b-distilled-1.1.safetensors", upsampler: "ltx-2.3-spatial-upscaler-x2-1.1.safetensors", distilled_lora: "ltx-2.3-22b-distilled-lora-384.safetensors", lora_strength: 0.6, gemma_dir: "", inference_steps: 8, cfg_scale: 3.0, stg_scale: 1.0, fps: 25.0, use_fp8: true },
};

export function SettingsPage() {
  const { data: remote, error: loadError, mutate } = useSWR("settings", api.settings.get);
  const [settings, setSettings] = useState<AppSettings>(EMPTY_SETTINGS);
  const [dirty, setDirty] = useState(false);
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

  // TTS
  const ttsPreset = TTS_PRESETS[settings.tts.provider];
  const ttsIsCustom = !ttsPreset;
  const ttsNeedsKey = ttsIsCustom || (ttsPreset?.needsKey ?? false);
  const ttsModels = ttsPreset?.models ?? [];
  const ttsVoiceList = VOICES[settings.tts.provider] ?? [];

  const ttsProviderOptions = [
    ...Object.entries(TTS_PRESETS).map(([k, v]) => ({ value: k, label: v.label })),
    { value: "__custom__", label: "自定义" },
  ];

  const handleTTSProviderChange = (v: string) => {
    if (v === "__custom__") patch("tts", { provider: "__custom__", base_url: "", model: "", api_key: "" });
    else { const p = TTS_PRESETS[v]; if (p) patch("tts", { provider: v, base_url: p.baseUrl, model: p.models[0] ?? "" }); }
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
        <button onClick={handleSave} disabled={!dirty} className={`${btnPrimary} ${dirty ? "" : "opacity-40 cursor-default"}`}>
          保存
        </button>
      </div>

      <Section title="文章摘要" desc="对采集的文章进行 LLM 摘要（留空服务商则复用文本模型配置）">
        <Field label="服务商">
          <Select
            value={settings.summary.provider || ""}
            onChange={(v) => {
              const p = SUMMARY_PRESETS[v];
              if (p) patch("summary", { provider: v, base_url: p.baseUrl, model: p.models[0] ?? "" });
              else patch("summary", { provider: v });
            }}
            options={Object.entries(SUMMARY_PRESETS).map(([k, v]) => ({ value: k, label: v.label }))}
          />
        </Field>
        {settings.summary.provider && (
          <>
            <Field label="接口地址">
              <input value={settings.summary.base_url} onChange={(e) => patch("summary", { base_url: e.target.value })} placeholder="自动填充" className={monoInputCls} />
            </Field>
            <Field label="模型">
              <ModelInput
                value={settings.summary.model}
                onChange={(v) => patch("summary", { model: v })}
                suggestions={SUMMARY_PRESETS[settings.summary.provider]?.models ?? []}
              />
            </Field>
            <SecretField label="API Key" value={settings.summary.api_key} onChange={(v) => patch("summary", { api_key: v })} />
          </>
        )}
        <Field label="最大长度">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.summary.max_length} onChange={(e) => patch("summary", { max_length: Number(e.target.value) })} min={50} max={500} step={10} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-12 text-right">{settings.summary.max_length}字</span>
          </div>
        </Field>
      </Section>

      <ProviderSection title="文本模型" desc="用于脚本生成的 AI 文本模型" presets={TEXT_PRESETS} config={settings.text} onChange={(p) => patch("text", p)} />
      <ProviderSection title="图片模型" desc="用于场景配图的 AI 图片模型" presets={IMAGE_PRESETS} config={settings.image} onChange={(p) => patch("image", p)} />

      <Section title="语音合成" desc="视频旁白的文字转语音服务">
        <Field label="服务商">
          <Select value={ttsIsCustom ? "__custom__" : settings.tts.provider} onChange={handleTTSProviderChange} options={ttsProviderOptions} />
        </Field>
        {ttsIsCustom && (
          <Field label="服务商名称">
            <input value={settings.tts.provider === "__custom__" ? "" : settings.tts.provider} onChange={(e) => patch("tts", { provider: e.target.value })} placeholder="例如 cosyvoice" className={inputCls} />
          </Field>
        )}
        {ttsNeedsKey && (
          <>
            <Field label="接口地址">
              <input value={settings.tts.base_url} onChange={(e) => patch("tts", { base_url: e.target.value })} placeholder={ttsIsCustom ? "https://api.example.com/v1" : "自动填充"} className={monoInputCls} />
            </Field>
            <SecretField label="API Key" value={settings.tts.api_key} onChange={(v) => patch("tts", { api_key: v })} />
          </>
        )}
        {(ttsModels.length > 0 || ttsIsCustom) && (
          <Field label="模型">
            <ModelInput value={settings.tts.model} onChange={(v) => patch("tts", { model: v })} suggestions={ttsModels} />
          </Field>
        )}
        <Field label="音色">
          {ttsVoiceList.length > 0 ? (
            <Select value={settings.tts.voice} onChange={(v) => patch("tts", { voice: v })} options={ttsVoiceList} />
          ) : (
            <input value={settings.tts.voice} onChange={(e) => patch("tts", { voice: e.target.value })} placeholder="音色 ID" className={inputCls} />
          )}
        </Field>
        <Field label="语速">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.tts.speed} onChange={(e) => patch("tts", { speed: Number(e.target.value) })} min={0.5} max={2.0} step={0.1} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-12 text-right">{settings.tts.speed.toFixed(1)}x</span>
          </div>
        </Field>
      </Section>

      <Section title="流水线默认值">
        <Field label="时间范围">
          <Select value={settings.pipeline.default_time_range} onChange={(v) => patch("pipeline", { default_time_range: v })} options={[
            { value: "1d", label: "最近 1 天" }, { value: "3d", label: "最近 3 天" }, { value: "7d", label: "最近 7 天" }, { value: "15d", label: "最近 15 天" }, { value: "1m", label: "最近 1 个月" },
          ]} />
        </Field>
        <Field label="最大文章数">
          <input type="number" value={settings.pipeline.default_max_articles} onChange={(e) => patch("pipeline", { default_max_articles: Number(e.target.value) })} min={1} max={50} className={inputCls} />
        </Field>
        <Field label="视频路线">
          <Select value={settings.pipeline.default_video_route} onChange={(v) => patch("pipeline", { default_video_route: v })} options={[
            { value: "hyperframes", label: "Hyperframes (MVP)" }, { value: "ltx", label: "LTX 2.3" },
          ]} />
        </Field>
        <Field label="语言">
          <Select value={settings.pipeline.default_language} onChange={(v) => patch("pipeline", { default_language: v })} options={[
            { value: "zh", label: "中文" }, { value: "en", label: "English" },
          ]} />
        </Field>
      </Section>

      <Section title="视频输出">
        <Field label="分辨率">
          <Select value={settings.video.resolution} onChange={(v) => patch("video", { resolution: v })} options={[
            { value: "1080x1920", label: "1080 × 1920" }, { value: "1920x1080", label: "1920 × 1080" },
            { value: "1024x1024", label: "1024 × 1024" }, { value: "720x1280", label: "720 × 1280" },
          ]} />
        </Field>
        <Field label="画面比例">
          <Select value={settings.video.aspect_ratio} onChange={(v) => patch("video", { aspect_ratio: v })} options={[
            { value: "9:16", label: "9:16 (竖屏)" }, { value: "16:9", label: "16:9 (横屏)" },
            { value: "1:1", label: "1:1 (方形)" }, { value: "4:3", label: "4:3" },
          ]} />
        </Field>
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
      </Section>

      <Section title="LTX-2.3 视频生成" desc="本地 AI 视频生成模型配置（选择 LTX 路线时使用）">
        <Field label="模型目录">
          <input value={settings.ltx.model_dir} onChange={(e) => patch("ltx", { model_dir: e.target.value })} placeholder="/path/to/models/ltx-2.3" className={monoInputCls} />
        </Field>
        <Field label="Checkpoint">
          <input value={settings.ltx.checkpoint} onChange={(e) => patch("ltx", { checkpoint: e.target.value })} className={monoInputCls} />
        </Field>
        <Field label="空间上采样器">
          <input value={settings.ltx.upsampler} onChange={(e) => patch("ltx", { upsampler: e.target.value })} className={monoInputCls} />
        </Field>
        <Field label="蒸馏 LoRA">
          <input value={settings.ltx.distilled_lora} onChange={(e) => patch("ltx", { distilled_lora: e.target.value })} className={monoInputCls} />
        </Field>
        <Field label="LoRA 强度">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.ltx.lora_strength} onChange={(e) => patch("ltx", { lora_strength: Number(e.target.value) })} min={0} max={1} step={0.1} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-10 text-right">{settings.ltx.lora_strength.toFixed(1)}</span>
          </div>
        </Field>
        <Field label="Gemma 目录">
          <input value={settings.ltx.gemma_dir} onChange={(e) => patch("ltx", { gemma_dir: e.target.value })} placeholder="留空则使用模型目录/gemma" className={monoInputCls} />
        </Field>
        <Field label="推理步数">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.ltx.inference_steps} onChange={(e) => patch("ltx", { inference_steps: Number(e.target.value) })} min={4} max={50} step={1} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-10 text-right">{settings.ltx.inference_steps}</span>
          </div>
        </Field>
        <Field label="CFG Scale">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.ltx.cfg_scale} onChange={(e) => patch("ltx", { cfg_scale: Number(e.target.value) })} min={1} max={7} step={0.5} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-10 text-right">{settings.ltx.cfg_scale.toFixed(1)}</span>
          </div>
        </Field>
        <Field label="STG Scale">
          <div className="flex items-center gap-3">
            <input type="range" value={settings.ltx.stg_scale} onChange={(e) => patch("ltx", { stg_scale: Number(e.target.value) })} min={0} max={2} step={0.1} className="flex-1 accent-blue-500" />
            <span className="text-sm text-white/50 tabular-nums w-10 text-right">{settings.ltx.stg_scale.toFixed(1)}</span>
          </div>
        </Field>
        <Field label="帧率">
          <Select value={String(settings.ltx.fps)} onChange={(v) => patch("ltx", { fps: Number(v) })} options={[
            { value: "24", label: "24 fps" }, { value: "25", label: "25 fps" }, { value: "48", label: "48 fps" }, { value: "50", label: "50 fps" },
          ]} />
        </Field>
        <Field label="FP8 量化">
          <button type="button" onClick={() => patch("ltx", { use_fp8: !settings.ltx.use_fp8 })} className={toggleCls(settings.ltx.use_fp8)}>
            <span className={toggleThumbCls(settings.ltx.use_fp8)} />
          </button>
        </Field>
      </Section>

      <p className="text-xs text-white/20 text-center pt-2">
        设置保存在 backend/config.yaml
      </p>
    </div>
  );
}
