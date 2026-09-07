"""Promote an immutable direct preview without repeating material preparation."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_text
from cdmw.services.mesh_rust_preview_files import (
    atomic_preview_publication,
    validate_preview_files,
)


def _resource_names(value: object) -> set[str]:
    names: set[str] = set()

    def visit(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, dict):
            if {"path", "sha256", "byte_length", "data_type"} <= item.keys():
                names.add(str(item["path"]))
            else:
                for child in item.values():
                    visit(child)

    visit(value)
    return names


@atomic_preview_publication
def promote_rust_preview_package_from_preview_core(
    direct_package,
    preview_core_package_dir,
    *,
    source_manifest,
    output_package_dir,
    cancelled=None,
):
    """Copy verified direct resources, then add the source's full layer graph.

    The caller holds the direct package's cache lease for this entire operation.
    Neither that package nor its source manifest is modified.
    """

    from cdmw.services.mesh_rust_authoring import _session_root_identity
    from cdmw.services.mesh_rust_preview_package import (
        _build_preview_core_material_graph,
        _cancelled,
        _read_preview_manifest,
        _texture_status,
        _validated_preview_core_source,
    )

    _cancelled(cancelled)
    source_package, native, *_ = _validated_preview_core_source(
        preview_core_package_dir, source_manifest
    )
    direct_root, manifest = _read_preview_manifest(direct_package.manifest_path)
    if (
        manifest.get("texture_status", {}).get("quality") != "direct"
        or manifest.get("source", {}).get("path") != native.get("source_path", "")
        or manifest.get("source", {}).get("sha256", "")
        != str(native.get("source_sha256", "") or "").strip().upper()
        or manifest.get("material_contract", {}).get("conservation")
        != native.get("material_conservation")
    ):
        raise ValueError("Direct preview does not match the material source.")
    validate_preview_files(direct_root, manifest)
    package_dir = Path(output_package_dir)
    package_dir.mkdir(parents=True, exist_ok=False)
    root_identity = _session_root_identity(package_dir)
    for name in sorted(_resource_names(manifest)):
        _cancelled(cancelled)
        target = package_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(direct_root / name, target)
    # Verify the copies as well, including a source changed during the copy.
    validate_preview_files(package_dir, manifest)
    manifest["preview_core_material_graph"] = _build_preview_core_material_graph(
        source_package,
        package_dir,
        native["batches"],
        quality="full",
        textures=manifest["textures"],
        expected_root_identity=root_identity,
        cancelled=cancelled,
    )
    manifest["texture_status"] = _texture_status(manifest["textures"], "full")
    session_id = uuid4().hex
    manifest["session_id"] = session_id
    manifest["state"]["preview_scene"]["session_id"] = session_id
    _cancelled(cancelled)
    atomic_write_text(
        package_dir / "manifest.json",
        json.dumps(manifest, separators=(",", ":"), sort_keys=True),
    )
    return replace(
        direct_package,
        package_dir=package_dir,
        manifest_path=package_dir / "manifest.json",
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        scene_session_id=session_id,
    )
