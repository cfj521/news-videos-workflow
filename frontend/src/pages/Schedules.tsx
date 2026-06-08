import { useState } from "react";
import useSWR from "swr";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Schedule } from "../types";
import { btnPrimary, cardCls, chipCls, toggleCls, toggleThumbCls } from "../styles";
import { CreateRunDialog } from "../components/CreateRunDialog";
import { DeleteIconButton } from "../components/DeleteIconButton";
import { formatScheduleSummary } from "../lib/schedule";

function fmt(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function SchedulesPage() {
  const { data: schedules, mutate } = useSWR<Schedule[]>("schedules", api.schedules.list);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);

  const onToggle = async (s: Schedule) => {
    await api.schedules.toggle(s.slug, !s.enabled);
    mutate();
  };
  const onDelete = async (s: Schedule) => {
    if (!window.confirm(`删除计划「${s.name}」？`)) return;
    await api.schedules.remove(s.slug);
    mutate();
  };

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold tracking-tight">计划任务</h1>
        <button onClick={() => setShowCreate(true)} className={btnPrimary}>+ 计划任务</button>
      </div>

      <div className="flex flex-col gap-2">
        {schedules?.map((s) => (
          <div
            key={s.slug}
            onClick={() => setEditing(s)}
            className={`${cardCls} px-4 py-3 flex items-center gap-4 cursor-pointer hover:bg-white/[0.02] transition`}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white/92 truncate">{s.name}</span>
                <span className={`${chipCls} bg-white/[0.06] text-white/66 text-[10px]`}>{formatScheduleSummary(s.freq, s.run_at)}</span>
                {!s.enabled && <span className={`${chipCls} bg-white/[0.06] text-white/46 text-[10px]`}>已停用</span>}
              </div>
              <div className="text-xs text-white/46 mt-0.5">
                下次：{fmt(s.next_run_at)} · 上次：{s.last_run_id
                  ? <Link to="/" onClick={(e) => e.stopPropagation()} className="text-blue-300 hover:underline">{fmt(s.last_run_at)} #{s.last_run_id}</Link>
                  : "—"}
              </div>
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); onToggle(s); }}
              className={toggleCls(s.enabled)}
              title={s.enabled ? "点击停用" : "点击启用"}
            >
              <span className={toggleThumbCls(s.enabled)} />
            </button>
            <DeleteIconButton onClick={(e) => { e.stopPropagation(); onDelete(s); }} title="删除此计划" />
          </div>
        ))}
        {(!schedules || schedules.length === 0) && (
          <p className="text-white/60 text-sm">暂无计划任务，点击上方按钮创建</p>
        )}
      </div>

      {showCreate && (
        <CreateRunDialog
          schedule
          onCreated={() => setShowCreate(false)}
          onScheduled={() => { setShowCreate(false); mutate(); }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editing && (
        <CreateRunDialog
          edit={editing}
          onCreated={() => setEditing(null)}
          onScheduled={() => { setEditing(null); mutate(); }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
