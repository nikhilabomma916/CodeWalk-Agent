import { describe, expect, it } from "vitest";

import type { HistoryEvent } from "@/services/api/history";

import { describeEvent, eventFacts, groupByDay } from "./history-format";

function event(overrides: Partial<HistoryEvent>): HistoryEvent {
  return {
    id: "e1",
    event_type: "file.updated",
    project_id: "p1",
    project_name: "Demo",
    file_id: "f1",
    file_path: "src/app.py",
    analysis_id: "a1",
    details: {},
    created_at: "2026-10-01T10:00:00",
    ...overrides,
  };
}

describe("groupByDay", () => {
  const now = new Date(2026, 9, 1, 15, 0); // 1 Oct 2026, local time

  it("labels today and yesterday and keeps order", () => {
    const groups = groupByDay(
      [
        event({ id: "a", created_at: new Date(2026, 9, 1, 12).toISOString() }),
        event({ id: "b", created_at: new Date(2026, 9, 1, 9).toISOString() }),
        event({ id: "c", created_at: new Date(2026, 8, 30, 23).toISOString() }),
        event({ id: "d", created_at: new Date(2026, 8, 20, 8).toISOString() }),
      ],
      now,
    );
    expect(groups.map((g) => g.label.split(",")[0])).toEqual([
      "Today",
      "Yesterday",
      expect.not.stringMatching(/Today|Yesterday/),
    ]);
    expect(groups[0].events.map((e) => e.id)).toEqual(["a", "b"]);
    expect(groups[2].events.map((e) => e.id)).toEqual(["d"]);
  });

  it("returns nothing for no events", () => {
    expect(groupByDay([], now)).toEqual([]);
  });
});

describe("describeEvent / eventFacts", () => {
  it("describes saves with version and problem count", () => {
    const saved = event({ details: { version: 3, diagnostic_count: 2 } });
    expect(describeEvent(saved)).toBe("Saved src/app.py");
    expect(eventFacts(saved)).toEqual(["v3", "2 problems"]);
    expect(eventFacts(event({ details: { version: 1, diagnostic_count: 0 } }))).toEqual([
      "v1",
      "no problems",
    ]);
  });

  it("describes renames and restores from recorded details", () => {
    expect(describeEvent(event({ details: { renamed_from: "old.py" } }))).toBe(
      "Renamed old.py to src/app.py",
    );
    expect(
      describeEvent(
        event({ event_type: "project.updated", details: { renamed_from: "Old" }, file_path: null }),
      ),
    ).toBe("Renamed project Old to Demo");
    expect(
      describeEvent(
        event({ event_type: "file.restored", details: { restored_from: 2, version: 4 } }),
      ),
    ).toBe("Restored src/app.py to version 2");
  });

  it("summarizes project analyses", () => {
    const analyzed = event({
      event_type: "project.analyzed",
      file_path: null,
      details: { statistics: { files: 12, symbols: 40 }, diagnostic_count: 0 },
    });
    expect(describeEvent(analyzed)).toBe("Analyzed project Demo");
    expect(eventFacts(analyzed)).toEqual(["12 files", "40 symbols"]);
  });

  it("ignores malformed details instead of showing them", () => {
    expect(eventFacts(event({ details: { version: "three", diagnostic_count: null } }))).toEqual(
      [],
    );
  });
});

describe("AI events", () => {
  it("describes AI activity with its model and outcome", () => {
    const reviewed = event({
      event_type: "ai.analyzed",
      details: { diagnostic_count: 2, model: "claude-opus-5-5" },
    });
    expect(describeEvent(reviewed)).toBe("AI review of src/app.py");
    expect(eventFacts(reviewed)).toEqual(["2 findings", "claude-opus-5-5"]);
    expect(describeEvent(event({ event_type: "ai.explained", details: {} }))).toBe(
      "AI explained a problem in src/app.py",
    );
    expect(
      describeEvent(
        event({ event_type: "ai.fix_suggested", details: { status: "no_suggestion" } }),
      ),
    ).toBe("AI found no safe fix for src/app.py");
    expect(
      eventFacts(event({ event_type: "ai.explained", details: { diagnostic_count: 0 } })),
    ).toEqual([]);
  });
});
