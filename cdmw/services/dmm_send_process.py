"""Run Send to DMM outside the GUI's Python interpreter.

Composing the items is mostly Python, and the window shares the interpreter with any
background thread, so a send in a thread made the whole window lag. The child process
does the complete send (it writes DMM's mod folder itself) and reports progress through
a private file; only a small result record comes back.
"""
from __future__ import annotations

import json
import shutil
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from cdmw.core.common import run_process_with_cancellation
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled

_SCHEMA = 1
_MAX_PACKAGES = 128
_MAX_RECORD = 1024 * 1024
_STAGING_PREFIX = ".cdmw-send-"


class DmmSendProcessError(ValueError):
    """The send in the child process failed; the message is the child's own."""


def _worker_command(input_path: Path, output_path: Path) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[2] / "cdmw_app.py"))
    return [*command, "--dmm-send-worker", "--input", str(input_path), "--output", str(output_path)]


def _read_record(path: Path) -> object:
    with path.open("rb") as stream:
        data = stream.read(_MAX_RECORD + 1)
    if len(data) > _MAX_RECORD:
        raise DmmSendProcessError("Send to DMM returned an oversized record.")
    return json.loads(data.decode("utf-8"))


def _write_record(path: Path, value: object) -> None:
    path.write_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _staging_folders(mods: Path) -> set[Path]:
    # dmm_send stages beside DMM's mods folder (in its parent), never inside it.
    parent = Path(mods).parent
    try:
        return {path for path in parent.iterdir() if path.is_dir() and path.name.startswith(_STAGING_PREFIX)}
    except OSError:
        return set()


def send_item_packages_in_subprocess(package_paths, game_root, mods, title: str, *,
                                     stop_event: threading.Event | None = None,
                                     on_log: Callable[[str], None] | None = None,
                                     on_progress: Callable[[int, int, str], None] | None = None):
    """Send packages to DMM as dmm_send.send_item_packages does, in a child process."""
    from cdmw.services.dmm_send import DmmSendResult

    raise_if_cancelled(stop_event, "Send to DMM cancelled.")
    paths = [str(Path(path).resolve()) for path in package_paths]
    if not paths:
        raise ValueError("Select at least one item package to send to DMM.")
    if len(paths) > _MAX_PACKAGES:
        raise ValueError(f"Send at most {_MAX_PACKAGES} item packages at a time.")
    mods = Path(mods).resolve()
    request = {"schema": _SCHEMA, "nonce": uuid4().hex, "root": str(Path(game_root).resolve()),
               "mods": str(mods), "title": str(title), "packages": paths}
    staging_before = _staging_folders(mods)
    with TemporaryDirectory(prefix="cdmw_dmm_send_") as directory:
        folder = Path(directory)
        input_path, output_path = folder / "request.json", folder / "result.json"
        _write_record(input_path, request)
        position, partial = 0, b""

        def poll() -> None:
            nonlocal position, partial
            try:
                with (folder / "progress.jsonl").open("rb") as stream:
                    stream.seek(position)
                    data = stream.read(65536)
                    position += len(data)
                lines = (partial + data).split(b"\n")
                partial = lines.pop()
                for line in lines:
                    message = json.loads(line.decode("utf-8"))
                    if isinstance(message, str):
                        if on_log is not None:
                            on_log(message[:16000])
                    elif (on_progress is not None and isinstance(message, list) and len(message) == 3
                          and all(type(n) is int for n in message[:2]) and isinstance(message[2], str)):
                        on_progress(message[0], message[1], message[2][:16000])
            except (OSError, ValueError):
                # Progress is advisory; it must never strand the running child.
                partial = b""

        def published():
            # The child writes its result only after it replaced DMM's mod.
            if not output_path.is_file():
                return None
            result = _read_record(output_path)
            if (not isinstance(result, dict) or result.get("nonce") != request["nonce"]
                    or not isinstance(result.get("folder"), str) or Path(result["folder"]).parent != mods):
                raise DmmSendProcessError("Send to DMM returned an invalid result. Send again.")
            return DmmSendResult(Path(result["folder"]), bool(result.get("replaced")), str(result.get("title", title)))

        try:
            try:
                code, stdout, stderr = run_process_with_cancellation(
                    _worker_command(input_path, output_path), stop_event=stop_event, on_poll=poll,
                    timeout_seconds=6 * 3600, background=True)
            except RunCancelled:
                # A cancel that arrives after the child published still reports the published mod.
                result = published()
                if result is not None:
                    return result
                raise
            poll()
            result = published() if code == 0 else None
            if result is not None:
                return result
            raise_if_cancelled(stop_event, "Send to DMM cancelled.")
            if code == 2:
                raise RunCancelled("Send to DMM cancelled.")
            raise DmmSendProcessError((stderr or stdout).strip()[-1200:] or f"Send to DMM failed ({code}).")
        finally:
            # A child stopped mid-write cannot remove its own staging folder.
            for leftover in _staging_folders(mods) - staging_before:
                shutil.rmtree(leftover, ignore_errors=True)


def run_dmm_send_worker(input_path: Path, output_path: Path) -> int:
    """Internal helper mode: perform one send and write its result record."""
    from cdmw.services.dmm_send import send_item_packages

    request = _read_record(input_path)
    if (not isinstance(request, dict) or request.get("schema") != _SCHEMA
            or set(request) != {"schema", "nonce", "root", "mods", "title", "packages"}
            or not isinstance(request["packages"], list) or not 0 < len(request["packages"]) <= _MAX_PACKAGES
            or not all(isinstance(request[key], str) for key in ("nonce", "root", "mods", "title"))):
        print("Send to DMM received an invalid request.", file=sys.stderr)
        return 1
    stop = threading.Event()
    handlers = {}
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            number = getattr(signal, name)
            handlers[number] = signal.signal(number, lambda *_: stop.set())
    try:
        with (input_path.parent / "progress.jsonl").open("ab", buffering=0) as progress:
            def write(value):
                progress.write(json.dumps(value, ensure_ascii=False).encode("utf-8") + b"\n")

            result = send_item_packages(
                [Path(path) for path in request["packages"]], Path(request["root"]), Path(request["mods"]),
                request["title"], stop_event=stop, on_log=lambda message: write(str(message)[:16000]),
                on_progress=lambda current, total, detail: write([int(current), int(total), str(detail)[:16000]]))
        _write_record(output_path, {"nonce": request["nonce"], "folder": str(result.folder),
                                    "replaced": bool(result.replaced), "title": result.title})
        return 0
    except RunCancelled:
        return 2
    except Exception as exc:  # noqa: BLE001 - the parent shows the message
        print(str(exc) or type(exc).__name__, file=sys.stderr)
        return 1
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)


__all__ = ["DmmSendProcessError", "run_dmm_send_worker", "send_item_packages_in_subprocess"]
