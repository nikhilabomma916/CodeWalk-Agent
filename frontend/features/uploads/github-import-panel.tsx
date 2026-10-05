"use client";

import { FolderGit2, GitBranch, Loader2, Unplug } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useId, useState } from "react";

import { buttonClass } from "@/components/ui/page-frame";
import { plural } from "@/lib/format";
import { isApiError } from "@/services/api/errors";
import {
  disconnectGitHub,
  getGitHubStatus,
  importGitHubRepository,
  listGitHubBranches,
  listGitHubRepositories,
  startGitHubConnect,
  type GitHubImportResult,
  type GitHubRepository,
  type GitHubStatus,
} from "@/services/api/github";

const label = "block text-[11px] text-fg-muted";
const input =
  "w-full rounded border border-border bg-surface-sunken px-2 py-1 text-xs text-fg outline-none focus:border-accent";

/** What the server's OAuth callback reports in `?github=`; anything else is ignored. */
export const CALLBACK_MESSAGES: Record<string, { tone: "ok" | "error"; text: string }> = {
  connected: { tone: "ok", text: "GitHub is connected. Choose a repository to import." },
  github_oauth_state_invalid: {
    tone: "error",
    text: "The GitHub authorization expired or was started elsewhere. Connect again.",
  },
  github_oauth_failed: {
    tone: "error",
    text: "GitHub did not accept the authorization. Try again.",
  },
  github_unavailable: { tone: "error", text: "GitHub could not be reached. Try again shortly." },
  github_error: { tone: "error", text: "Connecting GitHub failed. Try again." },
};

const SKIP_REASONS: Record<string, string> = {
  secret: "credentials files",
  ignored: "dependency or build folders",
  binary: "binary files",
  too_large: "files over the size limit",
  symlink: "links",
  special_file: "special files",
  invalid_path: "unsafe paths",
  limit: "over the file limit",
  exists: "already present",
  duplicate: "duplicates",
};

const errorText = (error: unknown, fallback: string) =>
  isApiError(error) ? error.message : fallback;

/**
 * Module 20: connect a GitHub account and import a repository branch as an upload. The OAuth token
 * stays on the server; the browser only sees the account name and repository metadata.
 */
