from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping, Optional, Sequence

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
    load_mesh_import_sources(state)
    rebuild_mesh_import(state)
    resolve_mesh_import_supplemental_files(state)
    resolve_mesh_import_sidecars(state)
    attach_mesh_import_texture_previews(state)
    collect_mesh_import_references(state)
    configure_mesh_import_materials(state)
    generate_mesh_import_material_payloads(state)
    prepare_mesh_import_paired_lod(state)
    return finish_mesh_import_preview(state)
