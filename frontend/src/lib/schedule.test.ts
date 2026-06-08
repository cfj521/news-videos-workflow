import { describe, it, expect } from "vitest";
import { formatScheduleSummary, composeRunAt, decomposeRunAt } from "./schedule";

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

describe("composeRunAt", () => {
  const base = { onceAt: "", tod: "", weekday: 0, monthDay: 1 as number | "last" };
  it("once 原样返回 onceAt", () => {
    expect(composeRunAt("once", { ...base, onceAt: "2026-06-15T08:30" })).toBe("2026-06-15T08:30");
  });
  it("daily → 2000-01-01T<时间>", () => {
    expect(composeRunAt("daily", { ...base, tod: "08:05" })).toBe("2000-01-01T08:05");
  });
  it("weekly 周一(0)→01-01、周日(6)→01-07", () => {
    expect(composeRunAt("weekly", { ...base, tod: "09:00", weekday: 0 })).toBe("2024-01-01T09:00");
    expect(composeRunAt("weekly", { ...base, tod: "09:00", weekday: 6 })).toBe("2024-01-07T09:00");
  });
  it("monthly 15 号 / 月末", () => {
    expect(composeRunAt("monthly", { ...base, tod: "08:00", monthDay: 15 })).toBe("2024-12-15T08:00");
    expect(composeRunAt("monthly", { ...base, tod: "08:00", monthDay: "last" })).toBe("2024-12-31T08:00");
  });
});

describe("decomposeRunAt", () => {
  it("once → onceAt", () => {
    expect(decomposeRunAt("once", "2026-06-15T08:30:00").onceAt).toBe("2026-06-15T08:30");
  });
  it("daily → tod", () => {
    expect(decomposeRunAt("daily", "2000-01-01T08:05:00").tod).toBe("08:05");
  });
  it("weekly 周日 → weekday 6", () => {
    const p = decomposeRunAt("weekly", "2024-01-07T09:00:00");  // 周日
    expect(p.weekday).toBe(6);
    expect(p.tod).toBe("09:00");
  });
  it("monthly day31 → last、day28 → 28", () => {
    expect(decomposeRunAt("monthly", "2024-12-31T08:00:00").monthDay).toBe("last");
    expect(decomposeRunAt("monthly", "2024-12-28T08:00:00").monthDay).toBe(28);
  });
});

describe("compose/decompose 往返", () => {
  it("daily", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 0, monthDay: 1 as number | "last" };
    const back = decomposeRunAt("daily", composeRunAt("daily", p));
    expect(back.tod).toBe("07:30");
  });
  it("weekly", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 3, monthDay: 1 as number | "last" };
    const back = decomposeRunAt("weekly", composeRunAt("weekly", p));
    expect(back.weekday).toBe(3);
    expect(back.tod).toBe("07:30");
  });
  it("monthly last", () => {
    const p = { onceAt: "", tod: "07:30", weekday: 0, monthDay: "last" as number | "last" };
    const back = decomposeRunAt("monthly", composeRunAt("monthly", p));
    expect(back.monthDay).toBe("last");
  });
});

describe("formatScheduleSummary monthly 月末", () => {
  it("day31 → 每月月末", () => {
    expect(formatScheduleSummary("monthly", "2024-12-31T08:00:00")).toBe("每月月末 08:00");
  });
  it("day15 → 每月 15 号（保留）", () => {
    expect(formatScheduleSummary("monthly", "2026-06-15T08:00:00")).toBe("每月 15 号 08:00");
  });
});
