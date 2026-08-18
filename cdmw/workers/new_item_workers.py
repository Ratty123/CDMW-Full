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
from cdmw.domain.archives.mutation import ArchivePatchResult
from cdmw.domain.new_item.spec import NewItemSpec
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.services.new_item_planning import NewItemPlan
from cdmw.services.new_item_service import NewItemExportResult, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot

LogSink = Callable[[str], None]
Task = Callable[[LogSink, threading.Event], object]


def snapshot_task(
    entries: Iterable[ArchiveEntry],
    *,
    service: NewItemService,
    read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
) -> Callable[[LogSink, threading.Event], NewItemSnapshot]:
    """Read every table a new item touches; seconds of work, once per archive scan."""

    frozen = tuple(entries)

    def run(log: LogSink, stop_event: threading.Event) -> NewItemSnapshot:
        return service.build_snapshot(frozen, read_entry=read_entry, on_log=log, stop_event=stop_event)

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
