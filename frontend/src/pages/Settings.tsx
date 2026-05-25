import { useState, useEffect } from "react";
import { useToast } from "../components/Toast";

const SETTINGS_KEY = "newsvid_settings";

interface AppSettings {
  // API Keys
  anthropicKey: string;
  openaiKey: string;
  tavilyKey: string;
  braveKey: string;
  serperKey: string;
  // Pipeline Defaults
  defaultTimeRange: string;
  defaultMaxArticles: number;
  defaultVideoRoute: "hyperframes" | "ltx";
  defaultLanguage: "zh" | "en";
  // TTS Settings
  defaultVoice: string;
  defaultSpeed: number;
  // Video Settings
  resolution: string;
  fps: string;
}

const DEFAULT_SETTINGS: AppSettings = {
  anthropicKey: "",
  openaiKey: "",
  tavilyKey: "",
  braveKey: "",
  serperKey: "",
  defaultTimeRange: "7d",
  defaultMaxArticles: 5,
  defaultVideoRoute: "hyperframes",
  defaultLanguage: "zh",
  defaultVoice: "zh-CN-XiaoxiaoNeural",
  defaultSpeed: 1.0,
  resolution: "1080x1920",
  fps: "30",
};

function loadSettings(): AppSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {}
  return { ...DEFAULT_SETTINGS };
}

function SettingsSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-gray-800 rounded-lg p-5 mb-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-4 uppercase tracking-wide">
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function SettingsField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <label className="text-sm text-gray-400 w-48 flex-shrink-0">{label}</label>
      <div className="flex-1 max-w-md">{children}</div>
    </div>
  );
}

function ApiKeyField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  return (
    <SettingsField label={label}>
      <div className="flex gap-2">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="sk-..."
          className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500 font-mono"
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          className="px-2 py-2 text-gray-500 hover:text-gray-300 text-sm border border-gray-700 rounded bg-gray-800"
          title={show ? "Hide" : "Show"}
        >
          {show ? "🙈" : "👁"}
        </button>
      </div>
    </SettingsField>
  );
}

const inputCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";
const selectCls =
  "w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-blue-500";

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(loadSettings);
  const { showToast } = useToast();

  // Reload if localStorage changes in another tab
  useEffect(() => {
    const handler = () => setSettings(loadSettings());
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  const set = <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = () => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    showToast("Settings saved locally", "success");
  };

  return (
    <div className="max-w-2xl">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Settings</h1>
        <button
          onClick={handleSave}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium"
        >
          Save Settings
        </button>
      </div>

      <SettingsSection title="API Keys">
        <ApiKeyField
          label="Anthropic"
          value={settings.anthropicKey}
          onChange={(v) => set("anthropicKey", v)}
        />
        <ApiKeyField
          label="OpenAI"
          value={settings.openaiKey}
          onChange={(v) => set("openaiKey", v)}
        />
        <ApiKeyField
          label="Tavily"
          value={settings.tavilyKey}
          onChange={(v) => set("tavilyKey", v)}
        />
        <ApiKeyField
          label="Brave Search"
          value={settings.braveKey}
          onChange={(v) => set("braveKey", v)}
        />
        <ApiKeyField
          label="Serper"
          value={settings.serperKey}
          onChange={(v) => set("serperKey", v)}
        />
      </SettingsSection>

      <SettingsSection title="Pipeline Defaults">
        <SettingsField label="Default Time Range">
          <select
            value={settings.defaultTimeRange}
            onChange={(e) => set("defaultTimeRange", e.target.value)}
            className={selectCls}
          >
            <option value="1d">Last 1 day</option>
            <option value="3d">Last 3 days</option>
            <option value="7d">Last 7 days</option>
            <option value="15d">Last 15 days</option>
            <option value="1m">Last month</option>
          </select>
        </SettingsField>
        <SettingsField label="Default Max Articles">
          <input
            type="number"
            value={settings.defaultMaxArticles}
            onChange={(e) => set("defaultMaxArticles", Number(e.target.value))}
            min={1}
            max={50}
            className={inputCls}
          />
        </SettingsField>
        <SettingsField label="Default Video Route">
          <select
            value={settings.defaultVideoRoute}
            onChange={(e) =>
              set("defaultVideoRoute", e.target.value as "hyperframes" | "ltx")
            }
            className={selectCls}
          >
            <option value="hyperframes">Hyperframes (MVP)</option>
            <option value="ltx">LTX 2.3</option>
          </select>
        </SettingsField>
        <SettingsField label="Default Language">
          <select
            value={settings.defaultLanguage}
            onChange={(e) =>
              set("defaultLanguage", e.target.value as "zh" | "en")
            }
            className={selectCls}
          >
            <option value="zh">Chinese (zh)</option>
            <option value="en">English (en)</option>
          </select>
        </SettingsField>
      </SettingsSection>

      <SettingsSection title="TTS Settings">
        <SettingsField label="Default Voice">
          <select
            value={settings.defaultVoice}
            onChange={(e) => set("defaultVoice", e.target.value)}
            className={selectCls}
          >
            <optgroup label="Chinese">
              <option value="zh-CN-XiaoxiaoNeural">
                zh-CN-XiaoxiaoNeural (Female)
              </option>
              <option value="zh-CN-YunxiNeural">
                zh-CN-YunxiNeural (Male)
              </option>
              <option value="zh-CN-XiaohanNeural">
                zh-CN-XiaohanNeural (Female)
              </option>
              <option value="zh-CN-YunyangNeural">
                zh-CN-YunyangNeural (Male, News)
              </option>
            </optgroup>
            <optgroup label="English">
              <option value="en-US-JennyNeural">
                en-US-JennyNeural (Female)
              </option>
              <option value="en-US-GuyNeural">en-US-GuyNeural (Male)</option>
              <option value="en-US-AriaNeural">en-US-AriaNeural (Female)</option>
            </optgroup>
          </select>
        </SettingsField>
        <SettingsField label="Default Speed">
          <div className="flex items-center gap-3">
            <input
              type="range"
              value={settings.defaultSpeed}
              onChange={(e) => set("defaultSpeed", Number(e.target.value))}
              min={0.5}
              max={2.0}
              step={0.1}
              className="flex-1"
            />
            <span className="text-sm text-gray-300 w-10 text-right">
              {settings.defaultSpeed.toFixed(1)}x
            </span>
          </div>
        </SettingsField>
      </SettingsSection>

      <SettingsSection title="Video Settings">
        <SettingsField label="Resolution">
          <select
            value={settings.resolution}
            onChange={(e) => set("resolution", e.target.value)}
            className={selectCls}
          >
            <option value="1080x1920">1080×1920 (Portrait / Vertical)</option>
            <option value="1920x1080">1920×1080 (Landscape / Horizontal)</option>
          </select>
        </SettingsField>
        <SettingsField label="FPS">
          <select
            value={settings.fps}
            onChange={(e) => set("fps", e.target.value)}
            className={selectCls}
          >
            <option value="24">24 fps</option>
            <option value="25">25 fps</option>
            <option value="30">30 fps</option>
          </select>
        </SettingsField>
      </SettingsSection>

      <p className="text-xs text-gray-600 mt-4">
        Settings are stored in browser localStorage. Backend wiring coming
        soon.
      </p>
    </div>
  );
}
