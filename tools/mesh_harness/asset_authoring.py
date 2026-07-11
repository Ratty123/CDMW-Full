from __future__ import annotations

from cdmw.services.asset_authoring_service import ASSET_AUTHORING_MESH_HEALTH_SCHEMA
from cdmw.services.asset_authoring_service import ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA
from cdmw.services.asset_authoring_service import ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA
from cdmw.services.asset_authoring_service import ASSET_AUTHORING_TANGENT_REPORT_SCHEMA
from cdmw.services.asset_authoring_service import ASSET_AUTHORING_UV_REPORT_SCHEMA
from cdmw.services.asset_authoring_service import AssetAuthoringService
from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService
from pathlib import Path
from cdmw.services.asset_authoring_service import asset_authoring_discovery_report
import json

from tools.mesh_harness.fixtures import (
    build_synthetic_mesh,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
)

def run_asset_authoring_discovery(output_dir: Path) -> dict[str, object]:
    report = asset_authoring_discovery_report()
    report_path = output_dir / "asset_authoring_discovery.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    helpers = report.get("helpers", {})
    helper_count = len(helpers) if isinstance(helpers, Mapping) else 0
    return {
        "ok": bool(report.get("status") == "ok" and helper_count),
        "report_path": str(report_path),
        "helper_count": helper_count,
        "unavailable_helpers": [
            str(key)
            for key, value in (helpers.items() if isinstance(helpers, Mapping) else ())
            if isinstance(value, Mapping) and value.get("status") != "available"
        ],
    }

def run_asset_authoring_mesh_health(output_dir: Path) -> dict[str, object]:
    original_mesh = build_synthetic_mesh()
    edited_mesh = build_synthetic_mesh()
    submesh = edited_mesh.submeshes[0]
    submesh.vertices.extend([submesh.vertices[1], (2.0, 2.0, 2.0)])
    submesh.faces.extend([(0, 0, 1), (0, 1, 99), (0, 1, 2)])
    submesh.vertex_count = len(submesh.vertices)
    submesh.face_count = len(submesh.faces)
    edited_mesh.total_vertices = len(submesh.vertices)
    edited_mesh.total_faces = len(submesh.faces)

    authoring = AssetAuthoringService()
    report = authoring.mesh_health_report(edited_mesh, original_mesh=original_mesh)
    optimization_report = authoring.mesh_optimization_report(
        edited_mesh,
        original_mesh=original_mesh,
        simplify_ratio=0.5,
        target_error=0.02,
    )
    report_path = output_dir / "asset_authoring_mesh_health.json"
    optimization_path = output_dir / "asset_authoring_mesh_optimization.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    optimization_path.write_text(json.dumps(optimization_report, indent=2, sort_keys=True), encoding="utf-8")
    totals = report.get("totals", {})
    topology = report.get("topology", {})
    topology_changed = isinstance(topology, Mapping) and bool(topology.get("topology_changed"))
    return {
        "ok": bool(
            report.get("schema") == ASSET_AUTHORING_MESH_HEALTH_SCHEMA
            and isinstance(totals, Mapping)
            and int(totals.get("duplicate_vertices", 0) or 0) >= 1
            and int(totals.get("degenerate_faces", 0) or 0) >= 1
            and int(totals.get("invalid_indices", 0) or 0) >= 1
            and topology_changed
            and optimization_report.get("schema") == ASSET_AUTHORING_MESH_OPTIMIZATION_SCHEMA
            and not bool(optimization_report.get("mutates", True))
        ),
        "report_path": str(report_path),
        "optimization_report_path": str(optimization_path),
        "totals": totals,
        "topology_changed": topology_changed,
        "optimization_status": str(optimization_report.get("status") or ""),
    }

def run_asset_authoring_uv_report(output_dir: Path) -> dict[str, object]:
    mesh = build_synthetic_mesh()
    report = AssetAuthoringService().uv_authoring_report(mesh, atlas_size=(1024, 1024), include_native_unwrap=True)
    report_path = output_dir / "asset_authoring_uv_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    bounds = report.get("uv_bounds", {})
    native_unwrap = report.get("native_unwrap", {})
    return {
        "ok": bool(
            report.get("schema") == ASSET_AUTHORING_UV_REPORT_SCHEMA
            and int(report.get("island_count", 0) or 0) >= 1
            and isinstance(bounds, Mapping)
            and bool(bounds.get("available"))
        ),
        "report_path": str(report_path),
        "island_count": int(report.get("island_count", 0) or 0),
        "native_unwrap_status": native_unwrap.get("status") if isinstance(native_unwrap, Mapping) else "",
        "uv_bounds": bounds,
    }

def run_asset_authoring_tangent_report(output_dir: Path) -> dict[str, object]:
    original_mesh = build_synthetic_mesh()
    working_mesh = build_synthetic_mesh()
    authoring = AssetAuthoringService()
    before = authoring.tangent_authoring_report(original_mesh)
    service = MeshService()
    view = service.open_edit_session(working_mesh, session_id="asset-authoring-tangent-report", mode="edit")
    try:
        command = service.apply_command(
            view.session_id,
            MeshEditCommand(
                "generate_tangents",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
            ),
        )
        after = authoring.tangent_authoring_report(
            service.working_mesh(view.session_id),
            original_mesh=original_mesh,
        )
    finally:
        service.close_edit_session(view.session_id)

    report = {
        **after,
        "operation": "generate_tangents",
        "command": _command_summary(command),
        "before": before,
        "mutates_archives": False,
    }
    report_path = output_dir / "asset_authoring_tangent_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    totals = report.get("totals", {})
    before_totals = before.get("totals", {})
    return {
        "ok": bool(
            report.get("schema") == ASSET_AUTHORING_TANGENT_REPORT_SCHEMA
            and command.ok
            and isinstance(totals, Mapping)
            and int(totals.get("complete_tangent_parts", 0) or 0) >= 1
            and isinstance(before_totals, Mapping)
            and int(before_totals.get("missing_tangent_parts", 0) or 0) >= 1
        ),
        "report_path": str(report_path),
        "complete_tangent_parts": (
            int(totals.get("complete_tangent_parts", 0) or 0) if isinstance(totals, Mapping) else 0
        ),
        "missing_before_parts": (
            int(before_totals.get("missing_tangent_parts", 0) or 0) if isinstance(before_totals, Mapping) else 0
        ),
    }

def run_asset_authoring_openimageio_report(output_dir: Path) -> dict[str, object]:
    source = output_dir / "openimageio_source.tga"
    source.write_bytes(b"source image placeholder")
    converted = output_dir / "openimageio_source.png"
    helper = output_dir / "missing-oiiotool.exe"
    service = AssetAuthoringService()
    configured_paths = {"openimageio": helper}
    report = {
        **service.openimageio_source_report(source, configured_paths),
        "metadata_command": service.openimageio_metadata_command(source, configured_paths),
        "convert_command": service.openimageio_convert_command(source, converted, configured_paths),
        "diff_command": service.openimageio_diff_command(source, converted, configured_paths),
    }
    report_path = output_dir / "asset_authoring_openimageio_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "ok": bool(
            report.get("schema") == ASSET_AUTHORING_SOURCE_IMAGE_SCHEMA
            and report.get("status") == "helper_unavailable"
            and bool(report.get("openimageio_source_candidate"))
            and not bool(report.get("can_convert"))
        ),
        "report_path": str(report_path),
        "source_path": str(source),
        "status": str(report.get("status", "")),
    }
