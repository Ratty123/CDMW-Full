from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.core.atomic_file import atomic_copy_file, atomic_write_bytes, atomic_write_text
from cdmw.modding.mesh_asset import mesh_asset_from_bytes, mesh_asset_to_inspect_dict
from cdmw.modding.mesh_exporter import export_obj
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_importer import rebuild_mesh_with_report
from cdmw.modding.mesh_obj_importer import import_obj, validate_obj_sidecar_source_identity
from cdmw.modding.mesh_roundtrip import (
    parse_allowed_difference,
    roundtrip_mesh_file,
    roundtrip_summary_lines,
)
from cdmw.services.mesh_service import MeshService


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mesh pipeline checks without opening the UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Parse a mesh and write MeshAsset inspection JSON.")
    inspect_parser.add_argument("asset", type=Path)
    inspect_parser.add_argument("--out", type=Path)

    export_parser = subparsers.add_parser("export", help="Export an editable GLB/OBJ package with MeshAsset sidecar metadata.")
    export_parser.add_argument("asset", type=Path)
    export_parser.add_argument("--out", type=Path, required=True)
    export_parser.add_argument("--name", default="mesh")
    export_parser.add_argument("--manifest", type=Path)

    import_parser = subparsers.add_parser("import", help="Import an edited GLB/OBJ package and write an import report.")
    import_parser.add_argument("asset", type=Path)
    import_parser.add_argument("edited", type=Path)
    import_parser.add_argument("--out", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate an edited GLB/OBJ package against the source asset.")
    validate_parser.add_argument("asset", type=Path)
    validate_parser.add_argument("edited", type=Path)
    validate_parser.add_argument("--report", type=Path, required=True)

    rebuild_parser = subparsers.add_parser("rebuild", help="Validate and rebuild a patched mesh asset from an edited package.")
    rebuild_parser.add_argument("asset", type=Path)
    rebuild_parser.add_argument("edited", type=Path)
    rebuild_parser.add_argument("--out", type=Path, required=True)
    rebuild_parser.add_argument("--report", type=Path, required=True)

    roundtrip_parser = subparsers.add_parser("roundtrip", help="Parse and rebuild a mesh with no edits.")
    roundtrip_parser.add_argument("asset", type=Path)
    roundtrip_parser.add_argument("--out", type=Path)
    roundtrip_parser.add_argument("--report", type=Path)
    roundtrip_parser.add_argument("--tolerant", action="store_true")
    roundtrip_parser.add_argument(
        "--allow-range",
        action="append",
        default=[],
        help="Inclusive allowed diff range, e.g. 0x10-0x1F:timestamp.",
    )

    args = parser.parse_args(argv)
    if args.command == "inspect":
        return _inspect(args.asset, args.out)
    if args.command == "export":
        return _export(args.asset, args.out, name=args.name, manifest_path=args.manifest)
    if args.command == "import":
        return _import(args.asset, args.edited, args.out)
    if args.command == "validate":
        report = _validate(args.asset, args.edited, args.report)
        return 0 if report.get("ok") is True else 1
    if args.command == "rebuild":
        return _rebuild(args.asset, args.edited, args.out, args.report)
    if args.command == "roundtrip":
        allowed = tuple(parse_allowed_difference(value) for value in args.allow_range)
        result = roundtrip_mesh_file(
            args.asset,
            output_path=args.out,
            report_path=args.report,
            strict=not (args.tolerant or allowed),
            allowed_differences=allowed,
        )
        for line in roundtrip_summary_lines(result.report):
            print(line)
        return 0 if result.report.get("result") == "PASS" else 1
    raise AssertionError(args.command)


def _inspect(asset_path: Path, out_path: Path | None) -> int:
    asset = mesh_asset_from_bytes(asset_path.read_bytes(), str(asset_path))
    payload = json.dumps(mesh_asset_to_inspect_dict(asset), indent=2)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, payload + "\n")
    else:
        print(payload)
    return 0


