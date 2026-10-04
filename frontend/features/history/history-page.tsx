"use client";

import {
  Code2,
  FilePen,
  FilePlus,
  FileX,
  FolderPlus,
  FolderX,
  Pencil,
  RefreshCw,
  RotateCcw,
  ScanSearch,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { IconButton } from "@/components/ui/icon-button";
import { buttonClass, PageFrame } from "@/components/ui/page-frame";
import { StateMessage } from "@/components/ui/state-message";
import { codingHref } from "@/features/workspace/use-coding-deep-link";
import { formatDateTime, plural } from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import {
  getHistoryEvent,
  HISTORY_EVENT_TYPES,
  listHistory,
  type HistoryEvent,
  type HistoryEventDetail,
  type HistoryEventType,
  type HistoryQuery,
} from "@/services/api/history";
import { getFileVersion, listProjects, type ServerProject } from "@/services/api/projects";

import {
  describeEvent,
  EVENT_TYPE_LABELS,
  eventDiagnosticCount,
  eventFacts,
  eventVersion,
  groupByDay,
} from "./history-format";

const PAGE_SIZE = 50;

const EVENT_ICONS: Record<HistoryEventType, LucideIcon> = {
  "project.created": FolderPlus,
  "project.updated": Pencil,
  "project.deleted": FolderX,
  "project.analyzed": ScanSearch,
  "file.created": FilePlus,
  "file.updated": FilePen,
  "file.restored": RotateCcw,
  "file.deleted": FileX,
  "file.analyzed": ScanSearch,
  "ai.analyzed": Sparkles,
  "ai.explained": Sparkles,
  "ai.fix_suggested": Sparkles,
};

function isEventType(value: string | null): value is HistoryEventType {
  return value !== null && (HISTORY_EVENT_TYPES as readonly string[]).includes(value);
}

function errorMessage(error: unknown, fallback: string): string {
  return isApiError(error) ? error.message : fallback;
}

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; events: HistoryEvent[]; total: number; loadingMore: boolean };

function useHistoryFilters() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const projectId = params.get("project") ?? "";
  const rawType = params.get("type");
  const eventType: HistoryEventType | "" = isEventType(rawType) ? rawType : "";

  const setFilter = useCallback(
    (key: "project" | "type", value: string) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      const query = next.toString();
      router.replace(query ? `${pathname}?${query}` : pathname);
    },
    [params, pathname, router],
  );
  return { projectId, eventType, setFilter };
}

