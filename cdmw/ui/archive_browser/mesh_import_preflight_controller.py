"""Cancellable worker dispatch for archive mesh-import setup preflight."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox

from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.services.mesh_workflow_service import read_archive_entry_baseline_data
from cdmw.services.mesh_workflow_service import MeshImportPreflight, build_mesh_import_preflight
from cdmw.domain.mesh.session import MeshImportSetupSelection
from cdmw.domain.library.scene_selection import ModelArchiveSelectionRequired
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_workflow_service import ReplacementAssetProfile, analyze_replacement_asset
from cdmw.services.mesh_workflow_service import ParsedMesh, parse_mesh
from cdmw.services.mesh_workflow_service import SceneImportResult, import_scene_mesh_with_report
from cdmw.services.diagnostics_service import is_expected_cancellation_message
from cdmw.ui.archive_browser.mesh_import_setup_state import mesh_import_setup_control_text


@dataclass(frozen=True, slots=True)
class MeshImportSetupPreflightRequest:
    request_id: int
    entry: ArchiveEntry
    scene_path: Path
    scene_import_result: Optional[SceneImportResult]
    original_mesh: Optional[ParsedMesh]
    force_static_replacement: bool
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    selected_member: str = ""


@dataclass(frozen=True, slots=True)
class MeshImportSetupPreflightResult:
    request_id: int
    scene_import_result: SceneImportResult
    original_mesh: Optional[ParsedMesh]
    profile: Optional[ReplacementAssetProfile]
    preflight: MeshImportPreflight
    has_roundtrip_sidecar: bool


@dataclass(frozen=True, slots=True)
class MeshImportMemberSelectionResult:
    request_id: int
    members: tuple[str, ...]


def _prepare_mesh_import_setup_preflight(
    request: MeshImportSetupPreflightRequest,
    owner: object,
    progress: Callable[[int, int, str], None],
    stop_event: threading.Event,
) -> MeshImportSetupPreflightResult | MeshImportMemberSelectionResult:
    raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
    progress(0, 4, "Reading replacement scene...")
    loaded_scene = request.scene_import_result
    if loaded_scene is None:
        kwargs: dict[str, object] = {"stop_event": stop_event}
        if request.selected_member:
            kwargs["selected_member"] = request.selected_member
        try:
            loaded_scene = import_scene_mesh_with_report(request.scene_path, **kwargs)
        except ModelArchiveSelectionRequired as exc:
            return MeshImportMemberSelectionResult(request.request_id, exc.members)
    raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
    is_obj = request.scene_path.suffix.lower() == ".obj" and not request.force_static_replacement
    has_roundtrip_sidecar = bool(getattr(owner, "_has_valid_obj_roundtrip_sidecar")(request.scene_path)) if is_obj else False
    progress(1, 4, "Reading original archive mesh...")
    loaded_original = request.original_mesh
    profile: Optional[ReplacementAssetProfile] = None
    try:
        if loaded_original is None:
            original_data = read_archive_entry_baseline_data(
                request.entry,
                read_entry_data=read_archive_entry_data,
            ).data
            raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
            loaded_original = parse_mesh(original_data, request.entry.path)
        raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
        progress(2, 4, "Analyzing target compatibility...")
        profile = analyze_replacement_asset(
            request.entry,
            archive_entries_by_basename=request.archive_entries_by_basename,
            parsed_mesh=loaded_original,
        )
    except Exception:
        raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
        profile = None
        loaded_original = None
    raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
    progress(3, 4, "Checking asset compatibility...")
    preflight = build_mesh_import_preflight(
        request.entry,
        request.scene_path,
        replacement_mesh=loaded_scene.mesh,
        original_mesh=loaded_original,
        import_diagnostics=loaded_scene.diagnostics,
    )
    raise_if_cancelled(stop_event, "Mesh import setup cancelled.")
    progress(4, 4, preflight.summary)
    return MeshImportSetupPreflightResult(
        request_id=request.request_id,
        scene_import_result=loaded_scene,
        original_mesh=loaded_original,
        profile=profile,
        preflight=preflight,
        has_roundtrip_sidecar=has_roundtrip_sidecar,
    )


def dispatch_mesh_import_setup_preflight(
    owner: object,
    entry: ArchiveEntry,
    scene_path: Path,
    *,
    title: str,
    on_complete: Callable[[Optional[MeshImportSetupSelection]], None],
    scene_import_result: Optional[SceneImportResult] = None,
    source_skeleton: object | None = None,
    original_mesh: Optional[ParsedMesh] = None,
    source_label: str = "",
    force_static_replacement: bool = False,
    placement_review_title: str = "",
    placement_context_note: str = "",
    full_import_model_replacement: bool = False,
    selected_member: str = "",
) -> int:
    request_id = int(getattr(owner, "archive_mesh_import_setup_request_id", 0) or 0) + 1
    setattr(owner, "archive_mesh_import_setup_request_id", request_id)
    request = MeshImportSetupPreflightRequest(
        request_id=request_id,
        entry=entry,
        scene_path=Path(scene_path),
        scene_import_result=scene_import_result,
        original_mesh=original_mesh,
        force_static_replacement=bool(force_static_replacement),
        archive_entries_by_basename=getattr(owner, "archive_entries_by_basename"),
        selected_member=str(selected_member or ""),
    )
    setup_control_text = mesh_import_setup_control_text()

    def task(
        _log: Callable[[str], None],
        progress: Callable[[int, int, str], None],
        stop_event: threading.Event,
    ) -> object:
        return _prepare_mesh_import_setup_preflight(request, owner, progress, stop_event)

    def ready(payload: object) -> None:
        if isinstance(payload, MeshImportMemberSelectionResult):
            if payload.request_id != int(getattr(owner, "archive_mesh_import_setup_request_id", 0) or 0):
                return
            selected, accepted = QInputDialog.getItem(
                owner,
                "Choose Model from ZIP",
                "This ZIP contains multiple importable models. Choose one:",
                list(payload.members),
                0,
                False,
            )
            if not accepted:
                on_complete(None)
                return
            dispatch_mesh_import_setup_preflight(
                owner, entry, scene_path, title=title, on_complete=on_complete,
                scene_import_result=scene_import_result, source_skeleton=source_skeleton,
                original_mesh=original_mesh, source_label=source_label,
                force_static_replacement=force_static_replacement,
                placement_review_title=placement_review_title, placement_context_note=placement_context_note,
                full_import_model_replacement=full_import_model_replacement, selected_member=str(selected),
            )
            return
        if (
            not isinstance(payload, MeshImportSetupPreflightResult)
            or payload.request_id != int(getattr(owner, "archive_mesh_import_setup_request_id", 0) or 0)
            or bool(getattr(owner, "_shutting_down", False))
        ):
            return
        prompt = getattr(owner, "_prompt_archive_mesh_import_setup")
        setup = prompt(
            entry,
            Path(scene_path),
            title=title,
            prepared_preflight=payload,
            source_skeleton=source_skeleton,
            source_label=source_label,
            force_static_replacement=force_static_replacement,
            placement_review_title=placement_review_title,
            placement_context_note=placement_context_note,
            full_import_model_replacement=full_import_model_replacement,
        )
        on_complete(setup)

    def failed(message: str) -> None:
        if (
            request_id != int(getattr(owner, "archive_mesh_import_setup_request_id", 0) or 0)
            or bool(getattr(owner, "_shutting_down", False))
            or is_expected_cancellation_message(message)
            or "cancel" in str(message).casefold()
        ):
            return
        QMessageBox.warning(
            owner,
            setup_control_text["unsupported_title"],
            f"{Path(scene_path).name} could not be imported.\n\n{message}",
        )
        on_complete(None)

    run_when_idle = getattr(owner, "_run_utility_task_when_idle")
    run_when_idle(
        status_message=setup_control_text["startup_label"],
        task=task,
        on_complete=ready,
        on_error=failed,
        show_archive_progress=True,
        task_accepts_progress=True,
        task_accepts_cancel=True,
    )
    return request_id


__all__ = [
    "MeshImportSetupPreflightRequest",
    "MeshImportSetupPreflightResult",
    "MeshImportMemberSelectionResult",
    "dispatch_mesh_import_setup_preflight",
]
