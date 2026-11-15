"""Cancellable tasks behind Drafts & Mods' Combine into one mod (GitHub issue 31).

Each factory returns ``run(log, stop)`` for a worker thread. Nothing here runs
on the UI thread and nothing writes into the game: the plan task only reads the
selected builds, and the export task writes a new mod folder that the combine
service refuses to place inside the game or any selected build.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled

LogSink = Callable[[str], None]
CANCELLED = "Combining built mods was cancelled."


@dataclass(frozen=True, slots=True)
class CombinedSavedWork:
    """What the export task wrote and the Drafts & Mods record that lists it."""

    result: object
    record: dict


def mesh_build_combine_prepare_task(rows: Sequence[object]) -> Callable[[LogSink, threading.Event], object]:
    """Read the selected builds and plan their combination; writes nothing."""

    folders = tuple(Path(row.mod_root) for row in rows)
    labels = tuple(str(row.display_name or "") for row in rows)

    def run(log: LogSink, stop: threading.Event):
        from cdmw.services.mesh_build_combine_service import prepare_mesh_build_combine

        log(f"Checking {len(folders)} built mods...")
        return prepare_mesh_build_combine(folders, labels=labels, stop_event=stop)

    return run


def mesh_build_combine_export_task(
    prepared: object,
    destination: Path | str,
    *,
    title: str,
    draft_root: Path | str,
    rows: Sequence[object],
    game_root: Path | str | None,
    create_zip: bool = False,
    list_entries: Callable | None = None,
) -> Callable[[LogSink, threading.Event], CombinedSavedWork]:
    """Write the combined mod, then list it in Drafts & Mods.

    ``game_root`` is the configured game folder. It is always passed to the
    service, on the loose route too, so an output folder inside the game is
    refused there as well. The catalogue is listed only when the plan needs a
    DMM archive group. A cancel that arrives after the mod was written takes
    the new folder back out, so a cancelled run leaves nothing behind.
    """

    destination = Path(destination)
    title = str(title)
    rows = tuple(rows)
    game = Path(game_root) if str(game_root or "").strip() else None

    def run(log: LogSink, stop: threading.Event) -> CombinedSavedWork:
        from cdmw.domain.packages.mesh_build_combine import LAYOUT_ARCHIVE_GROUP
        from cdmw.services.mesh_build_combine_service import export_combined_mesh_builds, remove_combined_output
        from cdmw.services.mesh_saved_work_service import register_combined_mod

        entries: Sequence = ()
        if game is not None and prepared.plan.layout == LAYOUT_ARCHIVE_GROUP:
            if list_entries is None:
                from cdmw.workers.new_item_workers import list_archive_entries as list_entries_default

                entries = list_entries_default(game, log, stop)
            else:
                entries = list_entries(game, log, stop)
        raise_if_cancelled(stop, CANCELLED)
        chosen_empty = destination.expanduser().resolve().is_dir()
        result = export_combined_mesh_builds(
            prepared, destination, title=title, create_zip=create_zip, game_root=game,
            entries=entries, on_log=log, stop_event=stop,
        )
        try:
            raise_if_cancelled(stop, CANCELLED)
            record = register_combined_mod(
                draft_root, mod_root=result.output_path, target_paths=result.target_paths,
                combined_from=rows, zip_path=result.zip_path, manager_profile=result.manager_profile,
                display_name=title,
            )
        except BaseException:
            remove_combined_output(destination.expanduser().resolve(), result.output_path, result.zip_path,
                                   restore_empty=chosen_empty)
            raise
        log(f"Combined mod written: {result.output_path}")
        return CombinedSavedWork(result, record)

    return run


__all__ = [
    "CANCELLED",
    "CombinedSavedWork",
    "RunCancelled",
    "mesh_build_combine_export_task",
    "mesh_build_combine_prepare_task",
]
