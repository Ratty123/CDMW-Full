from __future__ import annotations

import os
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.models import ArchiveEntry
from cdmw.services.modify_original_workspace_service import (
    ModifyOriginalWorkspacePreparationRequest,
    prepare_modify_original_workspace,
    read_modify_original_source_asset,
)
from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
    StaticReplacementPromptPreflightRequest,
    prepare_static_replacement_prompt_preflight,
)
from tools.mesh_harness.archive_provenance import _archive_content_fingerprints
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key


_LOAD_SAMPLE = "character/model/1_pc/8_pdw/nude/cd_pdw_00_nude_00_0001.pac"
_RUN_LABELS = ("cold", "refresh", "warm")


def _extension_index(entries: Sequence[ArchiveEntry]) -> dict[str, tuple[ArchiveEntry, ...]]:
    grouped: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.extension, []).append(entry)
    return {extension: tuple(values) for extension, values in grouped.items()}


def _stage_rows(started: float):
    rows: list[dict[str, object]] = []

    def record(current: int, total: int, detail: str) -> None:
        rows.append(
            {
                "current": int(current),
                "total": int(total),
                "detail": str(detail or ""),
                "elapsed_ms": round(max(0.0, (time.perf_counter() - started) * 1000.0), 3),
            }
        )

    return rows, record


def _stage_delta(rows: Sequence[Mapping[str, object]], start: int, end: int) -> float:
    start_value = next(
        (float(row.get("elapsed_ms", 0.0) or 0.0) for row in rows if row.get("current") == start),
        0.0,
    )
    end_value = next(
        (float(row.get("elapsed_ms", 0.0) or 0.0) for row in rows if row.get("current") == end),
        start_value,
    )
    return round(max(0.0, end_value - start_value), 3)