export function GitHubImportPanel({
  callbackResult,
  onImported,
}: {
  callbackResult: string | null;
  onImported(): void;
}) {
  const ids = { repo: useId(), branch: useId(), name: useId() };
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [page, setPage] = useState(1);
  const [repoName, setRepoName] = useState("");
  const [branches, setBranches] = useState<string[]>([]);
  const [branch, setBranch] = useState("");
  const [projectName, setProjectName] = useState("");
  const [busy, setBusy] = useState<null | "connect" | "load" | "import" | "disconnect">(null);
  const [result, setResult] = useState<GitHubImportResult | null>(null);

  const callback = callbackResult ? CALLBACK_MESSAGES[callbackResult] : undefined;
  const repository = repositories.find((r) => r.full_name === repoName);

  const loadRepositories = useCallback(async (next: number) => {
    setBusy("load");
    try {
      const data = await listGitHubRepositories(next);
      setRepositories((current) => (next === 1 ? data.items : [...current, ...data.items]));
      setHasMore(data.has_more);
      setPage(next);
    } catch (e) {
      setError(errorText(e, "Unable to list your repositories."));
    } finally {
      setBusy(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    let current: GitHubStatus;
    try {
      current = await getGitHubStatus();
    } catch {
      setStatus(null); // no GitHub integration reachable: the panel stays hidden
      return;
    }
    setStatus(current);
    if (current.connected) await loadRepositories(1);
  }, [loadRepositories]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) void refresh();
    });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  const chooseRepository = async (fullName: string) => {
    setRepoName(fullName);
    setBranches([]);
    setBranch("");
    setResult(null);
    const chosen = repositories.find((r) => r.full_name === fullName);
    if (!chosen) return;
    setProjectName(chosen.name);
    setBusy("load");
    try {
      const data = await listGitHubBranches(chosen.owner, chosen.name);
      setBranches(data.items);
      setBranch(
        data.items.includes(chosen.default_branch) ? chosen.default_branch : (data.items[0] ?? ""),
      );
    } catch (e) {
      setError(errorText(e, "Unable to list branches."));
    } finally {
      setBusy(null);
    }
  };

  const connect = async () => {
    setBusy("connect");
    setError(null);
    try {
      window.location.assign(await startGitHubConnect());
    } catch (e) {
      setError(errorText(e, "Unable to start connecting GitHub."));
      setBusy(null);
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    setError(null);
    try {
      await disconnectGitHub();
      setRepositories([]);
      setRepoName("");
      setResult(null);
      await refresh();
    } catch (e) {
      setError(errorText(e, "Unable to disconnect GitHub."));
    } finally {
      setBusy(null);
    }
  };

  const runImport = async () => {
    if (!repository || !branch) return;
    setBusy("import");
    setError(null);
    setResult(null);
    try {
      const imported = await importGitHubRepository({
        owner: repository.owner,
        repository: repository.name,
        branch,
        project_name: projectName.trim() || undefined,
      });
      setResult(imported);
      onImported();
    } catch (e) {
      setError(errorText(e, "The repository could not be imported."));
      if (isApiError(e) && e.code === "github_reauthorization_required") void refresh();
    } finally {
      setBusy(null);
    }
  };

  if (status === null) return null;
  if (status && !status.configured) return null; // the server has no GitHub OAuth app

  return (
    <section aria-labelledby={`${ids.repo}-title`} className="border-b border-border px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2
          id={`${ids.repo}-title`}
          className="flex items-center gap-1.5 text-xs font-medium text-fg"
        >
          <FolderGit2 aria-hidden className="size-3.5" />
          Import from GitHub
        </h2>
        {status?.connected ? (
          <div className="flex items-center gap-2 text-[11px] text-fg-muted">
            <span>
              Connected as <span className="text-fg">@{status.login}</span>
            </span>
            <button
              type="button"
              className={buttonClass.secondary}
              disabled={busy !== null}
              onClick={() => void disconnect()}
            >
              <Unplug aria-hidden className="size-3.5" />
              Disconnect
            </button>
          </div>
        ) : (
          status && (
            <button
              type="button"
              className={buttonClass.primary}
              disabled={busy !== null}
              onClick={() => void connect()}
            >
              <FolderGit2 aria-hidden className="size-3.5" />
              {busy === "connect" ? "Opening GitHub…" : "Connect GitHub"}
            </button>
          )
        )}
      </div>

      {callback && (
        <p
          role="status"
          className={`mt-2 text-xs ${callback.tone === "ok" ? "text-success" : "text-danger"}`}
        >
          {callback.text}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
      {status && !status.connected && (
        <p className="mt-1 text-[11px] text-fg-muted">
          {status.private_repositories
            ? "Connect your account to import public and private repositories."
            : "Connect your account to import public repositories."}{" "}
          The access token stays on the server, encrypted.
        </p>
      )}

      {status?.connected && (
        <form
          className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => {
            event.preventDefault();
            void runImport();
          }}
        >
          <div>
            <label htmlFor={ids.repo} className={label}>
              Repository
            </label>
            <select
              id={ids.repo}
              value={repoName}
              disabled={busy !== null}
              onChange={(event) => void chooseRepository(event.target.value)}
              className={input}
            >
              <option value="">
                {repositories.length === 0 && busy === "load" ? "Loading…" : "Choose a repository"}
              </option>
              {repositories.map((r) => (
                <option key={r.id} value={r.full_name}>
                  {r.full_name}
                  {r.private ? " (private)" : ""}
                </option>
              ))}
            </select>
            {hasMore && (
              <button
                type="button"
                className="mt-1 text-[11px] text-accent hover:underline"
                disabled={busy !== null}
                onClick={() => void loadRepositories(page + 1)}
              >
                Load more repositories
              </button>
            )}
          </div>
          <div>
            <label htmlFor={ids.branch} className={label}>
              Branch
            </label>
            <select
              id={ids.branch}
              value={branch}
              disabled={busy !== null || branches.length === 0}
              onChange={(event) => setBranch(event.target.value)}
              className={input}
            >
              {branches.length === 0 && <option value="">—</option>}
              {branches.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={ids.name} className={label}>
              Project name
            </label>
            <input
              id={ids.name}
              value={projectName}
              maxLength={100}
              disabled={busy !== null}
              onChange={(event) => setProjectName(event.target.value)}
              className={input}
            />
          </div>
          <button
            type="submit"
            className={buttonClass.primary}
            disabled={busy !== null || !repository || !branch}
          >
            {busy === "import" ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <GitBranch aria-hidden className="size-3.5" />
            )}
            {busy === "import" ? "Importing…" : "Import"}
          </button>
        </form>
      )}

      {busy === "import" && (
        <p role="status" className="mt-2 text-[11px] text-fg-muted">
          Downloading the repository, storing its files and indexing them. Large repositories can
          take up to two minutes.
        </p>
      )}

      {result && (
        <div
          role="status"
          className="mt-2 rounded border border-border bg-surface-sunken p-2 text-xs"
        >
          <p className="text-fg">
            Imported {plural(result.files_imported, "file")} from {result.repository} (
            {result.branch} @ {result.commit_sha.slice(0, 7)}).{" "}
            {result.indexing === "completed"
              ? `Indexed ${plural(result.indexed_files, "file")}.`
              : "Indexing failed; run Analyze on the project to retry."}
          </p>
          {result.files_skipped > 0 && (
            <p className="mt-1 text-fg-muted">
              Skipped {plural(result.files_skipped, "file")}:{" "}
              {Object.entries(result.skipped_by_reason)
                .map(([reason, count]) => `${count} ${SKIP_REASONS[reason] ?? reason}`)
                .join(", ")}
              .
            </p>
          )}
          <Link
            href={`/app/uploads/${result.project_id}`}
            className="mt-1 inline-block text-accent hover:underline"
          >
            Open {result.project_name}
          </Link>
        </div>
      )}
    </section>
  );
}
