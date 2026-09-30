"""Game-update evidence used by the current archive opening workflow."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
import threading
import time

from cdmw.models import RunCancelled
from cdmw.services.archive_environment_service import resolve_crimson_desert_executable


def check_game_executable_fingerprints(
    package_root: Path, records: Mapping[str, object], *, stop_event: threading.Event | None = None,
) -> tuple[dict[str, dict[str, object]] | None, tuple[str, ...], bool]:
    executable = resolve_crimson_desert_executable(package_root)
    if executable is None:
        return None, (), False
    try:
        before = executable.stat()
        key = str(executable).strip().lower()
        updated = {str(k): dict(v) for k, v in records.items() if isinstance(v, Mapping)}
        previous = updated.get(key, {})
        previous_hash = str(previous.get("sha256", "") or "").strip()
        if previous_hash and previous.get("size") == before.st_size and previous.get("mtime_ns") == before.st_mtime_ns:
            return None, (), False
        digest = hashlib.sha256()
        with executable.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if stop_event is not None and stop_event.is_set():
                    raise RunCancelled("Game executable check cancelled.")
                digest.update(chunk)
        after = executable.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None, ("Game update check skipped: the executable changed while hashing.",), False
        current_hash = digest.hexdigest()
    except OSError as error:
        return None, (f"Game update check skipped: could not read {executable}: {error}",), False
    checked_at = time.time()
    record = dict(previous)
    record.update(path=str(executable), sha256=current_hash, size=before.st_size,
                  mtime_ns=before.st_mtime_ns, checked_at=checked_at)
    changed = bool(previous_hash and previous_hash != current_hash)
    if changed:
        record.update(previous_sha256=previous_hash, update_detected_at=checked_at)
    updated[key] = record
    if not previous_hash:
        logs = (f"Recorded CrimsonDesert.exe hash baseline: {executable}",)
    elif changed:
        logs = (
            "The game build changed. Use New Item > Tools > Check mods for game updates to review older mods and overlays.",
            "Game update detected via CrimsonDesert.exe hash. Refreshing the standalone archive catalogue.",
        )
    else:
        logs = ()
    return updated, logs, changed
