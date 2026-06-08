import { describe, it, expect } from "vitest";
import { backendStagesToVisual, payloadToDialogState } from "./runConfig";

describe("backendStagesToVisual", () => {
  it("全阶段 1-6 → 可视 {1,2,4,5,6}", () => {
    expect([...backendStagesToVisual([1, 2, 3, 4, 5, 6])]).toEqual([1, 2, 4, 5, 6]);
  });
  it("[1,2,3] → {1,2}", () => {
    expect([...backendStagesToVisual([1, 2, 3])]).toEqual([1, 2]);
  });
  it("audio 无 4：[1,2,3,5,6] → {1,2,5,6}", () => {
    expect([...backendStagesToVisual([1, 2, 3, 5, 6])]).toEqual([1, 2, 5, 6]);
  });
  it("空数组 → 空集", () => {
    expect([...backendStagesToVisual([])]).toEqual([]);
  });
});

describe("payloadToDialogState", () => {
  it("aihot payload：sourceMode=aihot、sourceIds=null、阶段反填", () => {
    const s = payloadToDialogState({
      video_route: "comfyui", time_range: "3d", selected_stages: [1, 2, 3],
      aihot_config: { method: "daily" }, publish_platforms: ["yt"],
    });
    expect(s.sourceMode).toBe("aihot");
    expect(s.sourceIds).toBeNull();
    expect(s.aihotCfg).toEqual({ method: "daily" });
    expect([...s.selectedVisual]).toEqual([1, 2]);
    expect(s.videoRoute).toBe("comfyui");
    expect([...(s.targetIds ?? [])]).toEqual(["yt"]);
  });
  it("custom payload：sourceMode=custom、sourceIds=Set、targetIds=null", () => {
    const s = payloadToDialogState({ source_ids: ["a", "b"] });
    expect(s.sourceMode).toBe("custom");
    expect([...(s.sourceIds ?? [])]).toEqual(["a", "b"]);
    expect(s.targetIds).toBeNull();
  });
});
