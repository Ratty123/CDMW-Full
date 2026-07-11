from __future__ import annotations

from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from typing import Mapping

from PySide6.QtWidgets import QTabWidget

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


def _native_update_has_payload(update: object) -> bool:
    if not isinstance(update, _tab.MeshEditorNativeUpdate):
        return False
    return bool(
        update.vertex_groups
        or update.triangle_groups
        or update.triangle_source_submesh_indices
        or update.selection_groups
        or update.refresh_selection
        or update.material_override_groups
        or update.replace_all_triangles
    )
def _mesh_edit_result_with_metric(result: object, key: str, elapsed_ms: float) -> object:
    if not isinstance(result, _tab.MeshEditResult):
        return result
    metrics: dict[str, float] = {}
    for raw_key, raw_value in dict(result.metrics or {}).items():
        try:
            metrics[str(raw_key)] = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
    metrics[str(key)] = max(0.0, float(elapsed_ms))
    return replace(result, metrics=metrics)
def _rebuild_report_json_payload(report: object) -> dict[str, object]:
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        payload = {
            key: getattr(report, key)
            for key in (
                "mesh_format",
                "source_asset_hash",
                "rebuilt_asset_hash",
                "source_size",
                "rebuilt_size",
                "parse_confidence",
                "validation_status",
                "byte_identical",
                "changed_byte_ranges",
                "edited_lods",
                "edited_submeshes",
                "changed_channels",
                "recomputed_fields",
                "warnings",
                "developer_overrides",
                "edit_operations",
                "output_path",
            )
            if hasattr(report, key)
        }
    payload["changed_range_count"] = int(
        getattr(report, "changed_range_count", len(tuple(payload.get("changed_byte_ranges", ()) or ()))) or 0
    )
    return {str(key): _json_safe_report_value(value) for key, value in payload.items()}
def _validation_report_json_payload(report: object) -> dict[str, object]:
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        payload = {
            key: getattr(report, key)
            for key in (
                "mesh_format",
                "submesh_count",
                "vertex_count",
                "face_count",
                "issues",
                "parse_confidence",
                "source_asset_hash",
                "no_op_roundtrip_status",
                "no_op_byte_identical",
                "no_op_unexpected_differences",
            )
            if hasattr(report, key)
        }
    blockers = tuple(getattr(report, "blockers", ()) or ())
    warnings = tuple(getattr(report, "warnings", ()) or ())
    payload["ok"] = bool(getattr(report, "ok", not blockers))
    payload["blocker_count"] = len(blockers)
    payload["warning_count"] = len(warnings)
    result = {str(key): _json_safe_report_value(value) for key, value in payload.items()}
    issues = result.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and "severity" in issue:
                issue["severity"] = _public_validation_severity(issue.get("severity"))
                issue.setdefault("can_continue", issue["severity"] not in {"error", "fatal"})
                issue.setdefault("expected", None)
                issue.setdefault("actual", None)
                issue.setdefault("lod_index", -1)
                issue.setdefault("submesh_index", -1)
    return result
def _public_validation_severity(severity: object) -> str:
    raw = str(severity or "").strip().lower()
    if raw == "blocker":
        return "error"
    return raw if raw in {"info", "warning", "error", "fatal"} else "error"
def _json_safe_report_value(value: object) -> object:
    if is_dataclass(value):
        return _json_safe_report_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe_report_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe_report_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
def _mesh_editor_texture_binding_target(value: object) -> tuple[str, int]:
    parts = str(value or "").split(":", 2)
    if len(parts) < 2:
        return "", -1
    try:
        submesh_index = int(parts[1])
    except (TypeError, ValueError):
        submesh_index = -1
    return str(parts[0] or ""), submesh_index
def _mesh_editor_tab_index(tabs: QTabWidget, title: str) -> int:
    normalized = str(title or "").strip().lower()
    for index in range(tabs.count()):
        if tabs.tabText(index).strip().lower() == normalized:
            return index
    return -1
