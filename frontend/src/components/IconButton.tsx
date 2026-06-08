// 统一的「图标按钮」：中性软底悬浮，必带 title + aria-label（可访问性 + 可发现性）。
// 行内操作（编辑/配置）、工具栏动作（添加/导入/刷新/重置/关闭）通用。删除请用 DeleteIconButton。
type Variant = "default" | "primary";

const VARIANTS: Record<Variant, string> = {
  default: "text-white/55 hover:text-white/92 hover:bg-white/[0.08]",
  primary: "text-blue-300/80 hover:text-blue-200 hover:bg-blue-500/15",
};

export function IconButton({
  onClick, title, children, disabled, variant = "default", className = "",
}: {
  onClick: (e: React.MouseEvent) => void;
  title: string;            // 必填：hover 提示 + 无障碍标签
  children: React.ReactNode;
  disabled?: boolean;
  variant?: Variant;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`p-1.5 rounded-md transition disabled:opacity-30 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </button>
  );
}
