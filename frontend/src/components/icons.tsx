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

export const ImportIcon = ({ size, className }: IconProps) =>
  svg(<><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></>, size, className);
