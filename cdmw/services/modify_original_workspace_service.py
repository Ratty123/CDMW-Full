"""Cancellable preparation for the safe Modify Original clone workflow."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.archive_workflow_service import export_archive_mesh
from cdmw.services.atomic_file_service import atomic_write_text
from cdmw.services.mesh_workflow_service import (
    import_scene_mesh_with_report,
    parse_mesh,
    read_archive_entry_baseline_data,
)


ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]
CleanupCallback = Callable[[LogCallback], None]
SupplementalFilesCallback = Callable[[Path, threading.Event], Sequence[Path]]


@dataclass(frozen=True, slots=True)
class ModifyOriginalWorkspacePreparationRequest:
    """Immutable inputs captured before the preparation worker starts."""

    entry: ArchiveEntry
    workspace_dir: Path
    create_workspace: bool
    include_family_files: bool
    open_workspace_after_create: bool
    cleanup_stale_sessions: bool
    archive_entries_by_normalized_path: Mapping[str, Sequence[ArchiveEntry]]
    archive_entries_by_basename: Mapping[str, Sequence[ArchiveEntry]]
    related_entries: tuple[ArchiveEntry, ...] = ()
    model_texture_references: tuple[object, ...] = ()
    asset_family_graph: object | None = None


def prepare_modify_original_workspace(
    request: ModifyOriginalWorkspacePreparationRequest,
    *,
    log: LogCallback | None = None,
    progress: ProgressCallback | None = None,
    stop_event: threading.Event | None = None,
    cleanup_stale_sessions: CleanupCallback | None = None,
    collect_supplemental_files: SupplementalFilesCallback | None = None,
) -> dict[str, object]:
    """Export, import, and parse the exact safe clone used by Modify Original.

    The caller owns worker/thread lifetime. This function performs no UI work and
    never writes to PAMT/PAZ sources; all output is confined to ``workspace_dir``.
    """

    stop = stop_event or threading.Event()
    emit = log or (lambda _message: None)
    report = progress or (lambda _current, _total, _detail: None)
    workspace_dir = Path(request.workspace_dir).expanduser().resolve()
    entry = request.entry
    create_workspace = bool(request.create_workspace)
    include_family = bool(request.include_family_files)
    open_after = bool(create_workspace and request.open_workspace_after_create)

    raise_if_cancelled(stop, "Modify Original preparation cancelled.")
    total_steps = 5
    report(1, total_steps, "Modify Original: creating safe clone folder...")
    if request.cleanup_stale_sessions and cleanup_stale_sessions is not None:
        cleanup_stale_sessions(emit)
    workspace_dir.parent.mkdir(parents=True, exist_ok=True)
    emit(
        f"Creating Modify Original workspace: {workspace_dir}"
        if create_workspace
        else f"Preparing Modify Original in-app session: {workspace_dir}"
    )
    if include_family and not create_workspace:
        emit(
            "Modify Original in-app session uses the archive material graph directly; "
            "resolved asset-family file copying is skipped to keep startup responsive."
        )

    report(2, total_steps, "Modify Original: writing editable OBJ clone...")
    export_result = export_archive_mesh(
        entry,
        workspace_dir,
        "obj",
        archive_entries_by_normalized_path=request.archive_entries_by_normalized_path,
        archive_entries_by_basename=request.archive_entries_by_basename,
        related_entries=request.related_entries,
        allow_missing_skeleton=True,
        resolve_skeleton_for_obj=create_workspace,
        model_texture_references=request.model_texture_references,
        asset_family_graph=request.asset_family_graph,
        build_preview_context=create_workspace,
        on_log=emit,
    )
    raise_if_cancelled(stop, "Modify Original preparation cancelled.")
    obj_paths = [path for path in export_result.output_paths if path.suffix.lower() == ".obj"]
    if not obj_paths:
        raise ValueError("OBJ export did not produce an editable clone file.")
    obj_path = obj_paths[0]

    emit("Preloading Modify Original clone geometry off the UI thread...")
    report(3, total_steps, "Modify Original: loading editable clone geometry...")
    scene_import_result = import_scene_mesh_with_report(obj_path, stop_event=stop)
    emit("Preloading original archive mesh for Geometry alignment...")
    report(4, total_steps, "Modify Original: loading original archive mesh...")
    original_data = read_archive_entry_baseline_data(
        entry,
        read_entry_data=lambda archive_entry: read_archive_entry_data(
            archive_entry,
            stop_event=stop,
        ),
    ).data
    original_mesh = parse_mesh(original_data, entry.path)
    source_skeleton = None
    supplemental_files = tuple(
        Path(path)
        for path in (
            collect_supplemental_files(workspace_dir, stop)
            if collect_supplemental_files is not None
            else ()
        )
    )
    raise_if_cancelled(stop, "Modify Original preparation cancelled.")

    readme_path: Path | None = None
    manifest_path = workspace_dir / "modify_original_workspace.json"
    if create_workspace:
        readme_path = workspace_dir / "MODIFY_ORIGINAL_README.txt"
        atomic_write_text(
            readme_path,
            "\n".join(
                [
                    "Crimson Desert Mod Workbench - Modify Original Workspace",
                    "",
                    f"Source archive mesh: {entry.path}",
                    f"Editable OBJ clone: {obj_path.name}",
                    "",
                    "What this workspace is for:",
                    "- The app opens this OBJ clone in Mesh Replacement Setup automatically.",
                    "- Use Geometry in the alignment window to resize, move, or reshape existing mesh parts.",
                    "- Keep topology, material names, and draw-part structure stable for the safest import.",
                    "- Edit copied DDS/material sidecar files under referenced_files/ when you want texture/material context changes.",
                    "",
                    "What this workspace does not do:",
                    "- It does not patch game archives directly.",
                    "- It does not make arbitrary topology, skeleton, or animation edits safe.",
                    "- It does not bypass the existing loose-mod export and validation path.",
                    "",
                    "Back in the app, use Mesh Replacement Setup and Geometry to review the clone and write a mod-ready loose package.",
                ]
            ),
        )
    atomic_write_text(
        manifest_path,
        json.dumps(
            {
                "format": "cdmw_modify_original_workspace_v1",
                "workspace_mode": "user_workspace" if create_workspace else "internal_app_session",
                "create_workspace": create_workspace,
                "source_archive_path": entry.path,
                "source_package": entry.package_label,
                "workspace_dir": str(workspace_dir),
                "editable_obj": str(obj_path),
                "related_file_count": len(request.related_entries),
                "supplemental_file_count": len(supplemental_files),
                "include_family_files": include_family,
                "open_workspace_after_create": open_after,
                "process_id": os.getpid(),
                "created_at": time.time(),
                "exported_files": [str(path) for path in export_result.output_paths],
                "policy": "safe_clone_workspace_imports_through_mesh_replacement_geometry_path",
            },
            indent=2,
        ),
    )
    report(5, total_steps, "Modify Original: opening Geometry workspace...")
    return {
        "workspace_dir": workspace_dir,
        "obj_path": obj_path,
        "readme_path": readme_path,
        "manifest_path": manifest_path,
        "create_workspace": create_workspace,
        "output_paths": tuple(export_result.output_paths),
        "summary_lines": tuple(export_result.summary_lines),
        "related_count": len(request.related_entries),
        "supplemental_files": supplemental_files,
        "scene_import_result": scene_import_result,
        "source_skeleton": source_skeleton,
        "original_mesh": original_mesh,
    }


__all__ = [
    "ModifyOriginalWorkspacePreparationRequest",
    "prepare_modify_original_workspace",
]
