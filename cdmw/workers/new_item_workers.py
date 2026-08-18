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
from typing import Callable, Iterable, Optional

from cdmw.core.item_icon_addition import NewItemIcon
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.archives.mutation import ArchivePatchResult
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.new_item_planning import NewItemPlan
from cdmw.services.new_item_service import NewItemExportResult, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot

LogSink = Callable[[str], None]
Task = Callable[[LogSink, threading.Event], object]


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
        return service.build_snapshot(listed, read_entry=read_entry, on_log=log, stop_event=stop_event)

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
) -> Callable[[LogSink, threading.Event], NewItemPlan]:
    """Validate, allocate and compose the plan (fourteen language tables, an icon encode,
    the material route's texture encodes)."""

    def run(log: LogSink, stop_event: threading.Event) -> NewItemPlan:
        return service.plan(
            spec, snapshot, model=model, scene=scene, icon=icon, icon_source_path=icon_source_path, on_log=log, stop_event=stop_event
        )

    return run


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


__all__ = ["export_task", "install_task", "plan_task", "snapshot_task"]
