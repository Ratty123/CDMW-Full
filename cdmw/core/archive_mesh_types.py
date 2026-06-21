from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional, Tuple

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ImportAutoFixResult,
    ImportIssue,
    MeshImportDiff,
    ModelPreviewData,
)
from cdmw.modding.mesh_parser import ParsedMesh

@dataclass(slots=True)
class MeshExportResult:
    output_paths: List[Path]
    summary_lines: List[str]
    requires_confirmation: bool = False
    confirmation_title: str = ""
    confirmation_message: str = ""


@dataclass(slots=True)
class MeshImportPreviewResult:
    rebuilt_data: bytes
    parsed_mesh: ParsedMesh
    preview_model: ModelPreviewData
    summary_lines: List[str]
    import_mode: str = "roundtrip"
    texture_references: Tuple[ArchiveModelTextureReference, ...] = ()
    supplemental_file_specs: Tuple["MeshImportSupplementalFileSpec", ...] = ()
    paired_lod_data: Optional[bytes] = None
    paired_lod_path: str = ""
    import_diffs: Tuple[MeshImportDiff, ...] = ()
    import_issues: Tuple[ImportIssue, ...] = ()
    auto_fix_result: ImportAutoFixResult = field(default_factory=ImportAutoFixResult)
    roundtrip_manifest: Optional[dict] = None
    source_owned_output_draw_sections: Tuple[object, ...] = ()
    material_authority_settings: Mapping[str, object] = field(default_factory=dict)

@dataclass(slots=True)
class ArchiveLooseExportResult:
    package_root: Path
    written_files: List[Path]
    authority_audit_path: Optional[Path] = None
    authority_mismatch_count: int = 0
    package_roots: Tuple[Path, ...] = ()


@dataclass(slots=True)
class ActiveFileAuthorityAuditRow:
    virtual_path: str
    local_path: str
    local_size: int
    local_sha256: str
    active_source: str = ""
    active_size: int = 0
    active_sha256: str = ""
    duplicate_count: int = 0
    status: str = "not_found"
    note: str = ""


@dataclass(slots=True)
class ActiveFileAuthorityAuditResult:
    package_root: Path
    game_root: Path
    rows: List[ActiveFileAuthorityAuditRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    mismatch_count: int = 0
    audit_path: Optional[Path] = None
    requires_report: bool = False


@dataclass(slots=True)
class MeshImportSupplementalFileSpec:
    source_path: Path
    target_path: str = ""
    kind: str = ""
    target_entry: Optional[ArchiveEntry] = None
    used_for_preview: bool = False
    payload_data: bytes = b""
    note: str = ""
