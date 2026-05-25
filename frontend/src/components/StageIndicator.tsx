import { STAGE_LABELS, type StageNumber } from "../types";

interface Props {
  currentStage: number | null;
  status: string;
}

export function StageIndicator({ currentStage, status }: Props) {
  const stages: StageNumber[] = [1, 2, 3, 4, 5, 6];

  return (
    <div className="flex gap-1">
      {stages.map((s) => {
        let color = "bg-gray-700";
        if (status === "failed") {
          color =
            s === currentStage
              ? "bg-red-500"
              : s < (currentStage ?? 0)
                ? "bg-green-600"
                : "bg-gray-700";
        } else if (status === "done") {
          color = "bg-green-600";
        } else if (status === "review") {
          color =
            s === currentStage
              ? "bg-yellow-500"
              : s < (currentStage ?? 0)
                ? "bg-green-600"
                : "bg-gray-700";
        } else if (s === currentStage) {
          color = "bg-blue-500 animate-pulse";
        } else if (s < (currentStage ?? 0)) {
          color = "bg-green-600";
        }

        return (
          <div
            key={s}
            className={`w-8 h-2 rounded-full ${color}`}
            title={STAGE_LABELS[s]}
          />
        );
      })}
    </div>
  );
}
