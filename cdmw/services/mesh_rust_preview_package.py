"""Bounded viewport-only packages for the resident Rust Archive Preview.

The package deliberately reuses the same PAC/PAC_XML material preparation as
the Rust Mesh Editor.  It contains renderer-ready geometry, original DDS
payloads and material ownership, but no editable output directory or Vortice
handoff files.
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from cdmw.core.atomic_file import atomic_write_text
from cdmw.domain.cancellation import RunCancelled
from cdmw.modding.mesh_deformer import clone_mesh_for_editing
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.static_mesh_scene_frame import (
    StaticMeshSceneFrame,
    StaticSceneRoleFrame,
    StaticWorldBounds,
    build_authoritative_static_scene_frame,
    static_scene_source_identity,
)
from cdmw.modding.static_mesh_types import StaticReplacementTransform
from cdmw.services.mesh_rust_authoring import (
    _RustMaterialSynthesisState,
    _atomic_write_payload,
    _encode_rust_preview_dds,
    _mesh_channel_payload,
    _mesh_document_payload,
    _mesh_lods,
    _mesh_material_presentations,
    _mesh_texture_payloads,
    _session_root_identity,
    _source_hash,
)
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_RENDERER,
    RUST_PREVIEW_BACKEND,
    RUST_PREVIEW_PACKAGE,
    RUST_PREVIEW_PROTOCOL,
)


@dataclass(frozen=True, slots=True)
class RustPreviewPackage:
    package_dir: Path
    manifest_path: Path
    status_path: Path
    output_dir: Path
    edit_operations_path: Path
    material_signature: str = ""
    scene_frame: StaticMeshSceneFrame | None = None
    scene_session_id: str = ""
    editable_submesh_count: int = 0
    reference_submesh_count: int = 0
    runtime_output_external: bool = False


class _CancellationView:
    """The Rust material builder only needs Event.is_set().

    Adapting the caller's cancellation callback keeps long PAC/PAC_XML material
    synthesis cancellable without owning a second polling thread.
    """

    def __init__(self, callback: Callable[[], bool] | None) -> None:
        self._callback = callback

    def is_set(self) -> bool:
        return bool(self._callback is not None and self._callback())


_PREVIEW_IMAGE_TEXTURES = (
    ("base", "preview_texture_dds_path", ("preview_texture_path", "texture")),
    (
        "normal",
        "preview_normal_texture_dds_path",
        ("preview_normal_texture_path",),
    ),
    (
        "material",
        "preview_material_texture_dds_path",
        ("preview_material_texture_path",),
    ),
    (
        "height",
        "preview_height_texture_dds_path",
        ("preview_height_texture_path",),
    ),
    (
        "emissive",
        "preview_emissive_texture_dds_path",
        ("preview_emissive_texture_path",),
    ),
)


def _existing_preview_image(source: object, attributes: Sequence[str]) -> Path | None:
    for attribute in attributes:
        value = str(getattr(source, attribute, "") or "").strip()
        if not value:
            continue
        try:
            path = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.is_file() and path.suffix.casefold() in {
            ".bmp",
            ".gif",
            ".jpeg",
            ".jpg",
            ".png",
            ".tga",
            ".tif",
            ".tiff",
            ".webp",
        }:
            return path
    return None


def _encode_non_dds_preview_textures(
    mesh: ParsedMesh,
    staging_root: Path,
    stop_event: _CancellationView,
    synthesis: _RustMaterialSynthesisState,
) -> dict[tuple[int, int, str], Path]:
    """Convert external-model images to owned DDS while preserving PAC DDS unchanged."""

    overrides: dict[tuple[int, int, str], Path] = {}
    for lod_index, submeshes in enumerate(_mesh_lods(mesh)):
        for submesh_index, submesh in enumerate(submeshes):
            for role, dds_attribute, image_attributes in _PREVIEW_IMAGE_TEXTURES:
                declared_dds = str(getattr(submesh, dds_attribute, "") or "").strip()
                if declared_dds:
                    try:
                        dds_path = Path(declared_dds).expanduser().resolve(strict=True)
                    except (OSError, RuntimeError):
                        dds_path = None
                    if dds_path is not None and dds_path.is_file():
                        continue
                image_path = _existing_preview_image(submesh, image_attributes)
                if image_path is None:
                    continue
                target = staging_root / (
                    f"lod-{lod_index:04d}-material-{submesh_index:04d}-{role}.dds"
                )
                _encode_rust_preview_dds(
                    image_path,
                    target,
                    role,
                    stop_event,  # type: ignore[arg-type]
                    synthesis,
                )
                setattr(submesh, dds_attribute, str(target))
                overrides[
                    (lod_index, submesh_index, "base_color" if role == "base" else role)
                ] = target
    return overrides


def _scene_mesh(mesh: ParsedMesh, reference_mesh: ParsedMesh | None) -> ParsedMesh:
    from cdmw.modding.mesh_edit_ops import refresh_mesh_totals

    scene = clone_mesh_for_editing(mesh)
    if reference_mesh is not None:
        reference = clone_mesh_for_editing(reference_mesh)
        for index, submesh in enumerate(reference.submeshes):
            submesh.name = f"original_reference_{index}_{submesh.name or 'part'}"
        scene.submeshes.extend(reference.submeshes)
    refresh_mesh_totals(scene)
    return scene


def _part_identities(mesh: ParsedMesh) -> list[dict[str, object]]:
    return [
        {
            "scene_submesh_index": index,
            "source_submesh_index": int(
                getattr(submesh, "source_submesh_index", index) or index
            ),
            "name": str(getattr(submesh, "name", "") or f"Part {index + 1}"),
            "material": str(getattr(submesh, "material", "") or ""),
        }
        for index, submesh in enumerate(tuple(getattr(mesh, "submeshes", ()) or ()))
    ]


def _cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise RunCancelled("Rust preview package preparation cancelled.")


def build_rust_preview_package(
    mesh: ParsedMesh,
    *,
    output_root: Path | str | None = None,
    output_package_dir: Path | str | None = None,
    reference_mesh: ParsedMesh | None = None,
    comparison_mode: str = "replacement_only",
    reference_draw: str = "wire",
    interaction_profile: str = "read_only",
    interaction_mode: str | None = None,
    scene_transform: StaticReplacementTransform | None = None,
    scene_generation: int = 1,
    scene_session_id: str = "",
    selection_pivot_source: tuple[float, float, float] | None = None,
    preview_overlays: Mapping[str, object] | None = None,
    effects_overlay: Mapping[str, object] | None = None,
    framing_bounds: tuple[Sequence[float], Sequence[float]] | None = None,
    material_package_path: Path | str | None = None,
    include_material_resources: bool = True,
    theme: Mapping[str, object] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> RustPreviewPackage:
    """Publish one immutable Rust preview package.

    ``static_replacement`` is the only profile allowed to advertise preview
    mesh-edit input.  Both profiles remain read-only with respect to PAMT/PAZ.
    """

    profile = str(interaction_profile or "read_only").strip().lower()
    if profile not in {"read_only", "static_replacement"}:
        raise ValueError(f"Unsupported Rust preview interaction profile: {profile}")
    mode = str(
        interaction_mode
        or ("mesh_edit" if profile == "static_replacement" else "preview")
    ).strip().lower()
    if mode not in {"preview", "placement", "mesh_edit"}:
        raise ValueError(f"Unsupported Rust preview interaction mode: {mode}")
    _cancelled(cancelled)
    root = (
        Path(output_root)
        if output_root is not None
        else Path(tempfile.gettempdir()) / "cdmw_rust_preview"
    )
    package_dir = (
        Path(output_package_dir)
        if output_package_dir is not None
        else root / f"package_{int(time.time() * 1000)}_{uuid4().hex[:8]}"
    )
    package_dir.mkdir(parents=True, exist_ok=False)
    root_identity = _session_root_identity(package_dir)

    scene = _scene_mesh(mesh, reference_mesh)
    editable_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
    reference_count = len(tuple(getattr(reference_mesh, "submeshes", ()) or ())) if reference_mesh else 0
    target = reference_mesh if reference_mesh is not None else mesh
    frame = build_authoritative_static_scene_frame(
        target,
        mesh,
        scene_transform
        or StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
        source_identity=static_scene_source_identity(mesh, reference_mesh),
        scene_generation=max(1, int(scene_generation)),
        comparison_mode=str(comparison_mode or "replacement_only"),
        interaction_mode=mode,
        reference_draw=str(reference_draw or "wire"),
        selection_pivot_source=selection_pivot_source,
        cancelled=cancelled,
    )
    if reference_mesh is None:
        empty = StaticWorldBounds((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        frame = replace(
            frame,
            reference=StaticSceneRoleFrame(
                role="reference",
                model_matrix=frame.reference.model_matrix,
                world_bounds=empty,
                visible=False,
                submesh_indices=(),
            ),
            framing_bounds=frame.editable.world_bounds,
            framing_extent=max(0.01, frame.editable.world_bounds.extent),
        )
    _cancelled(cancelled)
    document = _atomic_write_payload(
        package_dir,
        "document.json",
        _mesh_document_payload(scene, allow_preview_formats=True),
        data_type="mesh_document_json",
        element_count=sum(len(level) for level in _mesh_lods(scene)),
        expected_root_identity=root_identity,
    )
    channels = _atomic_write_payload(
        package_dir,
        "channels.json",
        _mesh_channel_payload(scene),
        data_type="mesh_channels_compact_json",
        element_count=sum(
            len(tuple(getattr(submesh, "vertices", ()) or ()))
            for level in _mesh_lods(scene)
            for submesh in level
        ),
        expected_root_identity=root_identity,
    )
    synthesis = _RustMaterialSynthesisState()
    stop_event = _CancellationView(cancelled)
    if include_material_resources:
        with tempfile.TemporaryDirectory(
            prefix="cdmw-rust-preview-images-",
            dir=package_dir.parent,
        ) as preview_image_staging:
            image_overrides = _encode_non_dds_preview_textures(
                scene,
                Path(preview_image_staging),
                stop_event,
                synthesis,
            )
            textures = _mesh_texture_payloads(
                package_dir,
                scene,
                expected_root_identity=root_identity,
                stop_event=stop_event,  # type: ignore[arg-type]
                synthesis_state=synthesis,
                material_package_path=material_package_path or "",
                preview_texture_overrides=image_overrides,
            )
    else:
        textures = []
    presentations = _mesh_material_presentations(
        scene,
        generated_overrides=synthesis.presentation_overrides,
    )
    _cancelled(cancelled)
    session_id = str(scene_session_id or uuid4().hex)
    scene_payload = frame.to_protocol_payload()
    if framing_bounds is not None:
        low, high = framing_bounds
        minimum = [float(low[index]) for index in range(3)]
        maximum = [float(high[index]) for index in range(3)]
        bounds = {
            "min": minimum,
            "max": maximum,
            "center": [
                (minimum[index] + maximum[index]) * 0.5 for index in range(3)
            ],
        }
        extent = max(
            0.01,
            max(maximum[index] - minimum[index] for index in range(3)),
        )
        scene_payload["bounds"] = bounds
        scene_payload["framing"] = {"bounds": bounds, "extent": extent}
        grid = scene_payload.get("grid")
        if isinstance(grid, dict):
            grid["spacing"] = max(extent / 10.0, 0.01)
    scene_payload.update(
        {
            "renderer_authority": "rust_wgpu_resident_scene",
            "session_id": session_id,
            "part_identities": _part_identities(scene),
        }
    )
    overlays = preview_overlays or getattr(mesh, "cdmw_preview_overlays", None)
    if isinstance(overlays, Mapping):
        for source, target_key in (("skeleton", "skeleton_overlay"), ("cloth", "cloth_overlay"), ("effects", "effects_overlay")):
            value = overlays.get(source)
            if isinstance(value, Mapping):
                scene_payload[target_key] = dict(value)
    if isinstance(effects_overlay, Mapping):
        scene_payload["effects_overlay"] = dict(effects_overlay)
    manifest = {
        "schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL,
        "session_id": session_id,
        "process_generation": 1,
        "base_revision": 0,
        "shadow_revision": 0,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_PREVIEW_BACKEND,
        "interaction_profile": profile,
        "document": document,
        "channels": channels,
        "textures": textures,
        "material_presentations": presentations,
        "texture_status": {
            "available": bool(textures),
            "resource_count": len(textures),
            "reason": "" if textures else "No readable DDS preview textures were resolved.",
        },
        "source": {
            "path": str(getattr(mesh, "path", "") or ""),
            "format": str(getattr(mesh, "format", "") or ""),
            "sha256": _source_hash(mesh),
            "lod_index": 0,
        },
        "output_policy": {"policy": "read_only_preview", "archive_writes": False},
        "theme": dict(theme or {}),
        "state": {"preview_scene": scene_payload},
    }
    manifest_path = package_dir / "manifest.json"
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))
    return RustPreviewPackage(
        package_dir=package_dir,
        manifest_path=manifest_path,
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        material_signature=_source_hash(scene) or _source_hash(mesh),
        scene_frame=frame,
        scene_session_id=session_id,
        editable_submesh_count=editable_count,
        reference_submesh_count=reference_count,
    )


def rust_preview_package_from_path(path: Path | str) -> RustPreviewPackage:
    package_dir = Path(path)
    if package_dir.is_file():
        package_dir = package_dir.parent
    manifest_path = package_dir / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Rust preview manifest is not an object")
    expected = {
        "schema": RUST_PREVIEW_PACKAGE,
        "protocol": RUST_PREVIEW_PROTOCOL,
        "renderer": RUST_MESH_RENDERER,
        "edit_backend": RUST_PREVIEW_BACKEND,
    }
    for key, value in expected.items():
        if str(payload.get(key, "") or "") != value:
            raise ValueError(f"Rust preview manifest {key} does not match")
    return RustPreviewPackage(
        package_dir=package_dir.resolve(),
        manifest_path=manifest_path.resolve(),
        status_path=package_dir / "rust-preview-status.json",
        output_dir=package_dir,
        edit_operations_path=package_dir / "rust-preview-read-only.json",
        scene_session_id=str(payload.get("session_id", "") or ""),
    )


def validate_rust_preview_package(path: Path | str) -> tuple[str, ...]:
    try:
        rust_preview_package_from_path(path)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return (str(exc),)
    return ()


def build_rust_preview_prewarm_package(cache_root: Path | str) -> RustPreviewPackage:
    root = Path(cache_root) / "rust_preview" / "prewarm"
    root.mkdir(parents=True, exist_ok=True)
    for candidate in sorted(root.glob("package_*"), reverse=True):
        try:
            if not validate_rust_preview_package(candidate):
                return rust_preview_package_from_path(candidate)
        except OSError:
            continue
    submesh = SubMesh(
        name="rust_preview_prewarm",
        material="prewarm",
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    mesh = ParsedMesh(
        path="procedural://rust-preview-prewarm",
        format="procedural",
        bbox_min=(-0.5, -0.5, 0.0),
        bbox_max=(0.5, 0.5, 0.0),
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )
    return build_rust_preview_package(mesh, output_root=root)


__all__ = [
    "RustPreviewPackage",
    "build_rust_preview_package",
    "build_rust_preview_prewarm_package",
    "rust_preview_package_from_path",
    "validate_rust_preview_package",
]
