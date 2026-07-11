from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from cdmw.models import ArchiveEntry
from cdmw.modding.scene_importer import SceneImportResult
from cdmw.modding.static_mesh_replacer import StaticMeshReplacementOptions


@dataclass
class MeshImportBuildState:
    entry: ArchiveEntry
    obj_path: Path
    import_mode: str
    static_replacement_options: Optional[StaticMeshReplacementOptions]
    scene_import_result: Optional[SceneImportResult]
    source_display_label: str
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]]
    texconv_path: Optional[Path]
    texture_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]]
    texture_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]]
    visible_texture_mode: str
    supplemental_files: Sequence[Path]
    stop_event: Optional[threading.Event]
    imported_mesh: Any = None
    manifest_payload: Any = None
    original_baseline: Any = None
    original_data: bytes = b""
    original_mesh: Any = None
    original_sidecars_for_static: tuple = ()
    normalized_import_mode: str = ""
    static_mappings: list = field(default_factory=list)
    enable_missing_base_color_parameters: bool = False
    effective_static_source_mesh: Any = None
    static_report: Any = None
    rebuilt_data: bytes = b""
    parsed_mesh: Any = None
    preview_model: Any = None
    summary_lines: list[str] = field(default_factory=list)
    resolved_supplemental_files: tuple[Path, ...] = ()
    sidecar_texture_references: tuple = ()
    sidecar_reference_paths: tuple[str, ...] = ()
    sidecar_texts_by_normalized_path: dict[str, tuple[str, ...]] = field(default_factory=dict)
    sidecar_texts_by_basename: dict[str, tuple[str, ...]] = field(default_factory=dict)
    original_archive_sidecar_texture_references: tuple = ()
    original_archive_sidecar_reference_paths: tuple[str, ...] = ()
    selected_sidecar_texture_references: tuple = ()
    selected_sidecar_reference_paths: tuple[str, ...] = ()
    selected_sidecar_texts_by_normalized_path: dict[str, tuple[str, ...]] = field(default_factory=dict)
    selected_sidecar_texts_by_basename: dict[str, tuple[str, ...]] = field(default_factory=dict)
    normalized_visible_texture_mode: str = "mesh_base_first"
    texture_references: tuple = ()
    supplemental_file_specs: tuple = ()
    material_options: dict[str, object] = field(default_factory=dict)
    material_authority_settings: dict[str, object] = field(default_factory=dict)
    paired_lod_data: Optional[bytes] = None
    paired_lod_path: str = ""
