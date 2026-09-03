"""Synchronous, bounded client for audit-only full-archive lookups.

The desktop client is intentionally Qt based.  The equipment audit runs as a
headless, resumable command, so it owns a small stdio client instead of creating
a GUI event loop.  Protocol limits and session identity remain identical to the
production worker contract.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from cdmw.models import ArchiveEntry


ARCHIVE_WORKER_PROTOCOL_VERSION = 3
ARCHIVE_WORKER_MAXIMUM_MESSAGE_BYTES = 1024 * 1024
ARCHIVE_WORKER_STDERR_TAIL_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class AuditArchiveSession:
    session_id: str
    package_root: Path
    fingerprint: str
    entry_count: int
    index_version: int
    cache_hit: bool


class AuditArchiveWorkerClient:
    """Own one worker process and execute one request at a time."""

    def __init__(
        self,
        worker_command: Sequence[Path | str],
        *,
        cache_root: Path | str,
        progress: Callable[[str, Mapping[str, object]], None] | None = None,
    ) -> None:
        command = tuple(str(value) for value in worker_command if str(value).strip())
        if not command:
            raise ValueError("Archive worker command cannot be empty.")
        self._command = command
        self._cache_root = Path(cache_root).expanduser().resolve()
        self._progress = progress
        self._process: subprocess.Popen[bytes] | None = None
        self._messages: queue.Queue[bytes | None] = queue.Queue()
        self._stderr_tail: deque[bytes] = deque()
        self._stderr_tail_size = 0
        self._reader_threads: tuple[threading.Thread, threading.Thread] = ()
        self._session: AuditArchiveSession | None = None

    @property
    def session(self) -> AuditArchiveSession | None:
        return self._session

    @property
    def process_id(self) -> int:
        return int(self._process.pid) if self._process is not None else 0

    @property
    def stderr_tail(self) -> str:
        return b"".join(self._stderr_tail).decode("utf-8", "replace")

    def __enter__(self) -> "AuditArchiveWorkerClient":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def start(self, *, timeout_seconds: float = 15.0) -> Mapping[str, object]:
        if self._process is not None:
            raise RuntimeError("Archive audit worker is already running.")
        self._cache_root.mkdir(parents=True, exist_ok=True)
        command = [*self._command, "--cache-root", str(self._cache_root)]
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creationflags,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(self._process.stdout,),
            name="equipment-audit-archive-worker-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._read_stderr,
            args=(self._process.stderr,),
            name="equipment-audit-archive-worker-stderr",
            daemon=True,
        )
        self._reader_threads = (stdout_thread, stderr_thread)
        stdout_thread.start()
        stderr_thread.start()
        result = self.request(
            "ping",
            {"client_version": "cdmw-equipment-material-audit-v1"},
            timeout_seconds=timeout_seconds,
        )
        if (
            int(result.get("protocol_version", 0) or 0)
            != ARCHIVE_WORKER_PROTOCOL_VERSION
            or int(result.get("index_version", 0) or 0) != 3
        ):
            self.close()
            raise RuntimeError("Archive audit worker handshake is incompatible.")
        return result

    def open_archive(
        self,
        package_root: Path | str,
        *,
        timeout_seconds: float = 900.0,
    ) -> AuditArchiveSession:
        root = Path(package_root).expanduser().resolve(strict=True)
        result = self.request(
            "open_archive",
            {
                "package_root": str(root),
                "force_refresh": False,
                "supersedes_session_id": None,
            },
            timeout_seconds=timeout_seconds,
        )
        session_id = str(result.get("session_id", "") or "").strip()
        if not session_id:
            raise RuntimeError("Archive audit worker returned no session id.")
        session = AuditArchiveSession(
            session_id=session_id,
            package_root=root,
            fingerprint=str(result.get("fingerprint", "") or "").strip(),
            entry_count=int(result.get("entry_count", 0) or 0),
            index_version=int(result.get("index_version", 0) or 0),
            cache_hit=bool(result.get("cache_hit", False)),
        )
        if session.index_version != 3 or session.entry_count <= 0:
            raise RuntimeError("Archive audit worker opened an invalid archive index.")
        self._session = session
        return session

    def resolve_values(
        self,
        kind: str,
        values: Sequence[str],
        *,
        chunk_size: int = 128,
        result_limit: int = 4096,
        timeout_seconds: float = 120.0,
    ) -> tuple[Mapping[str, object], ...]:
        session = self._session
        if session is None:
            raise RuntimeError("Archive audit worker has no open archive session.")
        if kind not in {"exact_paths", "basenames"}:
            raise ValueError(f"Unsupported equipment audit lookup kind: {kind}")
        if not 1 <= chunk_size <= 512:
            raise ValueError("Archive audit lookup chunk size must be between 1 and 512.")
        normalized_values = tuple(
            dict.fromkeys(str(value or "").replace("\\", "/").strip().strip("/") for value in values)
        )
        normalized_values = tuple(value for value in normalized_values if value)
        entries: list[Mapping[str, object]] = []
        seen: set[tuple[object, ...]] = set()
        for start in range(0, len(normalized_values), chunk_size):
            chunk = normalized_values[start : start + chunk_size]
            batches: list[Mapping[str, object]] = []
            result = self.request(
                "resolve_entries",
                {
                    "session_id": session.session_id,
                    "kind": kind,
                    "entry_ids": [],
                    "identities": [],
                    "values": list(chunk),
                    "roles": [],
                    "limit": result_limit,
                    "query_id": None,
                },
                session_id=session.session_id,
                timeout_seconds=timeout_seconds,
                batch_payloads=batches,
            )
            if bool(result.get("truncated", False)):
                raise RuntimeError(
                    "Archive audit lookup was truncated; reduce the lookup chunk size."
                )
            raw_entry_groups = [batch.get("entries", ()) for batch in batches]
            raw_entry_groups.append(result.get("entries", ()))
            chunk_entry_count = 0
            for raw_entries in raw_entry_groups:
                if not isinstance(raw_entries, Sequence) or isinstance(
                    raw_entries, (str, bytes, bytearray)
                ):
                    raise RuntimeError("Archive audit lookup returned an invalid entry list.")
                chunk_entry_count += len(raw_entries)
                for raw_entry in raw_entries:
                    if not isinstance(raw_entry, Mapping):
                        raise RuntimeError("Archive audit lookup returned an invalid entry row.")
                    identity = raw_entry.get("identity")
                    identity = identity if isinstance(identity, Mapping) else {}
                    key = (
                        str(identity.get("normalized_path", "") or "").casefold(),
                        str(identity.get("source_pamt", "") or "").casefold(),
                        int(identity.get("paz_index", 0) or 0),
                        int(identity.get("archive_offset", 0) or 0),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    entries.append(dict(raw_entry))
            if chunk_entry_count != int(result.get("total_matches", 0) or 0):
                raise RuntimeError(
                    "Archive audit lookup batch count did not match its terminal result."
                )
        return tuple(entries)

    def request(
        self,
        operation: str,
        payload: Mapping[str, object],
        *,
        session_id: str | None = None,
        timeout_seconds: float = 120.0,
        batch_payloads: list[Mapping[str, object]] | None = None,
    ) -> Mapping[str, object]:
        process = self._process
        if process is None or process.stdin is None:
            raise RuntimeError("Archive audit worker is not running.")
        request_id = str(uuid4())
        message = {
            "protocol_version": ARCHIVE_WORKER_PROTOCOL_VERSION,
            "request_id": request_id,
            "ui_generation": 0,
            "session_id": session_id,
            "operation": str(operation),
            "status": "request",
            "payload": dict(payload),
            "error": None,
        }
        encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        if len(encoded) > ARCHIVE_WORKER_MAXIMUM_MESSAGE_BYTES:
            raise ValueError("Archive audit worker request exceeds the one MiB limit.")
        try:
            process.stdin.write(encoded)
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(self._process_failure("request write failed")) from exc

        deadline = time.monotonic() + max(0.5, float(timeout_seconds))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Archive audit worker {operation} timed out after {timeout_seconds:.1f}s."
                )
            try:
                raw_line = self._messages.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if process.poll() is not None:
                    raise RuntimeError(self._process_failure(f"{operation} exited early"))
                continue
            if raw_line is None:
                raise RuntimeError(self._process_failure(f"{operation} closed stdout"))
            if len(raw_line) > ARCHIVE_WORKER_MAXIMUM_MESSAGE_BYTES:
                raise RuntimeError("Archive audit worker emitted an oversized message.")
            try:
                response = json.loads(raw_line.decode("utf-8", "strict"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("Archive audit worker emitted invalid JSON.") from exc
            if not isinstance(response, Mapping):
                raise RuntimeError("Archive audit worker response must be an object.")
            if str(response.get("request_id", "")) != request_id:
                raise RuntimeError("Archive audit worker response request id did not match.")
            if int(response.get("protocol_version", 0) or 0) != ARCHIVE_WORKER_PROTOCOL_VERSION:
                raise RuntimeError("Archive audit worker response protocol did not match.")
            status = str(response.get("status", "") or "").casefold()
            response_payload = response.get("payload")
            if status in {"started", "progress", "batch"}:
                if (
                    status == "batch"
                    and batch_payloads is not None
                    and isinstance(response_payload, Mapping)
                ):
                    batch_payloads.append(dict(response_payload))
                if self._progress is not None and isinstance(response_payload, Mapping):
                    self._progress(status, response_payload)
                continue
            if status == "result":
                if not isinstance(response_payload, Mapping):
                    raise RuntimeError("Archive audit worker result payload must be an object.")
                return response_payload
            if status == "cancelled":
                raise RuntimeError(f"Archive audit worker {operation} was cancelled.")
            if status == "error":
                error = response.get("error")
                error = error if isinstance(error, Mapping) else {}
                code = str(error.get("code", "worker_error") or "worker_error")
                detail = str(error.get("message", "") or "").strip()
                raise RuntimeError(f"Archive audit worker {operation} failed ({code}): {detail}")
            raise RuntimeError(f"Archive audit worker emitted unsupported status {status!r}.")

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                self.request("shutdown", {}, timeout_seconds=3.0)
            except Exception:
                pass
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._process = None
        self._session = None

    def _read_stdout(self, stream: BinaryIO) -> None:
        try:
            while True:
                line = stream.readline(ARCHIVE_WORKER_MAXIMUM_MESSAGE_BYTES + 2)
                if not line:
                    break
                self._messages.put(line.rstrip(b"\r\n"))
        finally:
            self._messages.put(None)

    def _read_stderr(self, stream: BinaryIO) -> None:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            self._stderr_tail.append(chunk)
            self._stderr_tail_size += len(chunk)
            while (
                self._stderr_tail
                and self._stderr_tail_size > ARCHIVE_WORKER_STDERR_TAIL_BYTES
            ):
                removed = self._stderr_tail.popleft()
                self._stderr_tail_size -= len(removed)

    def _process_failure(self, reason: str) -> str:
        process = self._process
        returncode = process.poll() if process is not None else None
        detail = " ".join(self.stderr_tail.split())[-1000:]
        suffix = f"; stderr: {detail}" if detail else ""
        return f"Archive audit worker {reason} (exit={returncode}){suffix}"


def archive_entry_from_worker(value: Mapping[str, object]) -> ArchiveEntry:
    """Convert a validated worker row into the production archive-entry type."""

    path = str(value.get("path", "") or "").replace("\\", "/").strip().strip("/")
    pamt_path = Path(str(value.get("source_pamt", "") or "")).expanduser().resolve()
    paz_file = Path(str(value.get("paz_file", "") or "")).expanduser().resolve()
    if not path or not pamt_path.is_file() or not paz_file.is_file():
        raise ValueError("Archive worker row does not reference readable live archive files.")
    return ArchiveEntry(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_file,
        offset=int(value.get("offset", 0) or 0),
        comp_size=int(value.get("stored_size", 0) or 0),
        orig_size=int(value.get("original_size", 0) or 0),
        flags=int(value.get("flags", 0) or 0),
        paz_index=int(value.get("paz_index", 0) or 0),
    )


__all__ = [
    "ARCHIVE_WORKER_MAXIMUM_MESSAGE_BYTES",
    "AuditArchiveSession",
    "AuditArchiveWorkerClient",
    "archive_entry_from_worker",
]