def run_real_archive_mesh_editor_load_smoke(
    game_root: Path,
    output_dir: Path,
) -> dict[str, object]:
    """Measure the read-only Archive Browser to embedded Builder load path."""

    pamt_path = Path(game_root) / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "error": f"missing PAMT: {pamt_path}",
        }

    entries = tuple(parse_archive_pamt(pamt_path))
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    entry = next(iter(entries_by_path.get(_archive_key(_LOAD_SAMPLE), ())), None)
    if not isinstance(entry, ArchiveEntry):
        return {
            "ok": False,
            "read_only": True,
            "error": f"load sample not found: {_LOAD_SAMPLE}",
        }

    fingerprint_paths = tuple(
        path
        for path in (pamt_path, Path(entry.paz_file) if entry.paz_file is not None else None)
        if isinstance(path, Path) and path.is_file()
    )
    fingerprints_before = _archive_content_fingerprints(fingerprint_paths)
    extension_index = _extension_index(entries)
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QProgressDialog, QWidget

    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
        active_builder_timer_names,
        configure_synthetic_archive_context,
    )
    from cdmw.ui.archive_browser.static_replacement_dialog_prompt import (
        prompt_archive_static_replacement_options,
    )
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    class TransitionProbe(QObject):
        def __init__(self, owner: QWidget) -> None:
            super().__init__(owner)
            self.owner = owner
            self.progress_shows: list[str] = []
            self.partial_builder_shows: list[dict[str, str]] = []

        def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
            if event.type() != QEvent.Type.Show or not isinstance(watched, QWidget):
                return False
            if isinstance(watched, QProgressDialog) and watched.parentWidget() is self.owner:
                self.progress_shows.append(str(watched.windowTitle() or ""))
            builder = watched
            while builder is not None:
                if builder.objectName() == "MeshReplacementAlignmentDialog":
                    if not bool(getattr(builder, "_cdmw_builder_construction_complete", False)):
                        self.partial_builder_shows.append(
                            {
                                "type": type(watched).__name__,
                                "object_name": str(watched.objectName() or ""),
                            }
                        )
                    break
                builder = builder.parentWidget()
            return False

    app = QApplication.instance() or QApplication(["mesh-editor-real-archive-load-smoke"])
    settings_path = output_dir / "mesh-editor-load.ini"
    settings = create_settings(settings_file_path=settings_path)
    window = MainWindow(
        app_context=AppContext(
            settings=settings,
            services=ServiceContainer.create_default(settings=settings),
            event_bus=AppEventBus(),
        )
    )
    window.settings_file_path = settings_path
    configure_synthetic_archive_context(window, entry)
    window.archive_entries = list(entries)
    window.archive_entries_by_normalized_path = entries_by_path
    window.archive_entries_by_basename = entries_by_basename
    window.archive_entries_by_extension = extension_index
    window.show()
    window._activate_tool_widget(window.archive_browser_tab)
    app.processEvents()
    archive_before_path = output_dir / "archive-browser-before.png"
    archive_before_saved = bool(window.grab().save(str(archive_before_path), "PNG"))

    runtime_events: list[tuple[str, dict[str, object]]] = []
    original_recorder = window._record_runtime_event

    def capture_runtime_event(event: str, **fields: object) -> object:
        runtime_events.append((event, dict(fields)))
        return original_recorder(event, **fields)

    window._record_runtime_event = capture_runtime_event
    runs: list[dict[str, object]] = []
    failure: str | None = None
    try:
        for run_index, label in enumerate(_RUN_LABELS, start=1):
            run_root = output_dir / f"run-{run_index:02d}-{label}"
            run_root.mkdir(parents=True, exist_ok=True)
            action_started = time.perf_counter()
            transition_probe = TransitionProbe(window)
            app.installEventFilter(transition_probe)

            inspection_started = time.perf_counter()
            source_data, source_hash = read_modify_original_source_asset(entry)
            inspection_ms = max(0.0, (time.perf_counter() - inspection_started) * 1000.0)

            preparation_started = time.perf_counter()
            preparation_stages, preparation_progress = _stage_rows(preparation_started)
            prepared = prepare_modify_original_workspace(
                ModifyOriginalWorkspacePreparationRequest(
                    entry=entry,
                    workspace_dir=run_root / "workspace",
                    create_workspace=False,
                    include_family_files=False,
                    open_workspace_after_create=False,
                    cleanup_stale_sessions=False,
                    archive_entries_by_normalized_path=entries_by_path,
                    archive_entries_by_basename=entries_by_basename,
                    source_asset_data=source_data,
                    source_asset_sha256=source_hash,
                ),
                progress=preparation_progress,
                stop_event=threading.Event(),
            )
            preparation_ms = max(0.0, (time.perf_counter() - preparation_started) * 1000.0)

            preflight_started = time.perf_counter()
            preflight_stages, preflight_progress = _stage_rows(preflight_started)
            preflight = prepare_static_replacement_prompt_preflight(
                StaticReplacementPromptPreflightRequest(
                    request_id=run_index,
                    entry=entry,
                    obj_path=prepared["obj_path"],
                    supplemental_files=tuple(prepared.get("supplemental_files", ())),
                    scene_import_result=prepared["scene_import_result"],
                    original_mesh=prepared["original_mesh"],
                    archive_entries_by_normalized_path=entries_by_path,
                    archive_entries_by_basename=entries_by_basename,
                    archive_entries_by_extension=extension_index,
                ),
                progress=preflight_progress,
                stop_event=threading.Event(),
            )
            preflight_ms = max(0.0, (time.perf_counter() - preflight_started) * 1000.0)

            event_start = len(runtime_events)
            existing_dialogs = set(window._modeless_alignment_dialogs)
            builder_started = time.perf_counter()
            try:
                prompt_archive_static_replacement_options(
                    window,
                    entry,
                    prepared["obj_path"],
                    supplemental_files=tuple(prepared.get("supplemental_files", ())),
                    scene_import_result=prepared["scene_import_result"],
                    original_mesh=prepared["original_mesh"],
                    dialog_title="Modify Original Geometry",
                    placement_context_note="Read-only load diagnostics.",
                    defer_original_texture_preview=True,
                    embedded_host=window.mesh_editor_tab.builder_host(),
                    _prepared_prompt_preflight=preflight,
                )
                builder_ms = max(0.0, (time.perf_counter() - builder_started) * 1000.0)
                new_dialogs = set(window._modeless_alignment_dialogs) - existing_dialogs
                if len(new_dialogs) != 1:
                    raise RuntimeError(f"expected one embedded Builder, got {len(new_dialogs)}")
                dialog_key = next(iter(new_dialogs))
                dialog = window._modeless_alignment_dialogs[dialog_key]
                construction_context = getattr(dialog, "_cdmw_builder_construction_context", {})
                post_open_tasks = construction_context.get("alignment_post_open_tasks")
                if isinstance(post_open_tasks, list):
                    post_open_tasks.clear()
                app.processEvents()
            finally:
                app.removeEventFilter(transition_probe)

            revealed_path = run_root / "mesh-editor-revealed.png"
            revealed_saved = bool(window.grab().save(str(revealed_path), "PNG"))
            open_steps = [
                str(fields.get("step") or "")
                for event, fields in runtime_events[event_start:]
                if event == "mesh_alignment_open_step"
            ]
            presentations = [
                dict(fields)
                for event, fields in runtime_events[event_start:]
                if event == "mesh_alignment_startup_presentation"
            ]
            builder_startup_steps = [
                dict(fields)
                for event, fields in runtime_events[event_start:]
                if event == "mesh_alignment_startup_step"
            ]
            viewport_combo = dialog.findChild(QComboBox, "MeshAlignmentViewportDisplayModeCombo")
            material_request = getattr(dialog, "_mesh_editor_embedded_request_material_resources", None)
            startup_progress = getattr(dialog, "_cdmw_builder_startup_progress", None)
            startup_progress_timer_active = bool(
                startup_progress is not None
                and any(timer.isActive() for timer in startup_progress.findChildren(QTimer))
            )
            builder_complete = bool(getattr(dialog, "_cdmw_builder_construction_complete", False))
            builder_mounted = dialog.parentWidget() is window.mesh_editor_tab.builder_host()
            mesh_editor_revealed = bool(window._is_tool_visible_or_current(window.mesh_editor_tab))
            action_total_ms = max(0.0, (time.perf_counter() - action_started) * 1000.0)
            active_timers: tuple[str, ...] = ()
            try:
                dialog.reject()
                app.processEvents()
                active_timers = active_builder_timer_names(construction_context)
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                app.processEvents()
            finally:
                window._activate_tool_widget(window.archive_browser_tab)
                app.processEvents()

            exact_mapping = bool(
                preflight.suggested_mappings
                and all(
                    mapping.confidence_label == "exact-original-clone"
                    for mapping in preflight.suggested_mappings
                )
            )
            runs.append(
                {
                    "label": label,
                    "inspection_ms": round(inspection_ms, 3),
                    "preparation_ms": round(preparation_ms, 3),
                    "preparation_performance": dict(prepared.get("performance", {})),
                    "preparation_stages": preparation_stages,
                    "preflight_ms": round(preflight_ms, 3),
                    "preflight_reported_ms": round(preflight.total_elapsed_ms, 3),
                    "preflight_clone_ms": round(preflight.mesh_clone_elapsed_ms, 3),
                    "preflight_clone_stage_ms": _stage_delta(preflight_stages, 3, 4),
                    "preflight_clone_strategy": preflight.mesh_clone_strategy,
                    "preflight_routing_ms": preflight.routing_elapsed_ms,
                    "preflight_routing_stage_ms": _stage_delta(preflight_stages, 6, 7),
                    "preflight_stages": preflight_stages,
                    "builder_ms": round(builder_ms, 3),
                    "action_total_ms": round(action_total_ms, 3),
                    "open_steps": open_steps,
                    "builder_startup_steps": builder_startup_steps,
                    "startup_presentations": presentations,
                    "progress_dialog_show_count": len(transition_probe.progress_shows),
                    "progress_dialog_titles": transition_probe.progress_shows,
                    "startup_progress_timer_active": startup_progress_timer_active,
                    "partial_builder_show_count": len(transition_probe.partial_builder_shows),
                    "partial_builder_shows": transition_probe.partial_builder_shows,
                    "builder_complete": builder_complete,
                    "builder_mounted": builder_mounted,
                    "mesh_editor_revealed": mesh_editor_revealed,
                    "viewport_display_control_present": viewport_combo is not None,
                    "material_request_wired": callable(material_request),
                    "exact_original_clone_mapping": exact_mapping,
                    "active_timers_after_close": active_timers,
                    "revealed_capture": str(revealed_path),
                    "revealed_capture_saved": revealed_saved,
                }
            )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        window._record_runtime_event = original_recorder
        window._finalize_close()
        window.deleteLater()
        app.processEvents()
        settings.sync()

    fingerprints_after = _archive_content_fingerprints(fingerprint_paths)
    archives_unchanged = bool(fingerprints_before and fingerprints_before == fingerprints_after)
    runs_ok = bool(
        len(runs) == len(_RUN_LABELS)
        and all(
            row["preflight_clone_strategy"] == "python_worker_copy"
            and row["progress_dialog_show_count"] == 0
            and not row["startup_progress_timer_active"]
            and row["partial_builder_show_count"] == 0
            and row["builder_complete"]
            and row["builder_mounted"]
            and row["mesh_editor_revealed"]
            and row["viewport_display_control_present"]
            and row["material_request_wired"]
            and row["exact_original_clone_mapping"]
            and not row["active_timers_after_close"]
            and row["revealed_capture_saved"]
            for row in runs
        )
    )
    result: dict[str, object] = {
        "ok": bool(failure is None and runs_ok and archives_unchanged and archive_before_saved),
        "read_only": True,
        "workflow": "real PAMT/PAC -> Modify Original clone -> preflight -> embedded Mesh Editor reveal",
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "model_path": entry.path,
        "entry_count": len(entries),
        "archive_browser_capture": str(archive_before_path),
        "archive_browser_capture_saved": archive_before_saved,
        "runs": runs,
        "archive_fingerprint_paths": [str(path) for path in fingerprint_paths],
        "archive_content_fingerprints_before": fingerprints_before,
        "archive_content_fingerprints_after": fingerprints_after,
        "archive_sources_unchanged": archives_unchanged,
    }
    if failure is not None:
        result["error"] = failure
    return result


__all__ = ["run_real_archive_mesh_editor_load_smoke"]
