"""Synthetic offscreen construction smoke for the archive Mesh Builder."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QComboBox

from cdmw.domain.archives.backend_mode import ArchiveBackendMode, ArchiveBackendSelection
from cdmw.models import ArchiveEntry, ModelPreviewData
from cdmw.services.mesh_workflow_service import (
    ParsedMesh,
    ReplacementAssetProfile,
    SceneImportResult,
)
from cdmw.ui.archive_browser.static_replacement_dialog_prompt import (
    prompt_archive_static_replacement_options,
)
from cdmw.ui.archive_browser.static_replacement_prompt_preflight import (
    StaticReplacementPromptPreflightResult,
)


def synthetic_archive_entry(root: Path) -> ArchiveEntry:
    return ArchiveEntry(
        "character/model/synthetic_mesh_builder.pac",
        root / "0009" / "0.pamt",
        root / "0009" / "0.paz",
        0,
        1,
        1,
        0,
        0,
    )


def synthetic_builder_preflight(
    *,
    modify_original_clone_mode: bool,
) -> StaticReplacementPromptPreflightResult:
    mesh = ParsedMesh(path="synthetic_mesh_builder.obj")
    scene = SceneImportResult(mesh=mesh)
    preview = ModelPreviewData(path="synthetic_mesh_builder.obj")
    profile = ReplacementAssetProfile(
        source_path="character/model/synthetic_mesh_builder.pac",
        mesh_format="pac",
        category_hint="object",
        asset_family="character",
        support_level="Supported",
        replacement_support="Supported",
        export_supported=True,
        geometry_mode="static",
        lod_mode="selected",
        sidecar_mode="preserve",
    )
    return StaticReplacementPromptPreflightResult(
        request_id=1,
        scene_import_result=scene,
        original_mesh=mesh,
        replacement_mesh_base=mesh,
        replacement_mesh=mesh,
        original_preview_model=preview,
        replacement_preview_model=preview,
        asset_profile=profile,
        suggested_mappings=(),
        texture_files=(),
        auto_texture_sources=(),
        texture_sets={},
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        sidecar_bindings=(),
        sidecar_text_values=(),
        sidecar_texts_by_normalized_path={},
        sidecar_texts_by_basename={},
        modify_original_clone_mode=modify_original_clone_mode,
        scene_flip_v=False,
        placement_fit=None,
        source_bounds=None,
        reference_bounds=None,
        texture_lookup_source="synthetic_startup_smoke",
        texture_lookup_dds_count=0,
        texture_lookup_sidecar_count=0,
        texture_lookup_reference_count=0,
    )


def configure_synthetic_archive_context(window: object, entry: ArchiveEntry) -> None:
    remote_bridge = getattr(window, "archive_remote_bridge", None)
    deactivate = getattr(remote_bridge, "deactivate", None)
    if callable(deactivate):
        deactivate()
    window.archive_remote_bridge = None
    window.archive_backend_selection = ArchiveBackendSelection(
        ArchiveBackendMode.LEGACY,
        "mesh_builder_startup_smoke",
        True,
    )
    window.archive_backend_mode = ArchiveBackendMode.LEGACY
    window.archive_entries = [entry]
    window.archive_entries_by_normalized_path = {entry.path.casefold(): (entry,)}
    window.archive_entries_by_basename = {entry.basename.casefold(): (entry,)}


def _failure_detail(events: list[tuple[str, dict[str, object]]]) -> str:
    failures = [
        fields
        for event, fields in events
        if event == "mesh_alignment_construction_failed"
    ]
    if not failures:
        return "no construction-failure diagnostic was recorded"
    latest = failures[-1]
    return (
        f"stage={latest.get('stage')!s}, "
        f"message={latest.get('message')!s}"
    )


def active_builder_timer_names(context: object) -> tuple[str, ...]:
    if not isinstance(context, dict):
        return ()
    active: list[str] = []
    for name, value in context.items():
        if not str(name).endswith("_timer") or not isinstance(value, QTimer):
            continue
        try:
            if value.isActive():
                active.append(str(name))
        except RuntimeError:
            continue
    return tuple(sorted(active))


def _exercise_builder_mode(
    window: object,
    app: QApplication,
    root: Path,
    events: list[tuple[str, dict[str, object]]],
    *,
    mode_name: str,
    modify_original_clone_mode: bool,
) -> None:
    existing_keys = set(window._modeless_alignment_dialogs)
    prompt_archive_static_replacement_options(
        window,
        window.archive_entries[0],
        root / f"{mode_name}.obj",
        dialog_title=f"Synthetic {mode_name}",
        _prepared_prompt_preflight=synthetic_builder_preflight(
            modify_original_clone_mode=modify_original_clone_mode,
        ),
    )
    app.processEvents()

    new_keys = set(window._modeless_alignment_dialogs) - existing_keys
    if len(new_keys) != 1:
        raise RuntimeError(
            f"Mesh Builder {mode_name} startup smoke did not open exactly one dialog: "
            f"{_failure_detail(events)}."
        )
    dialog_key = next(iter(new_keys))
    dialog = window._modeless_alignment_dialogs[dialog_key]
    construction_context = getattr(dialog, "_cdmw_builder_construction_context", {})
    try:
        if not bool(getattr(dialog, "_cdmw_builder_construction_complete", False)):
            raise RuntimeError(
                f"Mesh Builder {mode_name} startup smoke did not complete construction: "
                f"{_failure_detail(events)}."
            )
        if dialog.findChild(QComboBox, "MeshAlignmentViewportDisplayModeCombo") is None:
            raise RuntimeError(
                f"Mesh Builder {mode_name} startup smoke is missing the viewport display control."
            )
    finally:
        dialog.reject()
        app.processEvents()
        active_timers = active_builder_timer_names(construction_context)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    if dialog_key in window._modeless_alignment_dialogs:
        raise RuntimeError(f"Mesh Builder {mode_name} startup smoke did not cleanly close its dialog.")
    if active_timers:
        raise RuntimeError(
            f"Mesh Builder {mode_name} startup smoke left active timers after close: "
            f"{', '.join(active_timers)}."
        )


def verify_mesh_builder_startup_smoke_target(
    window: object,
    app: QApplication,
) -> tuple[str, ...]:
    """Construct both Builder entry modes without assets, rendering, or archive I/O."""

    events: list[tuple[str, dict[str, object]]] = []
    original_record_runtime_event = getattr(window, "_record_runtime_event", None)

    def capture_runtime_event(event: str, **fields: object) -> object:
        events.append((event, dict(fields)))
        if callable(original_record_runtime_event):
            return original_record_runtime_event(event, **fields)
        return {}

    window._record_runtime_event = capture_runtime_event
    completed_modes: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw-mesh-builder-startup-smoke-") as temp_dir:
            root = Path(temp_dir)
            entry = synthetic_archive_entry(root)
            configure_synthetic_archive_context(window, entry)
            for mode_name, modify_original_clone_mode in (
                ("Import Mesh", False),
                ("Modify Original", True),
            ):
                _exercise_builder_mode(
                    window,
                    app,
                    root,
                    events,
                    mode_name=mode_name,
                    modify_original_clone_mode=modify_original_clone_mode,
                )
                completed_modes.append(mode_name)
    finally:
        if callable(original_record_runtime_event):
            window._record_runtime_event = original_record_runtime_event

    if any(event == "mesh_alignment_construction_failed" for event, _fields in events):
        raise RuntimeError(
            "Mesh Builder startup smoke recorded a construction failure after completion: "
            f"{_failure_detail(events)}."
        )
    if any(event == "mesh_dotnet_process_started" for event, _fields in events):
        raise RuntimeError("Synthetic Mesh Builder construction unexpectedly started the renderer.")
    return tuple(completed_modes)


# Earlier private names; kept so an out-of-tree caller does not break on the
# promotion to a reusable fixture surface.
_synthetic_archive_entry = synthetic_archive_entry
_synthetic_preflight = synthetic_builder_preflight
_configure_synthetic_archive_context = configure_synthetic_archive_context
_active_builder_timer_names = active_builder_timer_names


__all__ = [
    "active_builder_timer_names",
    "configure_synthetic_archive_context",
    "synthetic_archive_entry",
    "synthetic_builder_preflight",
    "verify_mesh_builder_startup_smoke_target",
]
