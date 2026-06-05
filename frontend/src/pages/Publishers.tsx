import { useState } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import type { PublishTarget } from "../types";
import { PLATFORM_LABELS, PLATFORM_MEDIA, PLATFORM_FIELDS } from "../types";
import {
  btnPrimary, btnSecondary, btnDanger, cardCls, chipCls,
  inputCls, labelCls, dialogOverlayCls, dialogPanelCls, errorTextCls,
  toggleCls, toggleThumbCls,
} from "../styles";
import { Select } from "../components/Select";
import { PasswordInput } from "../components/PasswordInput";

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
  // 启用/禁用不在本窗口内改，由列表外侧的开关按 target 控制；这里仅在保存时透传原值
  const [enabled] = useState(target?.enabled ?? true);
  const [fields, setFields] = useState<Record<string, string>>(() => parseConfig(target?.config_json ?? null));
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
            {fd.secret ? (
              <PasswordInput
                value={fields[fd.key] ?? ""}
                onChange={(v) => setFields((prev) => ({ ...prev, [fd.key]: v }))}
                placeholder={fd.placeholder}
                className={`${inputCls} font-mono text-[13px]`}
              />
            ) : (
              <input
                type="text"
                value={fields[fd.key] ?? ""}
                onChange={(e) => setFields((prev) => ({ ...prev, [fd.key]: e.target.value }))}
                placeholder={fd.placeholder}
                className={`${inputCls} font-mono text-[13px]`}
              />
            )}
          </div>
        ))}

        {error && <p className={`${errorTextCls} mb-3`}>{error}</p>}

        <div className="flex justify-end gap-3 mt-4">
          <button onClick={onClose} className={btnSecondary}>取消</button>
          <button onClick={handleSubmit} disabled={loading} className={btnPrimary}>
            {loading ? "保存中..." : isEdit ? "保存" : "添加"}
          </button>
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

  const handleToggleEnabled = async (t: PublishTarget) => {
    await api.publishers.update(t.id, { enabled: !t.enabled });
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
                    <span className="text-sm font-medium text-white/96">{t.name}</span>
                    <span className={`${chipCls} ${PLATFORM_CHIP[t.platform] ?? "bg-white/[0.06] text-white/66"}`}>
                      {PLATFORM_LABELS[t.platform] ?? t.platform}
                    </span>
                    <span className={`${chipCls} bg-white/[0.06] text-white/66`}>
                      {MEDIA_LABEL[PLATFORM_MEDIA[t.platform] ?? "video"]}
                    </span>
                    {!t.enabled && <span className="text-[10px] text-white/52 italic">已禁用</span>}
                  </div>
                  <div className="flex gap-4 mt-2">
                    {fieldDefs.slice(0, 3).map((fd) => {
                      const val = cfg[fd.key];
                      if (!val) return null;
                      return (
                        <span key={fd.key} className="text-[11px] text-white/52">
                          {fd.label}: {fd.secret ? maskValue(val) : val}
                        </span>
                      );
                    })}
                  </div>
                </div>
                <div className="flex items-center gap-3" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    onClick={() => handleToggleEnabled(t)}
                    className={toggleCls(t.enabled)}
                    title={t.enabled ? "已启用（点击禁用此账号）" : "已禁用（点击启用此账号）"}
                  >
                    <span className={toggleThumbCls(t.enabled)} />
                  </button>
                  <button onClick={() => handleDelete(t.id)} className={btnDanger}>删除</button>
                </div>
              </div>
            </div>
          );
        })}
        {(!targets || targets.length === 0) && (
          <div className={`${cardCls} p-12 text-center`}>
            <p className="text-white/60 text-sm">暂无发布平台</p>
            <p className="text-white/46 text-xs mt-1">添加平台以启用视频发布功能</p>
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
