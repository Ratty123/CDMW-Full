"""Compare every cached archive coordinate outside the GUI's Python heap."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace

from cdmw.constants import APP_VERSION
from cdmw.core.common import run_process_with_cancellation
from cdmw.core.archive_resident_index import ResidentArchiveSource
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.services.new_item_provenance import SourceTracker, StaleNewItemSource

# A completed comparison is a pure function of the mapped catalogue bytes and the
# parsed index bytes. Recording both digests beside the generation lets a later
# session re-hash the indexes instead of repeating the comparison. The app version
# retires a record whenever the parser or the comparison could have changed.
_WITNESS_NAME = "new-item-verification.json"
_WITNESS_SCHEMA = 1


def _witness_path(catalogue) -> Path:
    return Path(catalogue.source.index_path).with_name(_WITNESS_NAME)


def _load_witness(catalogue, request, expected_paths):
    try:
        path = _witness_path(catalogue)
        if path.stat().st_size > 1024 * 1024:
            return None
        stored = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(stored, dict) or stored.get("witness_schema") != _WITNESS_SCHEMA
                or stored.get("app_version") != APP_VERSION
                or any(stored.get(key) != value for key, value in request.items())):
            return None
        indexes = tuple((Path(path), checksum) for path, checksum in stored["indexes"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if len(indexes) != len(expected_paths) or {path for path, _ in indexes} != expected_paths:
        return None
    return indexes


def _store_witness(catalogue, request, indexes) -> None:
    record = {**request, "witness_schema": _WITNESS_SCHEMA, "app_version": APP_VERSION,
              "indexes": [(str(path), checksum) for path, checksum in indexes]}
    try:
        _write_state(_witness_path(catalogue), json.dumps(record))
    except OSError:
        pass  # The next session repeats the full comparison.


def _adopt_witnesses(catalogue, request, indexes, provenance: SourceTracker, stop_event) -> None:
    if catalogue.verification_digest(stop_event) != request["catalogue_digest"]:
        raise StaleNewItemSource("Archive catalogue changed during verification. Refresh the archives.")
    catalogue.validate_sources(stop_event)
    for path, checksum in indexes:
        provenance.pin_index(path, checksum, stop_event)
    provenance.validate_indexes(stop_event)
    catalogue.validate_sources(stop_event)
    raise_if_cancelled(stop_event)


def _worker_command(request: Path, result: Path) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[2] / "cdmw_app.py"))
    return [*command, "--archive-verification-worker", "--input", str(request), "--output", str(result)]


def _write_state(path: Path, value: str) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _leave_background_priority() -> None:
    """Requested work no longer yields to every normal-priority process."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x20)  # NORMAL_PRIORITY_CLASS


class _WorkerControl:
    def __init__(self, path: Path):
        self.path = path
        self._next_poll = 0.0
        self._state = "run"
        self._foreground = False

    def is_set(self):
        while True:
            now = time.monotonic()
            if now >= self._next_poll:
                # Losing the control channel must never leave an orphan working.
                try:
                    self._state = self.path.read_text(encoding="utf-8")
                except OSError:
                    self._state = "cancel"
                self._next_poll = now + 0.025
            if self._state == "foreground" and not self._foreground:
                self._foreground = True
                _leave_background_priority()
            if self._state != "pause":
                return self._state not in {"run", "foreground"}
            time.sleep(0.025)


