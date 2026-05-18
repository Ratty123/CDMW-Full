from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from cdmw.constants import APP_NAME
from cdmw.core.mesh_native import audit_mesh_native
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh


SUPPORTED_PARITY_EXTENSIONS = {".pac", ".pam", ".pamlod"}


@dataclass(slots=True)
class MeshNativeParityCase:
    path: str
    format: str
    layout: str = ""
    status: str = "unknown"
    mismatches: list[str] = field(default_factory=list)
    python_summary: dict[str, Any] = field(default_factory=dict)
    native_summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok" and not self.mismatches


@dataclass(slots=True)
class MeshNativeParityReport:
    status: str
    root: str
    cases: list[MeshNativeParityCase]
    enabled_rebuild_layouts: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "cdmw_mesh_native_parity_v1",
            "status": self.status,
            "root": self.root,
            "case_count": len(self.cases),
            "ok_count": sum(1 for case in self.cases if case.ok),
            "enabled_rebuild_layouts": self.enabled_rebuild_layouts,
            "cases": [
                {
                    "path": case.path,
                    "format": case.format,
                    "layout": case.layout,
                    "status": case.status,
                    "mismatches": case.mismatches,
                    "python_summary": case.python_summary,
                    "native_summary": case.native_summary,
                }
                for case in self.cases
            ],
        }


def mesh_native_parity_manifest_path() -> Optional[Path]:
    raw_path = os.environ.get("CDMW_MESH_NATIVE_PARITY_MANIFEST", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidate = Path(local_app_data) / APP_NAME / "mesh_native_parity.json"
        if candidate.is_file():
            return candidate
    return None


def _manifest_layout_enabled(manifest_key: str, format_name: str, layout: str) -> bool:
    manifest_path = mesh_native_parity_manifest_path()
    if manifest_path is None or not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, Mapping) or manifest.get("schema") != "cdmw_mesh_native_parity_v1":
        return False
    if manifest.get("status") != "ok":
        return False
    enabled = manifest.get(manifest_key)
    if not isinstance(enabled, Mapping):
        return False
    layouts = enabled.get(str(format_name or "").lower())
    if not isinstance(layouts, list):
        return False
    normalized_layout = str(layout or "").strip().lower()
    return normalized_layout in {str(item or "").strip().lower() for item in layouts}


def native_mesh_rebuild_parity_enabled(format_name: str, layout: str) -> bool:
    return _manifest_layout_enabled("enabled_rebuild_layouts", format_name, layout)


def native_mesh_full_rebuild_parity_enabled(format_name: str, layout: str) -> bool:
    return _manifest_layout_enabled("enabled_full_rebuild_layouts", format_name, layout)


def discover_mesh_fixture_paths(root: Path, *, limit: int = 0) -> list[Path]:
    root = Path(root).expanduser()
    if not root.exists():
        return []
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_PARITY_EXTENSIONS
    ]
    paths.sort(key=lambda path: path.as_posix().lower())
    if limit > 0:
        return paths[:limit]
    return paths


def _normalize_format_filter(formats: Optional[Iterable[str]]) -> set[str]:
    if formats is None:
        return set(SUPPORTED_PARITY_EXTENSIONS)
    normalized: set[str] = set()
    for value in formats:
        text = str(value or "").strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = f".{text}"
        if text in SUPPORTED_PARITY_EXTENSIONS:
            normalized.add(text)
    return normalized or set(SUPPORTED_PARITY_EXTENSIONS)


def python_mesh_summary(mesh: ParsedMesh) -> dict[str, Any]:
    submeshes = list(getattr(mesh, "submeshes", []) or [])
    return {
        "format": str(getattr(mesh, "format", "") or "").lower(),
        "submesh_count": len(submeshes),
        "vertex_count": sum(len(getattr(submesh, "vertices", []) or []) for submesh in submeshes),
        "face_count": sum(len(getattr(submesh, "faces", []) or []) for submesh in submeshes),
        "index_count": sum(len(getattr(submesh, "faces", []) or []) * 3 for submesh in submeshes),
        "has_uvs": bool(getattr(mesh, "has_uvs", False)),
        "has_bones": bool(getattr(mesh, "has_bones", False)),
        "submesh_names": [str(getattr(submesh, "name", "") or "") for submesh in submeshes],
        "materials": [str(getattr(submesh, "material", "") or "") for submesh in submeshes],
        "textures": [str(getattr(submesh, "texture", "") or "") for submesh in submeshes],
    }


def native_audit_summary(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "format": str(audit.get("format") or "").lower(),
        "layout": str(audit.get("layout") or audit.get("parser") or ""),
        "submesh_count": int(audit.get("submesh_count") or 0),
        "vertex_count": int(audit.get("vertex_count") or 0),
        "face_count": int(audit.get("face_count") or 0),
        "index_count": int(audit.get("index_count") or 0),
        "lod_count": int(audit.get("lod_count") or 0),
        "parity_ready": bool(audit.get("parity_ready", False)),
        "rebuild_supported": bool(audit.get("rebuild_supported", False)),
    }


