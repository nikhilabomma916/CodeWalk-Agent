import { plural } from "@/lib/format";
import type { HistoryEvent, HistoryEventType } from "@/services/api/history";

export const EVENT_TYPE_LABELS: Record<HistoryEventType, string> = {
  "project.created": "Project created",
  "project.updated": "Project updated",
  "project.deleted": "Project deleted",
  "project.analyzed": "Project analysis completed",
  "file.created": "File created",
  "file.updated": "File saved",
  "file.restored": "File restored",
  "file.deleted": "File deleted",
  "file.analyzed": "File analyzed",
};

function detail<T>(
  event: HistoryEvent,
  key: string,
  guard: (value: unknown) => value is T,
): T | undefined {
  const value = event.details[key];
  return guard(value) ? value : undefined;
}

const isNumber = (value: unknown): value is number => typeof value === "number";
const isString = (value: unknown): value is string => typeof value === "string";

export function eventVersion(event: HistoryEvent): number | undefined {
  return detail(event, "version", isNumber);
}

export function eventDiagnosticCount(event: HistoryEvent): number | undefined {
  return detail(event, "diagnostic_count", isNumber);
}

/** One-line description of what happened, built only from recorded data. */
export function describeEvent(event: HistoryEvent): string {
  const file = event.file_path ?? "a file";
  switch (event.event_type) {
    case "project.created":
      return `Created project ${event.project_name}`;
    case "project.updated": {
      const renamedFrom = detail(event, "renamed_from", isString);
      return renamedFrom
        ? `Renamed project ${renamedFrom} to ${event.project_name}`
        : `Updated project ${event.project_name}`;
    }
    case "project.deleted":
      return `Deleted project ${event.project_name}`;
    case "project.analyzed":
      return `Analyzed project ${event.project_name}`;
    case "file.created":
      return `Created ${file}`;
    case "file.updated": {
      const renamedFrom = detail(event, "renamed_from", isString);
      const version = eventVersion(event);
      if (renamedFrom && version === undefined) return `Renamed ${renamedFrom} to ${file}`;
      return `Saved ${file}`;
    }
    case "file.restored": {
      const from = detail(event, "restored_from", isNumber);
      return from ? `Restored ${file} to version ${from}` : `Restored ${file}`;
    }
    case "file.deleted":
      return `Deleted ${file}`;
    case "file.analyzed":
      return `Analyzed ${file}`;
  }
}

/** Short secondary facts: version, diagnostics, project statistics. */
export function eventFacts(event: HistoryEvent): string[] {
  const facts: string[] = [];
  const version = eventVersion(event);
  if (version !== undefined) facts.push(`v${version}`);
  const diagnostics = eventDiagnosticCount(event);
  if (diagnostics !== undefined && event.event_type !== "project.analyzed") {
    facts.push(diagnostics === 0 ? "no problems" : plural(diagnostics, "problem"));
  }
  const statistics = event.details.statistics;
  if (event.event_type === "project.analyzed" && statistics && typeof statistics === "object") {
    const stats = statistics as Record<string, unknown>;
    if (isNumber(stats.files)) facts.push(plural(stats.files, "file"));
    if (isNumber(stats.symbols)) facts.push(plural(stats.symbols, "symbol"));
  }
  return facts;
}

export interface DayGroup {
  key: string;
  label: string;
  events: HistoryEvent[];
}

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

/**
 * Groups events (already sorted) by local calendar day: "Today", "Yesterday",
 * then the date. Uses the browser's time zone, since that is what "today"
 * means to the person reading it.
 */
export function groupByDay(events: HistoryEvent[], now: Date = new Date()): DayGroup[] {
  const today = dayKey(now);
  const yesterdayDate = new Date(now);
  yesterdayDate.setDate(now.getDate() - 1);
  const yesterday = dayKey(yesterdayDate);
  const groups: DayGroup[] = [];
  for (const event of events) {
    const date = new Date(event.created_at);
    const key = dayKey(date);
    let group = groups[groups.length - 1];
    if (!group || group.key !== key) {
      const label =
        key === today
          ? "Today"
          : key === yesterday
            ? "Yesterday"
            : date.toLocaleDateString(undefined, {
                weekday: "long",
                year: "numeric",
                month: "long",
                day: "numeric",
              });
      group = { key, label, events: [] };
      groups.push(group);
    }
    group.events.push(event);
  }
  return groups;
}
