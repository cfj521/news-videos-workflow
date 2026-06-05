// Shared design tokens — single source of truth for all components.

// --- Form controls ---
export const inputCls =
  "w-full rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-white/96 placeholder:text-white/46 outline-none transition focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30";

export const selectCls = `${inputCls} appearance-none cursor-pointer`;

export const monoInputCls = `${inputCls} font-mono text-[13px]`;

export const labelCls = "block text-xs font-medium text-white/66 mb-1.5";

// --- Buttons：按动作语义命名（add / edit / delete / regen / confirm / cancel / approve）---
// 尺寸约定：confirm/cancel/approve/delete 为对话框默认尺寸；add/edit/regen 为行内小尺寸。

// confirm：主确认动作，实心蓝（创建/保存/确认/生成/下载）
export const btnConfirm =
  "px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium text-[#fff] transition shadow-lg shadow-blue-600/20 active:scale-[0.98] disabled:opacity-40 disabled:cursor-default";

// cancel：取消/次要动作，描边
export const btnCancel =
  "px-4 py-2 rounded-lg text-sm font-medium text-white/76 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white/92 transition active:scale-[0.98] disabled:opacity-40 disabled:cursor-default";

// approve：审核通过并继续，实心琥珀（正向、强调，区别于普通确认）
export const btnApprove =
  "px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-black text-sm font-medium transition active:scale-[0.98] disabled:opacity-40 disabled:cursor-default";

// add / edit：新增、编辑等中性行内动作，描边小号
const neutralCompact =
  "px-3 py-1.5 rounded-lg text-xs font-medium text-white/66 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white/85 transition select-none disabled:opacity-40 disabled:cursor-default";
export const btnAdd = neutralCompact;
export const btnEdit = neutralCompact;

// delete：删除动作，软红三尺寸
const dangerBase =
  "rounded-lg font-medium bg-red-500/15 border border-red-500/20 text-red-300 hover:bg-red-500/25 transition disabled:opacity-40 disabled:cursor-not-allowed";
export const btnDelete = `px-4 py-2 text-sm active:scale-[0.98] ${dangerBase}`;   // 对话框确认删除主按钮
export const btnDeleteCompact = `px-3 py-1.5 text-xs ${dangerBase}`;              // 行内删除（如分镜删除）
export const btnDeleteIcon =
  "w-5 h-5 flex items-center justify-center text-sm leading-none rounded text-red-400/60 hover:text-red-300 hover:bg-red-500/15 transition disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-red-400/60 disabled:hover:bg-transparent"; // × 图标删除

// regen：重新生成动作。通用为青色，场景级保留彩色区分（配音/图片/提示词）
const regenBase =
  "px-3 py-1.5 rounded-lg text-xs font-medium transition border disabled:opacity-40 disabled:cursor-not-allowed";
export const btnRegen = `${regenBase} bg-cyan-500/10 border-cyan-500/20 text-cyan-300 hover:bg-cyan-500/20`;
export const btnRegenAudio = `${regenBase} bg-violet-500/10 border-violet-500/20 text-violet-300 hover:bg-violet-500/20`;
export const btnRegenImage = `${regenBase} bg-emerald-500/10 border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/20`;
export const btnRegenPrompt = `${regenBase} bg-amber-500/10 border-amber-500/20 text-amber-300 hover:bg-amber-500/20`;

// icon：纯图标控件（播放/全屏等）
export const btnIcon =
  "p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] text-white/66 hover:text-white/85 transition";

// segItem：分段选择项（平台/采集方式等互斥切换）
export const segItem = (active: boolean) =>
  `px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
    active
      ? "bg-blue-500/15 border-blue-500/30 text-blue-300"
      : "bg-white/[0.03] border-white/[0.06] text-white/66 hover:text-white/85"
  }`;

// --- Legacy aliases：保留旧引用，逐步迁移到上面的动作语义名 ---
export const btnPrimary = btnConfirm;
export const btnSecondary = btnCancel;
export const btnCompact = neutralCompact;
export const btnDanger = btnDelete;
export const btnGhost = btnCancel;
export const btnSmall = neutralCompact;
export const btnActionAudio = btnRegenAudio;
export const btnActionImage = btnRegenImage;
export const btnActionPrompt = btnRegenPrompt;
export const btnActionReroll = btnRegen;

// --- Toggle switch ---
export const toggleCls = (on: boolean) =>
  `w-10 h-[22px] rounded-full transition-colors relative cursor-pointer shrink-0 ${on ? "bg-blue-500" : "bg-white/[0.1]"}`;

export const toggleThumbCls = (on: boolean) =>
  `absolute top-0.5 w-[18px] h-[18px] rounded-full bg-[#fff] shadow transition-all ${on ? "left-[20px]" : "left-0.5"}`;

// --- Status chips ---
export const STATUS_CHIP: Record<string, string> = {
  pending: "bg-white/[0.06] text-white/76",
  processing: "bg-blue-500/15 text-blue-300",
  review: "bg-amber-500/15 text-amber-300",
  done: "bg-emerald-500/15 text-emerald-300",
  failed: "bg-red-500/15 text-red-300",
};

export const TYPE_CHIP: Record<string, string> = {
  rss: "bg-emerald-500/15 text-emerald-300",
  api: "bg-blue-500/15 text-blue-300",
  search: "bg-purple-500/15 text-purple-300",
  scrape: "bg-amber-500/15 text-amber-300",
};

// --- Layout ---
export const cardCls =
  "rounded-xl bg-white/[0.03] border border-white/[0.06]";

export const dialogOverlayCls =
  "fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 animate-backdrop";

export const dialogPanelCls =
  "bg-[var(--color-surface-raised)] border border-white/[0.08] rounded-2xl p-6 max-h-[90vh] overflow-y-auto shadow-2xl animate-dialog";

export const sectionTitleCls =
  "text-[13px] font-semibold tracking-widest uppercase text-white/66";

export const chipCls =
  "px-2 py-0.5 rounded-md text-xs font-medium";

// --- Feedback ---
export const errorTextCls = "text-red-400 text-sm";

// --- Helpers ---
export const cx = (...cls: (string | false | undefined)[]) =>
  cls.filter(Boolean).join(" ");
