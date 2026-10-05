"""Manages the long-lived Node.js TypeScript analyzer worker.

The worker (``backend/tools/typescript-analyzer/analyzer.mjs``) runs the TypeScript
compiler's language service. Source text is sent as JSON over stdin; it is parsed
and type-checked, never executed. One worker serves all requests; requests are
serialized, time out individually, and a hung or crashed worker is restarted.

Shutdown (``close``, from the application lifespan on SIGTERM) is bounded: the worker's stdin is
closed (it exits on end of input), then it is terminated and finally killed, without waiting for a
request in progress, which fails instead. The worker also exits by itself when its parent dies,
because its stdin closes. No worker is started after ``close``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)

TOOL_DIR = Path(__file__).resolve().parents[3] / "tools" / "typescript-analyzer"
SCRIPT = TOOL_DIR / "analyzer.mjs"
TYPESCRIPT_PACKAGE = TOOL_DIR / "node_modules" / "typescript" / "package.json"


class TypeScriptWorkerError(Exception):
    """Client-safe reason the worker could not analyze the source."""


class TypeScriptWorker:
    def __init__(self, node_binary: str | None = None, startup_timeout: float = 20.0) -> None:
        self._node = node_binary or shutil.which("node")
        self._startup_timeout = startup_timeout
        self._process: subprocess.Popen[str] | None = None
        self._responses: Queue[dict[str, Any]] = Queue()
        self._lock = threading.Lock()
        self._next_id = 0
        self._closed = False
        self.version: str | None = None

    def unavailable_reason(self) -> str | None:
        if not self._node:
            return "Node.js was not found on PATH"
        if not SCRIPT.is_file() or not TYPESCRIPT_PACKAGE.is_file():
            return "TypeScript analyzer is not installed (run npm run setup)"
        return None

    def analyze(self, file_name: str, text: str, timeout: float) -> list[dict[str, Any]]:
        response = self._request({"fileName": file_name, "text": text}, timeout)
        diagnostics = response.get("diagnostics")
        if not isinstance(diagnostics, list):
            raise TypeScriptWorkerError("TypeScript analyzer returned an invalid response")
        return diagnostics

    def _request(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        reason = self.unavailable_reason()
        if reason:
            raise TypeScriptWorkerError(reason)
        with self._lock:
            self._ensure_started()
            self._next_id += 1
            request_id = self._next_id
            try:
                self._send({"id": request_id, **payload})
            except (OSError, ValueError) as exc:  # ValueError: stdin closed by close()
                self._stop()
                raise TypeScriptWorkerError("TypeScript analyzer stopped unexpectedly") from exc
            response = self._await(request_id, timeout)
        if not response.get("ok"):
            logger.warning("TypeScript analyzer error: %s", response.get("error"))
            raise TypeScriptWorkerError("TypeScript analyzer failed on this input")
        return response

    def _await(self, request_id: int, timeout: float) -> dict[str, Any]:
        while True:
            try:
                response = self._responses.get(timeout=timeout)
            except Empty:
                logger.warning("TypeScript analyzer timed out after %.1fs; restarting it", timeout)
                self._stop()
                raise TypeScriptWorkerError(f"TypeScript analysis timed out after {timeout:g}s") from None
            if response.get("__eof__"):
                self._stop()
                raise TypeScriptWorkerError("TypeScript analyzer stopped unexpectedly")
            if response.get("id") == request_id:
                return response
            # A late response to a request that already timed out; discard it.

    def _ensure_started(self) -> None:
        if self._closed:
            raise TypeScriptWorkerError("TypeScript analysis is unavailable while the server shuts down")
        if self._process is not None and self._process.poll() is None:
            return
        if self._node is None:
            raise TypeScriptWorkerError("Node.js was not found on PATH")
        self._responses = Queue()
        self._process = subprocess.Popen(  # noqa: S603 - trusted script, no shell, source sent via stdin
            [self._node, "--max-old-space-size=512", str(SCRIPT)],
            cwd=TOOL_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        threading.Thread(target=self._read_loop, args=(self._process, self._responses), daemon=True).start()
        if self._closed:  # close() ran while the process was being created
            self._stop()
            raise TypeScriptWorkerError("TypeScript analysis is unavailable while the server shuts down")
        self._next_id += 1
        ping_id = self._next_id
        try:
            self._send({"id": ping_id, "ping": True})
        except (OSError, ValueError) as exc:
            self._stop()
            raise TypeScriptWorkerError("TypeScript analyzer stopped unexpectedly") from exc
        ready = self._await(ping_id, self._startup_timeout)
        self.version = ready.get("version")
        logger.info("TypeScript analyzer started (typescript %s)", self.version)

    def _send(self, message: dict[str, Any]) -> None:
        stdin = self._process.stdin if self._process is not None else None
        if stdin is None:
            raise OSError("worker is not running")
        stdin.write(json.dumps(message) + "\n")
        stdin.flush()

    @staticmethod
    def _read_loop(process: subprocess.Popen[str], responses: Queue[dict[str, Any]]) -> None:
        for line in process.stdout or ():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                responses.put(message)
        responses.put({"__eof__": True})

    def _stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()

    def close(self, timeout: float = 5.0) -> None:
        """Stops the worker within about ``timeout`` seconds, even while a request is in progress."""
        self._closed = True
        process = self._process
        if process is not None:
            self._shut_down(process, timeout)  # an in-progress request sees end of output and fails
        if self._lock.acquire(timeout=timeout):
            try:
                self._stop()
            finally:
                self._lock.release()

    @staticmethod
    def _shut_down(process: subprocess.Popen[str], timeout: float) -> None:
        """End of input first (the worker exits cleanly), then SIGTERM, then SIGKILL."""
        step = max(timeout / 3, 0.1)
        if process.stdin is not None:
            with contextlib.suppress(OSError, ValueError):
                process.stdin.close()
        for signal_process in (None, process.terminate, process.kill):
            if signal_process is not None and process.poll() is None:
                with contextlib.suppress(OSError):
                    signal_process()
            try:
                process.wait(timeout=step)
                return
            except subprocess.TimeoutExpired:
                continue
