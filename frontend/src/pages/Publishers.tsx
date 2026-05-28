import { useState } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import type { PublishTarget } from "../types";
import { PLATFORM_LABELS, PLATFORM_MEDIA } from "../types";
import {
  btnPrimary, btnSecondary, btnDanger, btnCompact, cardCls, chipCls,
  inputCls, labelCls, dialogOverlayCls, dialogPanelCls, errorTextCls,
} from "../styles";
import { Select } from "../components/Select";

// ── Platform config field definitions ───────────────────

interface FieldDef {
  key: string;
  label: string;
  secret?: boolean;
  placeholder?: string;
}

const PLATFORM_FIELDS: Record<string, FieldDef[]> = {
  youtube: [
    { key: "client_id", label: "Client ID", placeholder: "xxxxx.apps.googleusercontent.com" },
    { key: "client_secret", label: "Client Secret", secret: true, placeholder: "GOCSPX-..." },
    { key: "refresh_token", label: "Refresh Token", secret: true },
  ],
  instagram: [
    { key: "user_id", label: "User ID", placeholder: "Instagram 商业账号 ID" },
    { key: "access_token", label: "Access Token", secret: true },
    { key: "file_host_url", label: "视频公开 URL", placeholder: "https://your-cdn.com/video.mp4" },
  ],
  bilibili: [
    { key: "sessdata", label: "SESSDATA", secret: true },
    { key: "bili_jct", label: "bili_jct", secret: true },
    { key: "buvid3", label: "buvid3", secret: true },
    { key: "tid", label: "分区 ID", placeholder: "17 (科技>数码)" },
  ],
  douyin: [
    { key: "method", label: "接入方式", placeholder: "api / playwright" },
    { key: "client_key", label: "Client Key" },
    { key: "client_secret", label: "Client Secret", secret: true },
    { key: "access_token", label: "Access Token", secret: true },
  ],
  kuaishou: [
    { key: "method", label: "接入方式", placeholder: "api / playwright" },
    { key: "app_id", label: "App ID" },
    { key: "app_secret", label: "App Secret", secret: true },
    { key: "access_token", label: "Access Token", secret: true },
  ],
  ximalaya: [
    { key: "access_token", label: "Access Token", secret: true },
  ],
  xiaoyuzhou: [
    { key: "cookie", label: "Cookie", secret: true },
  ],
  netease_music: [
    { key: "cookie", label: "Cookie", secret: true },
  ],
  apple_podcasts: [
    { key: "rss_url", label: "RSS URL", placeholder: "https://feeds.example.com/podcast.xml" },
  ],
};

const PLATFORM_OPTIONS = Object.entries(PLATFORM_LABELS).map(([k, v]) => ({ value: k, label: v }));

// ── Helpers ─────────────────────────────────────────────

function parseConfig(json: string | null): Record<string, string> {
  if (!json) return {};
  try { return JSON.parse(json); } catch { return {}; }
}

function buildConfig(fields: Record<string, string>): string | null {
  const cleaned: Record<string, string> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (v.trim()) cleaned[k] = v.trim();
  }
  return Object.keys(cleaned).length > 0 ? JSON.stringify(cleaned) : null;
}

function maskValue(v: string): string {
  if (!v || v.length < 8) return "••••";
  return v.slice(0, 4) + "••••" + v.slice(-4);
}

// ── Add/Edit Dialog ─────────────────────────────────────

