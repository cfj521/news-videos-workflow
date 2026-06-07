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
  // --- 可选增强 props（不传时行为与之前完全一致）---
  searchable?: boolean; // 为 true 时，下拉顶部显示搜索框
  selectAll?: boolean;  // 为 true 时，显示全选/全不选控件
  allSelected?: boolean; // 当前是否全选（配合 selectAll 使用）
  onSelectAll?: (next: boolean) => void; // 切换全选状态的回调
  variant?: "list" | "chips"; // 默认 "list"（原有行为）；"chips" 时渲染为标签片
}

export function MultiSelect({
  values,
  onToggle,
  options,
  className,
  placeholder,
  emptyHint,
  searchable,
  selectAll,
  allSelected,
  onSelectAll,
  variant = "list",
}: Props) {
  const [open, setOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const selectedSet = new Set(values);
  const selectedLabels = options.filter((o) => selectedSet.has(o.value)).map((o) => o.label);

  // 根据搜索词过滤选项（仅在 searchable 启用时有实质作用）
  const filteredOptions = searchable && searchTerm
    ? options.filter((o) => o.label.toLowerCase().includes(searchTerm.toLowerCase()))
    : options;

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // 摘要文案：全选时可显示"全部 (N)"，其余保持原逻辑
  const summary =
    selectedLabels.length === 0
      ? placeholder ?? "请选择..."
      : selectAll && allSelected
        ? `全部 (${options.length})`
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
        <span className={selectedLabels.length ? "text-white/96 truncate" : "text-white/46"}>
          {summary}
        </span>
        <svg
          className={`w-3.5 h-3.5 text-white/60 shrink-0 transition-transform ${open ? "rotate-180" : ""}`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-20 mt-1.5 w-full rounded-lg border border-white/[0.08] bg-[var(--color-surface-raised)] shadow-xl overflow-hidden flex flex-col">
          {/* ---- 固定头部：搜索框 + 全选控件（不随选项滚动）---- */}
          {(searchable || selectAll) && (
            <div className="shrink-0 border-b border-white/[0.06]">
              {searchable && (
                <div className="px-3 py-2">
                  <input
                    type="text"
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder="搜索..."
                    className="w-full bg-white/[0.06] border border-white/[0.08] rounded-md px-2.5 py-1 text-sm text-white/90 placeholder:text-white/40 outline-none focus:border-blue-400/40 focus:bg-white/[0.08] transition"
                  />
                </div>
              )}
              {selectAll && (
                <button
                  type="button"
                  onClick={() => onSelectAll?.(!allSelected)}
                  className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-white/70 hover:text-white/90 hover:bg-white/[0.05] transition"
                >
                  <span>{allSelected ? "全不选" : "全选"}</span>
                  <span className="text-white/50">
                    已选 {values.length}/{options.length}
                  </span>
                </button>
              )}
            </div>
          )}

          {/* ---- 选项区域（可滚动）---- */}
          <div className="overflow-y-auto max-h-60">
            {filteredOptions.length === 0 ? (
              <div className="px-3 py-2.5 text-sm text-white/60">
                {searchable && searchTerm ? "无匹配项" : (emptyHint ?? "无可选项")}
              </div>
            ) : variant === "chips" ? (
              /* chips 变体：标签片样式 */
              <div className="flex flex-wrap gap-2 p-2">
                {filteredOptions.map((o) => {
                  const checked = selectedSet.has(o.value);
                  return (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => onToggle(o.value)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1 text-xs rounded-md border transition ${
                        checked
                          ? "bg-blue-500/35 text-white border-blue-400/60 font-medium"
                          : "bg-white/[0.03] text-white/70 border-white/[0.08] hover:text-white/92 hover:border-white/20"
                      }`}
                    >
                      {o.label}
                    </button>
                  );
                })}
              </div>
            ) : (
              /* list 变体（默认）：原有 checkbox 行样式 */
              filteredOptions.map((o) => {
                const checked = selectedSet.has(o.value);
                return (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => onToggle(o.value)}
                    className={`w-full text-left px-3 py-2 text-sm flex items-center gap-2.5 transition ${
                      checked ? "bg-blue-500/15 text-blue-200" : "text-white/85 hover:bg-white/[0.06] hover:text-white/96"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      readOnly
                      className="w-3.5 h-3.5 rounded accent-blue-500 pointer-events-none"
                    />
                    <span className="flex-1 truncate">{o.label}</span>
                    {o.hint && <span className="text-xs text-white/60 shrink-0">{o.hint}</span>}
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