def _export(asset_path: Path, output_dir: Path, *, name: str, manifest_path: Path | None) -> int:
    service = MeshService()
    mesh = service.load_mesh_file(asset_path, run_roundtrip=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_paths = tuple(Path(path) for path in export_glb(mesh, str(output_dir), name or "mesh")) + tuple(
        Path(path) for path in export_obj(mesh, str(output_dir), name or "mesh")
    )
    glb_path = output_dir / f"{name or 'mesh'}.glb"
    obj_path = output_dir / f"{name or 'mesh'}.obj"
    sidecar_path = Path(f"{glb_path}.meta.json")
    cdmeta_path = output_dir / "mesh.cdmeta.json"
    original_hash_path = output_dir / "original_asset_hash.txt"
    if sidecar_path.is_file():
        atomic_copy_file(sidecar_path, cdmeta_path)
        sidecar = json.loads(cdmeta_path.read_text(encoding="utf-8"))
        atomic_write_text(original_hash_path, str(sidecar.get("source_asset_hash", "") or ""))
    manifest = {
        "format": "cdmw_mesh_pipeline_export_v1",
        "asset": str(asset_path),
        "package_dir": str(output_dir),
        "mesh": str(glb_path),
        "obj": str(obj_path),
        "metadata": str(cdmeta_path) if cdmeta_path.is_file() else "",
        "original_asset_hash": str(original_hash_path) if original_hash_path.is_file() else "",
        "files": [str(path) for path in exported_paths],
    }
    if manifest_path is not None:
        _write_json(manifest_path, manifest)
    print(f"Exported editable package: {output_dir}")
    return 0


def _import(asset_path: Path, edited_path: Path, output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = _validate(asset_path, edited_path, output_dir / "validation_report.json")
    try:
        edited_mesh = _load_edited_mesh(asset_path, edited_path)
        operations = tuple(getattr(edited_mesh, "_cdmw_edit_operations", ()) or ())
    except Exception:
        operations = ()
    payload = {
        "format": "cdmw_mesh_pipeline_import_v1",
        "asset": str(asset_path),
        "edited": str(_editable_mesh_path(edited_path)),
        "ok": report.get("ok") is True,
        "validation_report": "validation_report.json",
        "edit_operations": "edit_operations.json" if operations else "",
    }
    if operations:
        _write_json(output_dir / "edit_operations.json", {"operations": list(operations)})
    _write_json(output_dir / "import_report.json", payload)
    print(f"Imported editable package: {output_dir}")
    return 0 if payload["ok"] else 1


def _validate(asset_path: Path, edited_path: Path, report_path: Path) -> dict[str, object]:
    original_data = asset_path.read_bytes()
    try:
        service = MeshService()
        original_mesh = service.load_mesh_file(asset_path, run_roundtrip=True)
        view = service.open_edit_session(original_mesh, session_id="mesh-pipeline-validate", mode="edit")
        edited_mesh = _load_edited_mesh(asset_path, edited_path)
        validate_obj_sidecar_source_identity(edited_mesh, original_data)
        updated = service.replace_working_mesh(view.session_id, edited_mesh)
        report = _validation_report_payload(service.validate_export(updated.session_id))
    except Exception as exc:
        report = _blocked_report(asset_path, edited_path, exc)
    _write_json(report_path, report)
    for issue in report.get("issues", ()):
        if isinstance(issue, dict) and issue.get("can_continue") is False:
            print(f"BLOCKED {issue.get('code')}: {issue.get('message')}")
    if report.get("ok") is True:
        print("Validation: PASS")
    return report


def _rebuild(asset_path: Path, edited_path: Path, output_path: Path, report_path: Path) -> int:
    original_data = asset_path.read_bytes()
    service = MeshService()
    original_mesh = service.load_mesh_file(asset_path, run_roundtrip=True)
    view = service.open_edit_session(original_mesh, session_id="mesh-pipeline-rebuild", mode="edit")
    edited_mesh = _load_edited_mesh(asset_path, edited_path)
    validate_obj_sidecar_source_identity(edited_mesh, original_data)
    updated = service.replace_working_mesh(view.session_id, edited_mesh)
    validation = service.validate_export(updated.session_id)
    if not validation.ok:
        _write_json(report_path, _validation_report_payload(validation))
        for issue in validation.blockers[:6]:
            print(f"BLOCKED {issue.code}: {issue.message}")
        return 1
    working_mesh = service.working_mesh(updated.session_id)
    result = rebuild_mesh_with_report(
        working_mesh,
        original_data,
        validation_status="passed",
        output_path=str(output_path),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(output_path, result.data)
    _write_json(report_path, asdict(result.report))
    print(f"Rebuild: {'byte-identical' if result.report.byte_identical else 'changed'}")
    return 0


def _load_edited_mesh(asset_path: Path, edited_path: Path):
    mesh_path = _editable_mesh_path(edited_path)
    _ensure_cdmeta_sidecar_alias(mesh_path)
    mesh = import_glb_with_sidecar(mesh_path) if mesh_path.suffix.lower() == ".glb" else import_obj(str(mesh_path))
    if not str(getattr(mesh, "path", "") or "").strip():
        mesh.path = str(asset_path)
    if not str(getattr(mesh, "format", "") or "").strip():
        mesh.format = asset_path.suffix.lstrip(".").lower()
    return mesh


def _editable_mesh_path(path: Path) -> Path:
    if path.is_dir():
        for name in ("mesh.glb", "edited_mesh.glb", "edited.glb", "mesh.obj", "edited_mesh.obj", "edited.obj"):
            candidate = path / name
            if candidate.is_file():
                return candidate
    return path


def _ensure_cdmeta_sidecar_alias(mesh_path: Path) -> None:
    sidecar_path = Path(f"{mesh_path}.meta.json")
    if sidecar_path.is_file():
        return
    cdmeta_path = mesh_path.parent / "mesh.cdmeta.json"
    if cdmeta_path.is_file():
        atomic_copy_file(cdmeta_path, sidecar_path)


def _validation_report_payload(report) -> dict[str, object]:
    issues = [
        {
            "severity": _public_validation_severity(issue.severity),
            "code": issue.code,
            "message": issue.message,
            "category": issue.category,
            "expected": getattr(issue, "expected", None),
            "actual": getattr(issue, "actual", None),
            "lod_index": getattr(issue, "lod_index", -1),
            "submesh_index": issue.submesh_index,
            "vertex_index": issue.vertex_index,
            "face_index": issue.face_index,
            "can_continue": issue.severity != "blocker",
        }
        for issue in report.issues
    ]
    return {
        "format": "cdmw_mesh_pipeline_validation_v1",
        "ok": report.ok,
        "mesh_format": report.mesh_format,
        "submesh_count": report.submesh_count,
        "vertex_count": report.vertex_count,
        "face_count": report.face_count,
        "parse_confidence": report.parse_confidence,
        "source_asset_hash": report.source_asset_hash,
        "no_op_roundtrip_status": report.no_op_roundtrip_status,
        "no_op_byte_identical": report.no_op_byte_identical,
        "no_op_unexpected_differences": report.no_op_unexpected_differences,
        "issues": issues,
        "blocker_count": len(report.blockers),
        "warning_count": len(report.warnings),
    }


def _blocked_report(asset_path: Path, edited_path: Path, exc: Exception) -> dict[str, object]:
    return {
        "format": "cdmw_mesh_pipeline_validation_v1",
        "ok": False,
        "mesh_format": asset_path.suffix.lstrip(".").lower(),
        "submesh_count": 0,
        "vertex_count": 0,
        "face_count": 0,
        "parse_confidence": "",
        "source_asset_hash": "",
        "no_op_roundtrip_status": "",
        "no_op_byte_identical": None,
        "no_op_unexpected_differences": 0,
        "issues": [
            {
                "severity": "fatal",
                "code": "import_failed",
                "message": str(exc),
                "category": "import",
                "expected": "valid edited mesh package",
                "actual": str(exc),
                "lod_index": -1,
                "submesh_index": -1,
                "vertex_index": -1,
                "face_index": -1,
                "can_continue": False,
            }
        ],
        "blocker_count": 1,
        "warning_count": 0,
        "asset": str(asset_path),
        "edited": str(edited_path),
    }


def _public_validation_severity(severity: object) -> str:
    raw = str(severity or "").strip().lower()
    if raw == "blocker":
        return "error"
    return raw if raw in {"info", "warning", "error", "fatal"} else "error"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