function TargetDialog({ target, onSave, onClose }: {
  target: PublishTarget | null;
  onSave: () => void;
  onClose: () => void;
}) {
  const isEdit = !!target;
  const [name, setName] = useState(target?.name ?? "");
  const [platform, setPlatform] = useState(target?.platform ?? "youtube");
  const [enabled, setEnabled] = useState(target?.enabled ?? true);
  const [fields, setFields] = useState<Record<string, string>>(() => parseConfig(target?.config_json ?? null));
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fieldDefs = PLATFORM_FIELDS[platform] ?? [];

  const handlePlatformChange = (p: string) => {
    setPlatform(p as PublishTarget["platform"]);
    if (!isEdit) {
      setName(PLATFORM_LABELS[p] ?? p);
      setFields({});
    }
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError("名称为必填项"); return; }
    setLoading(true);
    try {
      const body = { name, platform, enabled, config_json: buildConfig(fields) };
      if (isEdit) await api.publishers.update(target!.id, body);
      else await api.publishers.create(body);
      onSave();
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally { setLoading(false); }
  };

  return (
    <div className={dialogOverlayCls}>
      <div className={`${dialogPanelCls} w-[520px]`}>
        <h2 className="text-lg font-semibold mb-5">{isEdit ? "编辑" : "添加"}发布平台</h2>

        <label className={labelCls}>平台</label>
        <Select value={platform} onChange={handlePlatformChange} options={PLATFORM_OPTIONS} className="mb-4" />

        <label className={labelCls}>名称</label>
        <input value={name} onChange={(e) => setName(e.target.value)} className={`${inputCls} mb-4`} />

        {fieldDefs.map((fd) => (
          <div key={fd.key} className="mb-3">
            <label className={labelCls}>{fd.label}</label>
            <div className="flex gap-2">
              <input
                type={fd.secret && !showSecrets[fd.key] ? "password" : "text"}
                value={fields[fd.key] ?? ""}
                onChange={(e) => setFields((prev) => ({ ...prev, [fd.key]: e.target.value }))}
                placeholder={fd.placeholder}
                className={`flex-1 ${inputCls} font-mono text-[13px]`}
              />
              {fd.secret && (
                <button type="button" onClick={() => setShowSecrets((p) => ({ ...p, [fd.key]: !p[fd.key] }))} className={btnCompact}>
                  {showSecrets[fd.key] ? "隐藏" : "显示"}
                </button>
              )}
            </div>
          </div>
        ))}

        {error && <p className={`${errorTextCls} mb-3`}>{error}</p>}

        <div className="flex justify-between items-center mt-4">
          <div>
            {isEdit && (
              <button
                type="button"
                onClick={() => setEnabled(!enabled)}
                className={`text-xs transition ${enabled ? "text-white/40 hover:text-red-300" : "text-emerald-300 hover:text-emerald-200"}`}
              >
                {enabled ? "禁用" : "启用"}
              </button>
            )}
          </div>
          <div className="flex gap-3">
            <button onClick={onClose} className={btnSecondary}>取消</button>
            <button onClick={handleSubmit} disabled={loading} className={btnPrimary}>
              {loading ? "保存中..." : isEdit ? "保存" : "添加"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────

const PLATFORM_CHIP: Record<string, string> = {
  youtube: "bg-red-500/15 text-red-300",
  instagram: "bg-pink-500/15 text-pink-300",
  bilibili: "bg-blue-500/15 text-blue-300",
  douyin: "bg-cyan-500/15 text-cyan-300",
  kuaishou: "bg-orange-500/15 text-orange-300",
  ximalaya: "bg-orange-500/15 text-orange-300",
  xiaoyuzhou: "bg-purple-500/15 text-purple-300",
  netease_music: "bg-rose-500/15 text-rose-300",
  apple_podcasts: "bg-violet-500/15 text-violet-300",
};

const MEDIA_LABEL: Record<string, string> = { video: "视频", audio: "音频", both: "音视频" };

export function PublishersPage() {
  const { data: targets, mutate } = useSWR("publishers", api.publishers.list);
  const [dialog, setDialog] = useState<{ target: PublishTarget | null } | null>(null);

  const handleDelete = async (id: number) => {
    await api.publishers.remove(id);
    mutate();
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">发布管理</h1>
        <button onClick={() => setDialog({ target: null })} className={btnPrimary}>+ 添加平台</button>
      </div>

      <div className="space-y-3">
        {targets?.map((t) => {
          const cfg = parseConfig(t.config_json);
          const fieldDefs = PLATFORM_FIELDS[t.platform] ?? [];
          return (
            <div
              key={t.id}
              onClick={() => setDialog({ target: t })}
              className={`${cardCls} p-5 cursor-pointer hover:bg-white/[0.04] transition ${!t.enabled ? "opacity-40" : ""}`}
            >
              <div className="flex justify-between items-start">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-white/80">{t.name}</span>
                    <span className={`${chipCls} ${PLATFORM_CHIP[t.platform] ?? "bg-white/[0.06] text-white/40"}`}>
                      {PLATFORM_LABELS[t.platform] ?? t.platform}
                    </span>
                    <span className={`${chipCls} bg-white/[0.06] text-white/40`}>
                      {MEDIA_LABEL[PLATFORM_MEDIA[t.platform] ?? "video"]}
                    </span>
                    {!t.enabled && <span className="text-[10px] text-white/25 italic">已禁用</span>}
                  </div>
                  <div className="flex gap-4 mt-2">
                    {fieldDefs.slice(0, 3).map((fd) => {
                      const val = cfg[fd.key];
                      if (!val) return null;
                      return (
                        <span key={fd.key} className="text-[11px] text-white/25">
                          {fd.label}: {fd.secret ? maskValue(val) : val}
                        </span>
                      );
                    })}
                  </div>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(t.id); }}
                  className={btnDanger}
                >
                  删除
                </button>
              </div>
            </div>
          );
        })}
        {(!targets || targets.length === 0) && (
          <div className={`${cardCls} p-12 text-center`}>
            <p className="text-white/30 text-sm">暂无发布平台</p>
            <p className="text-white/20 text-xs mt-1">添加平台以启用视频发布功能</p>
          </div>
        )}
      </div>

      {dialog && (
        <TargetDialog
          target={dialog.target}
          onSave={() => { setDialog(null); mutate(); }}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}
