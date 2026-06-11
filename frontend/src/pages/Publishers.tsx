import { useState, useEffect, useRef } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import type { PublishTarget } from "../types";
import { PLATFORM_LABELS, PLATFORM_MEDIA, PLATFORM_FIELDS, SCAN_LOGIN_PLATFORMS } from "../types";
import {
  btnPrimary, btnSecondary, btnRegen, cardCls, chipCls,
  inputCls, labelCls, dialogOverlayCls, dialogPanelCls, errorTextCls,
  toggleCls, toggleThumbCls,
} from "../styles";
import { Select } from "../components/Select";
import { PasswordInput } from "../components/PasswordInput";
import { DeleteIconButton } from "../components/DeleteIconButton";
import { PlusIcon } from "../components/icons";

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

// ── 扫码登录 ────────────────────────────────────────────


type LoginStatus = "idle" | "starting" | "qr_ready" | "success" | "failed" | "timeout" | "error";

interface LoginState {
  status: LoginStatus;
  sid: string | null;
  qrBase64: string | null;
  errorMsg: string | null;
}

/** 账号内部标识（cookie 文件名用）：自动生成，对用户不可见，用户只关心「名称」。 */
function genAccountId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return "acct-" + Math.random().toString(36).slice(2) + "-" + Date.now().toString(36);
}

function ScanLoginButton({ platform, account, onSuccess }: {
  platform: string;
  account: string;
  onSuccess?: () => void;
}) {
  const [state, setState] = useState<LoginState>({
    status: "idle", sid: null, qrBase64: null, errorMsg: null,
  });
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current != null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startLogin = async () => {
    stopPolling();
    setState({ status: "starting", sid: null, qrBase64: null, errorMsg: null });
    try {
      const { sid } = await api.publishers.loginStart(platform, account);
      setState((prev) => ({ ...prev, sid }));
      // 开始轮询
      pollRef.current = setInterval(async () => {
        try {
          const res = await api.publishers.loginPoll(sid);
          if (res.status === "qr_ready") {
            setState((prev) => ({ ...prev, status: "qr_ready", qrBase64: res.qr_base64 ?? null }));
          } else if (res.status === "success") {
            stopPolling();
            setState((prev) => ({ ...prev, status: "success", qrBase64: null }));
            onSuccess?.();   // 通知外层刷新列表/登录态徽标
          } else if (["failed", "timeout", "error"].includes(res.status)) {
            stopPolling();
            setState((prev) => ({
              ...prev,
              status: res.status as LoginStatus,
              qrBase64: null,
              errorMsg: res.error ?? null,
            }));
          }
          // starting 状态继续等待
        } catch {
          stopPolling();
          setState((prev) => ({ ...prev, status: "error", errorMsg: "轮询失败" }));
        }
      }, 1500);
    } catch (e) {
      setState({
        status: "error", sid: null, qrBase64: null,
        errorMsg: e instanceof Error ? e.message : "启动登录失败",
      });
    }
  };

  // 组件卸载时清理定时器（直接操作 ref，不依赖 stopPolling 函数引用）
  useEffect(() => () => { if (pollRef.current != null) clearInterval(pollRef.current); }, []);

  const statusLabel: Record<string, string> = {
    idle: "扫码登录",
    starting: "正在启动…",
    qr_ready: "请扫码",
    success: "登录成功",
    failed: "登录失败",
    timeout: "已超时",
    error: "出错了",
  };

  return (
    <div>
      {/* 占位图框：点按钮后二维码回填到这里 */}
      <div
        className="mx-auto mb-3 flex items-center justify-center rounded-lg border border-white/[0.1] bg-white/[0.03] overflow-hidden"
        style={{ width: 200, height: 200 }}
      >
        {state.status === "qr_ready" && state.qrBase64 ? (
          <img
            src={state.qrBase64}
            alt="登录二维码"
            className="w-full h-full"
            style={{ imageRendering: "pixelated" }}
          />
        ) : state.status === "starting" ? (
          <span className="text-white/50 text-sm">二维码生成中…</span>
        ) : state.status === "success" ? (
          <span className="text-emerald-400 text-sm">✓ 登录成功</span>
        ) : ["failed", "timeout", "error"].includes(state.status) ? (
          <div className="text-center px-3">
            <p className="text-red-400 text-sm">{statusLabel[state.status]}</p>
            {state.errorMsg && <p className="text-white/40 text-[11px] mt-1 break-all">{state.errorMsg}</p>}
          </div>
        ) : (
          <div className="text-center text-white/30">
            <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="1.5" className="mx-auto">
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
              <rect x="14.5" y="14.5" width="2.5" height="2.5" />
              <rect x="18.5" y="18.5" width="2.5" height="2.5" />
            </svg>
            <p className="text-[11px] mt-2">点击下方按钮生成二维码</p>
          </div>
        )}
      </div>

      <div className="flex justify-center">
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); startLogin(); }}
          disabled={state.status === "starting"}
          className={`${btnRegen} inline-flex items-center gap-1.5`}
          title="生成二维码"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
               className={state.status === "starting" ? "animate-spin" : ""}>
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <polyline points="21 3 21 9 15 9" />
          </svg>
          生成二维码
        </button>
      </div>
    </div>
  );
}