def verify_resident_catalogue(catalogue, provenance: SourceTracker, *, stop_event=None, on_log=None) -> None:
    """Import only complete witnesses for the parent's exact mapped generation.

    The child retains the existing full multiset comparison. Neither millions of
    ArchiveEntry objects nor their temporary Counters reach the GUI's collector.
    Parent-side rechecks close the gap between child verification and publication.
    A recorded comparison for the same mapped bytes skips the child only while
    every index still hashes to the digest that comparison parsed.
    """
    raise_if_cancelled(stop_event)
    catalogue.validate_sources(stop_event)
    source = asdict(catalogue.source)
    source["ignored_folders"] = list(catalogue.source.ignored_folders)
    request = {"schema": 1, "source": source,
               "catalogue_digest": catalogue.verification_digest(stop_event)}
    expected_paths = {path for path in catalogue.source_paths if path.suffix.lower() == ".pamt"}
    witnessed = _load_witness(catalogue, request, expected_paths)
    if witnessed is not None:
        try:
            # Confirm every index still hashes to its witnessed bytes before any
            # digest reaches the caller's tracker; a mismatch repeats the comparison.
            scratch = SourceTracker(None)
            for path, checksum in witnessed:
                scratch.pin_index(path, checksum, stop_event)
        except ValueError:
            witnessed = None
    if witnessed is not None:
        _adopt_witnesses(catalogue, request, witnessed, provenance, stop_event)
        return
    if on_log is not None:
        on_log("Checking the archive catalogue against the game's index files. "
               "This runs once after the game or a mod changes them...")
    state_reader = getattr(stop_event, "process_state", None)

    def child_state():
        # A preload gate reports run/pause until a consumer opens; any other
        # caller is already requested work and keeps normal priority.
        if callable(state_reader):
            return state_reader()
        return "cancel" if stop_event is not None and stop_event.is_set() else "foreground"

    with TemporaryDirectory(prefix="cdmw_archive_verification_") as folder:
        root = Path(folder)
        input_path, output_path = root / "request.json", root / "result.json"
        control_path = root / "control"
        input_path.write_text(json.dumps(request), encoding="utf-8")
        previous_state = None
        control_errors = []

        def poll():
            nonlocal previous_state
            current = child_state()
            if current != previous_state and not control_errors:
                try:
                    _write_state(control_path, current)
                    previous_state = current
                except OSError as exc:
                    # Cancel through the existing runner so it reaps the child
                    # before temporary files are removed, then report the error.
                    control_errors.append(exc)

        def cancel_child(process):
            try:
                _write_state(control_path, "cancel")
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass  # The runner bounds the remaining process-tree shutdown.

        poll()
        cancellation = SimpleNamespace(is_set=lambda: bool(control_errors) or child_state() == "cancel")
        try:
            raise_if_cancelled(cancellation)
            code, stdout, stderr = run_process_with_cancellation(
                _worker_command(input_path, output_path), stop_event=cancellation,
                on_poll=poll, on_cancel=cancel_child, background=previous_state != "foreground",
            )
            raise_if_cancelled(cancellation)
        except RunCancelled:
            if control_errors:
                raise RuntimeError(f"Cannot control archive verification: {control_errors[0]}") from control_errors[0]
            raise
        raise_if_cancelled(stop_event)
        try:
            result = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            detail = (stderr or stdout).strip()[-1200:]
            raise RuntimeError(detail or f"Archive verification produced no complete result ({code}).") from exc
        if code:
            message = result.get("error") if isinstance(result, dict) else None
            raise StaleNewItemSource(str(message or "Archive verification failed."))
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in request.items()):
            raise StaleNewItemSource("Archive verification returned a different catalogue generation.")
        try:
            indexes = tuple((Path(path), checksum) for path, checksum in result["indexes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StaleNewItemSource("Archive verification returned incomplete index witnesses.") from exc
        if len(indexes) != len(expected_paths) or {path for path, _ in indexes} != expected_paths:
            raise StaleNewItemSource("Archive verification omitted source indexes.")
        _adopt_witnesses(catalogue, request, indexes, provenance, stop_event)
        _store_witness(catalogue, request, indexes)


def run_archive_verification_worker(input_path: Path, output_path: Path) -> int:
    request = json.loads(input_path.read_text(encoding="utf-8"))
    stop = _WorkerControl(input_path.parent / "control")
    try:
        if request["schema"] != 1:
            raise ValueError("Unsupported archive verification request.")
        catalogue = ResidentArchiveSource(**request["source"]).open(stop)
        if catalogue.verification_digest(stop) != request["catalogue_digest"]:
            raise StaleNewItemSource("Archive catalogue changed before verification. Refresh the archives.")
        tracker = SourceTracker(None)
        catalogue.verify_parsed_indexes(lambda path: tracker.parse_index(path, stop_event=stop), stop_event=stop)
        tracker.validate_indexes(stop)
        if catalogue.verification_digest(stop) != request["catalogue_digest"]:
            raise StaleNewItemSource("Archive catalogue changed during verification. Refresh the archives.")
        result = {**request, "indexes": [(str(path), checksum) for path, checksum in tracker.capture().indexes]}
        raise_if_cancelled(stop)
    except RunCancelled:
        return 2
    except (OSError, ValueError) as exc:
        _write_state(output_path, json.dumps({"error": str(exc)}))
        return 1
    _write_state(output_path, json.dumps(result))
    return 0
