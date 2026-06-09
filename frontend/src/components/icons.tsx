// 统一的内联 SVG 图标集（lucide 风格，stroke=currentColor）。尺寸默认 16。
type IconProps = { size?: number; className?: string };

function svg(children: React.ReactNode, size = 16, className = "") {
  return (
    <svg
      width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      className={className}
    >
      {children}
    </svg>
  );
}

export const PencilIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" /></>, size, className);

export const PlusIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M12 5v14" /><path d="M5 12h14" /></>, size, className);

export const CloseIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M18 6 6 18" /><path d="M6 6l12 12" /></>, size, className);

export const RefreshIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M3 12a9 9 0 0 1 15-6.7L21 8" /><path d="M21 3v5h-5" /><path d="M21 12a9 9 0 0 1-15 6.7L3 16" /><path d="M3 21v-5h5" /></>, size, className);

export const ResetIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M3 2v6h6" /><path d="M3 13a9 9 0 1 0 3-7.7L3 8" /></>, size, className);

// 导入文章：箭头横向「进入容器」，明确区别于下载（托盘+下箭头）
export const ImportIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" /><path d="m10 17 5-5-5-5" /><path d="M15 12H3" /></>, size, className);

// 用于「AI 重新生成提示词」，区别于 RefreshIcon
export const SparklesIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M12 3l1.6 4.9a2 2 0 0 0 1.3 1.3L20 11l-4.9 1.6a2 2 0 0 0-1.3 1.3L12 19l-1.6-4.9a2 2 0 0 0-1.3-1.3L4 11l4.9-1.6a2 2 0 0 0 1.3-1.3z" /><path d="M19 4v3" /><path d="M20.5 5.5h-3" /></>, size, className);

// 用于「重新生成」（脚本/配音/图片）：魔杖+闪光，明确区别于刷新箭头 RefreshIcon，避免误读为「刷新」
export const WandIcon = ({ size, className }: IconProps) =>
  svg(<><path d="m21.64 3.64-1.28-1.28a1.21 1.21 0 0 0-1.72 0L2.36 18.64a1.21 1.21 0 0 0 0 1.72l1.28 1.28a1.2 1.2 0 0 0 1.72 0L21.64 5.36a1.2 1.2 0 0 0 0-1.72Z" /><path d="m14 7 3 3" /><path d="M5 6v4" /><path d="M19 14v4" /><path d="M10 2v2" /><path d="M7 8H3" /><path d="M21 16h-4" /><path d="M11 3H9" /></>, size, className);
