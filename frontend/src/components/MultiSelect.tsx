import { useState, useRef, useEffect } from "react";
import { selectCls } from "../styles";

export interface MultiOption {
  value: string;
  label: string;
  hint?: string; // 次要说明（如平台名）
}

interface Props {
  values: string[];
  onToggle: (value: string) => void;
  options: MultiOption[];
  className?: string;
  placeholder?: string;
  emptyHint?: string; // 无可选项时的提示
}

export function MultiSelect({ values, onToggle, options, className, placeholder, emptyHint }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selectedSet = new Set(values);
  const selectedLabels = options.filter((o) => selectedSet.has(o.value)).map((o) => o.label);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const summary =
    selectedLabels.length === 0
      ? placeholder ?? "请选择..."
      : selectedLabels.length <= 2
        ? selectedLabels.join("、")
        : `已选 ${selectedLabels.length} 个`;

  return (
    <div className={`relative ${className ?? ""}`} ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`${selectCls} text-left flex items-center justify-between`}
      >
        <span className={selectedLabels.length ? "text-white/90 truncate" : "text-white/20"}>
          {summary}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-white/30 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-20 mt-1.5 w-full rounded-lg border border-white/[0.08] bg-[var(--color-surface-raised)] shadow-xl overflow-hidden max-h-60 overflow-y-auto">
          {options.length === 0 ? (
            <div className="px-3 py-2.5 text-sm text-white/30">{emptyHint ?? "无可选项"}</div>
          ) : (
            options.map((o) => {
              const checked = selectedSet.has(o.value);
              return (
                <button
                  key={o.value}
                  type="button"
                  onClick={() => onToggle(o.value)}
                  className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2.5 transition ${
                    checked ? "bg-blue-500/15 text-blue-200" : "text-white/60 hover:bg-white/[0.06] hover:text-white/80"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    readOnly
                    className="w-3.5 h-3.5 rounded accent-blue-500 pointer-events-none"
                  />
                  <span className="flex-1 truncate">{o.label}</span>
                  {o.hint && <span className="text-xs text-white/30 shrink-0">{o.hint}</span>}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
