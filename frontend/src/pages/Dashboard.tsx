import { useState } from "react";
import useSWR from "swr";
import { api } from "../api/client";
import { CreateRunDialog } from "../components/CreateRunDialog";
import { RunCard } from "../components/RunCard";
import type { PipelineRun } from "../types";

export function DashboardPage() {
  const { data: runs, mutate } = useSWR<PipelineRun[]>("runs", api.runs.list, {
    refreshInterval: 5000,
  });
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Pipeline Runs</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium"
        >
          + New Run
        </button>
      </div>
      <div className="grid gap-3">
        {runs?.map((run) => <RunCard key={run.id} run={run} />)}
        {runs?.length === 0 && (
          <p className="text-gray-500 text-center py-12">No runs yet</p>
        )}
      </div>
      {showCreate && (
        <CreateRunDialog
          onCreated={() => {
            setShowCreate(false);
            mutate();
          }}
          onClose={() => setShowCreate(false)}
        />
      )}
    </div>
  );
}
