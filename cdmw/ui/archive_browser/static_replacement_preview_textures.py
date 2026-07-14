"""Preview texture-binding helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.models import (
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.domain.textures.material_parameters import effective_emissive_intensity, profile_accent_glow_intensity, profile_source_emissive_enabled, source_emissive_strength
from cdmw.ui.archive_browser.static_replacement_native_manifest import (
    apply_native_preview_core_material_manifest,
    load_native_preview_core_material_manifest_for_alignment,
)
from cdmw.ui.archive_browser.static_replacement_preview_cache import (
    model_has_preview_texture_keys,
    static_preview_prepared_cache_key,
)
from cdmw.ui.archive_browser.static_replacement_preview_material_authority import (
    apply_material_authority_preview_native_hints,
    clear_material_authority_preview_native_hints,
    material_authority_preview_native_override_values,
    material_authority_preview_parameters,
)


def source_preview_path(source_path_text: object) -> str:
    source = Path(str(source_path_text or "")).expanduser()
    return str(source)


def accent_glow_preview_intensity(profile: object) -> float:
    return profile_accent_glow_intensity(profile)


def accent_glow_preview_enabled(profile: object) -> bool:
    return not hasattr(profile, "emissive_mode") or profile_source_emissive_enabled(profile)


def add_preview_material_input(
    mesh: object,
    *,
    slot_kind: str,
    source_path: Path,
    semantic_type: str,
    semantic_subtype: str,
    packed_channels: Sequence[str] = (),
    shader_family: str = "",
    parameters: Sequence[PreviewMaterialParameterInput] = (),
    parameter_name: str = "",
    material_name: str = "",
    normal_space: str = "",
) -> None:
    existing = list(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    preview_path = source_preview_path(str(source_path))
    source_key = str(source_path).replace("\\", "/").casefold()
    new_subtype = str(semantic_subtype or "").strip().lower()
    new_parameter = str(parameter_name or "").strip()
    new_channels = tuple(str(channel or "").strip().lower() for channel in packed_channels if str(channel or "").strip())
    new_is_pbr = new_subtype in {"metallic_roughness", "metallicroughness"} or new_channels[:2] == ("roughness", "metallic")
    new_is_legacy_orm = (
        slot_kind in {"material_mask", "ao"}
        or new_subtype in {"orm", "rma", "mra", "material_mask"}
        or new_channels[:3] == ("ao", "roughness", "metallic")
    )
    filtered_existing: list[PreviewMaterialTextureInput] = []
    for item in existing:
        item_source = str(
            getattr(item, "source_texture_path", "")
            or getattr(item, "source_dds_path", "")
            or getattr(item, "preview_texture_path", "")
            or ""
        ).replace("\\", "/").casefold()
        item_subtype = str(getattr(item, "semantic_subtype", "") or "").strip().lower()
        item_parameter = str(getattr(item, "parameter_name", "") or "").strip()
        item_channels = tuple(
            str(channel or "").strip().lower()
            for channel in tuple(getattr(item, "packed_channels", ()) or ())
            if str(channel or "").strip()
        )
        item_is_pbr = item_subtype in {"metallic_roughness", "metallicroughness"} or item_channels[:2] == ("roughness", "metallic")
        item_is_legacy_orm = (
            str(getattr(item, "slot_kind", "") or "").strip().lower() in {"material_mask", "ao"}
            or item_subtype in {"orm", "rma", "mra", "material_mask"}
            or item_channels[:3] == ("ao", "roughness", "metallic")
        )
        if item_source and item_source == source_key:
            if item_parameter == new_parameter and item_subtype == new_subtype:
                return
            if item_is_pbr and new_is_legacy_orm:
                return
            if item_is_legacy_orm and new_is_pbr:
                continue
        filtered_existing.append(item)
    existing = filtered_existing
    existing.append(
        PreviewMaterialTextureInput(
            slot_kind=slot_kind,
            parameter_name=parameter_name
            or {
                "base": "_baseColorTexture",
                "normal": "_normalTexture",
                "material": "_materialTexture",
                "roughness": "_roughnessTexture",
                "metalness": "_metallicTexture",
                "ao": "_occlusionTexture",
                "emissive": "_emissiveIntensityTexture",
                "height": "_heightTexture",
            }.get(slot_kind, ""),
            source_texture_path=str(source_path),
            source_dds_path=str(source_path) if source_path.suffix.lower() == ".dds" else "",
            texture_name=source_path.name,
            preview_texture_path=preview_path,
            semantic_type=semantic_type,
            semantic_subtype=semantic_subtype,
            packed_channels=tuple(str(channel) for channel in packed_channels if str(channel)),
            material_name=str(material_name or getattr(mesh, "material_name", "") or "").strip(),
            shader_family=shader_family,
            confidence="source",
            visualized=True,
            normal_space=str(normal_space or "").strip().lower(),
            material_parameters=tuple(parameters),
        )
    )
    mesh.preview_material_texture_inputs = tuple(existing)
    if slot_kind == "emissive" or "emissive" in str(shader_family or "").lower():
        mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"


def texture_set_for_mapping(
    mapping: object,
    *,
    texture_sets: Mapping[str, object],
    replacement_mesh: object | None,
    texture_set_for_source_index: Callable[[int, Mapping[str, object]], object | None],
) -> object | None:
    if not texture_sets:
        return None
    if replacement_mesh is not None:
        matched_sets: dict[str, object] = {}
        matched_source_count = 0
        valid_source_count = 0
        submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
        for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            source_index = int(source_index)
            if source_index < 0 or source_index >= len(submeshes):
                continue
            valid_source_count += 1
            texture_set = texture_set_for_source_index(source_index, texture_sets)
            if texture_set is None:
                continue
            material_name = str(getattr(texture_set, "material_name", "") or "").strip()
            if material_name:
                matched_sets.setdefault(material_name.lower(), texture_set)
                matched_source_count += 1
        if len(matched_sets) == 1:
            if matched_source_count == valid_source_count:
                return next(iter(matched_sets.values()))
            return None
        if len(matched_sets) > 1:
            return None
        if valid_source_count == 1 and len(texture_sets) == 1:
            return next(iter(texture_sets.values()))
        return None
    if len(texture_sets) == 1:
        return next(iter(texture_sets.values()))
    return None


def apply_source_material_preview(
    mesh: object,
    texture_set: object,
    target_name: str,
    *,
    complete_external_swap_enabled: bool,
    basic_controls_profile_enabled: bool,
    material_authority_profile: object | None,
    texture_set_factor_parameters: Callable[[object], Sequence[PreviewMaterialParameterInput]],
    material_authority_preview_texture_slots: Callable[..., Mapping[str, object]],
    replacement_texture_slot_preview_semantics: Callable[..., tuple[str, str, Sequence[str], str]],
    resolve_model_texture_semantic_details: Callable[[Path], tuple[str, str, object, Sequence[str]]],
    is_gltf_metallic_roughness_path: Callable[[Path], bool],
    infer_model_preview_normal_strength: Callable[..., float],
    accent_glow_preview_intensity: float,
) -> None:
    clear_replacement_preview_texture_bindings(mesh)
    material_authority_enabled = bool(complete_external_swap_enabled and basic_controls_profile_enabled)
    apply_material_authority_preview_native_hints(
        mesh,
        material_authority_profile,
        enabled=material_authority_enabled and material_authority_profile is not None, source=texture_set,
    )
    if material_authority_enabled and material_authority_profile is not None:
        try:
            slots = material_authority_preview_texture_slots(texture_set, material_authority_profile, enabled=True)
        except Exception:
            slots = material_authority_preview_texture_slots(texture_set, enabled=False)
    else:
        slots = material_authority_preview_texture_slots(texture_set, enabled=False)

    material_factor_parameters = tuple(texture_set_factor_parameters(texture_set))
    material_authority_parameters = material_authority_preview_parameters(
        material_authority_profile,
        enabled=material_authority_enabled and material_authority_profile is not None,
    )
    material_preview_parameters = material_factor_parameters + material_authority_parameters
    material_name = str(target_name or getattr(mesh, "material_name", "") or "").strip()

    def source_slot_preview_semantics(source_slot: object | None, source_path: Path) -> tuple[str, str, Sequence[str], str]:
        return replacement_texture_slot_preview_semantics(source_slot, source_path=source_path)

    def add_material_input(
        *,
        slot_kind: str,
        source_path: Path,
        semantic_type: str,
        semantic_subtype: str,
        packed_channels: Sequence[str] = (),
        shader_family: str = "",
        parameters: Sequence[PreviewMaterialParameterInput] = (),
        parameter_name: str = "",
        normal_space: str = "",
    ) -> None:
        add_preview_material_input(
            mesh,
            slot_kind=slot_kind,
            source_path=source_path,
            semantic_type=semantic_type,
            semantic_subtype=semantic_subtype,
            packed_channels=packed_channels,
            shader_family=shader_family,
            parameters=parameters,
            parameter_name=parameter_name,
            material_name=material_name,
            normal_space=normal_space,
        )

    base_slot = slots.get("base")
    if base_slot is not None:
        source_path = getattr(base_slot, "source_path", None)
        if isinstance(source_path, Path):
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_texture_path",
                dds_attr="preview_texture_dds_path",
                name_attr="texture_name",
                source_path=source_path,
            )
            mesh.preview_color = (1.0, 1.0, 1.0)
            mesh.preview_texture_flip_vertical = False
            add_material_input(
                slot_kind="base",
                source_path=source_path,
                semantic_type="color",
                semantic_subtype="albedo",
                parameters=material_authority_parameters,
            )

    normal_slot = slots.get("normal")
    if normal_slot is not None:
        source_path = getattr(normal_slot, "source_path", None)
        if isinstance(source_path, Path):
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_normal_texture_path",
                dds_attr="preview_normal_texture_dds_path",
                name_attr="preview_normal_texture_name",
                source_path=source_path,
            )
            mesh.preview_normal_texture_strength = infer_model_preview_normal_strength(
                normal_texture_path=source_path.name,
                material_name=target_name,
                semantic_hint="normal",
                prefer_stronger=True,
            )
            add_material_input(
                slot_kind="normal",
                source_path=source_path,
                semantic_type="normal",
                semantic_subtype="normal",
                parameters=material_authority_parameters,
                normal_space=str(getattr(normal_slot, "normal_space", "") or ""),
            )

    height_slot = slots.get("height")
    if height_slot is not None:
        source_path = getattr(height_slot, "source_path", None)
        if isinstance(source_path, Path):
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_height_texture_path",
                dds_attr="preview_height_texture_dds_path",
                name_attr="preview_height_texture_name",
                source_path=source_path,
            )
            add_material_input(
                slot_kind="height",
                source_path=source_path,
                semantic_type="height",
                semantic_subtype="height",
                parameters=material_authority_parameters,
            )

    material_slot = slots.get("material")
    if material_slot is not None:
        source_path = getattr(material_slot, "source_path", None)
        if isinstance(source_path, Path):
            semantic_type, semantic_subtype, _confidence, packed_channels = resolve_model_texture_semantic_details(source_path)
            (
                declared_semantic_type,
                declared_semantic_subtype,
                declared_packed_channels,
                declared_parameter_name,
            ) = source_slot_preview_semantics(material_slot, source_path)
            if declared_semantic_subtype:
                semantic_type = declared_semantic_type
                semantic_subtype = declared_semantic_subtype
                packed_channels = declared_packed_channels
            elif is_gltf_metallic_roughness_path(source_path):
                semantic_type = "material"
                semantic_subtype = "metallic_roughness"
                packed_channels = ("roughness", "metallic")
                declared_parameter_name = "_metallicRoughnessTexture"
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_material_texture_path",
                dds_attr="preview_material_texture_dds_path",
                name_attr="preview_material_texture_name",
                source_path=source_path,
            )
            mesh.preview_material_texture_type = semantic_type
            mesh.preview_material_texture_subtype = semantic_subtype
            mesh.preview_material_texture_packed_channels = tuple(packed_channels)
            add_material_input(
                slot_kind="material",
                source_path=source_path,
                semantic_type=semantic_type,
                semantic_subtype=semantic_subtype,
                packed_channels=tuple(packed_channels),
                parameter_name=declared_parameter_name
                or ("_metallicRoughnessTexture" if semantic_subtype == "metallic_roughness" else ""),
                parameters=material_preview_parameters,
            )

    for source_slot_name, semantic_type, semantic_subtype, packed_channels in (
        ("material_mask", "material", "orm", ("ao", "roughness", "metallic")),
        ("detail_mask", "material", "detail_mask", ()),
        ("roughness", "roughness", "roughness", ("roughness",)),
        ("metallic", "metallic", "metallic", ("metallic",)),
        ("metalness", "metallic", "metallic", ("metallic",)),
        ("ao", "ao", "ao", ("ao",)),
    ):
        slot = slots.get(source_slot_name)
        if slot is None:
            continue
        source_path = getattr(slot, "source_path", None)
        if not isinstance(source_path, Path):
            continue
        if source_slot_name in {"material_mask", "detail_mask"}:
            if not str(getattr(mesh, "preview_material_texture_path", "") or "").strip():
                set_preview_texture_slot_path(
                    mesh,
                    path_attr="preview_material_texture_path",
                    dds_attr="preview_material_texture_dds_path",
                    name_attr="preview_material_texture_name",
                    source_path=source_path,
                )
                mesh.preview_material_texture_type = semantic_type
                mesh.preview_material_texture_subtype = semantic_subtype
                mesh.preview_material_texture_packed_channels = tuple(packed_channels)
            add_material_input(
                slot_kind=source_slot_name,
                source_path=source_path,
                semantic_type=semantic_type,
                semantic_subtype=semantic_subtype,
                packed_channels=packed_channels,
                parameter_name="_detailMaskTexture" if source_slot_name == "detail_mask" else "_materialTexture",
                parameters=material_preview_parameters,
            )
            continue
        (
            declared_semantic_type,
            declared_semantic_subtype,
            declared_packed_channels,
            declared_parameter_name,
        ) = source_slot_preview_semantics(slot, source_path)
        if declared_semantic_subtype:
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_material_texture_path",
                dds_attr="preview_material_texture_dds_path",
                name_attr="preview_material_texture_name",
                source_path=source_path,
            )
            mesh.preview_material_texture_type = declared_semantic_type
            mesh.preview_material_texture_subtype = declared_semantic_subtype
            mesh.preview_material_texture_packed_channels = tuple(declared_packed_channels)
            add_material_input(
                slot_kind="material",
                source_path=source_path,
                semantic_type=declared_semantic_type,
                semantic_subtype=declared_semantic_subtype,
                packed_channels=declared_packed_channels,
                parameter_name=declared_parameter_name,
                parameters=material_preview_parameters,
            )
        elif is_gltf_metallic_roughness_path(source_path):
            set_preview_texture_slot_path(
                mesh,
                path_attr="preview_material_texture_path",
                dds_attr="preview_material_texture_dds_path",
                name_attr="preview_material_texture_name",
                source_path=source_path,
            )
            mesh.preview_material_texture_type = "material"
            mesh.preview_material_texture_subtype = "metallic_roughness"
            mesh.preview_material_texture_packed_channels = ("roughness", "metallic")
            add_material_input(
                slot_kind="material",
                source_path=source_path,
                semantic_type="material",
                semantic_subtype="metallic_roughness",
                packed_channels=("roughness", "metallic"),
                parameter_name="_metallicRoughnessTexture",
                parameters=material_preview_parameters,
            )
        else:
            add_material_input(
                slot_kind=source_slot_name,
                source_path=source_path,
                semantic_type=semantic_type,
                semantic_subtype=semantic_subtype,
                packed_channels=packed_channels,
                parameters=material_preview_parameters,
            )

    emissive_slot = slots.get("emissive")
    if emissive_slot is not None:
        source_path = getattr(emissive_slot, "source_path", None)
        if isinstance(source_path, Path):
            add_material_input(
                slot_kind="emissive",
                source_path=source_path,
                semantic_type="emissive",
                semantic_subtype="emissive",
                shader_family="SkinnedMeshEmissive_Ver2",
                parameters=(
                    PreviewMaterialParameterInput(
                        parameter_kind="float",
                        parameter_name="_emissiveIntensity",
                        value=f"{float(accent_glow_preview_intensity):.6f}",
                        numeric_value=float(accent_glow_preview_intensity),
                    ),
                ),
            )


def apply_source_material_preview_for_model(
    preview_model: object,
    *,
    use_direct_source_preview: bool,
    direct_source_preview_index_map: Mapping[int, int],
    mapped_preview: bool,
    source_overlay_preview_index_map: Mapping[int, int],
    current_mappings: Sequence[object],
    texture_sets: Mapping[str, object],
    material_authority_profile: object | None,
    complete_external_swap_enabled: bool,
    basic_controls_profile_enabled: bool,
    texture_set_for_source_index: Callable[[int, Mapping[str, object]], object | None],
    texture_set_for_mapping: Callable[[object], object | None],
    source_display_name: Callable[[int], str],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
    texture_set_factor_parameters: Callable[[object], Sequence[PreviewMaterialParameterInput]],
    material_authority_preview_texture_slots: Callable[..., Mapping[str, object]],
    replacement_texture_slot_preview_semantics: Callable[..., tuple[str, str, Sequence[str], str]],
    resolve_model_texture_semantic_details: Callable[[Path], tuple[str, str, object, Sequence[str]]],
    is_gltf_metallic_roughness_path: Callable[[Path], bool],
    infer_model_preview_normal_strength: Callable[..., float],
    accent_glow_preview_intensity: float,
) -> None:
    meshes = list(getattr(preview_model, "meshes", ()) or ())
    if not texture_sets:
        enabled = bool(complete_external_swap_enabled and basic_controls_profile_enabled and material_authority_profile is not None)
        for mesh in meshes:
            apply_material_authority_preview_native_hints(mesh, material_authority_profile, enabled=enabled)
        return

    def apply_for_mesh(mesh_index: int, texture_set: object | None, target_name: str) -> None:
        if mesh_index < 0 or mesh_index >= len(meshes) or texture_set is None:
            return
        apply_source_material_preview(
            meshes[mesh_index],
            texture_set,
            target_name,
            complete_external_swap_enabled=complete_external_swap_enabled,
            basic_controls_profile_enabled=basic_controls_profile_enabled,
            material_authority_profile=material_authority_profile,
            texture_set_factor_parameters=texture_set_factor_parameters,
            material_authority_preview_texture_slots=material_authority_preview_texture_slots,
            replacement_texture_slot_preview_semantics=replacement_texture_slot_preview_semantics,
            resolve_model_texture_semantic_details=resolve_model_texture_semantic_details,
            is_gltf_metallic_roughness_path=is_gltf_metallic_roughness_path,
            infer_model_preview_normal_strength=infer_model_preview_normal_strength,
            accent_glow_preview_intensity=accent_glow_preview_intensity,
        )

    if use_direct_source_preview and direct_source_preview_index_map:
        for source_index, mesh_index in direct_source_preview_index_map.items():
            apply_for_mesh(
                int(mesh_index),
                texture_set_for_source_index(int(source_index), texture_sets),
                source_display_name(int(source_index)),
            )
        return

    if not mapped_preview and not source_overlay_preview_index_map:
        for source_index, _mesh in enumerate(meshes):
            apply_for_mesh(
                source_index,
                texture_set_for_source_index(source_index, texture_sets),
                source_display_name(source_index),
            )
        return

    for source_index, mesh_index in source_overlay_preview_index_map.items():
        apply_for_mesh(
            int(mesh_index),
            texture_set_for_source_index(int(source_index), texture_sets),
            source_display_name(int(source_index)),
        )

    for mapping in current_mappings:
        texture_set = texture_set_for_mapping(mapping)
        if texture_set is None:
            continue
        target_name = str(getattr(mapping, "target_submesh_name", "") or "")
        target_mesh_indices = preview_target_mesh_indices(
            preview_model,
            target_name,
            tuple(getattr(mapping, "source_submesh_indices", ()) or ()),
            mapped_preview,
            current_mappings,
        )
        for mesh_index in target_mesh_indices:
            apply_for_mesh(int(mesh_index), texture_set, target_name)


def preview_glow_color_from_candidates(
    candidates: Sequence[Sequence[object]],
) -> tuple[str, tuple[float, float, float]]:
    for candidate in candidates:
        if len(candidate) < 3:
            continue
        try:
            values = tuple(float(value) for value in candidate[:3])
        except (TypeError, ValueError, OverflowError):
            continue
        if any(value > 1.0 for value in values):
            values = tuple(value / 255.0 for value in values)
        rgb = tuple(max(0.0, min(1.0, value)) for value in values[:3])
        if any(value > 0.0 for value in rgb):
            bytes_rgb = tuple(max(0, min(255, int(round(value * 255.0)))) for value in rgb)
            return f"#{bytes_rgb[0]:02X}{bytes_rgb[1]:02X}{bytes_rgb[2]:02X}FF", rgb  # type: ignore[return-value]
    return "#FFFFFFFF", (1.0, 1.0, 1.0)


def clear_source_role_emissive_preview(mesh: object) -> None:
    existing = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    filtered = tuple(
        item
        for item in existing
        if str(getattr(item, "confidence", "") or "") != "source-role-preview"
    )
    if len(filtered) != len(existing):
        mesh.preview_material_texture_inputs = filtered
    overrides = getattr(mesh, "preview_native_material_overrides", None)
    if isinstance(overrides, Mapping) and bool(overrides.get("_source_role_emissive_preview")):
        next_overrides = dict(overrides)
        for key in (
            "_source_role_emissive_preview",
            "emissive_intensity",
            "emissive_color",
        ):
            next_overrides.pop(key, None)
        mesh.preview_native_material_overrides = next_overrides


def apply_source_role_emissive_preview(
    mesh: object,
    *,
    source_index: int,
    target_name: str,
    texture_set: object | None,
    adjustment: object | None,
    profile: object,
    source_label: str,
) -> None:
    clear_source_role_emissive_preview(mesh)
    if adjustment is None or not bool(getattr(adjustment, "enabled", True)):
        return
    if str(getattr(adjustment, "material_role", "") or "").strip().lower() != "glow":
        return
    if not accent_glow_preview_enabled(profile):
        return
    emissive_source = texture_set if source_emissive_strength(texture_set) is not None else mesh
    emissive_intensity = effective_emissive_intensity(
        profile,
        source=emissive_source,
        part_adjustment=adjustment,
    )
    color_hex, color_rgb = preview_glow_color_from_candidates(
        (
            tuple(getattr(adjustment, "emissive_color_rgb", ()) or ()),
            tuple(getattr(texture_set, "accent_glow_color_rgb", ()) or ()) if texture_set is not None else (),
            tuple(getattr(texture_set, "base_color_factor", ()) or ()) if texture_set is not None else (),
            tuple(getattr(mesh, "preview_color", ()) or ()),
        )
    )
    role_input = PreviewMaterialTextureInput(
        slot_kind="emissive",
        parameter_name="_emissiveIntensity",
        semantic_type="emissive",
        semantic_subtype="emissive",
        material_name=str(target_name or getattr(mesh, "material_name", "") or "").strip(),
        part_name=str(source_label or source_index),
        shader_family="SkinnedMeshEmissive_Ver2",
        confidence="source-role-preview",
        visualized=True,
        material_parameters=(
            PreviewMaterialParameterInput(
                parameter_kind="color",
                parameter_name="_emissiveColor",
                value=color_hex,
                color_value=color_rgb,
            ),
            PreviewMaterialParameterInput(
                parameter_kind="float",
                parameter_name="_emissiveIntensity",
                value=f"{emissive_intensity:.6f}",
                numeric_value=emissive_intensity,
            ),
        ),
    )
    existing = tuple(getattr(mesh, "preview_material_texture_inputs", ()) or ())
    mesh.preview_material_texture_inputs = (role_input,) + existing
    mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
    overrides = dict(getattr(mesh, "preview_native_material_overrides", {}) or {})
    overrides["_source_role_emissive_preview"] = True
    overrides["emissive_intensity"] = emissive_intensity
    overrides["emissive_color"] = color_hex
    mesh.preview_native_material_overrides = overrides


def apply_source_role_emissive_preview_for_model(
    preview_model: object,
    *,
    use_direct_source_preview: bool,
    direct_source_preview_index_map: Mapping[int, int],
    mapped_preview: bool,
    source_overlay_preview_index_map: Mapping[int, int],
    current_mappings: Sequence[object],
    texture_sets: Mapping[str, object],
    source_part_adjustments: Mapping[int, object],
    profile: object,
    texture_set_for_source_index: Callable[[int, Mapping[str, object]], object | None],
    source_display_name: Callable[[int], str],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
) -> None:
    meshes = list(getattr(preview_model, "meshes", ()) or ())

    def apply_for_source(mesh_index: int, source_index: int, target_name: str) -> None:
        if mesh_index < 0 or mesh_index >= len(meshes):
            return
        texture_set = texture_set_for_source_index(int(source_index), texture_sets) if texture_sets else None
        apply_source_role_emissive_preview(
            meshes[mesh_index],
            source_index=int(source_index),
            target_name=target_name,
            texture_set=texture_set,
            adjustment=source_part_adjustments.get(int(source_index)),
            profile=profile,
            source_label=source_display_name(int(source_index)),
        )

    if use_direct_source_preview and direct_source_preview_index_map:
        for source_index, mesh_index in direct_source_preview_index_map.items():
            apply_for_source(int(mesh_index), int(source_index), source_display_name(int(source_index)))
        return

    if not mapped_preview and not source_overlay_preview_index_map:
        for source_index, _mesh in enumerate(meshes):
            apply_for_source(source_index, source_index, source_display_name(source_index))
        return

    for source_index, mesh_index in source_overlay_preview_index_map.items():
        apply_for_source(int(mesh_index), int(source_index), source_display_name(int(source_index)))

    for mapping in current_mappings:
        glow_source_indices = [
            int(source_index)
            for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ())
            if str(
                getattr(
                    source_part_adjustments.get(int(source_index)),
                    "material_role",
                    "",
                )
                or ""
            ).strip().lower()
            == "glow"
        ]
        if not glow_source_indices:
            continue
        target_name = str(getattr(mapping, "target_submesh_name", "") or "")
        target_mesh_indices = preview_target_mesh_indices(
            preview_model,
            target_name,
            tuple(getattr(mapping, "source_submesh_indices", ()) or ()),
            mapped_preview,
            current_mappings,
        )
        source_index = glow_source_indices[0]
        for mesh_index in target_mesh_indices:
            apply_for_source(int(mesh_index), source_index, target_name)


def apply_manual_preview_texture_override_specs(
    preview_model: object,
    preview_specs: Sequence[Sequence[object]],
    *,
    mapped_preview: bool,
    current_mappings: Sequence[object],
    preview_target_mesh_indices: Callable[[object, str, Sequence[int], bool, Sequence[object]], Sequence[int]],
    resolve_model_texture_semantic_details: Callable[[object], tuple[str, str, object, Sequence[str]]],
    replacement_texture_slot_preview_semantics: Callable[..., tuple[str, str, Sequence[str], str]],
    is_gltf_metallic_roughness_path: Callable[[Path], bool],
    infer_model_preview_normal_strength: Callable[..., float],
    material_authority_preview_parameters: Sequence[PreviewMaterialParameterInput],
    accent_glow_preview_intensity: float,
) -> None:
    meshes = list(getattr(preview_model, "meshes", ()) or ())
    for spec in tuple(preview_specs or ()):
        try:
            target_name, slot_kind, preview_texture_path, source_name, source_indices, source_path = spec
        except ValueError:
            continue
        slot_kind = str(slot_kind or "")
        target_name = str(target_name or "")
        source_name = str(source_name or "")
        preview_texture_path = str(preview_texture_path or "")
        target_mesh_indices = preview_target_mesh_indices(
            preview_model,
            target_name,
            tuple(int(index) for index in tuple(source_indices or ())),
            mapped_preview,
            current_mappings,
        )
        for source_index in target_mesh_indices:
            if source_index < 0 or source_index >= len(meshes):
                continue
            mesh = meshes[source_index]
            source_path_obj = Path(str(source_path or "")).expanduser()
            dds_path = str(source_path_obj) if source_path_obj.suffix.lower() == ".dds" else ""
            if slot_kind == "base":
                mesh.preview_texture_path = preview_texture_path
                mesh.texture_name = source_name
                mesh.preview_texture_dds_path = dds_path
                mesh.preview_texture_flip_vertical = False
            elif slot_kind == "normal":
                mesh.preview_normal_texture_path = preview_texture_path
                mesh.preview_normal_texture_name = source_name
                mesh.preview_normal_texture_dds_path = dds_path
                mesh.preview_normal_texture_strength = infer_model_preview_normal_strength(
                    normal_texture_path=source_name,
                    material_name=target_name,
                    semantic_hint=slot_kind,
                    prefer_stronger=True,
                )
            elif slot_kind == "height":
                mesh.preview_height_texture_path = preview_texture_path
                mesh.preview_height_texture_name = source_name
                mesh.preview_height_texture_dds_path = dds_path
            elif slot_kind in {"material", "material_mask", "detail_mask", "roughness", "metallic", "metalness", "ao", "emissive"}:
                semantic_type, semantic_subtype, _confidence, packed_channels = resolve_model_texture_semantic_details(source_path)
                declared_semantic_type, declared_semantic_subtype, declared_packed_channels, declared_parameter_name = (
                    replacement_texture_slot_preview_semantics(None, source_path=source_path_obj)
                )
                if declared_semantic_subtype:
                    semantic_type = declared_semantic_type
                    semantic_subtype = declared_semantic_subtype
                    packed_channels = declared_packed_channels
                else:
                    declared_parameter_name = ""
                if is_gltf_metallic_roughness_path(source_path_obj) and not declared_semantic_subtype:
                    semantic_type = "material"
                    semantic_subtype = "metallic_roughness"
                    packed_channels = ("roughness", "metallic")
                    declared_parameter_name = "_metallicRoughnessTexture"
                mesh.preview_material_texture_path = preview_texture_path
                mesh.preview_material_texture_name = source_name
                mesh.preview_material_texture_dds_path = dds_path
                if slot_kind == "emissive":
                    mesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
                    mesh.preview_material_texture_inputs = (
                        PreviewMaterialTextureInput(
                            slot_kind="emissive",
                            parameter_name="_emissiveIntensityTexture",
                            source_texture_path=str(source_path_obj),
                            source_dds_path=dds_path,
                            texture_name=source_name,
                            preview_texture_path=preview_texture_path,
                            semantic_type="emissive",
                            semantic_subtype="emissive",
                            material_name=target_name.strip(),
                            shader_family="SkinnedMeshEmissive_Ver2",
                            confidence="manual",
                            visualized=True,
                            material_parameters=(
                                PreviewMaterialParameterInput(
                                    parameter_kind="float",
                                    parameter_name="_emissiveIntensity",
                                    value=f"{accent_glow_preview_intensity:.6f}",
                                    numeric_value=accent_glow_preview_intensity,
                                ),
                            )
                            + tuple(material_authority_preview_parameters),
                        ),
                    )
                else:
                    mesh.preview_material_texture_inputs = (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name=declared_parameter_name
                            or (
                                "_metallicRoughnessTexture"
                                if semantic_subtype == "metallic_roughness"
                                else "_materialTexture"
                            ),
                            source_texture_path=str(source_path_obj),
                            source_dds_path=dds_path,
                            texture_name=source_name,
                            preview_texture_path=preview_texture_path,
                            semantic_type=semantic_type,
                            semantic_subtype=semantic_subtype,
                            packed_channels=tuple(packed_channels),
                            material_name=target_name.strip(),
                            confidence="manual",
                            visualized=True,
                            material_parameters=tuple(material_authority_preview_parameters),
                        ),
                    )
                mesh.preview_material_texture_type = semantic_type
                mesh.preview_material_texture_subtype = semantic_subtype
                mesh.preview_material_texture_packed_channels = tuple(packed_channels)


def clear_replacement_preview_texture_bindings(mesh: object) -> None:
    # Imported replacement textures must win over original/archive bindings.
    for attr in (
        "preview_texture_path",
        "preview_texture_dds_path",
        "texture_name",
        "preview_normal_texture_path",
        "preview_normal_texture_dds_path",
        "preview_normal_texture_name",
        "preview_material_texture_path",
        "preview_material_texture_dds_path",
        "preview_material_texture_name",
        "preview_material_texture_type",
        "preview_material_texture_subtype",
        "preview_height_texture_path",
        "preview_height_texture_dds_path",
        "preview_height_texture_name",
    ):
        try:
            setattr(mesh, attr, "")
        except Exception:
            pass
    for attr in (
        "preview_material_texture_inputs",
        "preview_material_texture_packed_channels",
    ):
        try:
            setattr(mesh, attr, ())
        except Exception:
            pass
    try:
        mesh.preview_material_texture_inputs = ()
    except Exception:
        pass


def set_preview_texture_slot_path(
    mesh: object,
    *,
    path_attr: str,
    dds_attr: str,
    name_attr: str,
    source_path: Path,
) -> str:
    preview_path = source_preview_path(str(source_path))
    setattr(mesh, path_attr, preview_path)
    setattr(mesh, name_attr, source_path.name)
    if source_path.suffix.lower() == ".dds":
        setattr(mesh, dds_attr, str(source_path))
    else:
        setattr(mesh, dds_attr, "")
    return preview_path


__all__ = [
    "accent_glow_preview_enabled",
    "accent_glow_preview_intensity",
    "add_preview_material_input",
    "apply_material_authority_preview_native_hints",
    "apply_manual_preview_texture_override_specs",
    "apply_native_preview_core_material_manifest",
    "load_native_preview_core_material_manifest_for_alignment",
    "apply_source_material_preview",
    "apply_source_material_preview_for_model",
    "apply_source_role_emissive_preview_for_model",
    "clear_material_authority_preview_native_hints",
    "clear_replacement_preview_texture_bindings",
    "clear_source_role_emissive_preview",
    "apply_source_role_emissive_preview",
    "material_authority_preview_native_override_values",
    "material_authority_preview_parameters",
    "model_has_preview_texture_keys",
    "preview_glow_color_from_candidates",
    "set_preview_texture_slot_path",
    "source_preview_path",
    "static_preview_prepared_cache_key",
    "texture_set_for_mapping",
]
