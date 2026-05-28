import { STAGE_LABELS, type StageNumber } from "../types";

interface Props {
  currentStage: number | null;
  status: string;
}

export function StageIndicator({ currentStage, status }: Props) {
  const stages: StageNumber[] = [1, 2, 3, 4, 5, 6];

  return (
    <div className="flex gap-1.5">
      {stages.map((s) => {
        let cls = "bg-white/[0.08]";

        if (status === "failed") {
          if (s === currentStage) cls = "bg-red-400";
          else if (s < (currentStage ?? 0)) cls = "bg-emerald-400";
        } else if (status === "done") {
          cls = "bg-emerald-400";
        } else if (status === "review") {
          if (s === currentStage) cls = "bg-amber-400";
          else if (s < (currentStage ?? 0)) cls = "bg-emerald-400";
        } else if (s === currentStage) {
          cls = "bg-blue-400 animate-pulse-soft";
        } else if (s < (currentStage ?? 0)) {
          cls = "bg-emerald-400";
        }

        return (
          <div
            key={s}
            className={`h-1.5 flex-1 rounded-full transition-colors ${cls}`}
            title={STAGE_LABELS[s]}
          />
        );
      })}
    </div>
  );
}