// ── 登录态徽标 ───────────────────────────────────────────

function LoginBadge({ slug, refresh = 0 }: { slug: string; refresh?: number }) {
  const [loggedIn, setLoggedIn] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.publishers.loginStatus(slug).then((res) => {
      if (!cancelled) setLoggedIn(res.logged_in);
    }).catch(() => {
      if (!cancelled) setLoggedIn(false);
    });
    return () => { cancelled = true; };
  }, [slug, refresh]);

  if (loggedIn === null) return null;

  return (
    <span
      className={`${chipCls} ${loggedIn
        ? "bg-emerald-500/15 text-emerald-300"
        : "bg-white/[0.06] text-white/52"}`}
    >
      {loggedIn ? "已登录" : "未登录"}
    </span>
  );
}

// ── Add/Edit Dialog ─────────────────────────────────────

function TargetDialog({ target, onSave, onClose, loginTick = 0, onLoginSuccess }: {
  target: PublishTarget | null;
  onSave: () => void;
  onClose: () => void;
  loginTick?: number;
  onLoginSuccess?: () => void;
}) {
  const isEdit = !!target;
  const [name, setName] = useState(target?.name ?? "");
  const [platform, setPlatform] = useState(target?.platform ?? "youtube");
  // 启用/禁用不在本窗口内改，由列表外侧的开关按 target 控制；这里仅在保存时透传原值
  const [enabled] = useState(target?.enabled ?? true);
  const [fields, setFields] = useState<Record<string, string>>(() => parseConfig(target?.config_json ?? null));
  // 抖音/快手账号的内部标识：编辑时取已存的，新建时立即生成 UUID（无需先保存即可扫码）
  const [accountId] = useState<string>(() => parseConfig(target?.config_json ?? null).account || genAccountId());
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
      // 扫码平台把自动生成的 account 写进 config（cookie 标识），其它平台不动
      const cfgObj = SCAN_LOGIN_PLATFORMS.has(platform) ? { ...fields, account: accountId } : fields;
      const body = { name, platform, enabled, config_json: buildConfig(cfgObj) };
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
        <h2 className="text-lg font-semibold mb-5">{isEdit ? "编辑" : "添加"}发布账号</h2>

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

        {SCAN_LOGIN_PLATFORMS.has(platform) && (
          <div className="mb-4 rounded-lg border border-white/[0.08] p-3">
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-medium text-white/80">扫码登录</span>
              {isEdit && <LoginBadge slug={target!.id} refresh={loginTick} />}
            </div>
            <div className="mt-2">
              <ScanLoginButton platform={platform} account={accountId} onSuccess={onLoginSuccess} />
              <p className="text-[11px] text-white/40 mt-2 text-center">
                用 {PLATFORM_LABELS[platform] ?? platform}App 扫码登录该账号；登录态自动保存。{!isEdit && "扫码后填好名称点「添加」即可保存。"}
              </p>
            </div>
          </div>
        )}

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
  const [loginTick, setLoginTick] = useState(0);  // 登录成功后 +1，驱动列表与徽标刷新
  const refreshLogin = () => { setLoginTick((t) => t + 1); mutate(); };

  const handleDelete = async (id: string) => {
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
        <button onClick={() => setDialog({ target: null })} className={`${btnPrimary} inline-flex items-center gap-1.5`}><PlusIcon /> 添加账号</button>
      </div>

      <div className="space-y-3">
        {targets?.map((t) => {
          const cfg = parseConfig(t.config_json);
          const fieldDefs = PLATFORM_FIELDS[t.platform] ?? [];
          const isScanPlatform = SCAN_LOGIN_PLATFORMS.has(t.platform);
          return (
            <div
              key={t.id}
              onClick={() => setDialog({ target: t })}
              className={`${cardCls} p-5 cursor-pointer hover:bg-white/[0.04] transition ${!t.enabled ? "opacity-40" : ""}`}
            >
              <div className="flex justify-between items-center">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-white/96">{t.name}</span>
                    <span className={`${chipCls} ${PLATFORM_CHIP[t.platform] ?? "bg-white/[0.06] text-white/66"}`}>
                      {PLATFORM_LABELS[t.platform] ?? t.platform}
                    </span>
                    <span className={`${chipCls} bg-white/[0.06] text-white/66`}>
                      {MEDIA_LABEL[PLATFORM_MEDIA[t.platform] ?? "video"]}
                    </span>
                    {isScanPlatform && <LoginBadge slug={t.id} refresh={loginTick} />}
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
                  <DeleteIconButton onClick={() => handleDelete(t.id)} title="删除此账号" />
                </div>
              </div>
            </div>
          );
        })}
        {(!targets || targets.length === 0) && (
          <div className={`${cardCls} p-12 text-center`}>
            <p className="text-white/60 text-sm">暂无发布账号</p>
            <p className="text-white/46 text-xs mt-1">添加账号以启用视频发布功能</p>
          </div>
        )}
      </div>

      {dialog && (
        <TargetDialog
          target={dialog.target}
          onSave={() => { setDialog(null); mutate(); }}
          onClose={() => setDialog(null)}
          loginTick={loginTick}
          onLoginSuccess={refreshLogin}
        />
      )}
    </div>
  );
}
