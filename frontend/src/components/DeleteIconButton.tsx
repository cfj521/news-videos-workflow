// 统一的「图标样式」删除按钮：垃圾桶图标，红色软底悬浮。用于列表行内删除等场景。
export function DeleteIconButton({ onClick, title = "删除", disabled, className = "" }: {
  onClick: (e: React.MouseEvent) => void;
  title?: string;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`p-1.5 rounded-md text-red-400/60 hover:text-red-300 hover:bg-red-500/15 transition disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:text-red-400/60 disabled:hover:bg-transparent ${className}`}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 6h18" />
        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        <line x1="10" y1="11" x2="10" y2="17" />
        <line x1="14" y1="11" x2="14" y2="17" />
      </svg>
    </button>
  );
}
