"""Cancellable New Item Studio tasks: snapshot, plan, export and install.

Each factory returns a `(log, stop_event) -> result` callable shaped for
:class:`cdmw.workers.utility_workers.UtilityWorker` (`task_accepts_cancel=True`), so
the tab runs them through the existing utility-task runner off the UI thread. No
Qt here: the callables only take the log sink and the stop event the runner hands
them, and cancellation raises the shared `RunCancelled`.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.item_icon_addition import NewItemIcon
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.archives.mutation import ArchivePatchResult
from cdmw.domain.new_item.spec import IconSource, NewItemSpec
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.new_item_planning import NewItemPlan
from cdmw.services.new_item_service import NewItemExportResult, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot

LogSink = Callable[[str], None]
Task = Callable[[LogSink, threading.Event], object]


def model_source_cleanup_task(source: object) -> Task:
    """Wait for preview/build usages, then remove one retired import source."""

    def run(_log: LogSink, _stop_event: threading.Event) -> object:
        wait_until_unused = getattr(source, "wait_until_unused", None)
        if callable(wait_until_unused):
            wait_until_unused()
        cleanup = getattr(source, "cleanup", None)
        if callable(cleanup):
            cleanup()
        return None

    return run


def list_archive_entries(package_root: Path, log: LogSink, stop_event: threading.Event) -> tuple[ArchiveEntry, ...]:
    """Every entry of every package table under `package_root`, read directly.

    The shell's standalone catalogue backend shows the Archive Browser without ever
    filling the window's legacy entry list, so a tool that needs the whole list reads
    it here (about ten seconds for the shipped game); a package table that will not
    parse is skipped and said so.
    """

    from cdmw.core.archive_format import discover_pamt_files, parse_archive_pamt

    root = Path(package_root)
    tables = discover_pamt_files(root)
    if not tables:
        raise ValueError(f"No package tables (0.pamt) were found under {root}.")
    log(f"Listing the archives under {root} ({len(tables)} package tables)...")
    entries: list[ArchiveEntry] = []
    for index, pamt in enumerate(tables, start=1):
        raise_if_cancelled(stop_event, "New item snapshot cancelled.")
        try:
            entries.extend(parse_archive_pamt(pamt))
        except Exception as error:  # noqa: BLE001 - one bad package is not the end of the list
            log(f"Skipping {pamt.parent.name}/{pamt.name}: {error}")
        if index % 8 == 0 or index == len(tables):
            log(f"Listed {index}/{len(tables)} package tables, {len(entries):,} entries so far...")
    return tuple(entries)


def snapshot_task(
    entries: Iterable[ArchiveEntry],
    *,
    service: NewItemService,
    read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
    package_root: Optional[Path] = None,
    entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_extension: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Callable[[LogSink, threading.Event], NewItemSnapshot]:
    """Read every table a new item touches; seconds of work, once per archive scan.

    With no `entries` and a `package_root`, the archives are listed first
    (:func:`list_archive_entries`), which is what the studio does when the shell's
    catalogue backend has not filled the legacy entry list.
    """

    frozen = tuple(entries)

    def run(log: LogSink, stop_event: threading.Event) -> NewItemSnapshot:
        listed = frozen
        if not listed:
            if package_root is None:
                raise ValueError("The archive list is empty and no package root was given.")
            listed = list_archive_entries(Path(package_root), log, stop_event)
        return service.build_snapshot(
            listed,
            read_entry=read_entry,
            on_log=log,
            stop_event=stop_event,
            entries_by_normalized_path=entries_by_normalized_path,
            entries_by_basename=entries_by_basename,
            entries_by_extension=entries_by_extension,
        )

    return run


def plan_task(
    spec: NewItemSpec,
    snapshot: NewItemSnapshot,
    *,
    service: NewItemService,
    model: object | None = None,
    scene: object | None = None,
    icon: Optional[NewItemIcon] = None,
    icon_source_path: Optional[Path] = None,
    mod_base_folder: Optional[Path] = None,
    read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
    reserved_keys: Sequence[int] = (),
    reserved_stems: Sequence[str] = (),
) -> Callable[[LogSink, threading.Event], NewItemPlan]:
    """Validate, allocate and compose the plan (fourteen language tables, an icon encode,
    the material route's texture encodes). `reserved_*` are identities already handed out
    that the snapshot cannot see (an earlier plan this session, a loose mod not installed)."""

    def run(log: LogSink, stop_event: threading.Event) -> NewItemPlan:
        base = snapshot
        if mod_base_folder is not None:
            if read_entry is None:
                raise ValueError("Read the archives first.")
            from cdmw.services.new_item_mod_base import mod_folder_payloads, read_entry_over_mod_folder

            payloads = mod_folder_payloads(Path(mod_base_folder), stop_event=stop_event)
            if payloads:
                log("Reading the archives again so the next item gets its own key and stem...")
                try:
                    base = service.build_snapshot(
                        tuple(snapshot.entries.values()),
                        read_entry=read_entry_over_mod_folder(read_entry, payloads),
                        on_log=log,
                        stop_event=stop_event,
                    )
                except (OSError, ValueError) as exc:
                    raise ValueError(f"The mod folder could not be read as a base: {exc}") from exc
        resolved_icon = icon_source_path
        if spec.icon is IconSource.GENERATED and icon_source_path is not None:
            resolved_icon = _resolve_icon_source(spec, base, Path(icon_source_path), stop_event=stop_event)
        return service.plan(
            spec, base, model=model, scene=scene, icon=icon, icon_source_path=resolved_icon,
            reserved_keys=tuple(reserved_keys), reserved_stems=tuple(reserved_stems),
            on_log=log, stop_event=stop_event,
        )

    return run


def _resolve_icon_source(
    spec: NewItemSpec,
    snapshot: NewItemSnapshot,
    source: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    """Resolve a chosen image folder inside the planning worker."""

    if source.is_file():
        return source
    if not source.is_dir():
        raise ValueError(f"The icon source {source} does not exist.")
    from cdmw.services.item_icon_service import ItemIconService

    template = snapshot.row(spec.template_key)
    stems = [str(spec.stem or ""), str(snapshot.family(spec.template_key).model_stem)]
    chosen, _candidates, message = ItemIconService().choose_source(
        source,
        target_path=f"itemicon_prefab_{spec.stem or ''}.dds",
        related_stems=[stem for stem in stems if stem],
        display_name=spec.display_names.get("eng", "") or template.string_key,
        stop_event=stop_event,
    )
    if chosen is None:
        raise ValueError(message or f"No image in {source} matched the new item closely enough; pick a file instead.")
    return Path(chosen.path)


def export_task(
    plan: NewItemPlan,
    package_root: Path,
    *,
    service: NewItemService,
    manager: str = "CDUMM",
    package_info: Optional[ModPackageInfo] = None,
    options: Optional[ModPackageExportOptions] = None,
) -> Callable[[LogSink, threading.Event], NewItemExportResult]:
    def run(log: LogSink, stop_event: threading.Event) -> NewItemExportResult:
        log(f"Writing {plan.spec.internal_name} as a {manager} loose mod under {package_root}...")
        result = service.export_loose(
            plan, Path(package_root), manager=manager, package_info=package_info, options=options, stop_event=stop_event
        )
        log(f"Wrote {len(result.payload_paths)} file(s), {len(result.new_paths)} of them new.")
        return result

    return run


def install_task(
    plan: NewItemPlan,
    *,
    service: NewItemService,
    mutation_service,
    confirmed: bool,
) -> Callable[[LogSink, threading.Event], ArchivePatchResult]:
    """Install into the game archives: backup, validate, apply, restore on failure or cancel."""

    def run(log: LogSink, stop_event: threading.Event) -> ArchivePatchResult:
        return service.install(plan, mutation_service=mutation_service, confirmed=confirmed, on_log=log, stop_event=stop_event)

    return run


def install_overlay_task(
    plan: NewItemPlan,
    *,
    service: NewItemService,
    mutation_service,
    confirmed: bool,
) -> Callable[[LogSink, threading.Event], object]:
    """Install as an archive directory of the item's own, mounted ahead of the shipped ones."""

    def run(log: LogSink, stop_event: threading.Event) -> object:
        return service.install_overlay(plan, mutation_service=mutation_service, confirmed=confirmed, on_log=log, stop_event=stop_event)

    return run


def overlay_migration_task(package_root, *, mutation_service) -> Callable[[LogSink, threading.Event], object]:
    """Move what is already in the shipped archives out into the overlay, and put them back."""

    def run(log: LogSink, stop_event: threading.Event) -> object:
        from cdmw.services.archive_overlay_migration import migrate_into_overlay, plan_migration

        found = plan_migration(package_root, stop_event=stop_event)
        log(f"{len(found.entries)} archive entrie(s) differ from the oldest backup of them ({found.payload_bytes:,} bytes).")
        if found.is_empty:
            return found

        if not hasattr(mutation_service, "backup_files") or not hasattr(mutation_service, "restore_backup"):
            raise RuntimeError("The archive mutation service is not available in this window.")

        def backup(paths, description):
            return mutation_service.backup_files(paths, description=description, on_log=log)

        def restore(path):
            return mutation_service.restore_backup(path, confirmed=True, on_log=log)

        from cdmw.services.new_item_service import game_is_running

        return migrate_into_overlay(
            package_root,
            plan=found,
            backup=backup,
            restore_backup=restore,
            game_running=game_is_running,
            on_log=log,
            stop_event=stop_event,
        )

    return run


def overlay_removal_task(package_root, *, mutation_service) -> Callable[[LogSink, threading.Event], object]:
    """Unmount the overlay and delete it."""

    def run(log: LogSink, stop_event: threading.Event) -> object:
        from cdmw.services.archive_overlay_migration import remove_overlay

        if not hasattr(mutation_service, "backup_files") or not hasattr(mutation_service, "restore_backup"):
            raise RuntimeError("The archive mutation service is not available in this window.")

        def backup(paths, description):
            return mutation_service.backup_files(paths, description=description, on_log=log)

        def restore(path):
            return mutation_service.restore_backup(path, confirmed=True, on_log=log)

        from cdmw.services.new_item_service import game_is_running

        return remove_overlay(
            package_root,
            backup=backup,
            restore_backup=restore,
            game_running=game_is_running,
            on_log=log,
            stop_event=stop_event,
        )

    return run


__all__ = [
    "export_task",
    "install_overlay_task",
    "install_task",
    "model_source_cleanup_task",
    "overlay_migration_task",
    "overlay_removal_task",
    "plan_task",
    "snapshot_task",
]
