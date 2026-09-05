"""Decode effect metadata outside the GUI process's Python interpreter."""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Optional

from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.services.effect_catalogue import (
    EffectCatalogue, LogFn, ProgressFn, build_effect_catalogue,
    catalogue_signature, load_effect_catalogue, save_effect_catalogue,
)
from cdmw.services.new_item_snapshot import EFFECT_DIR, NewItemSnapshot


def _worker_command(input_path: Path, output_path: Path) -> list[str]:
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve().parents[2] / "cdmw_app.py"))
    return [*command, "--effect-catalogue-worker", "--input", str(input_path), "--output", str(output_path)]


def build_effect_catalogue_in_subprocess(
    snapshot: NewItemSnapshot,
    *,
    on_log: Optional[LogFn] = None,
    on_progress: Optional[ProgressFn] = None,
    stop_event: Optional[threading.Event] = None,
) -> EffectCatalogue:
    """Spool one effect at a time using the snapshot's reader, then decode in a child.

    Only the requested effect bytes cross the process boundary. The live archive
    index, snapshot, and reader closure remain in their owning process.
    """
    raise_if_cancelled(stop_event)
    signature = catalogue_signature(snapshot)
    wanted = sorted(snapshot.effect_stems)
    with TemporaryDirectory(prefix="cdmw_effect_catalogue_") as folder:
        root = Path(folder)
        rows = []
        with (root / "payloads.bin").open("wb") as payloads:
            for index, stem in enumerate(wanted):
                raise_if_cancelled(stop_event)
                path = f"{EFFECT_DIR}{stem}.pae"
                if not snapshot.has_entry(path):
                    continue
                entry = snapshot.entry(path)
                row = {
                    "stem": stem, "offset": payloads.tell(), "length": 0,
                    "orig_size": int(getattr(entry, "orig_size", 0) or getattr(entry, "comp_size", 0) or 0),
                    "error": "",
                }
                try:
                    data = bytes(snapshot.read_entry(entry))
                except (ValueError, OSError) as exc:
                    row["error"] = str(exc)
                else:
                    raise_if_cancelled(stop_event)
                    payloads.write(data)
                    row["length"] = len(data)
                    del data
                rows.append(row)
                if on_progress is not None and (index % 50 == 0 or index + 1 == len(wanted)):
                    on_progress(0, len(wanted), stem)
        raise_if_cancelled(stop_event)
        if not rows:
            return EffectCatalogue(signature=signature)
        input_path, output_path = root / "request.json", root / "result.json"
        input_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        progress_path = root / "progress.json"
        previous_progress = None

        def poll_progress() -> None:
            nonlocal previous_progress
            if on_progress is None:
                return
            try:
                progress = json.loads(progress_path.read_text(encoding="utf-8"))
                if not isinstance(progress, list) or len(progress) != 3:
                    return
                progress = (int(progress[0]), int(progress[1]), str(progress[2]))
            except (OSError, ValueError, TypeError):
                return
            if progress != previous_progress:
                previous_progress = progress
                on_progress(*progress)

        returncode, stdout, stderr = run_process_with_cancellation(
            _worker_command(input_path, output_path), stop_event=stop_event,
            on_poll=poll_progress, timeout_seconds=300,
        )
        raise_if_cancelled(stop_event)
        if returncode:
            raise RuntimeError((stderr or stdout).strip()[-1200:] or f"Effect indexing failed ({returncode}).")
        catalogue = load_effect_catalogue(output_path, signature=signature)
        if catalogue is None or set(catalogue.facts) != {row["stem"] for row in rows}:
            raise RuntimeError("Effect indexing did not produce a complete metadata catalogue.")
        if on_log is not None:
            on_log(f"Indexed {len(catalogue)} effects; {sum(bool(item.walk_note) for item in catalogue.facts.values())} did not decode.")
        return catalogue


class _StagedEffects:
    """The small read-only snapshot surface consumed by build_effect_catalogue."""

    def __init__(self, rows: list[dict], payloads) -> None:
        self._payloads = payloads
        self._size = os.fstat(payloads.fileno()).st_size
        self.entries = {f"{EFFECT_DIR}{row['stem']}.pae": SimpleNamespace(**row) for row in rows}
        self.effect_stems = tuple(row["stem"] for row in rows)

    def has_entry(self, path: str) -> bool:
        return path in self.entries

    def entry(self, path: str):
        return self.entries[path]

    def read_entry(self, entry) -> bytes:
        if entry.error:
            raise OSError(entry.error)
        if entry.offset < 0 or entry.length < 0 or entry.offset + entry.length > self._size:
            raise ValueError("Staged effect payload is incomplete.")
        self._payloads.seek(entry.offset)
        data = self._payloads.read(entry.length)
        if len(data) != entry.length:
            raise ValueError("Staged effect payload is incomplete.")
        return data


def run_effect_catalogue_worker(input_path: Path, output_path: Path) -> int:
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    progress_path = input_path.parent / "progress.json"
    temporary_progress = progress_path.with_suffix(".tmp")

    def progress(done: int, total: int, stem: str) -> None:
        try:
            temporary_progress.write_text(json.dumps([done, total, stem]), encoding="utf-8")
            os.replace(temporary_progress, progress_path)
        except OSError:
            pass  # Progress is advisory; the complete result still must publish.

    with (input_path.parent / "payloads.bin").open("rb") as payloads:
        catalogue = build_effect_catalogue(_StagedEffects(rows, payloads), on_progress=progress)
    save_effect_catalogue(catalogue, output_path)
    return 0
