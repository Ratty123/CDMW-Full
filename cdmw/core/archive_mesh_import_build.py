from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from cdmw.core.archive_mesh_import_build_stages import (
    attach_mesh_import_texture_previews,
    collect_mesh_import_references,
    finish_mesh_import_preview,
    load_mesh_import_sources,
    prepare_mesh_import_paired_lod,
    rebuild_mesh_import,
    resolve_mesh_import_sidecars,
    resolve_mesh_import_supplemental_files,
)
from cdmw.core.archive_mesh_import_build_state import MeshImportBuildState
from cdmw.core.archive_mesh_import_materials import (
    configure_mesh_import_materials,
    generate_mesh_import_material_payloads,
)
from cdmw.core.archive_mesh_types import MeshImportPreviewResult
from cdmw.models import ArchiveEntry
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions


def build_mesh_import_preview(
    entry: ArchiveEntry,
    obj_path: Path,
    *,
    import_mode: str = "roundtrip",
    static_replacement_options: Optional[StaticMeshReplacementOptions] = None,
    scene_import_result: Optional[SceneImportResult] = None,
    source_display_label: str = "",
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    visible_texture_mode: str = "mesh_base_first",
    supplemental_files: Sequence[Path] = (),
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> MeshImportPreviewResult:
    state = MeshImportBuildState(
        entry=entry,
        obj_path=obj_path,
        import_mode=import_mode,
        static_replacement_options=static_replacement_options,
        scene_import_result=scene_import_result,
        source_display_label=source_display_label,
        archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        texture_entries_by_normalized_path=texture_entries_by_normalized_path,
        texture_entries_by_basename=texture_entries_by_basename,
        visible_texture_mode=visible_texture_mode,
        supplemental_files=supplemental_files,
        stop_event=stop_event,
    )
    stages = (
        (load_mesh_import_sources, "Read source"),
        (rebuild_mesh_import, "Transform mesh"),
        (resolve_mesh_import_supplemental_files, "Resolve files"),
        (resolve_mesh_import_sidecars, "Resolve materials"),
        (attach_mesh_import_texture_previews, "Resolve textures"),
        (collect_mesh_import_references, "Resolve references"),
        (configure_mesh_import_materials, "Configure materials"),
        (generate_mesh_import_material_payloads, "Build materials"),
        (prepare_mesh_import_paired_lod, "Write package"),
    )
    total = len(stages) + 1
    for index, (stage, detail) in enumerate(stages):
        if on_progress is not None:
            on_progress(index, total, detail)
        stage(state)
    if on_progress is not None:
        on_progress(total - 1, total, "Publish")
    result = finish_mesh_import_preview(state)
    if on_progress is not None:
        on_progress(total, total, "Ready")
    return result