def compare_mesh_summaries(python_summary: Mapping[str, Any], native_summary: Mapping[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key in ("format", "submesh_count", "vertex_count", "face_count", "index_count"):
        if python_summary.get(key) != native_summary.get(key):
            mismatches.append(f"{key}: python={python_summary.get(key)!r} native={native_summary.get(key)!r}")
    return mismatches


def check_mesh_native_audit_parity(path: Path) -> MeshNativeParityCase:
    path = Path(path)
    try:
        data = path.read_bytes()
    except Exception as exc:
        case = MeshNativeParityCase(path=str(path), format=path.suffix.lstrip(".").lower())
        case.status = "python_error"
        case.mismatches.append(str(exc))
        return case
    return check_mesh_native_bytes_parity(data, path.name, source_path=str(path))


def check_mesh_native_bytes_parity(data: bytes, filename: str, *, source_path: str = "") -> MeshNativeParityCase:
    case = MeshNativeParityCase(path=str(source_path or filename), format=Path(filename).suffix.lstrip(".").lower())
    try:
        parsed = parse_mesh(data, filename)
        case.python_summary = python_mesh_summary(parsed)
    except Exception as exc:
        case.status = "python_error"
        case.mismatches.append(str(exc))
        return case
    audit = audit_mesh_native(data, filename)
    if audit.get("status") != "ok":
        case.status = "native_error"
        case.native_summary = dict(audit)
        case.mismatches.append(str(audit.get("message") or audit.get("fallback_reason") or audit.get("status")))
        return case
    case.native_summary = native_audit_summary(audit)
    case.layout = str(case.native_summary.get("layout") or "")
    case.mismatches = compare_mesh_summaries(case.python_summary, case.native_summary)
    case.status = "ok" if not case.mismatches else "mismatch"
    return case


def run_mesh_native_parity_corpus(
    root: Path,
    *,
    limit: int = 0,
    formats: Optional[Iterable[str]] = None,
    enable_rebuild_for_layouts: Optional[Mapping[str, Iterable[str]]] = None,
) -> MeshNativeParityReport:
    allowed_formats = _normalize_format_filter(formats)
    paths = [path for path in discover_mesh_fixture_paths(root, limit=0) if path.suffix.lower() in allowed_formats]
    if limit > 0:
        paths = paths[:limit]
    cases = [check_mesh_native_audit_parity(path) for path in paths]
    enabled: dict[str, list[str]] = {}
    if cases and all(case.ok for case in cases):
        requested = enable_rebuild_for_layouts or {}
        for format_name, layouts in requested.items():
            format_key = str(format_name or "").lower()
            ok_layouts = {
                case.layout
                for case in cases
                if case.ok and case.format == format_key and case.layout
            }
            selected = sorted({str(layout or "") for layout in layouts if str(layout or "") in ok_layouts})
            if selected:
                enabled[format_key] = selected
    status = "ok" if cases and all(case.ok for case in cases) else "missing_fixtures" if not cases else "failed"
    return MeshNativeParityReport(status=status, root=str(Path(root).expanduser()), cases=cases, enabled_rebuild_layouts=enabled)


def run_mesh_native_archive_parity_corpus(
    package_root: Path,
    *,
    per_format_limit: int = 5,
    max_bytes_per_entry: int = 64 * 1024 * 1024,
    skip_python_empty: bool = True,
    formats: Optional[Iterable[str]] = None,
    enable_rebuild_for_layouts: Optional[Mapping[str, Iterable[str]]] = None,
) -> MeshNativeParityReport:
    from cdmw.core.archive import read_archive_entry_data
    from cdmw.core.archive_accelerator import scan_archive_entries_native

    package_root = Path(package_root).expanduser()
    entries = scan_archive_entries_native(package_root, timeout_seconds=300.0)
    if entries is None:
        return MeshNativeParityReport(status="archive_scan_unavailable", root=str(package_root), cases=[])
    allowed_formats = _normalize_format_filter(formats)
    selected_counts = {ext: 0 for ext in allowed_formats}
    cases: list[MeshNativeParityCase] = []
    for entry in entries:
        ext = Path(str(getattr(entry, "path", "") or "")).suffix.lower()
        if ext not in allowed_formats:
            continue
        if per_format_limit > 0 and selected_counts[ext] >= per_format_limit:
            continue
        if int(getattr(entry, "orig_size", 0) or 0) > max_bytes_per_entry:
            continue
        try:
            data, _decompressed, _note = read_archive_entry_data(entry)
        except Exception as exc:
            selected_counts[ext] += 1
            cases.append(
                MeshNativeParityCase(
                    path=str(getattr(entry, "path", "") or ""),
                    format=ext.lstrip("."),
                    status="archive_read_error",
                    mismatches=[str(exc)],
                )
            )
            continue
        case = check_mesh_native_bytes_parity(data, str(getattr(entry, "path", "") or f"entry{ext}"), source_path=str(getattr(entry, "path", "") or ""))
        if skip_python_empty and int(case.python_summary.get("face_count") or 0) <= 0:
            continue
        selected_counts[ext] += 1
        cases.append(case)
        if per_format_limit > 0 and all(count >= per_format_limit for count in selected_counts.values()):
            break
    enabled: dict[str, list[str]] = {}
    if cases and all(case.ok for case in cases):
        requested = enable_rebuild_for_layouts or {}
        for format_name, layouts in requested.items():
            format_key = str(format_name or "").lower()
            ok_layouts = {
                case.layout
                for case in cases
                if case.ok and case.format == format_key and case.layout
            }
            selected = sorted({str(layout or "") for layout in layouts if str(layout or "") in ok_layouts})
            if selected:
                enabled[format_key] = selected
    status = "ok" if cases and all(case.ok for case in cases) else "missing_fixtures" if not cases else "failed"
    return MeshNativeParityReport(status=status, root=str(package_root), cases=cases, enabled_rebuild_layouts=enabled)


def write_mesh_native_parity_report(report: MeshNativeParityReport, output_path: Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return output_path


__all__ = [
    "MeshNativeParityCase",
    "MeshNativeParityReport",
    "check_mesh_native_audit_parity",
    "check_mesh_native_bytes_parity",
    "discover_mesh_fixture_paths",
    "native_mesh_full_rebuild_parity_enabled",
    "native_mesh_rebuild_parity_enabled",
    "run_mesh_native_archive_parity_corpus",
    "run_mesh_native_parity_corpus",
    "write_mesh_native_parity_report",
]
