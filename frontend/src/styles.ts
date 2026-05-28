// Shared design tokens — single source of truth for all components.

// --- Form controls ---
export const inputCls =
  "w-full rounded-lg bg-white/[0.04] border border-white/[0.08] px-3 py-2 text-sm text-white/90 placeholder:text-white/20 outline-none transition focus:border-blue-500/60 focus:ring-1 focus:ring-blue-500/30";

export const selectCls = `${inputCls} appearance-none cursor-pointer`;

export const monoInputCls = `${inputCls} font-mono text-[13px]`;

export const labelCls = "block text-xs font-medium text-white/40 mb-1.5";

// --- Buttons ---
// Primary: filled blue, main action (保存/创建/确认)
export const btnPrimary =
  "px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-sm font-medium text-white transition shadow-lg shadow-blue-600/20 active:scale-[0.98] disabled:opacity-40 disabled:cursor-default";

// Secondary: outline, secondary action (取消/显示/隐藏/重新渲染)
export const btnSecondary =
  "px-4 py-2 rounded-lg text-sm font-medium text-white/50 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white/70 transition active:scale-[0.98] disabled:opacity-40 disabled:cursor-default";

// Compact: smaller variant for toolbars/inline controls
export const btnCompact =
  "px-3 py-1.5 rounded-lg text-xs font-medium text-white/40 border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] hover:text-white/60 transition select-none disabled:opacity-40 disabled:cursor-default";

// Danger: destructive action (删除/禁用)
export const btnDanger =
  "px-4 py-2 rounded-lg text-sm font-medium bg-red-500/10 border border-red-500/20 text-red-400/70 hover:bg-red-500/20 hover:text-red-300 transition active:scale-[0.98]";

// Icon: square icon-only button (全屏/播放控制)
export const btnIcon =
  "p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] text-white/40 hover:text-white/60 transition";

// Legacy aliases (avoid breaking existing refs, but prefer new names)
export const btnGhost = btnSecondary;
export const btnSmall = btnCompact;

// --- Action buttons (colored by function, for scene editing) ---
const actionBase =
  "px-3 py-1.5 rounded-lg text-xs font-medium transition border disabled:opacity-40 disabled:cursor-not-allowed";

export const btnActionAudio =
  `${actionBase} bg-violet-500/10 border-violet-500/20 text-violet-300 hover:bg-violet-500/20`;

export const btnActionImage =
  `${actionBase} bg-emerald-500/10 border-emerald-500/20 text-emerald-300 hover:bg-emerald-500/20`;

export const btnActionPrompt =
  `${actionBase} bg-amber-500/10 border-amber-500/20 text-amber-300 hover:bg-amber-500/20`;

export const btnActionReroll =
  `${actionBase} bg-cyan-500/10 border-cyan-500/20 text-cyan-300 hover:bg-cyan-500/20`;

// --- Toggle switch ---
export const toggleCls = (on: boolean) =>
  `w-10 h-[22px] rounded-full transition-colors relative cursor-pointer shrink-0 ${on ? "bg-blue-500" : "bg-white/[0.1]"}`;

export const toggleThumbCls = (on: boolean) =>
  `absolute top-0.5 w-[18px] h-[18px] rounded-full bg-white shadow transition-all ${on ? "left-[20px]" : "left-0.5"}`;

// --- Status chips ---
export const STATUS_CHIP: Record<string, string> = {
  pending: "bg-white/[0.06] text-white/50",
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
  "text-[13px] font-semibold tracking-widest uppercase text-white/40";

export const chipCls =
  "px-2 py-0.5 rounded-md text-xs font-medium";

// --- Feedback ---
export const errorTextCls = "text-red-400 text-sm";

// --- Helpers ---
export const cx = (...cls: (string | false | undefined)[]) =>
  cls.filter(Boolean).join(" ");
