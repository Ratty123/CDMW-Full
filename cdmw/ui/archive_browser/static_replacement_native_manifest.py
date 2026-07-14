"""Native material manifest helpers for static replacement previews."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialTextureInput


NATIVE_MATERIAL_MANIFEST_OVERRIDE_KEYS = frozenset(
    {
        "base_tint_strength",
        "base_tint_only_fallback",
        "height_amount",
        "height_scale",
        "material_analysis",
        "material_category",
        "material_category_confidence",
        "material_category_reason",
        "material_layers",
        "material_response_disposition",
        "material_response_promoted",
        "material_shader_family",
        "metalness",
        "native_base_quality",
        "native_material_hints",
        "normal_strength",
        "primary_material_layer",
        "roughness",
        "specular",
    }
)


def apply_native_preview_core_material_manifest(
    preview_model: object,
    package_path: object,
    *,
    native_manifest_input_from_descriptor: Callable[..., PreviewMaterialTextureInput | None],
) -> int:
    if not isinstance(preview_model, ModelPreviewData):
        return 0
    manifest_path = Path(str(package_path or "")) / "manifest.json"
    if not manifest_path.is_file():
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    batches = manifest.get("batches") if isinstance(manifest, Mapping) else None
    if not isinstance(batches, Sequence) or isinstance(batches, (str, bytes, bytearray)):
        return 0
    preview_meshes = list(getattr(preview_model, "meshes", ()) or ())
    applied = 0
    for batch in batches:
        if not isinstance(batch, Mapping):
            continue
        identity = batch.get("editor_identity")
        if not isinstance(identity, Mapping):
            identity = {}
        try:
            source_component_index = int(identity.get("source_component_index", 0) or 0)
        except (TypeError, ValueError):
            source_component_index = 0
        if bool(identity.get("prefab_component", False)) or source_component_index != 0:
            continue
        raw_index = identity.get("source_submesh_index", batch.get("index", -1))
        try:
            mesh_index = int(raw_index)
        except (TypeError, ValueError):
            mesh_index = -1
        if mesh_index < 0 or mesh_index >= len(preview_meshes):
            continue
        mesh = preview_meshes[mesh_index]
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        dds_textures = batch.get("dds_textures")
        if not isinstance(dds_textures, Mapping):
            dds_textures = {}
        part_name = str(batch.get("material_name", "") or getattr(mesh, "material_name", "") or "")

        def apply_slot(slot: str, path_attr: str, dds_attr: str, name_attr: str = "") -> None:
            descriptor = dds_textures.get(slot)
            if not isinstance(descriptor, Mapping):
                return
            source_path = str(descriptor.get("source_path", "") or "").strip()
            archive_path = str(descriptor.get("archive_path", "") or "").strip()
            if source_path:
                setattr(mesh, dds_attr, source_path)
                setattr(mesh, path_attr, source_path)
            if name_attr:
                setattr(
                    mesh,
                    name_attr,
                    str(descriptor.get("texture_name", "") or "").strip()
                    or PurePosixPath(archive_path.replace("\\", "/")).name
                    or Path(source_path).name,
                )

        apply_slot("base", "preview_texture_path", "preview_texture_dds_path")
        apply_slot("normal", "preview_normal_texture_path", "preview_normal_texture_dds_path", "preview_normal_texture_name")
        apply_slot("material", "preview_material_texture_path", "preview_material_texture_dds_path", "preview_material_texture_name")
        apply_slot("height", "preview_height_texture_path", "preview_height_texture_dds_path", "preview_height_texture_name")
        if bool(batch.get("base_tint_only_fallback", False)):
            raw_base_color = batch.get("base_color")
            if isinstance(raw_base_color, Sequence) and not isinstance(raw_base_color, (str, bytes, bytearray)):
                try:
                    decoded_base_color = tuple(float(value) for value in raw_base_color[:3])
                except (TypeError, ValueError):
                    decoded_base_color = ()
                if len(decoded_base_color) == 3:
                    mesh.preview_color = decoded_base_color
            mesh.preview_texture_path = ""
            mesh.preview_texture_dds_path = ""
            mesh.preview_texture_image = None
        material_inputs: list[PreviewMaterialTextureInput] = []
        raw_inputs = dds_textures.get("material_inputs")
        if isinstance(raw_inputs, Sequence) and not isinstance(raw_inputs, (str, bytes, bytearray)):
            for item in raw_inputs:
                if isinstance(item, Mapping):
                    converted = native_manifest_input_from_descriptor(item, part_name=part_name)
                    if converted is not None:
                        material_inputs.append(converted)
        if not material_inputs:
            for slot in ("base", "normal", "material", "height"):
                descriptor = dds_textures.get(slot)
                if isinstance(descriptor, Mapping):
                    converted = native_manifest_input_from_descriptor(descriptor, fallback_slot=slot, part_name=part_name)
                    if converted is not None:
                        material_inputs.append(converted)
        if material_inputs:
            mesh.preview_material_texture_inputs = tuple(material_inputs)
        overrides = {
            str(key): copy.deepcopy(batch.get(key))
            for key in NATIVE_MATERIAL_MANIFEST_OVERRIDE_KEYS
            if key in batch
        }
        if overrides:
            mesh.preview_native_material_overrides = overrides
        mesh.preview_texture_approximation_note = "Material preview uses native C++ Archive Preview material manifest."
        mesh.preview_texture_image = None
        mesh.preview_normal_texture_image = None
        mesh.preview_material_texture_image = None
        mesh.preview_height_texture_image = None
        applied += 1
    return applied


def load_native_preview_core_material_manifest_for_alignment(
    target_preview_model: object,
    *,
    entry: object,
    package_root_text: str,
    active: bool,
    model_extensions: Sequence[str],
    cache_root: Path,
    render_settings: object,
    companion_entry: object | None,
    run_preview_job: Callable[..., object],
    clear_native_package_path: Callable[[], None],
    set_native_package_path: Callable[[object], None],
    apply_manifest: Callable[[object, object], int],
    record_runtime_event: Callable[..., object],
    dialog_title: str,
) -> int:
    if not active:
        return 0
    if str(getattr(entry, "extension", "") or "").strip().lower() not in set(model_extensions):
        return 0
    try:
        native_attempt = run_preview_job(
            entry,
            cache_root=cache_root,
            render_settings=render_settings,
            companion_entry=companion_entry,
            package_root=Path(package_root_text).expanduser() if package_root_text else None,
            timeout_seconds=8.0,
        )
    except Exception as exc:
        record_runtime_event(
            "mesh_alignment_native_material_manifest_failed",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            message=str(exc),
        )
        return 0
    if not bool(getattr(native_attempt, "succeeded", False)):
        clear_native_package_path()
        record_runtime_event(
            "mesh_alignment_native_material_manifest_unavailable",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            status=getattr(native_attempt, "status", ""),
            reason=getattr(native_attempt, "fallback_reason", ""),
        )
        return 0
    package_path = getattr(native_attempt, "package_path", None)
    set_native_package_path(package_path)
    applied = apply_manifest(target_preview_model, package_path)
    if applied:
        record_runtime_event(
            "mesh_alignment_native_material_manifest_applied",
            path=getattr(entry, "path", ""),
            dialog_title=dialog_title,
            batch_count=applied,
            package_path=package_path,
        )
    return applied


__all__ = [
    "NATIVE_MATERIAL_MANIFEST_OVERRIDE_KEYS",
    "apply_native_preview_core_material_manifest",
    "load_native_preview_core_material_manifest_for_alignment",
]
