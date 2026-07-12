"""Editable-package metadata readback checks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from cdmw.modding.mesh_exporter import _roundtrip_manifest_extra_payload
from cdmw.modding.mesh_parser import ParsedMesh


_REFERENCE_KEYS = (
    "source_asset_hash",
    "source_asset_size",
    "asset_id",
    "parse_confidence",
    "material_slots",
    "unknown_sections",
    "import_rules",
    "rules",
    "allowed_edit_operations",
)


def _load_sidecar(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"editable package metadata readback failed: {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"editable package metadata readback failed: {path.name} is not an object")
    return payload


def _require_contract(
    sidecars: tuple[Mapping[str, object], ...],
    expected: Mapping[str, object],
    key: str,
    label: str,
) -> None:
    expected_value = expected.get(key)
    if any(sidecar.get(key) != expected_value for sidecar in sidecars):
        raise RuntimeError(f"editable package {label} readback mismatch: {key}")


def readback_editable_package_metadata(
    staging_dir: Path,
    name: str,
    mesh: ParsedMesh,
) -> dict[str, object]:
    """Validate both editable sidecars against the mesh contract just exported."""

    sidecars = tuple(
        _load_sidecar(staging_dir / f"{name}{suffix}.meta.json")
        for suffix in (".glb", ".obj")
    )
    expected = _roundtrip_manifest_extra_payload(mesh, None)

    _require_contract(sidecars, expected, "lods", "draw-section lineage")
    _require_contract(sidecars, expected, "skeleton_info", "rig/skinning")
    for key in _REFERENCE_KEYS:
        _require_contract(sidecars, expected, key, "reference metadata")
    for sidecar in sidecars:
        if str(sidecar.get("source_path", "") or "") != str(mesh.path or ""):
            raise RuntimeError("editable package reference metadata readback mismatch: source_path")
        if str(sidecar.get("source_format", "") or "") != str(mesh.format or ""):
            raise RuntimeError("editable package reference metadata readback mismatch: source_format")

    lods = tuple(expected.get("lods", ()) or ())
    draw_sections = tuple(
        submesh
        for lod in lods
        if isinstance(lod, Mapping)
        for submesh in tuple(lod.get("submeshes", ()) or ())
        if isinstance(submesh, Mapping)
    )
    skeleton = expected.get("skeleton_info", {})
    skeleton = skeleton if isinstance(skeleton, Mapping) else {}
    return {
        "draw_section_lineage_readback": "passed",
        "draw_section_count": len(draw_sections),
        "draw_section_stable_ids": [str(row.get("stable_id", "") or "") for row in draw_sections],
        "rig_skinning_readback": "passed",
        "skinned": bool(skeleton.get("skinned")),
        "weighted_vertex_count": int(skeleton.get("weighted_vertex_count", 0) or 0),
        "reference_metadata_readback": "passed",
        "source_asset_hash": str(expected.get("source_asset_hash", "") or ""),
        "material_slot_count": len(tuple(expected.get("material_slots", ()) or ())),
        "sidecar_count": len(sidecars),
    }


__all__ = ["readback_editable_package_metadata"]