export function HistoryPage() {
  const { projectId, eventType, setFilter } = useHistoryFilters();
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [projects, setProjects] = useState<ServerProject[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const query = useMemo(
    (): HistoryQuery => ({
      projectId: projectId || undefined,
      eventTypes: eventType ? [eventType] : undefined,
    }),
    [eventType, projectId],
  );

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const page = await listHistory({ ...query, limit: PAGE_SIZE });
      setState({ status: "ready", events: page.items, total: page.total, loadingMore: false });
    } catch (error) {
      setState({ status: "error", message: errorMessage(error, "Unable to load your history.") });
    }
  }, [query]);

  const loadMore = async () => {
    if (state.status !== "ready") return;
    setState({ ...state, loadingMore: true });
    try {
      const page = await listHistory({ ...query, limit: PAGE_SIZE, offset: state.events.length });
      setState({
        status: "ready",
        events: [...state.events, ...page.items],
        total: page.total,
        loadingMore: false,
      });
    } catch {
      setState({ ...state, loadingMore: false });
    }
  };

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void load();
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  useEffect(() => {
    let cancelled = false;
    listProjects()
      .then((items) => !cancelled && setProjects(items))
      .catch(() => {}); // the filter then only offers "All projects"
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(() => (state.status === "ready" ? groupByDay(state.events) : []), [state]);
  const filtered = Boolean(projectId || eventType);
  const select =
    "h-7 max-w-48 rounded border border-border bg-surface-raised px-1.5 text-xs text-fg hover:border-border-strong";

  return (
    <PageFrame
      title="History"
      meta={state.status === "ready" ? plural(state.total, "event") : undefined}
      actions={
        <IconButton label="Refresh" onClick={() => void load()}>
          <RefreshCw aria-hidden className="size-3.5" />
        </IconButton>
      }
    >
      <div className="flex min-h-full flex-col lg:flex-row">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
            <label htmlFor="history-project" className="text-xs text-fg-muted">
              Project
            </label>
            <select
              id="history-project"
              className={select}
              value={projectId}
              onChange={(event) => setFilter("project", event.target.value)}
            >
              <option value="">All projects</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
              {projectId && !projects.some((p) => p.id === projectId) && (
                <option value={projectId}>Selected project</option>
              )}
            </select>
            <label htmlFor="history-type" className="ml-2 text-xs text-fg-muted">
              Activity
            </label>
            <select
              id="history-type"
              className={select}
              value={eventType}
              onChange={(event) => setFilter("type", event.target.value)}
            >
              <option value="">All activity</option>
              {HISTORY_EVENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {EVENT_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </div>

          {state.status === "loading" && <StateMessage title="Loading history…" />}
          {state.status === "error" && (
            <StateMessage
              tone="error"
              title="Unable to load history"
              action={
                <button type="button" className={buttonClass.secondary} onClick={() => void load()}>
                  Try again
                </button>
              }
            >
              {state.message}
            </StateMessage>
          )}
          {state.status === "ready" && state.events.length === 0 && (
            <StateMessage title={filtered ? "No matching activity." : "No activity yet."}>
              {filtered
                ? "Nothing recorded matches these filters."
                : "Creating projects, saving files, and running analyses will show up here."}
            </StateMessage>
          )}
          {state.status === "ready" && state.events.length > 0 && (
            <div className="pb-4">
              {groups.map((group) => (
                <section key={group.key} aria-labelledby={`day-${group.key}`}>
                  <h2
                    id={`day-${group.key}`}
                    className="sticky top-0 z-10 border-b border-border bg-surface/95 px-4 py-1.5 text-[11px] font-semibold tracking-wider text-fg-muted uppercase backdrop-blur"
                  >
                    {group.label}
                  </h2>
                  <ul>
                    {group.events.map((event) => (
                      <HistoryRow
                        key={event.id}
                        event={event}
                        selected={selectedId === event.id}
                        onSelect={() => setSelectedId(selectedId === event.id ? null : event.id)}
                      />
                    ))}
                  </ul>
                </section>
              ))}
              {state.events.length < state.total && (
                <div className="px-4 pt-3">
                  <button
                    type="button"
                    className={buttonClass.secondary}
                    disabled={state.loadingMore}
                    onClick={() => void loadMore()}
                  >
                    {state.loadingMore
                      ? "Loading…"
                      : `Load more (${state.total - state.events.length} remaining)`}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {selectedId && (
          <aside
            aria-label="Activity details"
            className="border-t border-border bg-surface-sunken lg:w-96 lg:shrink-0 lg:border-t-0 lg:border-l"
          >
            <HistoryDetail
              key={selectedId}
              eventId={selectedId}
              onClose={() => setSelectedId(null)}
            />
          </aside>
        )}
      </div>
    </PageFrame>
  );
}

function HistoryRow({
  event,
  selected,
  onSelect,
}: {
  event: HistoryEvent;
  selected: boolean;
  onSelect(): void;
}) {
  const Icon = EVENT_ICONS[event.event_type];
  const diagnostics = eventDiagnosticCount(event);
  const facts = eventFacts(event);
  return (
    <li>
      <button
        type="button"
        aria-expanded={selected}
        onClick={onSelect}
        className={`flex w-full items-start gap-3 px-4 py-2 text-left hover:bg-surface-hover ${
          selected ? "bg-surface-active" : ""
        }`}
      >
        <Icon
          aria-hidden
          className={`mt-0.5 size-4 shrink-0 ${
            event.event_type.endsWith("deleted") ? "text-danger/80" : "text-fg-muted"
          }`}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-fg">{describeEvent(event)}</span>
          <span className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-fg-muted">
            <span>{EVENT_TYPE_LABELS[event.event_type]}</span>
            {event.file_path && <span className="truncate">· {event.project_name}</span>}
            {facts.map((fact) => (
              <span
                key={fact}
                className={diagnostics && fact.includes("problem") ? "text-warning" : undefined}
              >
                · {fact}
              </span>
            ))}
          </span>
        </span>
        <time
          dateTime={event.created_at}
          title={formatDateTime(event.created_at)}
          className="shrink-0 text-[11px] text-fg-subtle tabular-nums"
        >
          {new Date(event.created_at).toLocaleTimeString(undefined, {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </time>
      </button>
    </li>
  );
}

function HistoryDetail({ eventId, onClose }: { eventId: string; onClose(): void }) {
  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; detail: HistoryEventDetail }
  >({ status: "loading" });
  const [version, setVersion] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; content: string }
  >({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    getHistoryEvent(eventId)
      .then((detail) => !cancelled && setState({ status: "ready", detail }))
      .catch(
        (error: unknown) =>
          !cancelled &&
          setState({ status: "error", message: errorMessage(error, "Unable to load details.") }),
      );
    return () => {
      cancelled = true;
    };
  }, [eventId]);

  const header = (
    <div className="flex h-9 items-center border-b border-border px-3">
      <h2 className="flex-1 text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
        Details
      </h2>
      <button type="button" onClick={onClose} className="text-xs text-fg-muted hover:text-fg">
        Close
      </button>
    </div>
  );

  if (state.status === "loading")
    return (
      <>
        {header}
        <p className="p-3 text-xs text-fg-muted">Loading…</p>
      </>
    );
  if (state.status === "error")
    return (
      <>
        {header}
        <p role="alert" className="p-3 text-xs text-danger">
          {state.message}
        </p>
      </>
    );

  const { detail } = state;
  const versionNumber = eventVersion(detail);
  const canOpenFile = detail.project_exists && detail.project_id && detail.current_file_path;
  const statistics = detail.details.statistics as Record<string, unknown> | undefined;
  const showVersion = async () => {
    if (!detail.project_id || !detail.file_id || versionNumber === undefined) return;
    setVersion({ status: "loading" });
    try {
      const data = await getFileVersion(detail.project_id, detail.file_id, versionNumber);
      setVersion({ status: "ready", content: data.content });
    } catch (error) {
      setVersion({
        status: "error",
        message:
          isApiError(error) && error.status === 404
            ? "This version is no longer kept."
            : errorMessage(error, "Unable to load this version."),
      });
    }
  };

  const row = (label: string, value: ReactNode) => (
    <>
      <dt className="text-fg-subtle">{label}</dt>
      <dd className="min-w-0 break-words text-fg">{value}</dd>
    </>
  );

  return (
    <>
      {header}
      <div className="space-y-3 p-3 text-xs">
        <p className="text-sm text-fg">{describeEvent(detail)}</p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5">
          {row("Action", EVENT_TYPE_LABELS[detail.event_type])}
          {row("When", formatDateTime(detail.created_at))}
          {row(
            "Project",
            detail.project_exists && detail.project_id ? (
              <Link
                href={`/app/projects/${detail.project_id}`}
                className="text-accent-text hover:underline"
              >
                {detail.current_project_name}
              </Link>
            ) : (
              <span>
                {detail.project_name} <span className="text-fg-subtle">(deleted)</span>
              </span>
            ),
          )}
          {detail.file_path &&
            row(
              "File",
              <span className="font-mono">
                {detail.file_path}
                {detail.current_file_path && detail.current_file_path !== detail.file_path && (
                  <span className="block text-fg-muted">now {detail.current_file_path}</span>
                )}
                {!detail.current_file_path && detail.project_exists && (
                  <span className="text-fg-subtle"> (no longer exists)</span>
                )}
              </span>,
            )}
          {versionNumber !== undefined && row("Version", versionNumber)}
          {statistics &&
            row(
              "Result",
              ["files", "lines", "symbols", "languages", "errors"]
                .filter((key) => typeof statistics[key] === "number")
                .map((key) => `${(statistics[key] as number).toLocaleString()} ${key}`)
                .join(" · "),
            )}
        </dl>

        {detail.analysis ? (
          <section className="rounded border border-border p-2">
            <h3 className="mb-1 text-[11px] font-semibold tracking-wider text-fg-muted uppercase">
              Analysis
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              {row("Status", detail.analysis.status)}
              {detail.analysis.language && row("Language", detail.analysis.language)}
              {row("Duration", `${detail.analysis.duration_ms} ms`)}
              {detail.analysis.analysis_type === "ai_review" &&
                row("Findings", detail.analysis.diagnostic_count)}
              {detail.analysis.analysis_type === "code" &&
                row(
                  "Problems",
                  detail.analysis.diagnostic_count === 0
                    ? "None"
                    : Object.entries(detail.analysis.severity_counts)
                        .map(([severity, count]) => `${count} ${severity}`)
                        .join(" · "),
                )}
            </dl>
          </section>
        ) : (
          detail.analysis_id === null &&
          eventDiagnosticCount(detail) !== undefined && (
            <p className="text-fg-subtle">
              The analysis recorded with this event is no longer kept (older analyses are pruned).
            </p>
          )
        )}

        <div className="flex flex-wrap gap-2">
          {canOpenFile && (
            <Link
              href={codingHref(detail.project_id!, detail.current_file_path)}
              className={buttonClass.primary}
            >
              <Code2 aria-hidden className="size-3.5" />
              Open file in Coding
            </Link>
          )}
          {detail.project_exists && detail.file_id && versionNumber !== undefined && (
            <button
              type="button"
              className={buttonClass.secondary}
              disabled={version.status === "loading"}
              onClick={() => void showVersion()}
            >
              View version {versionNumber}
            </button>
          )}
        </div>

        {version.status === "error" && <p className="text-danger">{version.message}</p>}
        {version.status === "ready" && (
          <pre
            aria-label={`Content of version ${versionNumber}`}
            className="max-h-80 overflow-auto rounded border border-border bg-app p-2 font-mono text-[11px] leading-4 text-fg"
          >
            {version.content || "(empty file)"}
          </pre>
        )}
      </div>
    </>
  );
}
