import { describe, it, expect } from "vitest";
import { formatScheduleSummary } from "./schedule";

describe("formatScheduleSummary", () => {
  it("once 显示完整日期时刻", () => {
    expect(formatScheduleSummary("once", "2026-06-15T08:00:00")).toBe("2026-06-15 08:00（单次）");
  });
  it("daily 只显示时分", () => {
    expect(formatScheduleSummary("daily", "2026-06-15T08:05:00")).toBe("每天 08:05");
  });
  it("weekly 显示星期（周日锚点）", () => {
    // 2026-06-14 是周日
    expect(formatScheduleSummary("weekly", "2026-06-14T09:00:00")).toBe("每周日 09:00");
  });
  it("monthly 显示号数", () => {
    expect(formatScheduleSummary("monthly", "2026-06-15T08:00:00")).toBe("每月 15 号 08:00");
  });
});
