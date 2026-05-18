"""Texture and material-sidecar planning for static mesh replacement."""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from .asset_replacement import classify_texture_binding, infer_cd_texture_role_from_path
from .mesh_parser import ParsedMesh
from .static_mesh_replacer import StaticSubmeshMapping, _semantic_tokens


@dataclass(slots=True)
class ReplacementTextureSlot:
    material_name: str
    slot_kind: str
    source_path: Path
    normal_space: str = ""


@dataclass(slots=True)
class ReplacementTextureSet:
    material_name: str
    slots: dict[str, ReplacementTextureSlot] = field(default_factory=dict)
    source_face_count: int = 0


@dataclass(slots=True)
class TextureSlotMapping:
    target_material_name: str
    target_texture_path: str
    slot_kind: str
    source_material_name: str
    source_path: Path
    output_texture_path: str
    normal_space: str = ""


@dataclass(slots=True)
class SidecarTextureParameterInjection:
    target_material_name: str
    parameter_name: str
    texture_path: str
    anchor_texture_paths: tuple[str, ...] = ()


@dataclass(slots=True)
class SidecarTextureParameterRename:
    target_material_name: str
    texture_path: str
    old_parameter_name: str
    new_parameter_name: str


@dataclass(slots=True)
class SidecarPatchPlan:
    sidecar_path: str
    texture_path_replacements: dict[str, str] = field(default_factory=dict)
    texture_parameter_injections: list[SidecarTextureParameterInjection] = field(default_factory=list)
    texture_parameter_renames: list[SidecarTextureParameterRename] = field(default_factory=list)
    texture_parameter_keep_rules: list[tuple[str, str]] = field(default_factory=list)
    prune_unmapped_texture_parameters: bool = False
    prune_material_names: list[str] = field(default_factory=list)
    neutralize_inherited_material_layers: bool = False
    complete_external_material_reset: bool = False
    neutralize_material_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SidecarPatchReport:
    sidecar_path: str = ""
    replaced_count: int = 0
    unchanged_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TextureReplacementPayload:
    target_path: str
    payload_data: bytes
    kind: str
    source_path: Path
    note: str = ""


@dataclass(slots=True)
class TextureReplacementReport:
    texture_sets: list[ReplacementTextureSet] = field(default_factory=list)
    material_routes: list["SourceMaterialRoutingResult"] = field(default_factory=list)
    slot_mappings: list[TextureSlotMapping] = field(default_factory=list)
    sidecar_reports: list[SidecarPatchReport] = field(default_factory=list)
    generated_payloads: list[TextureReplacementPayload] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SourceMaterialRoutingResult:
    target_material_name: str
    source_material_name: str = ""
    source_part_names: tuple[str, ...] = ()
    detected_roles: tuple[str, ...] = ()
    status: str = "Unknown"
    reason: str = ""
    blocker: bool = False


@dataclass(slots=True, frozen=True)
class TextureAssignmentGuidance:
    checked_by_default: bool
    confidence: str
    state_label: str
    reason: str
    advanced: bool = False


_HELPER_MATERIAL_SUFFIXES = ("black", "inside")


def is_static_replacement_helper_material_name(material_name: str) -> bool:
    """Return true for technical material wrappers that should stay manual.

    Helmet sidecars often contain helper wrappers such as ``*_black`` and
    ``*_inside`` for interior/occlusion shader behavior.  They should not
    receive broad source texture routing just because the replacement only has
    one material set.
    """

    normalized = _sanitize_texture_component(material_name)
    if not normalized:
        return False
    parts = tuple(part for part in normalized.split("_") if part)
    if not parts:
        return False
    if parts[-1] in _HELPER_MATERIAL_SUFFIXES:
        return True
    return "inside" in parts


_TEXTURE_SUFFIXES: tuple[tuple[str, str, str], ...] = (
    ("base", "BaseColorTexture", "basecolor"),
    ("base", "Base_ColorTexture", "base_color"),
    ("base", "OverlayColorTexture", "albedo"),
    ("base", "DiffuseTexture", "diffuse"),
    ("base", "AlbedoTexture", "albedo"),
    ("base", "ColorTexture", "color"),
    ("emissive", "EmissiveTexture", "emissive"),
    ("emissive", "EmissiveIntensityTexture", "emissive"),
    ("emissive", "EmissiveProgressTexture", "emissive"),
    ("base", "WaterFoamTexture", "color"),
    ("base", "DecalBaseColorTexture", "color"),
    ("base", "ColorDecalBaseColorTexture", "color"),
    ("base", "DetailDiffuseMaskR", "diffuse"),
    ("base", "DetailDiffuseMaskG", "diffuse"),
    ("base", "DetailDiffuseMaskB", "diffuse"),
    ("base", "DetailDiffuseBlend", "diffuse"),
    ("base", "DamageBlendingDiffuseTexture", "diffuse"),
    ("base", "IrisDiffuseTexture", "diffuse"),
    ("base", "WrinkleColorTexture0", "color"),
    ("base", "WrinkleColorTexture1", "color"),
    ("base", "TornPatternTexture", "color"),
    ("base", "Base_Color", "base_color"),
    ("base", "BaseColor", "basecolor"),
    ("base", "Base", "base"),
    ("base", "Albedo", "albedo"),
    ("base", "Alb", "albedo"),
    ("base", "Diffuse", "diffuse"),
    ("base", "Dif", "diffuse"),
    ("base", "Di", "diffuse"),
    ("base", "Color", "color"),
    ("base", "Colour", "color"),
    ("base", "Cd", "color"),
    ("base", "Col", "color"),
    ("base", "C", "color"),
    ("base", "Bc", "basecolor"),
    ("base", "Bcol", "basecolor"),
    ("base", "O", "albedo"),
    ("emissive", "Emissive", "emissive"),
    ("emissive", "Emission", "emissive"),
    ("emissive", "Emi", "emissive"),
    ("emissive", "Em", "emissive"),
    ("emissive", "Glow", "emissive"),
    ("emissive", "Illumination", "emissive"),
    ("emissive", "Illum", "emissive"),
    ("base", "DetailDiffuse", "diffuse"),
    ("base", "DetailColor", "color"),
    ("base", "GrimeDiffuse", "diffuse"),
    ("normal", "NormalTexture", ""),
    ("normal", "DetailNormalMaskR", ""),
    ("normal", "DetailNormalMaskG", ""),
    ("normal", "DetailNormalMaskB", ""),
    ("normal", "DetailNormalBlend", ""),
    ("normal", "GrimeNormalTextureR", ""),
    ("normal", "GrimeNormalTextureG", ""),
    ("normal", "GrimeNormalTextureB", ""),
    ("normal", "DamageBlendingNormalTexture", ""),
    ("normal", "IrisNormalTexture", ""),
    ("normal", "WrinkleNormalTexture0", ""),
    ("normal", "WrinkleNormalTexture1", ""),
    ("normal", "SkinDetailNormalTexture", ""),
    ("normal", "ParallaxNormalTex", ""),
    ("normal", "Normal_OpenGL", "opengl"),
    ("normal", "Normal_DirectX", "directx"),
    ("normal", "Normal_DX", "directx"),
    ("normal", "Normal", ""),
    ("normal", "NormalMap", ""),
    ("normal", "Norm", ""),
    ("normal", "Nrm", ""),
    ("normal", "Nm", ""),
    ("normal", "N", ""),
    ("normal", "Wn", ""),
    ("normal", "DetailNormal", ""),
    ("normal", "GrimeNormal", ""),
    ("normal", "Nor", ""),
    ("normal", "No", ""),
    ("roughness", "MetallicRoughness", "roughness"),
    ("roughness", "Metallic_Roughness", "roughness"),
    ("roughness", "MetalRough", "roughness"),
    ("roughness", "MetallicRough", "roughness"),
    ("roughness", "RoughnessMetallic", "roughness"),
    ("roughness", "RoughMetal", "roughness"),
    ("material", "Orm", "material"),
    ("material", "Rma", "material"),
    ("material", "Mra", "material"),
    ("material", "Arm", "material"),
    ("material", "SpecularGlossiness", "material"),
    ("material", "SpecGloss", "material"),
    ("material", "Clearcoat", "material"),
    ("material", "ClearCoat", "material"),
    ("metallic", "Metallic", "metallic"),
    ("metallic", "Metalness", "metallic"),
    ("roughness", "Roughness", "roughness"),
    ("roughness", "Roughne", "roughness"),
    ("roughness", "Roughnes", "roughness"),
    ("roughness", "Rough", "roughness"),
    ("roughness", "Rgh", "roughness"),
    ("roughness", "Gloss", "roughness"),
    ("roughness", "Gls", "roughness"),
    ("roughness", "Smooth", "roughness"),
    ("roughness", "Smoothness", "roughness"),
    ("roughness", "Rou", "roughness"),
    ("roughness", "Ro", "roughness"),
    ("ao", "Mixed_AO", "ao"),
    ("ao", "AmbientOcclusion", "ao"),
    ("ao", "Occlusion", "ao"),
    ("ao", "AO", "ao"),
    ("height", "HeightTexture", "height"),
    ("height", "DisplacementTexture", "height"),
    ("height", "DetailHeightMaskR", "height"),
    ("height", "DetailHeightMaskG", "height"),
    ("height", "DetailHeightMaskB", "height"),
    ("height", "WrinkleDisplacementTexture0", "height"),
    ("height", "WrinkleDisplacementTexture1", "height"),
    ("height", "ParallaxTex", "height"),
    ("height", "SubParallaxTex", "height"),
    ("height", "Displacement", "height"),
    ("height", "Height", "height"),
    ("height", "Hgt", "height"),
    ("height", "Hei", "height"),
    ("height", "He", "height"),
    ("height", "Disp", "height"),
    ("height", "Depth", "height"),
    ("height", "Dmap", "height"),
    ("height", "D", "height"),
    ("height", "H", "height"),
    ("height", "Bump", "height"),
    ("height", "Pom", "height"),
    ("height", "Ssdm", "height"),
    ("material", "MaterialTexture", "material"),
    ("material", "MaskTexture", "material"),
    ("material_mask", "ColorBlendingMaskTexture", "material"),
    ("detail_mask", "DetailMaskTexture", "detail"),
    ("detail_mask", "DetailMaterialMaskR", "detail"),
    ("detail_mask", "DetailMaterialMaskG", "detail"),
    ("detail_mask", "DetailMaterialMaskB", "detail"),
    ("detail_mask", "DetailMaterialBlend", "detail"),
    ("material_mask", "GrimeMaterialTextureR", "material"),
    ("material_mask", "GrimeMaterialTextureG", "material"),
    ("material_mask", "GrimeMaterialTextureB", "material"),
    ("material", "DamageBlendingMaterialTexture", "material"),
    ("material", "IrisMaterialTexture", "material"),
    ("material", "WrinkleMaskTexture0", "material"),
    ("material", "WrinkleMaskTexture1", "material"),
    ("material", "SkinDetailMaskTexture", "material"),
    ("material", "SkinDetailMaterialTexture", "material"),
    ("material", "AlphaTexture", "material"),
    ("material", "RgbTexture", "material"),
    ("material", "LayerMaskTexture", "material"),
    ("material", "WaterFlowTexture", "material"),
    ("material", "ParallaxMaterialTex", "material"),
    ("material", "FlowTexture", "material"),
    ("material", "SsdmDirectionTexture", "material"),
    ("material", "SsdmHairDirectionTexture", "material"),
    ("material", "Reflection", "material"),
    ("material", "Reflecti", "material"),
    ("material", "Reflect", "material"),
    ("material", "Ref", "material"),
    ("material", "Re", "material"),
    ("material", "Material", "material"),
    ("material", "Mat", "material"),
    ("material", "M", "material"),
    ("material_mask", "Ma", "material"),
    ("detail_mask", "Mg", "detail"),
    ("material", "Sp", "material"),
    ("material", "Spec", "material"),
    ("material", "Specular", "material"),
    ("material", "Gloss", "material"),
    ("material", "Gls", "material"),
    ("material", "Smooth", "material"),
    ("material", "Smoothness", "material"),
    ("material", "Orm", "material"),
    ("material", "Rma", "material"),
    ("material", "Mra", "material"),
    ("material", "Arm", "material"),
    ("material", "Opacity", "material"),
    ("material", "Alpha", "material"),
    ("material", "Op", "material"),
    ("material", "Subsurface", "material"),
    ("material", "Flow", "material"),
    ("material", "Vector", "material"),
    ("material", "Dr", "material"),
    ("material", "Mask", "material"),
    ("material", "Masks", "material"),
    ("material", "Mask_1bit", "material"),
    ("material_mask", "Mask_AMG", "material"),
    ("detail_mask", "DetailMask", "detail"),
    ("detail_mask", "DetailMaterial", "detail"),
    ("material_mask", "ColorBlendingMask", "material"),
    ("material_mask", "GrimeMaterial", "material"),
)


def analyze_replacement_textures(
    obj_mesh: ParsedMesh,
    texture_files: Sequence[Path],
    original_sidecar_texts: Sequence[str] = (),
    original_texture_refs: Sequence[object] = (),
) -> TextureReplacementReport:
    """Group replacement texture files and report likely material slots."""
    del original_sidecar_texts, original_texture_refs
    texture_sets = group_replacement_texture_sets(texture_files, obj_mesh=obj_mesh)
    report = TextureReplacementReport(texture_sets=list(texture_sets.values()))
    if not texture_sets and texture_files:
        report.warnings.append("No replacement texture files matched known material suffix patterns.")
    return report


def _with_source_material_reference_textures(
    texture_files: Sequence[Path],
    obj_mesh: ParsedMesh,
) -> tuple[Path, ...]:
    """Include texture paths carried by imported material metadata."""

    supported_suffixes = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}
    paths: list[Path] = []
    seen: set[str] = set()

    def add_path(value: object) -> None:
        text = str(value or "").strip()
        if not text:
            return
        path = Path(text).expanduser()
        try:
            path = path.resolve()
        except Exception:
            pass
        if path.suffix.lower() not in supported_suffixes or not path.is_file():
            return
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        paths.append(path)

    for texture_file in tuple(texture_files or ()):
        add_path(texture_file)
    for submesh in tuple(getattr(obj_mesh, "submeshes", ()) or ()):
        add_path(getattr(submesh, "texture", ""))
        for _slot_kind, slot_path in tuple(getattr(submesh, "texture_slots", ()) or ()):
            add_path(slot_path)
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            add_path(getattr(texture_input, "preview_texture_path", ""))
            add_path(getattr(texture_input, "source_texture_path", ""))
    return tuple(paths)


def build_texture_replacement_payloads(
    *,
    obj_mesh: ParsedMesh,
    rebuilt_mesh: Optional[ParsedMesh] = None,
    texture_files: Sequence[Path],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    on_log: Optional[Callable[[str], None]] = None,
    enable_missing_base_color_parameters: bool = False,
    texture_slot_overrides: Sequence[object] = (),
    source_material_texture_overrides: Sequence[object] = (),
    donor_material_plans: Sequence[object] = (),
    texture_output_size_mode: str = "source",
    pac_driven_sidecar: bool = False,
    neutralize_inherited_material_layers: bool = False,
    complete_external_material_reset: bool = False,
    removed_target_material_names: Sequence[str] = (),
    prune_removed_target_texture_parameters: bool = False,
    prune_unmapped_original_texture_parameters: bool = False,
) -> tuple[list[TextureReplacementPayload], TextureReplacementReport]:
    """Build generated DDS and patched sidecar payloads for a static replacement."""
    effective_texture_files = tuple(texture_files or ())
    if complete_external_material_reset:
        effective_texture_files = _with_source_material_reference_textures(
            effective_texture_files,
            obj_mesh,
        )
    report = analyze_replacement_textures(obj_mesh, effective_texture_files)
    texture_sets = {texture_set.material_name.lower(): texture_set for texture_set in report.texture_sets}
    _apply_source_material_texture_overrides(
        texture_sets,
        obj_mesh=obj_mesh,
        texture_slot_overrides=texture_slot_overrides,
        source_material_texture_overrides=source_material_texture_overrides,
        report=report,
    )
    if texture_sets:
        report.warnings[:] = [
            warning
            for warning in report.warnings
            if warning != "No replacement texture files matched known material suffix patterns."
        ]
    report.texture_sets = list(texture_sets.values())
    active_donor_material_plans = tuple(
        plan for plan in tuple(donor_material_plans or ()) if bool(getattr(plan, "enabled", True))
    )
    removed_target_material_names = tuple(
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    )
    prune_removed_target_texture_parameters = bool(prune_removed_target_texture_parameters and removed_target_material_names)
    prune_unmapped_original_texture_parameters = bool(prune_unmapped_original_texture_parameters)
    if (
        not texture_sets
        and not active_donor_material_plans
        and not prune_removed_target_texture_parameters
        and not prune_unmapped_original_texture_parameters
    ):
        return [], report

    if texture_sets:
        _attach_source_face_counts(texture_sets, obj_mesh)
        target_to_source_material = _choose_source_materials_for_targets(obj_mesh, texture_sets, submesh_mappings, report)
        if rebuilt_mesh is not None:
            _augment_source_materials_from_rebuilt_mesh(target_to_source_material, rebuilt_mesh, texture_sets)
    else:
        target_to_source_material = {}

    if pac_driven_sidecar and rebuilt_mesh is not None:
        generated_payloads: list[TextureReplacementPayload] = []
        if texture_sets:
            generated_payloads = _build_rebuilt_pac_driven_payloads(
                obj_mesh=obj_mesh,
                rebuilt_mesh=rebuilt_mesh,
                texture_sets=texture_sets,
                original_texture_refs=original_texture_refs,
                original_sidecars=original_sidecars,
                submesh_mappings=submesh_mappings,
                target_to_source_material=target_to_source_material,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                enable_missing_base_color_parameters=enable_missing_base_color_parameters,
                texture_slot_overrides=_manual_target_texture_slot_overrides(texture_slot_overrides),
                texture_output_size_mode=texture_output_size_mode,
                neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
                complete_external_material_reset=bool(complete_external_material_reset),
                removed_target_material_names=removed_target_material_names,
                prune_removed_target_texture_parameters=prune_removed_target_texture_parameters,
                prune_unmapped_original_texture_parameters=prune_unmapped_original_texture_parameters,
            )
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        if donor_sidecar_payloads:
            generated_payloads = _replace_sidecar_payloads(generated_payloads, donor_sidecar_payloads)
            generated_payloads.extend(
                _build_donor_material_texture_payloads(
                    active_donor_material_plans,
                    existing_payloads=generated_payloads,
                    report=report,
                )
            )
        if (prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters) and not texture_sets:
            keep_rules = _sidecar_keep_rules_from_slot_mappings(
                report.slot_mappings,
                _references_by_target_path(original_texture_refs),
            )
            if prune_unmapped_original_texture_parameters:
                pruned_payloads = _build_patched_sidecar_payloads(
                    original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
                    sidecar_replacements_by_path={},
                    sidecar_parameter_injections=(),
                    texture_parameter_keep_rules=keep_rules,
                    prune_unmapped_texture_parameters=True,
                    prune_material_names=(),
                    report=report,
                )
            else:
                pruned_payloads = _build_removed_target_prune_sidecar_payloads(
                    original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, generated_payloads),
                    removed_target_material_names=removed_target_material_names,
                    keep_rules=keep_rules,
                    report=report,
                )
            if pruned_payloads:
                generated_payloads = _replace_sidecar_payloads(generated_payloads, pruned_payloads)
        report.generated_payloads = generated_payloads
        _append_unused_texture_warnings(texture_sets, report)
        return list(report.generated_payloads), report

    if active_donor_material_plans and not texture_sets:
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=original_sidecars,
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        report.generated_payloads = donor_sidecar_payloads + _build_donor_material_texture_payloads(
            active_donor_material_plans,
            existing_payloads=donor_sidecar_payloads,
            report=report,
        )
        return list(report.generated_payloads), report

    texture_payloads: list[TextureReplacementPayload] = []
    sidecar_replacements_by_path: dict[str, str] = {}
    sidecar_parameter_injections: list[SidecarTextureParameterInjection] = []
    reference_by_target_path = _references_by_target_path(original_texture_refs)
    emitted_target_paths: set[str] = set()
    target_texture_slot_overrides = _manual_target_texture_slot_overrides(texture_slot_overrides)
    if target_texture_slot_overrides:
        override_payloads, override_replacements = _build_manual_texture_slot_override_payloads(
            texture_slot_overrides=target_texture_slot_overrides,
            reference_by_target_path=reference_by_target_path,
            texture_sets=texture_sets,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        texture_payloads.extend(override_payloads)
        sidecar_replacements_by_path.update(override_replacements)
        emitted_target_paths.update(_normalize_texture_path(payload.target_path) for payload in override_payloads)

    skipped_inactive_target_count = 0
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path:
            continue
        if _normalize_texture_path(target_path) in emitted_target_paths:
            continue
        if not _should_replace_original_texture_reference(reference, target_path):
            continue
        if not _reference_belongs_to_active_static_target(reference, target_path, target_to_source_material):
            skipped_inactive_target_count += 1
            continue
        target_material = str(getattr(reference, "material_name", "") or "").strip()
        source_material = _best_source_material_for_target(target_material, target_to_source_material)
        if not source_material:
            source_material = _best_source_material_for_target(
                PurePosixPath(str(target_path or "").replace("\\", "/")).stem,
                target_to_source_material,
            )
        texture_set = texture_sets.get(source_material.lower()) if source_material else None
        if texture_set is None:
            continue

        slot_kind = _infer_slot_kind(
            str(getattr(reference, "sidecar_parameter_name", "") or ""),
            target_path,
        )
        source_slot = _slot_for_target(texture_set, slot_kind)
        if source_slot is None:
            continue
        if slot_kind == "material" and source_slot.slot_kind != "material":
            report.warnings.append(
                f"{target_path} expects a packed material/mask texture; using {source_slot.slot_kind} source "
                f"{source_slot.source_path.name}. Bake or pack metallic/roughness/AO into the game's expected mask layout for best results."
            )

        target_entry = getattr(reference, "resolved_entry", None)
        if target_entry is None:
            report.warnings.append(f"Texture target could not be resolved in archive: {target_path}")
            continue
        output_texture_path = _replacement_output_texture_path(source_slot, target_path)

        try:
            payload = _build_texture_payload(
                source_slot,
                target_entry=target_entry,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
        except Exception as exc:
            report.errors.append(f"Failed to build replacement texture for {target_path}: {exc}")
            continue

        texture_payloads.append(
            TextureReplacementPayload(
                target_path=output_texture_path,
                payload_data=payload,
                kind="texture_generated",
                source_path=source_slot.source_path,
                note=f"{source_slot.material_name} {source_slot.slot_kind} -> {output_texture_path}",
            )
        )
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name=target_material,
                target_texture_path=target_path,
                slot_kind=slot_kind,
                source_material_name=source_slot.material_name,
                source_path=source_slot.source_path,
                output_texture_path=output_texture_path,
                normal_space=source_slot.normal_space,
            )
        )
        original_reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        if original_reference_name and original_reference_name != output_texture_path:
            sidecar_replacements_by_path[original_reference_name] = output_texture_path
        if target_path != output_texture_path:
            sidecar_replacements_by_path[target_path] = output_texture_path

    if skipped_inactive_target_count:
        report.warnings.append(
            f"Skipped {skipped_inactive_target_count:,} original texture binding(s) for draw/material slots with no replacement geometry."
        )

    if enable_missing_base_color_parameters:
        injected_payloads, injected_parameters = _build_missing_base_color_parameter_payloads(
            obj_mesh=obj_mesh,
            texture_sets=texture_sets,
            original_texture_refs=original_texture_refs,
            target_to_source_material=target_to_source_material,
            existing_slot_mappings=report.slot_mappings,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        texture_payloads.extend(injected_payloads)
        sidecar_parameter_injections.extend(injected_parameters)
    elif _needs_missing_base_color_parameter_payloads(
        texture_sets=texture_sets,
        target_to_source_material=target_to_source_material,
        existing_slot_mappings=report.slot_mappings,
        original_sidecars=original_sidecars,
    ):
        report.warnings.append(
            "A replacement base-color texture has no safe existing material slot. "
            "The app did not inject a new .pac_xml material parameter because this can make some shaders render untextured."
        )

    sidecar_payloads: list[TextureReplacementPayload] = []
    if texture_payloads and (sidecar_replacements_by_path or sidecar_parameter_injections):
        for sidecar_entry, sidecar_text in original_sidecars:
            sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
            patched_text, sidecar_report = patch_material_sidecar_text(
                sidecar_text,
                SidecarPatchPlan(
                    sidecar_path=sidecar_path,
                    texture_path_replacements=sidecar_replacements_by_path,
                    texture_parameter_injections=sidecar_parameter_injections,
                ),
            )
            report.sidecar_reports.append(sidecar_report)
            if sidecar_report.replaced_count <= 0 and (sidecar_replacements_by_path or sidecar_parameter_injections):
                report.warnings.append(
                    f"Patched sidecar {PurePosixPath(sidecar_path).name} did not apply any texture path or parameter changes."
                )
                continue
            sidecar_payloads.append(
                TextureReplacementPayload(
                    target_path=sidecar_path,
                    payload_data=patched_text.encode("utf-8"),
                    kind="sidecar_generated",
                    source_path=Path(PurePosixPath(sidecar_path).name),
                    note="Patched material sidecar cloned from original archive entry.",
                )
            )

    if active_donor_material_plans:
        donor_sidecar_payloads = _build_donor_material_sidecar_payloads(
            original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
            donor_material_plans=active_donor_material_plans,
            report=report,
        )
        if donor_sidecar_payloads:
            sidecar_payloads = _replace_sidecar_payloads(sidecar_payloads, donor_sidecar_payloads)
            texture_payloads.extend(
                _build_donor_material_texture_payloads(
                    active_donor_material_plans,
                    existing_payloads=tuple(texture_payloads) + tuple(sidecar_payloads),
                    report=report,
                )
            )

    _append_texture_contract_warnings(
        texture_payloads=texture_payloads,
        sidecar_payloads=sidecar_payloads,
        report=report,
    )
    report.generated_payloads = texture_payloads + sidecar_payloads
    _append_unused_texture_warnings(texture_sets, report)
    return list(report.generated_payloads), report


def patch_material_sidecar_text(
    original_text: str,
    sidecar_patch_plan: SidecarPatchPlan,
) -> tuple[str, SidecarPatchReport]:
    """Clone-patch sidecar text by replacing paths and optional compatible texture parameters."""
    patched = str(original_text or "")
    report = SidecarPatchReport(sidecar_path=sidecar_patch_plan.sidecar_path)
    for old_path, new_path in sidecar_patch_plan.texture_path_replacements.items():
        old_value = str(old_path or "").strip()
        new_value = str(new_path or "").strip()
        if not old_value or not new_value:
            continue
        if old_value == new_value:
            if old_value in patched:
                report.unchanged_count += 1
            continue
        replacement_variants = []
        slashless_old = old_value.replace("\\", "/").lstrip("/")
        if slashless_old:
            leading_slash_old = "/" + slashless_old
            if leading_slash_old not in replacement_variants:
                replacement_variants.append(leading_slash_old)
        replacement_variants.append(old_value)
        if slashless_old and slashless_old != old_value and slashless_old not in replacement_variants:
            replacement_variants.append(slashless_old)
        replaced_any = False
        for candidate_old in replacement_variants:
            occurrences = patched.count(candidate_old)
            if occurrences <= 0:
                continue
            patched = patched.replace(candidate_old, new_value)
            report.replaced_count += occurrences
            replaced_any = True
        if not replaced_any:
            report.warnings.append(f"Sidecar did not contain texture path: {old_value}")
            continue
    for injection in sidecar_patch_plan.texture_parameter_injections:
        patched, injected = _inject_sidecar_texture_parameter(patched, injection, report)
        if injected:
            report.replaced_count += 1
    for rename in sidecar_patch_plan.texture_parameter_renames:
        patched, renamed = _rename_sidecar_texture_parameter(patched, rename, report)
        if renamed:
            report.replaced_count += 1
    if sidecar_patch_plan.prune_unmapped_texture_parameters:
        if sidecar_patch_plan.prune_material_names:
            patched, removed_count = _prune_unmapped_sidecar_texture_parameters_for_materials(
                patched,
                material_names=sidecar_patch_plan.prune_material_names,
                keep_rules=sidecar_patch_plan.texture_parameter_keep_rules,
            )
        else:
            patched, removed_count = _prune_unmapped_sidecar_texture_parameters(
                patched,
                sidecar_patch_plan.texture_parameter_keep_rules,
            )
        if removed_count:
            report.replaced_count += removed_count
            report.warnings.append(
                f"Removed {removed_count:,} unmapped original texture parameter(s) from rebuilt material sidecar."
            )
    if sidecar_patch_plan.neutralize_inherited_material_layers:
        patched, neutralized_wrappers, neutralized_parameters = _neutralize_inherited_material_layers(
            patched,
            material_names=sidecar_patch_plan.neutralize_material_names,
            keep_rules=sidecar_patch_plan.texture_parameter_keep_rules,
            complete_external_reset=bool(sidecar_patch_plan.complete_external_material_reset),
        )
        if neutralized_parameters:
            report.replaced_count += neutralized_parameters
            report.warnings.append(
                "Neutralized inherited material layers for "
                f"{neutralized_wrappers:,} material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
            )
    return patched, report


def _build_rebuilt_pac_driven_payloads(
    *,
    obj_mesh: ParsedMesh,
    rebuilt_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    target_to_source_material: Mapping[str, str],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    enable_missing_base_color_parameters: bool,
    texture_slot_overrides: Sequence[object],
    texture_output_size_mode: str,
    neutralize_inherited_material_layers: bool,
    complete_external_material_reset: bool = False,
    removed_target_material_names: Sequence[str] = (),
    prune_removed_target_texture_parameters: bool = False,
    prune_unmapped_original_texture_parameters: bool = False,
) -> list[TextureReplacementPayload]:
    """Build texture and sidecar payloads from final rebuilt PAC/PAM draw sections.

    Only rebuilt submeshes with geometry drive generated texture payloads. The
    sidecar patch still preserves unrelated shader parameters because many
    game material wrappers rely on layer/detail/PBD data that is not part of
    the visible replacement texture set.
    """
    del obj_mesh
    references_by_material = _references_by_material(original_texture_refs)
    references_by_target_path = _references_by_target_path(original_texture_refs)
    active_target_names = _active_rebuilt_material_names(rebuilt_mesh, submesh_mappings)
    if not active_target_names:
        report.warnings.append("PAC-driven material sidecar had no rebuilt draw sections with geometry to bind.")
        return []

    if not texture_slot_overrides:
        source_driven_payloads = _build_source_driven_pac_material_payloads(
            texture_sets=texture_sets,
            original_texture_refs=original_texture_refs,
            original_sidecars=original_sidecars,
            active_target_names=active_target_names,
            target_to_source_material=target_to_source_material,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
            neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
            complete_external_material_reset=bool(complete_external_material_reset),
            removed_target_material_names=removed_target_material_names,
            prune_removed_target_texture_parameters=prune_removed_target_texture_parameters,
            prune_unmapped_original_texture_parameters=prune_unmapped_original_texture_parameters,
        )
        if source_driven_payloads:
            return source_driven_payloads

    payloads: list[TextureReplacementPayload] = []
    sidecar_replacements_by_path: dict[str, str] = {}
    sidecar_parameter_injections: list[SidecarTextureParameterInjection] = []
    sidecar_parameter_renames: list[SidecarTextureParameterRename] = []
    emitted_texture_paths: set[str] = set()
    manual_targets: set[str] = set()
    material_source_overrides: dict[str, str] = {}

    if texture_slot_overrides:
        override_payloads, override_replacements = _build_manual_texture_slot_override_payloads(
            texture_slot_overrides=texture_slot_overrides,
            reference_by_target_path=references_by_target_path,
            texture_sets=texture_sets,
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
        payloads.extend(override_payloads)
        sidecar_replacements_by_path.update(override_replacements)
        for mapping in report.slot_mappings:
            normalized_target = _normalize_texture_path(mapping.output_texture_path or mapping.target_texture_path)
            if normalized_target:
                manual_targets.add(normalized_target)
            if mapping.target_material_name and mapping.source_material_name:
                material_source_overrides.setdefault(
                    _normalize_sidecar_material_name(mapping.target_material_name),
                    mapping.source_material_name,
                )
        emitted_texture_paths.update(_normalize_texture_path(payload.target_path) for payload in override_payloads)

    for target_name in active_target_names:
        target_key = _normalize_sidecar_material_name(target_name)
        if is_static_replacement_helper_material_name(target_name) and target_key not in material_source_overrides:
            _warn_once(
                report,
                f"Preserved helper material wrapper {target_name}; automatic texture routing does not patch _black/_inside-style parts.",
            )
            continue
        source_material = material_source_overrides.get(target_key) or _best_source_material_for_target(
            target_name,
            target_to_source_material,
        )
        texture_set = texture_sets.get(str(source_material or "").strip().lower()) if source_material else None
        if texture_set is None:
            report.warnings.append(f"No replacement texture set was selected for rebuilt draw section {target_name}.")
            continue

        material_refs = _references_for_active_material(target_name, references_by_material)
        direct_refs = [
            reference
            for reference in material_refs
            if _is_direct_pac_driven_parameter(reference, _reference_target_path(reference))
        ]
        if not direct_refs:
            report.warnings.append(
                f"Rebuilt draw section {target_name} has no direct texture parameters in the original sidecar; "
                "base/normal/material slots may need manual sidecar authoring."
            )

        mapped_kinds: set[str] = set()
        direct_base_reference_exists = any(
            _infer_slot_kind(str(getattr(reference, "sidecar_parameter_name", "") or ""), _reference_target_path(reference)) == "base"
            for reference in direct_refs
        )
        repurposed_base_reference = (
            None
            if direct_base_reference_exists or texture_set.slots.get("base") is None
            else _color_blending_mask_reference(direct_refs)
        )
        for reference in direct_refs:
            target_path = _reference_target_path(reference)
            normalized_target = _normalize_texture_path(target_path)
            if not target_path or normalized_target in emitted_texture_paths:
                continue
            if normalized_target in manual_targets:
                continue
            target_entry = getattr(reference, "resolved_entry", None)
            if target_entry is None:
                report.warnings.append(f"Texture target could not be resolved in archive: {target_path}")
                continue
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "")
            if reference is repurposed_base_reference:
                slot_kind = "base"
                source_slot = texture_set.slots.get("base")
            else:
                slot_kind = _infer_slot_kind(parameter_name, target_path)
                source_slot = _slot_for_target(texture_set, slot_kind)
            if source_slot is None:
                continue
            if slot_kind in {"material", "material_mask", "detail_mask"} and source_slot.slot_kind != slot_kind:
                report.warnings.append(
                    f"{target_path} expects a packed material/mask texture; using {source_slot.slot_kind} source "
                    f"{source_slot.source_path.name}. Bake or pack metallic/roughness/AO into the game's expected mask layout for best results."
                )
            try:
                payload_data = _build_texture_payload(
                    source_slot,
                    target_entry=target_entry,
                    texconv_path=texconv_path,
                    read_original_texture_bytes=read_original_texture_bytes,
                    original_texture_source_path=original_texture_source_path,
                    report=report,
                    on_log=on_log,
                    texture_output_size_mode=texture_output_size_mode,
                )
            except Exception as exc:
                report.errors.append(f"Failed to build replacement texture for {target_path}: {exc}")
                continue
            output_texture_path = _replacement_output_texture_path(source_slot, target_path)
            payloads.append(
                TextureReplacementPayload(
                    target_path=output_texture_path,
                    payload_data=payload_data,
                    kind="texture_generated",
                    source_path=source_slot.source_path,
                    note=(
                        f"PAC-driven {target_name} base via existing color-blend slot: {source_slot.source_path.name}"
                        if reference is repurposed_base_reference
                        else f"PAC-driven {target_name} {slot_kind}: {source_slot.source_path.name}"
                    ),
                )
            )
            report.slot_mappings.append(
                TextureSlotMapping(
                    target_material_name=target_name,
                    target_texture_path=target_path,
                    slot_kind=slot_kind,
                    source_material_name=source_slot.material_name,
                    source_path=source_slot.source_path,
                    output_texture_path=output_texture_path,
                    normal_space=source_slot.normal_space,
                )
            )
            original_reference_name = str(getattr(reference, "reference_name", "") or "").strip()
            if original_reference_name and original_reference_name != output_texture_path:
                sidecar_replacements_by_path[original_reference_name] = output_texture_path
            if target_path != output_texture_path:
                sidecar_replacements_by_path[target_path] = output_texture_path
            if reference is repurposed_base_reference:
                sidecar_parameter_renames.append(
                    SidecarTextureParameterRename(
                        target_material_name=target_name,
                        texture_path=output_texture_path,
                        old_parameter_name="_colorBlendingMaskTexture",
                        new_parameter_name="_overlayColorTexture",
                    )
                )
                report.warnings.append(
                    f"PAC XML rebuild: repurposed _colorBlendingMaskTexture as _overlayColorTexture for {target_name}."
                )
            emitted_texture_paths.add(normalized_target)
            mapped_kinds.add(slot_kind)

        if "base" not in mapped_kinds and texture_set.slots.get("base") is not None:
            injected_payloads, injected_parameters = _build_base_color_injection_for_target(
                target_name=target_name,
                texture_set=texture_set,
                original_texture_refs=original_texture_refs,
                material_refs=material_refs,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
            payloads.extend(injected_payloads)
            sidecar_parameter_injections.extend(injected_parameters)
            if not injected_payloads and not enable_missing_base_color_parameters:
                report.warnings.append(
                    f"{target_name}: base color source {texture_set.slots['base'].source_path.name} is available, "
                    "but no compatible template was found for automatic PAC XML base-color injection."
                )

    sidecar_payloads = _build_patched_sidecar_payloads(
        original_sidecars=original_sidecars,
        sidecar_replacements_by_path=sidecar_replacements_by_path,
        sidecar_parameter_injections=sidecar_parameter_injections,
        sidecar_parameter_renames=sidecar_parameter_renames,
        texture_parameter_keep_rules=_sidecar_keep_rules_from_slot_mappings(
            report.slot_mappings,
            references_by_target_path,
        ),
        prune_unmapped_texture_parameters=bool(
            prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters
        ),
        prune_material_names=[] if prune_unmapped_original_texture_parameters else list(removed_target_material_names),
        neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
        complete_external_material_reset=bool(complete_external_material_reset),
        neutralize_material_names=list(active_target_names),
        report=report,
        include_unchanged_clone=bool(
            payloads
            and (
                sidecar_replacements_by_path
                or sidecar_parameter_injections
                or sidecar_parameter_renames
            )
        ),
    )
    _append_texture_contract_warnings(
        texture_payloads=payloads,
        sidecar_payloads=sidecar_payloads,
        report=report,
    )
    if payloads and not sidecar_payloads and original_sidecars:
        report.warnings.append(
            "PAC-driven texture payloads were built, but no .pac_xml sidecar changes were applied. "
            "This is expected only when texture paths are overwritten in-place."
        )
    elif sidecar_payloads:
        if neutralize_inherited_material_layers:
            report.warnings.append(
                "PAC-driven material sidecar rebuild used source-color faithful mode: inherited tint/grime/detail/color-blend layers were neutralized on active rebuilt draw sections."
            )
        else:
            report.warnings.append(
                "PAC-driven material sidecar rebuild preserved unmodified material parameters and patched only resolved texture bindings."
            )
    return payloads + sidecar_payloads


def _active_rebuilt_material_names(
    rebuilt_mesh: ParsedMesh,
    submesh_mappings: Sequence[StaticSubmeshMapping],
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    mapping_names_by_index = {
        int(mapping.target_submesh_index): str(mapping.target_submesh_name or "").strip()
        for mapping in submesh_mappings
    }
    for index, submesh in enumerate(rebuilt_mesh.submeshes):
        if not getattr(submesh, "vertices", None) or not getattr(submesh, "faces", None):
            continue
        name = (
            str(getattr(submesh, "material", "") or "").strip()
            or str(getattr(submesh, "name", "") or "").strip()
            or mapping_names_by_index.get(index, "")
            or f"target {index}"
        )
        key = _normalize_sidecar_material_name(name)
        if key and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def _references_by_material(original_texture_refs: Sequence[object]) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for reference in original_texture_refs:
        if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
            continue
        material_name = str(getattr(reference, "material_name", "") or "").strip()
        if not material_name:
            continue
        result.setdefault(_normalize_sidecar_material_name(material_name), []).append(reference)
    return result


def _references_for_active_material(
    target_name: str,
    references_by_material: Mapping[str, Sequence[object]],
) -> list[object]:
    target_key = _normalize_sidecar_material_name(target_name)
    if target_key in references_by_material:
        return list(references_by_material[target_key])
    scored: list[tuple[float, object]] = []
    for material_key, references in references_by_material.items():
        if not material_key:
            continue
        representative = str(getattr(references[0], "material_name", "") or material_key)
        score = _sidecar_material_match_score(target_name, representative)
        if _sidecar_material_names_match(target_name, representative):
            score += 8.0
        for reference in references:
            path_text = _reference_target_path(reference)
            if _active_target_tokens_match_path(target_name, path_text):
                score += 4.0
        if score > 0:
            for reference in references:
                scored.append((score, reference))
    best_score = max((score for score, _reference in scored), default=0.0)
    if best_score < 6.0:
        return []
    return [reference for score, reference in scored if score == best_score]


def _color_blending_mask_reference(references: Sequence[object]) -> Optional[object]:
    for reference in references:
        parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
        target_path = _reference_target_path(reference)
        if parameter == "_colorblendingmasktexture" and target_path.lower().endswith(".dds"):
            return reference
    return None


def _build_source_driven_pac_material_payloads(
    *,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    original_sidecars: Sequence[tuple[object, str]],
    active_target_names: Sequence[str],
    target_to_source_material: Mapping[str, str],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
    neutralize_inherited_material_layers: bool = False,
    complete_external_material_reset: bool = False,
    removed_target_material_names: Sequence[str] = (),
    prune_removed_target_texture_parameters: bool = False,
    prune_unmapped_original_texture_parameters: bool = False,
) -> list[TextureReplacementPayload]:
    removed_target_material_names = tuple(
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    )
    prune_removed_target_texture_parameters = bool(prune_removed_target_texture_parameters and removed_target_material_names)
    prune_unmapped_original_texture_parameters = bool(prune_unmapped_original_texture_parameters)
    if not original_sidecars or (
        not active_target_names
        and not prune_removed_target_texture_parameters
        and not prune_unmapped_original_texture_parameters
    ):
        return []

    target_bindings: dict[str, list[tuple[str, str, str]]] = {}
    target_pbr_scalars: dict[str, tuple[int, int, str]] = {}
    generated_payloads: list[TextureReplacementPayload] = []
    generated_by_source: dict[tuple[str, str], str] = {}
    emitted_paths: set[str] = set()
    texture_parent = _source_driven_texture_parent(original_texture_refs)
    texture_prefix = _source_driven_texture_prefix(original_sidecars)

    for target_name in active_target_names:
        if is_static_replacement_helper_material_name(target_name):
            _warn_once(
                report,
                f"Preserved helper material wrapper {target_name}; automatic source texture routing does not patch _black/_inside-style parts. "
                "Use Advanced original-DDS overrides only if you intentionally want to edit that helper shader.",
            )
            continue
        source_material = _best_source_material_for_target(target_name, target_to_source_material)
        texture_set = texture_sets.get(str(source_material or "").strip().lower()) if source_material else None
        if texture_set is None and len(texture_sets) == 1:
            texture_set = next(iter(texture_sets.values()))
        if texture_set is None:
            report.warnings.append(f"No replacement texture set was selected for rebuilt draw section {target_name}.")
            continue
        if complete_external_material_reset:
            pbr_scalars = _source_pbr_scalar_values(texture_set)
            if pbr_scalars is not None:
                target_pbr_scalars[target_name] = pbr_scalars

        bindings: list[tuple[str, str, str]] = []
        for source_slot in _source_driven_slots(
            texture_set,
            include_pbr_material_fallback=bool(complete_external_material_reset),
        ):
            parameter_name = _source_driven_parameter_name(source_slot.slot_kind)
            if not parameter_name:
                continue
            source_key = (
                str(source_slot.source_path.expanduser().resolve()).lower(),
                str(source_slot.slot_kind or "").strip().lower(),
            )
            output_texture_path = generated_by_source.get(source_key)
            if output_texture_path is None:
                template_reference = _source_driven_template_reference(original_texture_refs, source_slot.slot_kind)
                target_entry = getattr(template_reference, "resolved_entry", None) if template_reference is not None else None
                if target_entry is None:
                    report.warnings.append(
                        f"Could not find an original DDS template for {source_slot.slot_kind} source {source_slot.source_path.name}."
                    )
                    continue
                output_texture_path = _source_driven_texture_output_path(
                    texture_parent,
                    texture_prefix,
                    source_slot,
                    emitted_paths,
                )
                try:
                    payload_data = _build_texture_payload(
                        source_slot,
                        target_entry=target_entry,
                        texconv_path=texconv_path,
                        read_original_texture_bytes=read_original_texture_bytes,
                        original_texture_source_path=original_texture_source_path,
                        report=report,
                        on_log=on_log,
                        texture_output_size_mode=texture_output_size_mode,
                    )
                except Exception as exc:
                    report.errors.append(
                        f"Failed to build source-driven replacement texture for {source_slot.source_path.name}: {exc}"
                    )
                    continue
                generated_by_source[source_key] = output_texture_path
                generated_payloads.append(
                    TextureReplacementPayload(
                        target_path=output_texture_path,
                        payload_data=payload_data,
                        kind="texture_generated",
                        source_path=source_slot.source_path,
                        note=f"Source-driven material texture: {source_slot.source_path.name} -> {output_texture_path}",
                    )
                )
            bindings.append((parameter_name, output_texture_path, source_slot.slot_kind))
            report.slot_mappings.append(
                TextureSlotMapping(
                    target_material_name=target_name,
                    target_texture_path=f"(source-driven {parameter_name})",
                    slot_kind=source_slot.slot_kind,
                    source_material_name=source_slot.material_name,
                    source_path=source_slot.source_path,
                    output_texture_path=output_texture_path,
                    normal_space=source_slot.normal_space,
                )
            )
        if bindings:
            target_bindings[target_name] = bindings

    if not generated_payloads or not target_bindings:
        if prune_unmapped_original_texture_parameters:
            return _build_patched_sidecar_payloads(
                original_sidecars=original_sidecars,
                sidecar_replacements_by_path={},
                sidecar_parameter_injections=(),
                texture_parameter_keep_rules=(),
                prune_unmapped_texture_parameters=True,
                prune_material_names=(),
                report=report,
            )
        if prune_removed_target_texture_parameters:
            return _build_removed_target_prune_sidecar_payloads(
                original_sidecars=original_sidecars,
                removed_target_material_names=removed_target_material_names,
                keep_rules=(),
                report=report,
            )
        return []

    sidecar_payloads: list[TextureReplacementPayload] = []
    used_source_texture_paths: set[str] = set()
    for sidecar_entry, sidecar_text in original_sidecars:
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        patched_text, changed_wrappers, used_paths, changed_wrapper_names = _build_source_driven_sidecar_text(
            sidecar_text,
            target_bindings,
        )
        neutralized_parameters = 0
        if neutralize_inherited_material_layers and changed_wrappers > 0:
            keep_rules = [
                (parameter_name, texture_path)
                for bindings in target_bindings.values()
                for parameter_name, texture_path, _slot_kind in bindings
            ]
            patched_text, neutralized_wrappers, neutralized_parameters = _neutralize_inherited_material_layers(
                patched_text,
                material_names=list(changed_wrapper_names) or list(target_bindings.keys()),
                keep_rules=keep_rules,
                complete_external_reset=bool(complete_external_material_reset),
            )
            if neutralized_parameters:
                if complete_external_material_reset:
                    report.warnings.append(
                        "Complete external swap reset inherited target shader/material response for "
                        f"{neutralized_wrappers:,} source-driven material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
                    )
                else:
                    report.warnings.append(
                        "Neutralized inherited material layers for "
                        f"{neutralized_wrappers:,} source-driven material wrapper(s), {neutralized_parameters:,} parameter edit(s)."
                    )
        if changed_wrappers <= 0:
            report.warnings.append(
                f"Skipped source-driven sidecar {PurePosixPath(sidecar_path).name}; no compatible material wrapper texture slot could be patched."
            )
            continue
        if complete_external_material_reset and target_pbr_scalars:
            scalar_material_names = list(changed_wrapper_names) or [
                name for name in target_bindings.keys() if name in target_pbr_scalars
            ]
            applied_scalar_wrappers = 0
            applied_sources: set[str] = set()
            for target_name, (roughness_value, metallic_value, source_name) in target_pbr_scalars.items():
                names_for_target = [
                    name for name in scalar_material_names if _sidecar_material_names_match(name, target_name)
                ] or [target_name]
                patched_text, scalar_wrappers = _apply_source_pbr_scalar_parameters(
                    patched_text,
                    material_names=names_for_target,
                    roughness_value=roughness_value,
                    metallic_value=metallic_value,
                )
                if scalar_wrappers:
                    applied_scalar_wrappers += scalar_wrappers
                    applied_sources.add(source_name)
            if applied_scalar_wrappers:
                report.warnings.append(
                    "Complete external swap derived scratch roughness/metallic values from source PBR map(s) "
                    f"for {applied_scalar_wrappers:,} material wrapper(s): {', '.join(sorted(applied_sources))}."
                )
        used_source_texture_paths.update(_normalize_texture_path(path) for path in used_paths)
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note=(
                    "Source-driven material sidecar patched from replacement mesh textures; "
                    "source-color faithful mode neutralized inherited material layers."
                    if neutralize_inherited_material_layers and neutralized_parameters > 0
                    else "Source-driven material sidecar patched from replacement mesh textures."
                ),
            )
        )

    if sidecar_payloads:
        if used_source_texture_paths:
            before_count = len(generated_payloads)
            generated_payloads = [
                payload
                for payload in generated_payloads
                if _normalize_texture_path(payload.target_path) in used_source_texture_paths
            ]
            skipped_count = before_count - len(generated_payloads)
            if skipped_count:
                report.warnings.append(
                    f"Skipped {skipped_count:,} generated source texture(s) because no compatible original shader parameter used them."
                )
            report.slot_mappings[:] = [
                mapping
                for mapping in report.slot_mappings
                if not str(mapping.target_texture_path or "").startswith("(source-driven ")
                or _normalize_texture_path(mapping.output_texture_path) in used_source_texture_paths
            ]
        if neutralize_inherited_material_layers:
            if complete_external_material_reset:
                report.warnings.append(
                    "PAC XML source-driven patch: complete external swap reset target shader/material response and used source texture roles where possible."
                )
            elif any("Neutralized inherited material layers" in warning for warning in report.warnings):
                report.warnings.append(
                    "PAC XML source-driven patch: source-color faithful mode neutralized inherited tint/grime/detail/color-blend layers on patched wrappers."
                )
            else:
                report.warnings.append(
                    "PAC XML source-driven patch: source-color faithful mode was enabled, but no inherited material layers matched the patched wrappers."
                )
        else:
            report.warnings.append(
                "PAC XML source-driven patch: preserved original shader wrappers and rebound compatible direct texture slots only."
            )
        _append_texture_contract_warnings(
            texture_payloads=generated_payloads,
            sidecar_payloads=sidecar_payloads,
            report=report,
        )
    if prune_removed_target_texture_parameters or prune_unmapped_original_texture_parameters:
        keep_rules = [
            (parameter_name, texture_path)
            for bindings in target_bindings.values()
            for parameter_name, texture_path, _slot_kind in bindings
        ]
        if prune_unmapped_original_texture_parameters:
            pruned_payloads = _build_patched_sidecar_payloads(
                original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
                sidecar_replacements_by_path={},
                sidecar_parameter_injections=(),
                texture_parameter_keep_rules=keep_rules,
                prune_unmapped_texture_parameters=True,
                prune_material_names=(),
                report=report,
            )
        else:
            pruned_payloads = _build_removed_target_prune_sidecar_payloads(
                original_sidecars=_overlay_original_sidecars_with_payloads(original_sidecars, sidecar_payloads),
                removed_target_material_names=removed_target_material_names,
                keep_rules=keep_rules,
                report=report,
            )
        if pruned_payloads:
            sidecar_payloads = _replace_sidecar_payloads(sidecar_payloads, pruned_payloads)
    return generated_payloads + sidecar_payloads
    return []


def _source_driven_slots(
    texture_set: ReplacementTextureSet,
    *,
    include_pbr_material_fallback: bool = False,
) -> list[ReplacementTextureSlot]:
    # Source-driven .pac_xml patching stays conservative but understands full
    # Crimson material families.  Clear CD roles (_o/_n/_disp/_ma/_mg) may be
    # routed; standalone glTF PBR maps are not Crimson color-blend masks.
    order = ("base", "normal", "height", "material_mask", "detail_mask", "emissive")
    slots: list[ReplacementTextureSlot] = []
    seen_paths: set[tuple[str, str]] = set()
    for slot_kind in order:
        source_slot = texture_set.slots.get(slot_kind)
        if source_slot is None:
            continue
        key = (str(source_slot.source_path.expanduser().resolve()).lower(), str(source_slot.slot_kind).lower())
        if key in seen_paths:
            continue
        seen_paths.add(key)
        slots.append(source_slot)
    if include_pbr_material_fallback and not any(slot.slot_kind in {"material", "material_mask"} for slot in slots):
        for fallback_kind in ("material",):
            source_slot = texture_set.slots.get(fallback_kind)
            if source_slot is None:
                continue
            normalized_name = re.sub(r"[^a-z0-9]+", "", source_slot.source_path.name.lower())
            if any(
                token in normalized_name
                for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic", "roughmetal")
            ):
                continue
            key = (str(source_slot.source_path.expanduser().resolve()).lower(), "material_mask")
            if key in seen_paths:
                continue
            seen_paths.add(key)
            slots.append(
                ReplacementTextureSlot(
                    material_name=source_slot.material_name,
                    slot_kind="material_mask",
                    source_path=source_slot.source_path,
                    normal_space=source_slot.normal_space,
                )
            )
            break
    return slots


def _source_driven_parameter_name(slot_kind: str) -> str:
    normalized = str(slot_kind or "").strip().lower()
    return {
        "base": "_overlayColorTexture",
        "normal": "_normalTexture",
        "height": "_heightTexture",
        "material_mask": "_colorBlendingMaskTexture",
        "detail_mask": "_detailMaskTexture",
        "emissive": "_emissiveIntensityTexture",
    }.get(normalized, "")


def _byte4_uniform_rgb(value: int) -> int:
    byte_value = max(0, min(255, int(value)))
    return byte_value | (byte_value << 8) | (byte_value << 16)


def _mean_image_channel(path: Path, channel_index: int) -> Optional[float]:
    try:
        from PIL import Image, ImageStat

        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            if max(rgba.size) > 512:
                rgba.thumbnail((512, 512))
            stat = ImageStat.Stat(rgba)
            means = tuple(float(value) for value in stat.mean)
            if channel_index < 0 or channel_index >= len(means):
                return None
            return max(0.0, min(255.0, means[channel_index]))
    except Exception:
        return None


def _looks_like_gltf_metallic_roughness(path: Path) -> bool:
    normalized_name = re.sub(r"[^a-z0-9]+", "", path.name.lower())
    return any(
        token in normalized_name
        for token in ("metallicroughness", "metalrough", "metallicrough", "roughnessmetallic", "roughmetal")
    )


def _source_pbr_scalar_values(texture_set: ReplacementTextureSet) -> Optional[tuple[int, int, str]]:
    material_slot = texture_set.slots.get("material") or texture_set.slots.get("roughness")
    if material_slot is not None and _looks_like_gltf_metallic_roughness(material_slot.source_path):
        roughness = _mean_image_channel(material_slot.source_path, 1)
        metalness = _mean_image_channel(material_slot.source_path, 2)
        if roughness is not None or metalness is not None:
            rough_byte = int(round(roughness if roughness is not None else 127.0))
            metal_byte = int(round(metalness if metalness is not None else 0.0))
            return (
                _byte4_uniform_rgb(rough_byte),
                _byte4_uniform_rgb(metal_byte),
                material_slot.source_path.name,
            )
    roughness_slot = texture_set.slots.get("roughness")
    metallic_slot = texture_set.slots.get("metallic") or texture_set.slots.get("metalness")
    if roughness_slot is None and metallic_slot is None:
        return None
    roughness = _mean_image_channel(roughness_slot.source_path, 0) if roughness_slot is not None else None
    metalness = _mean_image_channel(metallic_slot.source_path, 0) if metallic_slot is not None else None
    if roughness is None and metalness is None:
        return None
    source_name = (
        roughness_slot.source_path.name
        if roughness_slot is not None
        else metallic_slot.source_path.name
        if metallic_slot is not None
        else "source PBR"
    )
    return (
        _byte4_uniform_rgb(int(round(roughness if roughness is not None else 127.0))),
        _byte4_uniform_rgb(int(round(metalness if metalness is not None else 0.0))),
        source_name,
    )


def _texture_role_for_parameter_and_path(parameter_name: str, texture_path: str) -> str:
    role = infer_cd_texture_role_from_path(texture_path)
    if role:
        return role
    classification = classify_texture_binding(parameter_name, texture_path)
    return str(classification.slot_kind or "").strip().lower()


def _source_driven_template_reference(
    original_texture_refs: Sequence[object],
    slot_kind: str,
) -> Optional[object]:
    normalized = str(slot_kind or "").strip().lower()
    preferred_parameters = {
        "base": ("_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture", "_emissiveintensitytexture"),
        "normal": ("_normaltexture",),
        "height": ("_heighttexture",),
        "material_mask": ("_colorblendingmasktexture", "_overlaycolortexture"),
        "detail_mask": ("_detailmasktexture",),
        "emissive": ("_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture", "_overlaycolortexture"),
    }.get(normalized, ())

    fallback: Optional[object] = None
    parameter_fallback: Optional[object] = None
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path.lower().endswith(".dds") or getattr(reference, "resolved_entry", None) is None:
            continue
        if fallback is None:
            fallback = reference
        parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
        role = _texture_role_for_parameter_and_path(parameter, target_path)
        if role == normalized:
            return reference
        if parameter in preferred_parameters and not parameter_fallback and (not role or role == normalized):
            parameter_fallback = reference
    return parameter_fallback or fallback


def _source_driven_texture_parent(original_texture_refs: Sequence[object]) -> str:
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if target_path.lower().endswith(".dds"):
            parent = PurePosixPath(target_path.replace("\\", "/")).parent.as_posix()
            if parent and parent != ".":
                return parent
    return "character/texture"


def _source_driven_texture_prefix(original_sidecars: Sequence[tuple[object, str]]) -> str:
    if original_sidecars:
        sidecar_path = str(getattr(original_sidecars[0][0], "path", "") or "").replace("\\", "/")
        name = PurePosixPath(sidecar_path).name.lower()
        for suffix in (".pac_xml", ".pam_xml", ".pamlod_xml", ".pami", ".xml"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if name.endswith(".pac") or name.endswith(".pam") or name.endswith(".pamlod"):
            name = PurePosixPath(name).stem
        cleaned = _sanitize_texture_component(name)
        if cleaned:
            return cleaned
    return "static_replacement"


def _source_driven_texture_output_path(
    texture_parent: str,
    texture_prefix: str,
    source_slot: ReplacementTextureSlot,
    emitted_paths: set[str],
) -> str:
    parent = str(texture_parent or "character/texture").replace("\\", "/").strip("/")
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    output_stem, role_suffix = _source_driven_texture_output_name_parts(prefix, source_slot)
    base_name = f"{output_stem}{role_suffix}.dds"
    candidate = f"{parent}/{base_name}" if parent else base_name
    normalized = _normalize_texture_path(candidate)
    if normalized not in emitted_paths:
        emitted_paths.add(normalized)
        return candidate
    index = 2
    while True:
        base_name = f"{output_stem}_{index}{role_suffix}.dds"
        candidate = f"{parent}/{base_name}" if parent else base_name
        normalized = _normalize_texture_path(candidate)
        if normalized not in emitted_paths:
            emitted_paths.add(normalized)
            return candidate
        index += 1


def _source_driven_texture_output_name_parts(
    texture_prefix: str,
    source_slot: ReplacementTextureSlot,
) -> tuple[str, str]:
    prefix = _sanitize_texture_component(texture_prefix) or "static_replacement"
    slot_kind = str(source_slot.slot_kind or "").strip().lower()
    source_stem = _sanitize_texture_component(source_slot.source_path.stem) or slot_kind or "texture"
    if slot_kind == "normal":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "normal_opengl",
                "normal_directx",
                "normal_dx",
                "normalmap",
                "detailnormal",
                "wrinklenormal",
                "damagenormal",
                "normal",
                "norm",
                "nrm",
                "nm",
                "wn",
                "n",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_n"
    if slot_kind == "height":
        source_stem = _strip_source_role_suffix(
            source_stem,
            ("displacement", "height", "depth", "dmap", "disp", "bump", "hgt", "hei", "he", "d", "h"),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_disp"
    if slot_kind == "material":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "colorblendingmask",
                "detailmaterial",
                "detailmask",
                "material_mask",
                "materialmask",
                "mask_amg",
                "mask_1bit",
                "material",
                "mask",
                "masks",
                "mat",
                "ma",
                "mg",
                "sp",
                "m",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_ma"
    if slot_kind == "material_mask":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "colorblendingmask",
                "material_mask",
                "materialmask",
                "mask_amg",
                "mask_1bit",
                "mask",
                "masks",
                "mat",
                "ma",
                "m",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_ma"
    if slot_kind == "detail_mask":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "detailmaterial",
                "detail_mask",
                "detailmask",
                "mg",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_mg"
    if slot_kind == "emissive":
        source_stem = _strip_source_role_suffix(
            source_stem,
            (
                "emissiveintensitytexture",
                "emissiveprogresstexture",
                "emissivetexture",
                "emissive",
                "emission",
                "illumination",
                "illum",
                "glow",
                "emi",
                "em",
            ),
        )
        return _source_driven_prefixed_stem(prefix, source_stem), "_emi"
    return _source_driven_prefixed_stem(prefix, source_stem), ""


def _source_driven_prefixed_stem(prefix: str, source_stem: str) -> str:
    cleaned = _sanitize_texture_component(source_stem)
    if not cleaned:
        return prefix
    if cleaned == prefix or cleaned.startswith(f"{prefix}_"):
        return cleaned
    return f"{prefix}_{cleaned}"


def _strip_source_role_suffix(source_stem: str, suffixes: Sequence[str]) -> str:
    cleaned = _sanitize_texture_component(source_stem)
    for suffix in sorted((_sanitize_texture_component(value) for value in suffixes), key=len, reverse=True):
        if not suffix:
            continue
        if cleaned == suffix:
            return ""
        marker = f"_{suffix}"
        if cleaned.endswith(marker):
            return cleaned[: -len(marker)].strip("_")
    return cleaned


def _sanitize_texture_component(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value or "").lower())).strip("_")


def _build_source_driven_sidecar_text(
    sidecar_text: str,
    target_bindings: Mapping[str, Sequence[tuple[str, str, str]]],
) -> tuple[str, int, set[str], set[str]]:
    wrapper_pattern = re.compile(
        r"\s*<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    default_bindings: Sequence[tuple[str, str, str]] = ()
    unique_binding_sets = {
        tuple((parameter, texture_path, slot_kind) for parameter, texture_path, slot_kind in bindings)
        for bindings in target_bindings.values()
    }
    if len(unique_binding_sets) == 1:
        default_bindings = next(iter(unique_binding_sets))
    changed_count = 0
    used_texture_paths: set[str] = set()
    changed_wrapper_names: set[str] = set()

    def replace_wrapper(match: re.Match[str]) -> str:
        nonlocal changed_count, used_texture_paths, changed_wrapper_names
        wrapper_text = match.group(0)
        wrapper_name = _source_driven_wrapper_name(wrapper_text)
        bindings = _source_driven_bindings_for_wrapper(wrapper_name, target_bindings, default_bindings)
        if not bindings:
            return wrapper_text
        patched_wrapper, changed, wrapper_used_paths = _patch_source_driven_wrapper_texture_slots(wrapper_text, bindings)
        if changed:
            changed_count += 1
            used_texture_paths.update(wrapper_used_paths)
            if wrapper_name:
                changed_wrapper_names.add(wrapper_name)
            return patched_wrapper
        return wrapper_text

    return (
        wrapper_pattern.sub(replace_wrapper, str(sidecar_text or "")),
        changed_count,
        used_texture_paths,
        changed_wrapper_names,
    )


def _patch_source_driven_wrapper_texture_slots(
    wrapper_text: str,
    bindings: Sequence[tuple[str, str, str]],
) -> tuple[str, bool, set[str]]:
    patched = wrapper_text
    changed = False
    used_paths: set[str] = set()
    for _parameter_name, texture_path, slot_kind in bindings:
        slot = str(slot_kind or "").strip().lower()
        texture_value = str(texture_path or "").replace("\\", "/").strip()
        if not slot or not texture_value:
            continue
        if slot == "base":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"),
                texture_value,
                preferred_existing_roles=("base",),
                allow_unclassified_parameter=True,
            )
            if not did_change:
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    "_overlayColorTexture",
                    texture_value,
                )
        elif slot == "normal":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_normaltexture",),
                texture_value,
                preferred_existing_roles=("normal",),
                allow_unclassified_parameter=True,
            )
        elif slot == "height":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_heighttexture",),
                texture_value,
                preferred_existing_roles=("height",),
                allow_unclassified_parameter=True,
            )
        elif slot == "material_mask":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_colorblendingmasktexture", "_overlaycolortexture"),
                texture_value,
                preferred_existing_roles=("material_mask",),
                allow_unclassified_parameter=True,
            )
        elif slot == "detail_mask":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_detailmasktexture",),
                texture_value,
                preferred_existing_roles=("detail_mask",),
                allow_unclassified_parameter=True,
            )
        elif slot == "material":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_colorblendingmasktexture", "_detailmasktexture"),
                texture_value,
                preferred_existing_roles=("material", "material_mask", "detail_mask"),
                allow_unclassified_parameter=True,
            )
        elif slot == "emissive":
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                ("_emissiveintensitytexture", "_emissivetexture", "_emissiveprogresstexture"),
                texture_value,
                preferred_existing_roles=("emissive", "base"),
                allow_unclassified_parameter=True,
            )
            if not did_change:
                patched, did_change = _insert_source_driven_texture_parameter(
                    patched,
                    "_emissiveIntensityTexture",
                    texture_value,
                )
            if did_change:
                patched = re.sub(
                    r'(<Material\b[^>]*\b_materialName=")([^"]*)(")',
                    r"\1SkinnedMeshEmissive_Ver2\3",
                    patched,
                    count=1,
                    flags=re.IGNORECASE | re.DOTALL,
                )
        else:
            did_change = False
        if did_change:
            changed = True
            used_paths.add(texture_value)
    return patched, changed, used_paths


def _replace_source_driven_texture_parameter(
    wrapper_text: str,
    candidate_names: Sequence[str],
    texture_path: str,
    *,
    rename_to: str = "",
    preferred_existing_roles: Sequence[str] = (),
    allow_unclassified_parameter: bool = False,
) -> tuple[str, bool]:
    normalized_candidates = {str(name or "").strip().lower() for name in candidate_names if str(name or "").strip()}
    if not normalized_candidates:
        return wrapper_text, False
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    normalized_preferred_roles = {
        str(role or "").strip().lower()
        for role in preferred_existing_roles
        if str(role or "").strip()
    }
    matches: list[tuple[int, re.Match[str], str]] = []
    for match in texture_pattern.finditer(wrapper_text):
        block = match.group(0)
        block_name = _sidecar_parameter_name(block).lower()
        if block_name not in normalized_candidates:
            continue
        path_match = re.search(r'\b(?:_path|path|Path|_value|Value|value)="([^"]*)"', block, flags=re.IGNORECASE)
        existing_path = path_match.group(1) if path_match is not None else ""
        role = _texture_role_for_parameter_and_path(block_name, existing_path)
        if normalized_preferred_roles:
            if role in normalized_preferred_roles:
                score = 100
            elif allow_unclassified_parameter and not infer_cd_texture_role_from_path(existing_path):
                score = 30
            else:
                continue
        else:
            score = 50
        matches.append((score, match, block))
    if not matches:
        return wrapper_text, False
    matches.sort(key=lambda item: item[0], reverse=True)
    _score, match, block = matches[0]
    patched_block = block
    if rename_to:
        patched_block = _rename_sidecar_parameter_name(patched_block, rename_to)
    patched_block = re.sub(
        r'(\b(?:_path|path|Path|_value|Value|value)=")[^"]*(")',
        lambda path_match: f'{path_match.group(1)}{_escape_xml_attr(texture_path)}{path_match.group(2)}',
        patched_block,
        count=1,
        flags=re.IGNORECASE,
    )
    if patched_block == block:
        return wrapper_text, False
    return wrapper_text[: match.start()] + patched_block + wrapper_text[match.end() :], True


def _insert_source_driven_texture_parameter(
    wrapper_text: str,
    parameter_name: str,
    texture_path: str,
) -> tuple[str, bool]:
    normalized_parameter = str(parameter_name or "").strip()
    normalized_texture_path = str(texture_path or "").replace("\\", "/").strip()
    if not wrapper_text or not normalized_parameter or not normalized_texture_path:
        return wrapper_text, False

    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    lower_parameter = normalized_parameter.lower()
    for match in texture_pattern.finditer(wrapper_text):
        if _sidecar_parameter_name(match.group(0)).lower() == lower_parameter:
            return wrapper_text, False

    parameter_vector_match = re.search(
        r'(<Vector\b[^>]*\bName="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        wrapper_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not parameter_vector_match:
        return wrapper_text, False

    parameter_body = parameter_vector_match.group(2)
    insert_offset_in_body, insert_index = _sidecar_texture_injection_position(parameter_body, normalized_parameter)
    if insert_index is None:
        insert_index = _next_material_parameter_index(wrapper_text)

    indent_match = re.search(r"\n([ \t]*)<MaterialParameter", wrapper_text)
    parameter_indent = indent_match.group(1) if indent_match else "\t\t\t\t\t\t\t"
    value_indent = f"{parameter_indent}\t"
    escaped_parameter = _escape_xml_attr(normalized_parameter)
    escaped_path = _escape_xml_attr(normalized_texture_path)
    item_id = _source_driven_parameter_item_id(normalized_parameter)
    block = (
        f'\n{parameter_indent}<MaterialParameterTexture StringItemID="{escaped_parameter}" '
        f'ItemID="{item_id}" _name="{escaped_parameter}" Index="{insert_index}">'
        f'\n{value_indent}<ResourceReferencePath_ITexture Name="_value" _path="{escaped_path}"/>'
        f"\n{parameter_indent}</MaterialParameterTexture>"
    )

    if insert_offset_in_body is not None:
        parameter_body = _shift_sidecar_parameter_indexes(parameter_body, insert_index)
        new_parameter_body = parameter_body[:insert_offset_in_body] + block + parameter_body[insert_offset_in_body:]
    else:
        new_parameter_body = parameter_body + block

    return (
        wrapper_text[: parameter_vector_match.start(2)]
        + new_parameter_body
        + wrapper_text[parameter_vector_match.end(2) :],
        True,
    )


def _source_driven_wrapper_name(wrapper_text: str) -> str:
    name_match = re.search(
        r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
        wrapper_text,
        flags=re.IGNORECASE,
    )
    return str(name_match.group(1) if name_match else "").strip()


def _source_driven_bindings_for_wrapper(
    wrapper_name: str,
    target_bindings: Mapping[str, Sequence[tuple[str, str, str]]],
    default_bindings: Sequence[tuple[str, str, str]],
) -> Sequence[tuple[str, str, str]]:
    if not target_bindings:
        return ()
    if is_static_replacement_helper_material_name(wrapper_name):
        return ()
    wrapper_key = _normalize_sidecar_material_name(wrapper_name)
    for target_name, bindings in target_bindings.items():
        if wrapper_key and wrapper_key == _normalize_sidecar_material_name(target_name):
            return bindings
    best_score = 0.0
    best_bindings: Sequence[tuple[str, str, str]] = ()
    for target_name, bindings in target_bindings.items():
        score = _sidecar_material_match_score(wrapper_name, target_name)
        if score > best_score:
            best_score = score
            best_bindings = bindings
    if best_score >= 6.0:
        return best_bindings
    return default_bindings


def _source_driven_parameter_body(bindings: Sequence[tuple[str, str, str]]) -> str:
    lines = [
        '\n\t\t\t\t\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" ItemID="8" _name="_renderSettingFlag" _value="4" Index="0"/>'
    ]
    index = 1
    for parameter_name, texture_path, _slot_kind in bindings:
        item_id = _source_driven_parameter_item_id(parameter_name)
        escaped_parameter = _escape_xml_attr(parameter_name)
        escaped_path = _escape_xml_attr(texture_path)
        lines.append(
            f'\n\t\t\t\t\t\t\t<MaterialParameterTexture StringItemID="{escaped_parameter}" ItemID="{item_id}" _name="{escaped_parameter}" Index="{index}">'
            f'\n\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path="{escaped_path}"/>'
            "\n\t\t\t\t\t\t\t</MaterialParameterTexture>"
        )
        index += 1
    return "".join(lines)


def _source_driven_parameter_item_id(parameter_name: str) -> str:
    normalized = str(parameter_name or "").strip().lower()
    return {
        "_overlaycolortexture": "1",
        "_normaltexture": "6",
        "_heighttexture": "4",
        "_emissivetexture": "271587251638718",
        "_emissiveintensitytexture": "1832808279553406",
        "_emissiveprogresstexture": "370587223877118",
        "_materialtexture": "3401228360876030",
        "_metallictexture": "488189023223806",
        "_roughnesstexture": "638052851515390",
        "_ambientocclusiontexture": "1028073018359806",
    }.get(normalized, "0")


def _is_direct_pac_driven_parameter(reference: object, target_path: str) -> bool:
    if not target_path.lower().endswith(".dds"):
        return False
    if _is_shared_material_layer_texture(target_path):
        return False
    parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
    return parameter in {
        "_overlaycolortexture",
        "_basecolortexture",
        "_diffusetexture",
        "_albedotexture",
        "_normaltexture",
        "_heighttexture",
        "_emissiveintensitytexture",
        "_emissivetexture",
        "_emissiveprogresstexture",
        "_colorblendingmasktexture",
        "_detailmasktexture",
    }


def _build_base_color_injection_for_target(
    *,
    target_name: str,
    texture_set: ReplacementTextureSet,
    original_texture_refs: Sequence[object],
    material_refs: Sequence[object],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
) -> tuple[list[TextureReplacementPayload], list[SidecarTextureParameterInjection]]:
    base_slot = texture_set.slots.get("base")
    if base_slot is None:
        return [], []
    template_reference = _base_color_template_reference(material_refs) or _base_color_template_reference(original_texture_refs)
    if template_reference is None or getattr(template_reference, "resolved_entry", None) is None:
        report.warnings.append(
            f"{target_name}: cannot inject _overlayColorTexture because no compatible base texture template was found."
        )
        return [], []
    output_texture_path = _infer_base_color_path_for_material(
        original_texture_refs,
        target_name,
        fallback_parent=_reference_target_parent(template_reference),
    )
    if not output_texture_path:
        report.warnings.append(f"{target_name}: could not infer output path for injected base color texture.")
        return [], []
    try:
        payload_data = _build_texture_payload(
            base_slot,
            target_entry=getattr(template_reference, "resolved_entry", None),
            texconv_path=texconv_path,
            read_original_texture_bytes=read_original_texture_bytes,
            original_texture_source_path=original_texture_source_path,
            report=report,
            on_log=on_log,
            texture_output_size_mode=texture_output_size_mode,
        )
    except Exception as exc:
        report.errors.append(f"Failed to build injected base-color texture for {target_name}: {exc}")
        return [], []
    payload = TextureReplacementPayload(
        target_path=output_texture_path,
        payload_data=payload_data,
        kind="texture_generated",
        source_path=base_slot.source_path,
        note=f"PAC-driven injected _overlayColorTexture for {target_name}",
    )
    report.slot_mappings.append(
        TextureSlotMapping(
            target_material_name=target_name,
            target_texture_path="(injected _overlayColorTexture)",
            slot_kind="base",
            source_material_name=base_slot.material_name,
            source_path=base_slot.source_path,
            output_texture_path=output_texture_path,
            normal_space=base_slot.normal_space,
        )
    )
    report.warnings.append(
        f"PAC XML rebuild: added _overlayColorTexture for {target_name} using {base_slot.source_path.name}."
    )
    return [payload], [
        SidecarTextureParameterInjection(
            target_material_name=target_name,
            parameter_name="_overlayColorTexture",
            texture_path=output_texture_path,
            anchor_texture_paths=tuple(
                _reference_target_path(reference)
                for reference in material_refs
                if _reference_target_path(reference)
            ),
        )
    ]


def _sidecar_keep_rules_from_slot_mappings(
    slot_mappings: Sequence[TextureSlotMapping],
    references_by_target_path: Mapping[str, object],
) -> list[tuple[str, str]]:
    keep_rules: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for mapping in slot_mappings:
        output_path = _normalize_texture_path(mapping.output_texture_path)
        if not output_path:
            continue
        parameter_name = ""
        target_path = str(mapping.target_texture_path or "").replace("\\", "/").strip()
        if target_path.startswith("("):
            parameter_match = re.search(r"source-driven\s+([^)\s]+)", target_path, flags=re.IGNORECASE)
            parameter_name = parameter_match.group(1) if parameter_match is not None else "_overlayColorTexture"
        else:
            reference = references_by_target_path.get(_normalize_texture_path(target_path))
            parameter_name = str(getattr(reference, "sidecar_parameter_name", "") or "").strip()
            if (
                str(mapping.slot_kind or "").strip().lower() == "base"
                and parameter_name.lower() == "_colorblendingmasktexture"
            ):
                parameter_name = "_overlayColorTexture"
        if not _should_keep_rebuilt_sidecar_texture_parameter(parameter_name, mapping.slot_kind):
            continue
        key = (parameter_name.strip().lower(), output_path)
        if key in seen:
            continue
        seen.add(key)
        keep_rules.append(key)
    return keep_rules


def _should_keep_rebuilt_sidecar_texture_parameter(parameter_name: str, slot_kind: str) -> bool:
    normalized_parameter = str(parameter_name or "").strip().lower()
    normalized_slot = str(slot_kind or "").strip().lower()
    if normalized_parameter in {
        "_overlaycolortexture",
        "_basecolortexture",
        "_diffusetexture",
        "_albedotexture",
        "_normaltexture",
        "_heighttexture",
        "_emissiveintensitytexture",
        "_emissivetexture",
        "_emissiveprogresstexture",
    }:
        return True
    if normalized_slot in {"material", "material_mask", "detail_mask"} and normalized_parameter in {
        "_colorblendingmasktexture",
        "_detailmasktexture",
        "_overlaycolortexture",
    }:
        return True
    return False


def _build_patched_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    sidecar_replacements_by_path: Mapping[str, str],
    sidecar_parameter_injections: Sequence[SidecarTextureParameterInjection],
    sidecar_parameter_renames: Sequence[SidecarTextureParameterRename] = (),
    texture_parameter_keep_rules: Sequence[tuple[str, str]] = (),
    prune_unmapped_texture_parameters: bool = False,
    prune_material_names: Sequence[str] = (),
    neutralize_inherited_material_layers: bool = False,
    complete_external_material_reset: bool = False,
    neutralize_material_names: Sequence[str] = (),
    report: TextureReplacementReport,
    include_unchanged_clone: bool = False,
) -> list[TextureReplacementPayload]:
    if not original_sidecars or not (
        include_unchanged_clone
        or sidecar_replacements_by_path
        or sidecar_parameter_injections
        or sidecar_parameter_renames
        or prune_unmapped_texture_parameters
        or neutralize_inherited_material_layers
    ):
        return []
    sidecar_payloads: list[TextureReplacementPayload] = []
    for sidecar_entry, sidecar_text in original_sidecars:
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        patched_text, sidecar_report = patch_material_sidecar_text(
            sidecar_text,
            SidecarPatchPlan(
                sidecar_path=sidecar_path,
                texture_path_replacements=dict(sidecar_replacements_by_path),
                texture_parameter_injections=list(sidecar_parameter_injections),
                texture_parameter_renames=list(sidecar_parameter_renames),
                texture_parameter_keep_rules=list(texture_parameter_keep_rules),
                prune_unmapped_texture_parameters=bool(prune_unmapped_texture_parameters),
                prune_material_names=list(prune_material_names),
                neutralize_inherited_material_layers=bool(neutralize_inherited_material_layers),
                complete_external_material_reset=bool(complete_external_material_reset),
                neutralize_material_names=list(neutralize_material_names),
            ),
        )
        report.sidecar_reports.append(sidecar_report)
        for warning in sidecar_report.warnings:
            if (
                ("unmapped original texture parameter" in warning or "Neutralized inherited material layers" in warning)
                and warning not in report.warnings
            ):
                report.warnings.append(warning)
        if sidecar_report.replaced_count <= 0 and prune_unmapped_texture_parameters:
            report.warnings.append(
                f"Skipped unchanged rebuilt sidecar {PurePosixPath(sidecar_path).name}; no texture parameters were patched or pruned."
            )
            continue
        if sidecar_report.replaced_count <= 0 and not include_unchanged_clone:
            report.warnings.append(
                f"Patched sidecar {PurePosixPath(sidecar_path).name} did not apply any texture path or parameter changes."
            )
            continue
        payload_note = (
            "PAC-driven material sidecar cloned from original archive entry."
            if sidecar_report.replaced_count <= 0
            else "PAC-driven material sidecar patched from original archive entry."
        )
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note=payload_note,
            )
        )
    return sidecar_payloads


def _build_removed_target_prune_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    removed_target_material_names: Sequence[str],
    keep_rules: Sequence[tuple[str, str]],
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    removed_names = [
        str(name or "").strip()
        for name in tuple(removed_target_material_names or ())
        if str(name or "").strip()
    ]
    if not original_sidecars or not removed_names:
        return []
    payloads = _build_patched_sidecar_payloads(
        original_sidecars=original_sidecars,
        sidecar_replacements_by_path={},
        sidecar_parameter_injections=(),
        texture_parameter_keep_rules=keep_rules,
        prune_unmapped_texture_parameters=True,
        prune_material_names=removed_names,
        report=report,
    )
    if payloads:
        report.warnings.append(
            "Removed original target texture parameters from patched material sidecar for: "
            + ", ".join(removed_names[:8])
            + ("..." if len(removed_names) > 8 else "")
        )
    return payloads


def _overlay_original_sidecars_with_payloads(
    original_sidecars: Sequence[tuple[object, str]],
    generated_payloads: Sequence[TextureReplacementPayload],
) -> tuple[tuple[object, str], ...]:
    generated_sidecar_text_by_path: dict[str, str] = {}
    for payload in tuple(generated_payloads or ()):
        if str(getattr(payload, "kind", "") or "") != "sidecar_generated":
            continue
        target_path = _normalize_texture_path(getattr(payload, "target_path", ""))
        if not target_path or not getattr(payload, "payload_data", b""):
            continue
        try:
            generated_sidecar_text_by_path[target_path] = bytes(payload.payload_data).decode("utf-8", errors="ignore")
        except Exception:
            continue
    if not generated_sidecar_text_by_path:
        return tuple(original_sidecars or ())
    overlaid: list[tuple[object, str]] = []
    for sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        sidecar_path = _normalize_texture_path(str(getattr(sidecar_entry, "path", "") or ""))
        overlaid.append((sidecar_entry, generated_sidecar_text_by_path.get(sidecar_path, sidecar_text)))
    return tuple(overlaid)


def _replace_sidecar_payloads(
    generated_payloads: Sequence[TextureReplacementPayload],
    replacement_sidecar_payloads: Sequence[TextureReplacementPayload],
) -> list[TextureReplacementPayload]:
    replacement_targets = {
        _normalize_texture_path(getattr(payload, "target_path", ""))
        for payload in tuple(replacement_sidecar_payloads or ())
        if _normalize_texture_path(getattr(payload, "target_path", ""))
    }
    if not replacement_targets:
        return list(generated_payloads or ())
    return [
        payload
        for payload in tuple(generated_payloads or ())
        if not (
            str(getattr(payload, "kind", "") or "") == "sidecar_generated"
            and _normalize_texture_path(getattr(payload, "target_path", "")) in replacement_targets
        )
    ] + list(replacement_sidecar_payloads or ())


def _build_donor_material_texture_payloads(
    donor_material_plans: Sequence[object],
    *,
    existing_payloads: Sequence[TextureReplacementPayload] = (),
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    payloads: list[TextureReplacementPayload] = []
    emitted = {
        _normalize_texture_path(getattr(payload, "target_path", ""))
        for payload in tuple(existing_payloads or ())
        if _normalize_texture_path(getattr(payload, "target_path", ""))
    }
    missing_count = 0
    for plan in tuple(donor_material_plans or ()):
        if not bool(getattr(plan, "enabled", True)):
            continue
        for binding in tuple(getattr(plan, "texture_bindings", ()) or ()):
            target_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            source_path_text = str(getattr(binding, "source_path", "") or "").strip()
            if not target_path or not source_path_text:
                continue
            normalized_target = _normalize_texture_path(target_path)
            if not normalized_target or normalized_target in emitted:
                continue
            try:
                source_path = Path(source_path_text).expanduser()
            except OSError:
                missing_count += 1
                continue
            if not source_path.is_file():
                missing_count += 1
                continue
            try:
                payload_data = source_path.read_bytes()
            except OSError as exc:
                report.warnings.append(f"Donor material texture could not be read: {source_path.name}: {exc}")
                continue
            payloads.append(
                TextureReplacementPayload(
                    target_path=target_path,
                    payload_data=payload_data,
                    kind="texture_donor_material",
                    source_path=source_path,
                    note="Donor material recipe texture included for patched sidecar.",
                )
            )
            emitted.add(normalized_target)
    if payloads:
        report.warnings.append(f"Included {len(payloads):,} donor material recipe texture file(s).")
    if missing_count:
        report.warnings.append(
            f"{missing_count:,} donor material texture reference(s) had no readable local DDS source; "
            "the patched sidecar may rely on files already present in the target archive."
        )
    return payloads


def _sidecar_kind_from_path(path_value: object) -> str:
    normalized = str(path_value or "").replace("\\", "/").strip().lower()
    if normalized.endswith(".pac_xml") or normalized.endswith(".pac.xml"):
        return "pac_xml"
    if normalized.endswith(".pami"):
        return "pami"
    if normalized.endswith(".pam_xml") or normalized.endswith(".pam.xml"):
        return "pam_xml"
    if normalized.endswith(".pamlod_xml") or normalized.endswith(".pamlod.xml"):
        return "pamlod_xml"
    if normalized.endswith(".xml"):
        return "xml"
    return ""


def _donor_plan_texture_bindings(plan: object) -> tuple[tuple[str, str, str, str], ...]:
    rows: list[tuple[str, str, str, str]] = []
    for binding in tuple(getattr(plan, "texture_bindings", ()) or ()):
        parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
        texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
        if not texture_path:
            continue
        slot_kind = str(getattr(binding, "slot_kind", "") or "").strip().lower()
        semantic_subtype = str(getattr(binding, "semantic_subtype", "") or "").strip().lower()
        if not slot_kind:
            slot_kind = _infer_slot_kind(parameter_name, texture_path)
        rows.append((parameter_name, texture_path, slot_kind, semantic_subtype))
    return tuple(rows)


def _donor_plan_anchor_texture_paths(plan: object) -> tuple[str, ...]:
    paths: list[str] = []
    for raw_path in tuple(getattr(plan, "donor_anchor_texture_paths", ()) or ()):
        path_text = str(raw_path or "").replace("\\", "/").strip()
        if path_text and path_text not in paths:
            paths.append(path_text)
    for _parameter_name, texture_path, _slot_kind, _semantic_subtype in _donor_plan_texture_bindings(plan):
        if texture_path and texture_path not in paths:
            paths.append(texture_path)
    return tuple(paths)


def _donor_binding_is_emissive(parameter_name: str, texture_path: str, semantic_subtype: str = "") -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", f"{parameter_name} {texture_path} {semantic_subtype}".lower())
    return any(token in compact for token in ("emissive", "glow", "illum", "emit"))


def _donor_parameter_candidates(parameter_name: str, slot_kind: str, texture_path: str, semantic_subtype: str = "") -> tuple[str, ...]:
    candidates: list[str] = []

    def add(value: str) -> None:
        key = str(value or "").strip()
        if key and key.lower() not in {candidate.lower() for candidate in candidates}:
            candidates.append(key)

    add(parameter_name)
    normalized_slot = str(slot_kind or "").strip().lower()
    if _donor_binding_is_emissive(parameter_name, texture_path, semantic_subtype):
        for name in ("_emissiveTexture", "_emissiveIntensityTexture", "_emissiveProgressTexture"):
            add(name)
        return tuple(candidates)
    if normalized_slot == "base":
        for name in ("_overlayColorTexture", "_baseColorTexture", "_diffuseTexture", "_albedoTexture"):
            add(name)
    elif normalized_slot == "normal":
        add("_normalTexture")
    elif normalized_slot == "height":
        add("_heightTexture")
    elif normalized_slot in {"material", "material_mask"}:
        for name in ("_colorBlendingMaskTexture", "_detailMaskTexture"):
            add(name)
    elif normalized_slot == "detail_mask":
        add("_detailMaskTexture")
    return tuple(candidates)


def _patch_donor_texture_bindings_into_wrapper(
    wrapper_text: str,
    plan: object,
) -> tuple[str, bool, set[str]]:
    patched = wrapper_text
    changed = False
    used_paths: set[str] = set()
    for parameter_name, texture_path, slot_kind, semantic_subtype in _donor_plan_texture_bindings(plan):
        exact_candidates = (parameter_name,) if parameter_name else ()
        did_change = False
        if exact_candidates:
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                exact_candidates,
                texture_path,
                allow_unclassified_parameter=True,
            )
        if not did_change:
            preferred_existing_roles: tuple[str, ...] = ()
            if not _donor_binding_is_emissive(parameter_name, texture_path, semantic_subtype) and slot_kind:
                preferred_existing_roles = (slot_kind,)
            patched, did_change = _replace_source_driven_texture_parameter(
                patched,
                _donor_parameter_candidates(parameter_name, slot_kind, texture_path, semantic_subtype),
                texture_path,
                preferred_existing_roles=preferred_existing_roles,
                allow_unclassified_parameter=True,
            )
        if did_change:
            changed = True
            used_paths.add(texture_path)
    return patched, changed, used_paths


def _texture_parameter_paths_by_name(
    wrapper_text: str,
    parameter_names: Sequence[str],
) -> dict[str, str]:
    wanted = {str(name or "").strip().lower() for name in tuple(parameter_names or ()) if str(name or "").strip()}
    if not wanted:
        return {}
    paths: dict[str, str] = {}
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(str(wrapper_text or "")):
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block).strip().lower()
        if parameter_name not in wanted or parameter_name in paths:
            continue
        path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        texture_path = str(path_match.group(1) if path_match else "").replace("\\", "/").strip()
        if texture_path:
            paths[parameter_name] = texture_path
    return paths


def _restore_texture_parameter_paths(
    wrapper_text: str,
    texture_paths_by_parameter: Mapping[str, str],
) -> tuple[str, int]:
    patched = wrapper_text
    changed_count = 0
    for parameter_name, texture_path in texture_paths_by_parameter.items():
        patched, changed = _replace_source_driven_texture_parameter(
            patched,
            (parameter_name,),
            texture_path,
            allow_unclassified_parameter=True,
        )
        if changed:
            changed_count += 1
    return patched, changed_count


def _donor_texture_patch_covers_selected_bindings(plan: object, used_paths: set[str]) -> bool:
    required_paths = {
        _normalize_texture_path(texture_path)
        for _parameter_name, texture_path, _slot_kind, _semantic_subtype in _donor_plan_texture_bindings(plan)
        if _normalize_texture_path(texture_path)
    }
    if not required_paths:
        return False
    normalized_used_paths = {_normalize_texture_path(path) for path in used_paths if _normalize_texture_path(path)}
    return required_paths <= normalized_used_paths


def _wrapper_open_close(wrapper_text: str) -> tuple[Optional[re.Match[str]], Optional[re.Match[str]]]:
    open_match = re.match(r"\s*<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>", wrapper_text, flags=re.IGNORECASE | re.DOTALL)
    if open_match is None:
        return None, None
    close_matches = list(
        re.finditer(rf"</{re.escape(open_match.group('tag'))}>\s*$", wrapper_text, flags=re.IGNORECASE | re.DOTALL)
    )
    return open_match, close_matches[-1] if close_matches else None


def _retarget_wrapper_submesh_attrs(wrapper_text: str, target_name: str) -> str:
    escaped_target = _escape_xml_attr(target_name)
    patched = wrapper_text
    for attr in ("_subMeshName", "subMeshName", "SubMeshName", "PrimitiveName", "primitiveName"):
        patched = re.sub(
            rf'({attr}=")[^"]*(")',
            lambda match: f"{match.group(1)}{escaped_target}{match.group(2)}",
            patched,
            flags=re.IGNORECASE,
        )
    return patched


def _graft_donor_wrapper_payload(target_wrapper_text: str, donor_wrapper_text: str, target_name: str) -> tuple[str, bool]:
    target_open, target_close = _wrapper_open_close(target_wrapper_text)
    donor_open, donor_close = _wrapper_open_close(donor_wrapper_text)
    if target_open is None or target_close is None or donor_open is None or donor_close is None:
        return target_wrapper_text, False
    donor_inner = donor_wrapper_text[donor_open.end() : donor_close.start()]
    patched = (
        target_wrapper_text[: target_open.start()]
        + target_open.group(0)
        + donor_inner
        + target_close.group(0)
        + target_wrapper_text[target_close.end() :]
    )
    patched = _retarget_wrapper_submesh_attrs(patched, target_name)
    return patched, patched != target_wrapper_text


def _target_wrapper_for_donor_plan(sidecar_text: str, plan: object) -> Optional[re.Match[str]]:
    target_name = str(getattr(plan, "target_material_name", "") or "").strip()
    if target_name:
        wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
        if wrapper_match is not None:
            return wrapper_match
    return _find_sidecar_material_wrapper_by_texture_paths(
        sidecar_text,
        tuple(getattr(plan, "target_anchor_texture_paths", ()) or ()),
    )


def _donor_wrapper_for_plan(plan: object) -> Optional[re.Match[str]]:
    donor_text = str(getattr(plan, "donor_sidecar_text", "") or "")
    if not donor_text.strip():
        return None
    for candidate in (
        str(getattr(plan, "donor_submesh_name", "") or "").strip(),
        str(getattr(plan, "donor_material_name", "") or "").strip(),
    ):
        if not candidate:
            continue
        wrapper_match = _find_sidecar_material_wrapper(donor_text, candidate)
        if wrapper_match is not None:
            return wrapper_match
    return _find_sidecar_material_wrapper_by_texture_paths(donor_text, _donor_plan_anchor_texture_paths(plan))


def _apply_donor_material_plan_to_sidecar(
    sidecar_text: str,
    *,
    sidecar_path: str,
    plan: object,
    report: TextureReplacementReport,
) -> tuple[str, bool, bool]:
    wrapper_match = _target_wrapper_for_donor_plan(sidecar_text, plan)
    if wrapper_match is None:
        return sidecar_text, False, False
    target_name = str(getattr(plan, "target_material_name", "") or "").strip()
    patch_mode = str(getattr(plan, "patch_mode", "") or "material_behavior").strip().lower()
    target_kind = _sidecar_kind_from_path(sidecar_path)
    donor_kind = str(getattr(plan, "donor_sidecar_kind", "") or "").strip().lower()
    if not donor_kind:
        donor_kind = _sidecar_kind_from_path(getattr(plan, "donor_sidecar_path", ""))

    if patch_mode in {
        "authoritative_recipe",
        "donor_authoritative_recipe",
        "authoritative_material_recipe",
        "full_recipe",
        "full_donor_recipe",
    }:
        if target_kind != "pac_xml" or donor_kind != "pac_xml":
            report.warnings.append(
                f"Authoritative donor material recipe for {target_name or 'target wrapper'} needs matching .pac_xml wrappers "
                f"({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
            )
            return sidecar_text, False, True
        donor_wrapper_match = _donor_wrapper_for_plan(plan)
        if donor_wrapper_match is None:
            report.warnings.append(
                f"Authoritative donor material recipe could not find donor wrapper for {target_name or 'target wrapper'}."
            )
            return sidecar_text, False, True
        new_wrapper, grafted = _graft_donor_wrapper_payload(
            wrapper_match.group(0),
            donor_wrapper_match.group(0),
            target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
        )
        if grafted:
            patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
            report.warnings.append(
                f"Authoritative donor material recipe grafted: "
                f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> "
                f"{target_name or 'target wrapper'}; donor texture/shader parameters replaced inherited target material bindings."
            )
            return patched, True, True
        report.warnings.append(
            f"Authoritative donor material recipe graft made no changes for {target_name or 'target wrapper'}."
        )
        return sidecar_text, False, True

    if patch_mode in {"material_profile", "donor_material_profile", "profile", "profile_graft"}:
        if target_kind != "pac_xml" or donor_kind != "pac_xml":
            report.warnings.append(
                f"Donor material profile for {target_name or 'target wrapper'} needs matching .pac_xml wrappers "
                f"({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
            )
            return sidecar_text, False, True
        donor_wrapper_match = _donor_wrapper_for_plan(plan)
        if donor_wrapper_match is None:
            report.warnings.append(f"Donor material profile could not find donor wrapper for {target_name or 'target wrapper'}.")
            return sidecar_text, False, True
        preserved_paths = _texture_parameter_paths_by_name(
            wrapper_match.group(0),
            (
                "_overlayColorTexture",
                "_baseColorTexture",
                "_diffuseTexture",
                "_albedoTexture",
                "_normalTexture",
            ),
        )
        new_wrapper, grafted = _graft_donor_wrapper_payload(
            wrapper_match.group(0),
            donor_wrapper_match.group(0),
            target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
        )
        if grafted and preserved_paths:
            new_wrapper, restored_count = _restore_texture_parameter_paths(new_wrapper, preserved_paths)
        else:
            restored_count = 0
        if grafted:
            patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
            report.warnings.append(
                f"Donor material profile grafted: "
                f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> "
                f"{target_name or 'target wrapper'}; preserved {restored_count:,} target base/normal texture binding(s)."
            )
            return patched, True, True
        report.warnings.append(f"Donor material profile graft made no changes for {target_name or 'target wrapper'}.")
        return sidecar_text, False, True

    if patch_mode in {"material_behavior", "donor_material_behavior", "graft", "wrapper_graft"}:
        if target_kind == "pac_xml" and donor_kind == "pac_xml":
            texture_patched_wrapper, texture_changed, used_paths = _patch_donor_texture_bindings_into_wrapper(wrapper_match.group(0), plan)
            if texture_changed and _donor_texture_patch_covers_selected_bindings(plan, used_paths):
                patched = sidecar_text[: wrapper_match.start()] + texture_patched_wrapper + sidecar_text[wrapper_match.end() :]
                report.warnings.append(
                    f"Donor material behavior used target-compatible texture parameters: "
                    f"{getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> {target_name or 'target wrapper'}."
                )
                return patched, True, True
            donor_wrapper_match = _donor_wrapper_for_plan(plan)
            if donor_wrapper_match is not None:
                new_wrapper, grafted = _graft_donor_wrapper_payload(
                    wrapper_match.group(0),
                    donor_wrapper_match.group(0),
                    target_name or _source_driven_wrapper_name(wrapper_match.group(0)),
                )
                if grafted:
                    patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
                    report.warnings.append(
                        f"Donor material behavior grafted: {getattr(plan, 'donor_material_name', '') or getattr(plan, 'donor_submesh_name', '')} -> {target_name or 'target wrapper'}."
                    )
                    return patched, True, True
                report.warnings.append(f"Donor material behavior graft made no changes for {target_name or 'target wrapper'}.")
                return sidecar_text, False, True
            report.warnings.append(f"Donor material behavior could not find donor wrapper for {target_name or 'target wrapper'}.")
            return sidecar_text, False, True
        report.warnings.append(
            f"Donor material behavior for {target_name or 'target wrapper'} needs matching .pac_xml wrappers; "
            f"falling back to donor texture binding ({donor_kind or 'unknown'} -> {target_kind or 'unknown'})."
        )

    new_wrapper, changed, _used_paths = _patch_donor_texture_bindings_into_wrapper(wrapper_match.group(0), plan)
    if not changed:
        report.warnings.append(f"Donor texture binding found no compatible target parameters for {target_name or 'target wrapper'}.")
        return sidecar_text, False, True
    patched = sidecar_text[: wrapper_match.start()] + new_wrapper + sidecar_text[wrapper_match.end() :]
    report.warnings.append(f"Donor texture binding patched target material wrapper: {target_name or 'target wrapper'}.")
    return patched, True, True


def _build_donor_material_sidecar_payloads(
    *,
    original_sidecars: Sequence[tuple[object, str]],
    donor_material_plans: Sequence[object],
    report: TextureReplacementReport,
) -> list[TextureReplacementPayload]:
    plans = tuple(plan for plan in tuple(donor_material_plans or ()) if bool(getattr(plan, "enabled", True)))
    if not plans:
        return []
    if not original_sidecars:
        report.warnings.append("Donor material source could not patch .pac_xml because no target material sidecar was available.")
        return []

    patched_by_path: dict[str, tuple[object, str, bool]] = {}
    for sidecar_entry, sidecar_text in tuple(original_sidecars or ()):
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "").strip()
        if sidecar_path:
            patched_by_path[sidecar_path] = (sidecar_entry, str(sidecar_text or ""), False)

    for plan in plans:
        target_name = str(getattr(plan, "target_material_name", "") or "").strip() or "target wrapper"
        plan_applied = False
        plan_matched_target = False
        for sidecar_path in list(patched_by_path):
            sidecar_entry, current_text, changed_before = patched_by_path[sidecar_path]
            patched_text, changed, matched_target = _apply_donor_material_plan_to_sidecar(
                current_text,
                sidecar_path=sidecar_path,
                plan=plan,
                report=report,
            )
            plan_matched_target = plan_matched_target or matched_target
            if changed:
                patched_by_path[sidecar_path] = (sidecar_entry, patched_text, True)
                plan_applied = True
                break
            patched_by_path[sidecar_path] = (sidecar_entry, current_text, changed_before)
        if not plan_matched_target:
            report.warnings.append(f"Donor material source target wrapper was not found: {target_name}.")
        elif not plan_applied:
            report.warnings.append(f"Donor material source did not modify target wrapper: {target_name}.")

    sidecar_payloads: list[TextureReplacementPayload] = []
    for sidecar_path, (_sidecar_entry, patched_text, changed) in patched_by_path.items():
        if not changed:
            continue
        sidecar_payloads.append(
            TextureReplacementPayload(
                target_path=sidecar_path,
                payload_data=patched_text.encode("utf-8"),
                kind="sidecar_generated",
                source_path=Path(PurePosixPath(sidecar_path).name),
                note="Donor material sidecar patched from another original mesh.",
            )
        )
    if sidecar_payloads:
        report.warnings.append(f"Generated {len(sidecar_payloads):,} donor material sidecar patch payload(s).")
    return sidecar_payloads


def _references_by_target_path(original_texture_refs: Sequence[object]) -> dict[str, object]:
    references: dict[str, object] = {}
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path:
            continue
        references.setdefault(_normalize_texture_path(target_path), reference)
        reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        if reference_name:
            references.setdefault(_normalize_texture_path(reference_name), reference)
    return references


def _normalize_texture_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


_SOURCE_MATERIAL_OVERRIDE_SLOT_ALIASES = {
    "basecolor": "base",
    "base_color": "base",
    "color": "base",
    "colour": "base",
    "diffuse": "base",
    "albedo": "base",
    "normalmap": "normal",
    "normal_map": "normal",
    "nrm": "normal",
    "heightmap": "height",
    "height_map": "height",
    "displacement": "height",
    "disp": "height",
    "materialmask": "material_mask",
    "material_mask": "material_mask",
    "mask_amg": "material_mask",
    "detailmask": "detail_mask",
    "detail_mask": "detail_mask",
    "detailmaterial": "detail_mask",
    "occlusion": "ao",
    "ambientocclusion": "ao",
    "ambient_occlusion": "ao",
    "specularglossiness": "material",
    "specular_glossiness": "material",
    "specgloss": "material",
    "clearcoat": "material",
    "clear_coat": "material",
    "emission": "emissive",
    "emissive": "emissive",
    "glow": "emissive",
    "illum": "emissive",
    "illumination": "emissive",
}


def _manual_target_texture_slot_overrides(texture_slot_overrides: Sequence[object]) -> tuple[object, ...]:
    return tuple(
        override
        for override in tuple(texture_slot_overrides or ())
        if _override_enabled(override) and _override_target_texture_path(override)
    )


def _apply_source_material_texture_overrides(
    texture_sets: dict[str, ReplacementTextureSet],
    *,
    obj_mesh: ParsedMesh,
    texture_slot_overrides: Sequence[object],
    source_material_texture_overrides: Sequence[object],
    report: TextureReplacementReport,
) -> None:
    applied_count = 0
    for raw_override in tuple(source_material_texture_overrides or ()) + tuple(texture_slot_overrides or ()):
        parsed = _parse_source_material_texture_override(raw_override)
        if parsed is None:
            continue
        source_material_name, slot_kind, source_path_text = parsed
        source_path = Path(source_path_text).expanduser()
        if not source_path.is_absolute():
            source_path = Path.cwd() / source_path
        source_path = source_path.resolve()
        if source_path.suffix.lower() not in {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}:
            _warn_once(report, f"Source-material texture override is not a supported image file: {source_path_text}")
            continue
        if not source_path.is_file():
            _warn_once(report, f"Source-material texture override file is missing: {source_path_text}")
            continue
        normalized_slot = _normalize_source_material_override_slot(slot_kind, source_path)
        if not normalized_slot:
            _warn_once(
                report,
                f"Source-material texture override for {source_material_name} did not specify a recognizable texture slot.",
            )
            continue
        source_role = infer_cd_texture_role_from_path(source_path_text)
        if (
            source_role
            and normalized_slot in {"base", "normal", "height", "material", "material_mask", "detail_mask", "ao", "emissive"}
            and source_role != normalized_slot
            and not (normalized_slot == "material" and source_role in {"material_mask", "detail_mask"})
        ):
            _warn_once(
                report,
                f"Source-material texture override role mismatch: {source_material_name} expects "
                f"{normalized_slot.replace('_', ' ')}, but {source_path.name} looks like {source_role.replace('_', ' ')}.",
            )
        material_name = _canonical_source_material_name(source_material_name, obj_mesh, texture_sets)
        texture_set = texture_sets.setdefault(material_name.lower(), ReplacementTextureSet(material_name=material_name))
        normal_space = _normal_space_for_source_path(source_path)
        texture_set.slots[normalized_slot] = ReplacementTextureSlot(
            material_name=texture_set.material_name,
            slot_kind=normalized_slot,
            source_path=source_path,
            normal_space=normal_space if normalized_slot == "normal" else "",
        )
        applied_count += 1
    if applied_count:
        _warn_once(report, f"Applied {applied_count:,} source-material texture override(s).")


def _parse_source_material_texture_override(raw_override: object) -> Optional[tuple[str, str, str]]:
    if not _override_enabled(raw_override):
        return None
    if isinstance(raw_override, Mapping):
        if _override_target_texture_path(raw_override):
            return None
        material_name = str(
            raw_override.get("source_material_name")
            or raw_override.get("material_name")
            or raw_override.get("source_material")
            or ""
        ).strip()
        slot_kind = str(raw_override.get("slot_kind") or raw_override.get("slot") or raw_override.get("role") or "").strip()
        source_path = str(raw_override.get("source_path") or raw_override.get("path") or "").strip()
    elif isinstance(raw_override, (tuple, list)) and len(raw_override) >= 3:
        material_name = str(raw_override[0] or "").strip()
        slot_kind = str(raw_override[1] or "").strip()
        source_path = str(raw_override[2] or "").strip()
    else:
        if _override_target_texture_path(raw_override):
            return None
        material_name = str(
            getattr(raw_override, "source_material_name", "")
            or getattr(raw_override, "material_name", "")
            or getattr(raw_override, "source_material", "")
            or ""
        ).strip()
        slot_kind = str(
            getattr(raw_override, "slot_kind", "")
            or getattr(raw_override, "slot", "")
            or getattr(raw_override, "role", "")
            or ""
        ).strip()
        source_path = str(getattr(raw_override, "source_path", "") or getattr(raw_override, "path", "") or "").strip()
    if not material_name or not source_path:
        return None
    return material_name, slot_kind, source_path


def _override_enabled(raw_override: object) -> bool:
    if isinstance(raw_override, Mapping):
        return bool(raw_override.get("enabled", True))
    if isinstance(raw_override, (tuple, list)) and len(raw_override) >= 4:
        return bool(raw_override[3])
    return bool(getattr(raw_override, "enabled", True))


def _override_target_texture_path(raw_override: object) -> str:
    if isinstance(raw_override, Mapping):
        return str(
            raw_override.get("target_texture_path")
            or raw_override.get("target_path")
            or raw_override.get("texture_path")
            or ""
        ).replace("\\", "/").strip()
    if isinstance(raw_override, (tuple, list)):
        return ""
    return str(
        getattr(raw_override, "target_texture_path", "")
        or getattr(raw_override, "target_path", "")
        or getattr(raw_override, "texture_path", "")
        or ""
    ).replace("\\", "/").strip()


def _normalize_source_material_override_slot(slot_kind: str, source_path: Path) -> str:
    normalized = str(slot_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _SOURCE_MATERIAL_OVERRIDE_SLOT_ALIASES.get(normalized, normalized)
    if normalized:
        return normalized
    source_role = infer_cd_texture_role_from_path(source_path.as_posix())
    if source_role:
        return source_role
    parsed = _parse_replacement_texture_filename(source_path, set())
    return parsed[1] if parsed is not None else ""


def _canonical_source_material_name(
    source_material_name: str,
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> str:
    raw_name = str(source_material_name or "").strip()
    key = raw_name.lower()
    existing = texture_sets.get(key)
    if existing is not None and str(existing.material_name or "").strip():
        return str(existing.material_name or "").strip()
    for submesh in getattr(obj_mesh, "submeshes", ()) or ():
        for value in (
            str(getattr(submesh, "material", "") or "").strip(),
            str(getattr(submesh, "name", "") or "").strip(),
        ):
            if value and value.lower() == key:
                return value
    return raw_name


def _normal_space_for_source_path(source_path: Path) -> str:
    stem = source_path.stem.lower()
    if "opengl" in stem:
        return "opengl"
    if "directx" in stem or "_dx" in stem:
        return "directx"
    return ""


def _build_manual_texture_slot_override_payloads(
    *,
    texture_slot_overrides: Sequence[object],
    reference_by_target_path: Mapping[str, object],
    texture_sets: Mapping[str, ReplacementTextureSet],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
) -> tuple[list[TextureReplacementPayload], dict[str, str]]:
    payloads: list[TextureReplacementPayload] = []
    sidecar_replacements: dict[str, str] = {}
    emitted_targets: set[str] = set()
    for override in texture_slot_overrides:
        if not bool(getattr(override, "enabled", True)):
            continue
        target_path = str(getattr(override, "target_texture_path", "") or "").replace("\\", "/").strip()
        source_path_text = str(getattr(override, "source_path", "") or "").strip()
        if not target_path or not source_path_text:
            continue
        normalized_target = _normalize_texture_path(target_path)
        if normalized_target in emitted_targets:
            continue
        reference = reference_by_target_path.get(normalized_target)
        if reference is None:
            report.warnings.append(f"Manual texture slot target was not found in original bindings: {target_path}")
            continue
        target_entry = getattr(reference, "resolved_entry", None)
        if target_entry is None:
            report.warnings.append(f"Manual texture slot target could not be resolved in archive: {target_path}")
            continue
        source_path = Path(source_path_text).expanduser().resolve()
        if not source_path.is_file():
            report.warnings.append(f"Manual texture source file is missing: {source_path_text}")
            continue
        slot_kind = str(getattr(override, "slot_kind", "") or "").strip().lower() or _infer_slot_kind(
            str(getattr(reference, "sidecar_parameter_name", "") or ""),
            target_path,
        )
        source_role = infer_cd_texture_role_from_path(source_path_text)
        if _is_shared_material_layer_texture(target_path):
            _warn_once(
                report,
                f"Manual texture override targets stock/shared shader texture {target_path}; this can tint the model, add grime/speckles, "
                "or affect shared material layers. Use only when intentionally editing a shader/detail layer.",
            )
        if source_role and slot_kind in {"base", "normal", "height", "material_mask", "detail_mask"} and source_role != slot_kind:
            _warn_once(
                report,
                f"Manual texture override role mismatch: {target_path} expects {slot_kind.replace('_', ' ')}, "
                f"but {source_path.name} looks like {source_role.replace('_', ' ')}.",
            )
        source_slot = _source_slot_from_manual_path(source_path, slot_kind, texture_sets)
        try:
            payload = _build_texture_payload(
                source_slot,
                target_entry=target_entry,
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
        except Exception as exc:
            report.errors.append(f"Failed to build manual replacement texture for {target_path}: {exc}")
            continue
        output_texture_path = _replacement_output_texture_path(source_slot, target_path)
        payloads.append(
            TextureReplacementPayload(
                target_path=output_texture_path,
                payload_data=payload,
                kind="texture_generated",
                source_path=source_slot.source_path,
                note=f"Manual texture slot: {source_slot.source_path.name} -> {output_texture_path}",
            )
        )
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name=str(getattr(override, "target_material_name", "") or getattr(reference, "material_name", "") or ""),
                target_texture_path=target_path,
                slot_kind=slot_kind,
                source_material_name=source_slot.material_name,
                source_path=source_slot.source_path,
                output_texture_path=output_texture_path,
                normal_space=source_slot.normal_space,
            )
        )
        original_reference_name = str(getattr(reference, "reference_name", "") or "").strip()
        if original_reference_name and original_reference_name != output_texture_path:
            sidecar_replacements[original_reference_name] = output_texture_path
        if target_path != output_texture_path:
            sidecar_replacements[target_path] = output_texture_path
        emitted_targets.add(normalized_target)
    if payloads:
        report.warnings.append(f"Applied {len(payloads):,} manual texture slot override(s).")
    return payloads, sidecar_replacements


def _source_slot_from_manual_path(
    source_path: Path,
    slot_kind: str,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> ReplacementTextureSlot:
    resolved_source = source_path.expanduser().resolve()
    for texture_set in texture_sets.values():
        for slot in texture_set.slots.values():
            if slot.source_path.expanduser().resolve() == resolved_source:
                return ReplacementTextureSlot(
                    material_name=slot.material_name,
                    slot_kind=slot_kind or slot.slot_kind,
                    source_path=resolved_source,
                    normal_space=slot.normal_space,
                )
    material_name = _manual_source_material_name(resolved_source)
    normal_space = "opengl" if "opengl" in resolved_source.stem.lower() else ("directx" if "directx" in resolved_source.stem.lower() or "_dx" in resolved_source.stem.lower() else "")
    return ReplacementTextureSlot(
        material_name=material_name,
        slot_kind=slot_kind or "material",
        source_path=resolved_source,
        normal_space=normal_space,
    )


def _manual_source_material_name(source_path: Path) -> str:
    parsed = _parse_replacement_texture_filename(source_path, set())
    if parsed is not None:
        return parsed[0]
    stem = source_path.stem
    return re.sub(
        r"_(base|base_color|basecolor|bc|bcol|diffuse|dif|di|albedo|alb|color|colour|col|c|o|emissive|emission|emi|em|glow|illum|illumination|detaildiffuse|detailcolor|decalbasecolor|waterfoam|normal|normalmap|normal_opengl|normal_directx|normal_dx|norm|nrm|nm|wn|n|detailnormal|wrinklenormal|damagenormal|height|hgt|hei|he|h|d|dmap|depth|disp|displacement|bump|pom|ssdm|wrinkledisplacement|metallicroughness|metallic_roughness|metalrough|metallicrough|roughnessmetallic|roughmetal|metallic|metalness|roughness|rough|rgh|gloss|gls|smooth|smoothness|mixed_ao|ambientocclusion|occlusion|ao|reflection|reflect|ref|material|mat|m|ma|mg|sp|spec|specular|specularglossiness|specular_glossiness|specgloss|clearcoat|clear_coat|orm|rma|mra|arm|opacity|alpha|op|subsurface|flow|vector|dr|rgb|mask|masks|mask_1bit|mask_amg|layermask|detailmask|detailmaterial|colorblendingmask|skindetailmask|grimediffuse|grimenormal|grimematerial|damagediffuse|damagematerial)$",
        "",
        stem,
        flags=re.IGNORECASE,
    ) or stem


def group_replacement_texture_sets(
    texture_files: Sequence[Path],
    *,
    obj_mesh: Optional[ParsedMesh] = None,
) -> dict[str, ReplacementTextureSet]:
    source_submeshes = list(obj_mesh.submeshes if obj_mesh is not None else [])
    known_materials = {
        name
        for sm in source_submeshes
        for name in (
            str(getattr(sm, "material", "") or "").strip(),
            str(getattr(sm, "name", "") or "").strip(),
        )
        if name
    }
    default_material = _default_texture_material_name(source_submeshes, known_materials)
    grouped: dict[str, ReplacementTextureSet] = {}
    for raw_path in texture_files:
        path = raw_path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix.lower() not in {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}:
            continue
        parsed = _parse_replacement_texture_filename(path, known_materials, default_material=default_material)
        if parsed is None:
            continue
        material_name, slot_kind, normal_space = parsed
        texture_set = grouped.setdefault(material_name.lower(), ReplacementTextureSet(material_name=material_name))
        existing = texture_set.slots.get(slot_kind)
        if existing is None or _texture_slot_priority(path, slot_kind) > _texture_slot_priority(existing.source_path, existing.slot_kind):
            texture_set.slots[slot_kind] = ReplacementTextureSlot(
                material_name=material_name,
                slot_kind=slot_kind,
                source_path=path,
                normal_space=normal_space,
            )
    _attach_source_texture_reference_base_slots(grouped, texture_files, source_submeshes)
    return grouped


def _parse_replacement_texture_filename(
    path: Path,
    known_materials: set[str],
    *,
    default_material: str = "",
) -> Optional[tuple[str, str, str]]:
    stem = path.stem
    lowered = stem.lower()
    matched: Optional[tuple[str, str, str, int]] = None
    for slot_kind, suffix, hint in _TEXTURE_SUFFIXES:
        suffix_match = _replacement_texture_suffix_match(stem, suffix)
        if suffix_match is None:
            continue
        prefix, suffix_score = suffix_match
        if not prefix:
            prefix = default_material
        if not prefix:
            continue
        prefix = _match_known_material_prefix(prefix, known_materials) or prefix
        score = suffix_score
        if prefix in known_materials:
            score += 100
        if matched is None or score > matched[3]:
            normal_space = hint if slot_kind == "normal" and hint in {"opengl", "directx"} else ""
            matched = (prefix, slot_kind, normal_space, score)
    if matched is None:
        return None
    return matched[0], matched[1], matched[2]


def _replacement_texture_suffix_match(stem: str, suffix: str) -> Optional[tuple[str, int]]:
    suffix_text = str(suffix or "").strip()
    if not suffix_text:
        return None
    normalized_suffix = re.sub(r"[^a-z0-9]+", "", suffix_text.lower())
    if not normalized_suffix:
        return None
    lowered = str(stem or "").lower()
    candidates: list[tuple[str, int]] = []
    suffix_pattern = r"[^a-z0-9]*".join(re.escape(part) for part in re.findall(r"[a-z0-9]+", suffix_text.lower()))
    if suffix_pattern:
        separator_match = re.search(rf"(?P<sep>^|[^a-z0-9]+)(?P<suffix>{suffix_pattern})$", lowered, flags=re.IGNORECASE)
        if separator_match is not None:
            prefix = stem[: separator_match.start("sep")].rstrip("_-. ")
            candidates.append((prefix, separator_match.end("suffix") - separator_match.start("suffix") + 20))
    compact_stem = re.sub(r"[^a-z0-9]+", "", lowered)
    if len(normalized_suffix) > 2 and compact_stem.endswith(normalized_suffix):
        compact_prefix = compact_stem[: -len(normalized_suffix)]
        if compact_prefix or len(normalized_suffix) > 2:
            raw_prefix = stem[: max(0, len(stem) - len(suffix_text))].rstrip("_-. ")
            candidates.append((raw_prefix, len(normalized_suffix)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (bool(item[0]), item[1]), reverse=True)
    return candidates[0]


def _attach_source_texture_reference_base_slots(
    grouped: dict[str, ReplacementTextureSet],
    texture_files: Sequence[Path],
    source_submeshes: Sequence[object],
) -> None:
    """Promote explicit scene material texture references to texture slots.

    OBJ/DAE/glTF imports often carry a material texture reference such as
    ``map_Kd textures/wood.png`` where the image filename has no ``_base`` or
    ``_albedo`` suffix. glTF also carries explicit normal, material, AO, and
    emissive slots. The suffix parser intentionally stays conservative, so
    this pass uses those source material references as stronger evidence.
    """

    if not source_submeshes or not texture_files:
        return
    texture_files_by_key: dict[str, Path] = {}
    for raw_path in texture_files:
        path = raw_path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix.lower() not in {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff"}:
            continue
        for key in _texture_reference_keys(path):
            texture_files_by_key.setdefault(key, path)
    if not texture_files_by_key:
        return

    def attach_slot(material_name: str, slot_kind: str, texture_reference: object, *, visible_base_guard: bool = False) -> None:
        normalized_slot = _normalize_source_texture_slot_kind(slot_kind)
        if not material_name or not normalized_slot:
            return
        reference_text = str(texture_reference or "").strip()
        if not reference_text:
            return
        matched_path: Optional[Path] = None
        for key in _texture_reference_keys(reference_text):
            matched_path = texture_files_by_key.get(key)
            if matched_path is not None:
                break
        if matched_path is None:
            return
        if visible_base_guard and not _source_texture_reference_is_visible_base(matched_path):
            return
        if _texture_path_already_grouped(grouped, matched_path):
            return
        texture_set = grouped.setdefault(material_name.lower(), ReplacementTextureSet(material_name=material_name))
        existing = texture_set.slots.get(normalized_slot)
        if existing is None or _texture_slot_priority(matched_path, normalized_slot) > _texture_slot_priority(
            existing.source_path,
            existing.slot_kind,
        ):
            texture_set.slots[normalized_slot] = ReplacementTextureSlot(
                material_name=material_name,
                slot_kind=normalized_slot,
                source_path=matched_path,
                normal_space="",
            )

    for source_submesh in source_submeshes:
        material_name = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip()
        if not material_name:
            continue
        attach_slot(material_name, "base", getattr(source_submesh, "texture", ""), visible_base_guard=True)
        for slot_kind, slot_path in tuple(getattr(source_submesh, "texture_slots", ()) or ()):
            attach_slot(material_name, str(slot_kind or ""), slot_path)


def _normalize_source_texture_slot_kind(slot_kind: str) -> str:
    normalized = str(slot_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "base_color": "base",
        "basecolor": "base",
        "diffuse": "base",
        "albedo": "base",
        "metallicroughness": "material",
        "metallic_roughness": "material",
        "specular_glossiness": "material",
        "specularglossiness": "material",
        "specular_gloss": "material",
        "specgloss": "material",
        "occlusion": "ao",
        "ambient_occlusion": "ao",
        "ambientocclusion": "ao",
        "emission": "emissive",
        "glow": "emissive",
        "illum": "emissive",
        "illumination": "emissive",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized in {
        "base",
        "normal",
        "height",
        "material",
        "material_mask",
        "detail_mask",
        "metallic",
        "roughness",
        "ao",
        "emissive",
    }:
        return normalized
    return ""


def _source_texture_reference_is_visible_base(path: Path) -> bool:
    role = infer_cd_texture_role_from_path(path.name)
    if role:
        return role == "base"
    normalized = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    technical_markers = (
        "normal",
        "normalmap",
        "nrm",
        "roughness",
        "metallic",
        "metalness",
        "height",
        "displacement",
        "ambientocclusion",
        "occlusion",
        "opacity",
        "alpha",
        "emissive",
        "emission",
        "glow",
        "illumination",
        "flow",
        "direction",
    )
    return not any(marker in normalized for marker in technical_markers)


def _texture_path_already_grouped(grouped: Mapping[str, ReplacementTextureSet], path: Path) -> bool:
    try:
        path_key = str(path.expanduser().resolve()).lower()
    except Exception:
        path_key = str(path).lower()
    for texture_set in grouped.values():
        for slot in (texture_set.slots or {}).values():
            try:
                slot_key = str(slot.source_path.expanduser().resolve()).lower()
            except Exception:
                slot_key = str(slot.source_path).lower()
            if slot_key == path_key:
                return True
    return False


def _default_texture_material_name(source_submeshes: Sequence[object], known_materials: set[str]) -> str:
    real_submeshes = [
        submesh
        for submesh in source_submeshes
        if str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
    ]
    if len(real_submeshes) == 1:
        only = real_submeshes[0]
        return str(getattr(only, "material", "") or getattr(only, "name", "") or "").strip()
    if len(known_materials) == 1:
        return next(iter(known_materials))
    semantic_materials = [
        material
        for material in known_materials
        if _semantic_tokens(material)
    ]
    return semantic_materials[0] if len(semantic_materials) == 1 else ""


def _match_known_material_prefix(prefix: str, known_materials: set[str]) -> str:
    raw_prefix = str(prefix or "").strip()
    if not raw_prefix or not known_materials:
        return ""
    prefix_lower = raw_prefix.lower()
    prefix_compact = re.sub(r"[^a-z0-9]+", "", prefix_lower)
    best_material = ""
    best_score = 0.0
    prefix_tokens = _semantic_tokens(raw_prefix)
    for material in known_materials:
        material_text = str(material or "").strip()
        if not material_text:
            continue
        material_lower = material_text.lower()
        material_compact = re.sub(r"[^a-z0-9]+", "", material_lower)
        score = 0.0
        if prefix_lower == material_lower:
            score += 100.0
        elif material_lower in prefix_lower:
            score += 85.0 + min(20.0, len(material_lower) * 0.25)
        elif material_compact and material_compact in prefix_compact:
            score += 75.0 + min(20.0, len(material_compact) * 0.25)
        material_tokens = _semantic_tokens(material_text)
        overlap = prefix_tokens & material_tokens
        if overlap:
            score += len(overlap) * 8.0 + min(10.0, sum(len(token) for token in overlap) * 0.4)
        if score > best_score:
            best_score = score
            best_material = material_text
    return best_material if best_score >= 12.0 else ""


def _texture_slot_priority(path: Path, slot_kind: str) -> tuple[int, int, int]:
    extension_rank = {
        ".dds": 60,
        ".png": 50,
        ".tga": 42,
        ".tif": 40,
        ".tiff": 40,
        ".bmp": 30,
        ".jpg": 20,
        ".jpeg": 20,
    }.get(path.suffix.lower(), 0)
    return (
        _texture_slot_semantic_priority(path, slot_kind),
        extension_rank,
        min(200, len(path.stem)),
    )


def _texture_slot_semantic_priority(path: Path, slot_kind: str) -> int:
    normalized = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    tokens = _semantic_tokens(path.stem)
    slot = str(slot_kind or "").strip().lower()

    if slot == "base":
        if any(marker in normalized for marker in ("basecolor", "basecolour", "basecol")):
            return 100
        if "albedo" in normalized:
            return 95
        if "diffuse" in normalized:
            return 90
        if any(token in tokens for token in ("color", "colour")) or normalized.endswith(("col", "bc", "bcol")):
            return 80
        if any(marker in normalized for marker in ("emissive", "glow", "illum")):
            return 30
        return 60

    if slot == "normal":
        if any(marker in normalized for marker in ("normalopengl", "normaldirectx", "normaldx")):
            return 100
        if any(marker in normalized for marker in ("normalmap", "normal")):
            return 90
        if normalized.endswith(("nrm", "nm")):
            return 75
        return 60

    if slot == "height":
        if any(marker in normalized for marker in ("displacement", "height", "parallax")):
            return 100
        if any(marker in normalized for marker in ("disp", "depth", "dmap")):
            return 85
        if any(marker in normalized for marker in ("bump", "pom", "ssdm")):
            return 70
        return 60

    if slot == "material_mask":
        if any(marker in normalized for marker in ("colorblendingmask", "materialmask", "maskamg")):
            return 100
        if normalized.endswith(("ma",)):
            return 95
        if any(token in tokens for token in ("mask", "material")):
            return 75
        return 50

    if slot == "detail_mask":
        if any(marker in normalized for marker in ("detailmask", "detailmaterial")):
            return 100
        if normalized.endswith(("mg",)):
            return 95
        return 50

    if slot == "material":
        if any(
            marker in normalized
            for marker in (
                "metallicroughness",
                "metalrough",
                "roughnessmetallic",
                "roughmetal",
                "specularglossiness",
                "specgloss",
                "clearcoat",
                "materialmask",
                "colorblendingmask",
                "detailmask",
                "detailmaterial",
                "maskamg",
                "mask1bit",
                "layermask",
            )
        ):
            return 100
        if any(token in tokens for token in ("orm", "rma", "mra", "arm", "mask", "material")):
            return 90
        if normalized.endswith(("ma", "mg", "sp")):
            return 90
        if any(marker in normalized for marker in ("reflection", "reflect", "specular", "spec", "gloss", "smoothness")):
            return 55
        return 50

    if slot == "metallic":
        return 70 if any(marker in normalized for marker in ("metallic", "metalness")) else 50
    if slot == "roughness":
        return 70 if any(marker in normalized for marker in ("roughness", "rough", "smoothness", "gloss")) else 50
    if slot == "ao":
        return 70 if any(marker in normalized for marker in ("mixedao", "ambientocclusion", "occlusion")) or "ao" in tokens else 50
    if slot == "emissive":
        return 80 if any(marker in normalized for marker in ("emissive", "emission", "glow", "illumination")) else 50
    return 0


def _attach_source_face_counts(texture_sets: Mapping[str, ReplacementTextureSet], obj_mesh: ParsedMesh) -> None:
    for submesh in obj_mesh.submeshes:
        material_key = str(submesh.material or submesh.name or "").strip().lower()
        texture_set = texture_sets.get(material_key)
        if texture_set is None:
            texture_set = _texture_set_for_source_texture_reference(submesh, texture_sets)
        if texture_set is not None:
            texture_set.source_face_count += len(submesh.faces)


def _choose_source_materials_for_targets(
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    report: TextureReplacementReport,
) -> dict[str, str]:
    result: dict[str, str] = {}
    routes = build_source_material_routing_plan(obj_mesh, texture_sets, submesh_mappings)
    report.material_routes = list(routes)
    _append_source_material_route_match_warnings(obj_mesh, texture_sets, submesh_mappings, report)
    blocked_targets: set[str] = set()
    for route in routes:
        target_key = str(route.target_material_name or "").strip().lower()
        if not target_key:
            continue
        if route.blocker:
            blocked_targets.add(target_key)
            _warn_once(report, route.reason)
            continue
        source_material = str(route.source_material_name or "").strip()
        if source_material:
            result[target_key] = source_material
        elif route.status == "Ignored" and route.reason:
            _warn_once(report, route.reason)
    for blocked_target in blocked_targets:
        result.pop(blocked_target, None)
    return result


def _augment_source_materials_from_rebuilt_mesh(
    target_to_source_material: dict[str, str],
    rebuilt_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> None:
    """Allow session-added draw sections to bind textures by their own material name.

    Mapped replacements get target-to-source routes from StaticSubmeshMapping.
    Independent session parts are already present in the rebuilt preview mesh,
    but they do not have an original target mapping. Matching them here lets
    source-driven texture generation use their own material/texture set instead
    of stealing an original draw slot.
    """
    for submesh in getattr(rebuilt_mesh, "submeshes", ()) or ():
        if not getattr(submesh, "vertices", None) or not getattr(submesh, "faces", None):
            continue
        target_material = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
        if not target_material:
            continue
        texture_set = _texture_set_for_source_submesh(submesh, target_material, texture_sets)
        if texture_set is None:
            continue
        for key in {
            target_material.lower(),
            _normalize_sidecar_material_name(target_material),
        }:
            if key and key not in target_to_source_material:
                target_to_source_material[key] = texture_set.material_name


def _append_source_material_route_match_warnings(
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    submesh_mappings: Sequence[StaticSubmeshMapping],
    report: TextureReplacementReport,
) -> None:
    for mapping in submesh_mappings:
        for source_index in tuple(mapping.source_submesh_indices or ()):
            if source_index < 0 or source_index >= len(obj_mesh.submeshes):
                continue
            source_submesh = obj_mesh.submeshes[source_index]
            material_key = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip().lower()
            if material_key in texture_sets:
                continue
            texture_set = _texture_set_for_source_texture_reference(source_submesh, texture_sets)
            if texture_set is not None:
                texture_name = Path(str(getattr(source_submesh, "texture", "") or "")).name
                _warn_once(
                    report,
                    f"Texture set {texture_set.material_name} was matched from source texture "
                    f"{texture_name or _source_submesh_display_name(source_submesh, source_index)} "
                    f"for {mapping.target_submesh_name}.",
                )
                continue
            inferred_texture_set = _best_texture_set_for_source_mapping(
                source_submesh,
                mapping.target_submesh_name,
                texture_sets,
            )
            if inferred_texture_set is not None:
                _warn_once(
                    report,
                    f"Texture set {inferred_texture_set.material_name} was matched to renamed source "
                    f"{_source_submesh_display_name(source_submesh, source_index)} for {mapping.target_submesh_name}.",
                )


def build_source_material_routing_plan(
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    submesh_mappings: Sequence[StaticSubmeshMapping],
) -> tuple[SourceMaterialRoutingResult, ...]:
    routes: list[SourceMaterialRoutingResult] = []
    for mapping in submesh_mappings:
        target_name = str(mapping.target_submesh_name or "").strip()
        if not target_name:
            continue
        if is_static_replacement_helper_material_name(target_name):
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_part_names=tuple(
                        _source_submesh_display_name(obj_mesh.submeshes[index], index)
                        for index in tuple(mapping.source_submesh_indices or ())
                        if 0 <= index < len(obj_mesh.submeshes)
                    ),
                    status="Ignored",
                    reason=(
                        f"Helper material wrapper {target_name} is preserved by default; automatic texture routing does not patch "
                        "_black/_inside-style parts. Use Advanced original-DDS overrides only when you intentionally want to edit it."
                    ),
                )
            )
            continue
        source_part_names: list[str] = []
        ignored_part_names: list[str] = []
        candidates_by_key: dict[str, ReplacementTextureSet] = {}
        for source_index in tuple(mapping.source_submesh_indices or ()):
            if source_index < 0 or source_index >= len(obj_mesh.submeshes):
                continue
            source_submesh = obj_mesh.submeshes[source_index]
            source_label = _source_submesh_display_name(source_submesh, source_index)
            source_part_names.append(source_label)
            texture_set = _texture_set_for_source_submesh(source_submesh, target_name, texture_sets)
            if texture_set is None:
                ignored_part_names.append(source_label)
                continue
            candidates_by_key.setdefault(str(texture_set.material_name or "").strip().lower(), texture_set)

        if not candidates_by_key and len(texture_sets) == 1:
            texture_set = next(iter(texture_sets.values()))
            candidates_by_key[str(texture_set.material_name or "").strip().lower()] = texture_set

        candidates = list(candidates_by_key.values())
        if len(candidates) > 1:
            candidate_names = [str(candidate.material_name or "").strip() for candidate in candidates if str(candidate.material_name or "").strip()]
            ignored_note = f" Untextured source part(s) ignored for texture routing: {', '.join(ignored_part_names[:4])}." if ignored_part_names else ""
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_material_name=", ".join(candidate_names),
                    source_part_names=tuple(source_part_names),
                    detected_roles=tuple(sorted({role for candidate in candidates for role in _texture_set_detected_roles(candidate)})),
                    status="Blocked",
                    reason=(
                        f"Texture routing blocker: {target_name} receives multiple replacement material sets "
                        f"({', '.join(candidate_names)}). Split the routing, atlas/bake the source textures, or manually choose one source material."
                    )
                    + ignored_note,
                    blocker=True,
                )
            )
            continue

        if not candidates:
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_part_names=tuple(source_part_names),
                    status="Ignored",
                    reason=(
                        f"Texture routing ignored {target_name}: mapped source part(s) have no detected base/normal texture set"
                        + (f" ({', '.join(ignored_part_names[:4])})." if ignored_part_names else ".")
                    ),
                )
            )
            continue

        chosen = candidates[0]
        roles = _texture_set_detected_roles(chosen)
        has_base = "base" in roles
        ignored_note = f" Untextured mapped source part(s) ignored for texture routing: {', '.join(ignored_part_names[:4])}." if ignored_part_names else ""
        if ignored_part_names and len(source_part_names) > len(ignored_part_names):
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_material_name=str(chosen.material_name or "").strip(),
                    source_part_names=tuple(source_part_names),
                    detected_roles=roles,
                    status="Blocked",
                    reason=(
                        f"Texture routing blocker: {target_name} mixes source material "
                        f"{str(chosen.material_name or '').strip() or 'replacement material'} with untextured/original "
                        "source part(s) in the same draw/material slot. One game slot can bind one material set, "
                        "so automatic routing is blocked to avoid repainting the whole target."
                    )
                    + ignored_note,
                    blocker=True,
                )
            )
            continue
        routes.append(
            SourceMaterialRoutingResult(
                target_material_name=target_name,
                source_material_name=str(chosen.material_name or "").strip(),
                source_part_names=tuple(source_part_names),
                detected_roles=roles,
                status="Ready" if has_base else "Review",
                reason=(
                    "Base/color and normal maps will be routed conservatively."
                    if has_base
                    else "No base/color map is detected for this routed material; final output may be grey."
                )
                + ignored_note,
            )
        )
    return tuple(routes)


def _texture_set_for_source_submesh(
    source_submesh: object,
    target_material_name: str,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> Optional[ReplacementTextureSet]:
    material_key = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip().lower()
    texture_set = texture_sets.get(material_key)
    if texture_set is not None:
        return texture_set
    texture_set = _texture_set_for_source_texture_reference(source_submesh, texture_sets)
    if texture_set is not None:
        return texture_set
    return _best_texture_set_for_source_mapping(source_submesh, target_material_name, texture_sets)


def _source_submesh_display_name(source_submesh: object, source_index: int) -> str:
    return (
        str(getattr(source_submesh, "material", "") or "").strip()
        or str(getattr(source_submesh, "name", "") or "").strip()
        or f"source {source_index}"
    )


def _texture_set_detected_roles(texture_set: ReplacementTextureSet) -> tuple[str, ...]:
    order = ("base", "normal", "height", "material_mask", "detail_mask", "emissive", "material", "metallic", "roughness", "ao")
    slots = getattr(texture_set, "slots", {}) or {}
    roles = [role for role in order if role in slots]
    roles.extend(sorted(str(role) for role in slots if str(role) not in set(order)))
    return tuple(roles)


def _texture_reference_keys(raw_reference: object) -> set[str]:
    raw_text = str(raw_reference or "").strip()
    if not raw_text:
        return set()
    normalized_text = raw_text.replace("\\", "/").lower()
    keys = {normalized_text}
    path = Path(raw_text).expanduser()
    if path.name:
        keys.add(path.name.lower())
    if path.stem:
        keys.add(path.stem.lower())
    try:
        keys.add(str(path.resolve()).replace("\\", "/").lower())
    except Exception:
        pass
    return {key for key in keys if key}


def _texture_set_for_source_texture_reference(
    source_submesh: object,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> Optional[ReplacementTextureSet]:
    source_texture_keys = _texture_reference_keys(getattr(source_submesh, "texture", ""))
    if not source_texture_keys:
        return None
    best: Optional[ReplacementTextureSet] = None
    best_score = 0
    slot_priority = {
        "base": 50,
        "normal": 30,
        "material_mask": 22,
        "detail_mask": 21,
        "material": 20,
        "height": 10,
    }
    for texture_set in texture_sets.values():
        for slot_kind, slot in (texture_set.slots or {}).items():
            slot_keys = _texture_reference_keys(slot.source_path)
            if not (source_texture_keys & slot_keys):
                continue
            score = slot_priority.get(str(slot_kind or "").strip().lower(), 1)
            if score > best_score:
                best_score = score
                best = texture_set
    return best


def _best_texture_set_for_source_mapping(
    source_submesh: object,
    target_material_name: str,
    texture_sets: Mapping[str, ReplacementTextureSet],
) -> Optional[ReplacementTextureSet]:
    best: Optional[ReplacementTextureSet] = None
    best_score = 0.0
    source_text = f"{getattr(source_submesh, 'name', '')} {getattr(source_submesh, 'material', '')} {target_material_name}"
    source_tokens = _semantic_tokens(source_text)
    for texture_set in texture_sets.values():
        texture_tokens = _semantic_tokens(texture_set.material_name)
        if not texture_tokens:
            continue
        overlap = source_tokens & texture_tokens
        score = len(overlap) * 8.0
        if overlap:
            score += min(12.0, sum(len(token) for token in overlap) * 0.5)
        score += _texture_source_candidate_score(target_material_name, texture_set)
        if "blade" in source_tokens and "cuchilla" in texture_tokens:
            score += 12.0
        if "handle" in source_tokens and "mango" in texture_tokens:
            score += 10.0
        if "guard" in source_tokens and "soporte" in texture_tokens:
            score += 10.0
        if score > best_score:
            best_score = score
            best = texture_set
    return best if best_score >= 10.0 else None


def _texture_source_candidate_score(target_material_name: str, texture_set: ReplacementTextureSet) -> float:
    target_tokens = _semantic_tokens(target_material_name)
    source_tokens = _semantic_tokens(texture_set.material_name)
    if not target_tokens or not source_tokens:
        return 0.0
    overlap = target_tokens & source_tokens
    score = len(overlap) * 8.0
    if overlap:
        score += min(10.0, sum(len(token) for token in overlap) * 0.5)
    if "handle" in target_tokens and "mango" in source_tokens:
        score += 5.0
    if "blade" in target_tokens and "cuchilla" in source_tokens:
        score += 5.0
    if "guard" in target_tokens and "soporte" in source_tokens:
        score += 5.0
    if "acc" in target_tokens and ("circular" in source_tokens or "circulares" in source_tokens):
        score += 4.0
    if "handle" in target_tokens and ("tip" in source_tokens or "edge" in source_tokens):
        score -= 4.0
    return score


def _best_source_material_for_target(target_material: str, target_to_source_material: Mapping[str, str]) -> str:
    target_key = str(target_material or "").strip().lower()
    if target_key in target_to_source_material:
        return target_to_source_material[target_key]
    best_value = ""
    best_score = 0.0
    target_tokens = _material_tokens(target_key)
    for target_name, source_material in target_to_source_material.items():
        source_tokens = _material_tokens(f"{target_name} {source_material}")
        overlap = target_tokens & source_tokens
        score = float(len(overlap) * 8)
        for token in overlap:
            score += min(6.0, len(token) * 0.75)
        if target_name and (target_name in target_key or target_key in target_name):
            score += min(20.0, len(target_name) * 0.5)
        target_name_tokens = _material_tokens(target_name)
        if "sword" in target_tokens and "blade" in target_name_tokens:
            score += 14.0
        if "blade" in target_tokens and "blade" in target_name_tokens:
            score += 14.0
        if "handle" in target_tokens and "handle" in target_name_tokens:
            score += 14.0
        if "guard" in target_tokens and "guard" in target_name_tokens:
            score += 14.0
        if "acc" in target_tokens and "acc" in target_name_tokens:
            score += 14.0
        if score > best_score:
            best_score = score
            best_value = source_material
    return best_value if best_score >= 11.5 else ""


def _material_tokens(value: str) -> set[str]:
    stop_words = {
        "cd",
        "phm",
        "pc",
        "texture",
        "material",
        "mesh",
        "obj",
        "dds",
        "png",
        "source",
        "target",
        "donor",
        "original",
        "replacement",
    }
    tokens: set[str] = set()
    for raw_token in re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split():
        token = re.sub(r"\d+$", "", raw_token.strip())
        if len(token) > 1 and token not in stop_words and not token.isdigit():
            tokens.add(token)
    return tokens


def _reference_target_path(reference: object) -> str:
    return str(
        getattr(reference, "resolved_archive_path", "")
        or getattr(reference, "reference_name", "")
        or ""
    ).replace("\\", "/").strip()


def _replacement_output_texture_path(source_slot: ReplacementTextureSlot, target_path: str) -> str:
    del source_slot
    normalized_target = str(target_path or "").replace("\\", "/").strip()
    if normalized_target:
        return normalized_target
    return "character/texture/static_replacement.dds"


def _is_shared_material_layer_texture(target_path: str) -> bool:
    basename = PurePosixPath(str(target_path or "").replace("\\", "/")).name.lower()
    return (
        basename.startswith("cd_texturelayer_")
        or basename.startswith("cd_temp")
        or basename.startswith("cd_metal_")
        or basename.startswith("blackoil")
        or basename.startswith("cd_common_default")
        or basename.startswith("nonetexture")
        or basename.startswith("none_texture")
    )


def is_shared_material_layer_texture(target_path: str) -> bool:
    return _is_shared_material_layer_texture(target_path)


def classify_texture_assignment_guidance(
    parameter_name: str,
    target_path: str,
    *,
    suggested_source: str = "",
    repeated_suggestion_count: int = 1,
) -> TextureAssignmentGuidance:
    """Return conservative UI guidance for automatic texture assignment."""

    classification = classify_texture_binding(parameter_name, target_path)
    has_source = bool(str(suggested_source or "").strip())
    is_shared = _is_shared_material_layer_texture(target_path)
    source_role = infer_cd_texture_role_from_path(suggested_source) if has_source else ""
    source_name = PurePosixPath(str(suggested_source or "").replace("\\", "/")).name.lower()
    subtype = str(classification.semantic_subtype or "").strip().lower()
    advanced_subtypes = {
        "color_blending_mask",
        "detail_mask",
        "emissive",
        "rgb_layer",
        "skin_detail_mask",
        "opacity_mask",
        "flow_vector",
        "direction_vector",
    }
    if is_shared:
        source_detail = ""
        if source_role:
            source_detail = f" Suggested source looks like {source_role.replace('_', ' ')}."
        return TextureAssignmentGuidance(
            checked_by_default=False,
            confidence="manual",
            state_label="Risky stock/shared layer",
            reason=(
                "Stock/shared shader rows such as cd_texturelayer, cd_metal, blackoil, and defaults drive grime/detail/dye behavior. "
                "Overriding them can tint the model, add dirt/speckles, or affect other materials; leave them unchanged unless this is intentional."
                + source_detail
            ),
            advanced=True,
        )
    if not has_source:
        return TextureAssignmentGuidance(
            checked_by_default=False,
            confidence="manual",
            state_label="Needs source",
            reason="No replacement texture source matched this slot. Assign one manually if this original DDS should be replaced.",
            advanced=True,
        )
    repeated_count = int(repeated_suggestion_count or 1)
    if repeated_count > 2:
        return TextureAssignmentGuidance(
            checked_by_default=False,
            confidence="suggested",
            state_label="Review repeated match",
            reason="The same source texture matched several target slots. Review before applying it everywhere.",
            advanced=True,
        )
    target_role = str(classification.slot_kind or "").strip().lower()
    source_is_pbr = any(
        token in source_name
        for token in ("metallicroughness", "metallic_roughness", "metalrough", "roughmetal", "roughnessmetallic")
    )
    direct_roles = {"base", "normal", "height", "material_mask", "detail_mask"}
    if has_source and target_role in direct_roles:
        if source_is_pbr:
            return TextureAssignmentGuidance(
                checked_by_default=False,
                confidence="suggested",
                state_label="Review PBR source",
                reason=(
                    "Standalone glTF MetallicRoughness/PBR maps are not the same as Crimson material/detail masks. "
                    "Pack or assign them manually if this shader row should use them."
                ),
                advanced=True,
            )
        if source_role and source_role != target_role:
            return TextureAssignmentGuidance(
                checked_by_default=False,
                confidence="suggested",
                state_label="Review role mismatch",
                reason=(
                    f"Suggested source looks like {source_role.replace('_', ' ')}, but this row expects "
                    f"{target_role.replace('_', ' ')}."
                ),
                advanced=True,
            )
        if target_role in {"material_mask", "detail_mask"} and not source_role:
            return TextureAssignmentGuidance(
                checked_by_default=False,
                confidence="suggested",
                state_label="Suggested manual",
                reason=(
                    f"This row expects a clear CD {target_role.replace('_', ' ')} source "
                    "such as a matching _ma or _mg texture."
                ),
                advanced=True,
            )
        if target_role in {"material_mask", "detail_mask"} and source_role == target_role:
            return TextureAssignmentGuidance(
                checked_by_default=True,
                confidence="high",
                state_label="High-confidence CD mask",
                reason=classification.reason or "Clear Crimson material-family mask with a matching replacement source.",
                advanced=False,
            )
    if not classification.visualized or subtype in advanced_subtypes:
        return TextureAssignmentGuidance(
            checked_by_default=False,
            confidence="suggested",
            state_label="Suggested manual",
            reason=classification.reason or "This shader slot is preserved for export but is not safe to auto-assign.",
            advanced=True,
        )
    if classification.slot_kind in {"base", "normal", "height", "material", "material_mask", "detail_mask"}:
        return TextureAssignmentGuidance(
            checked_by_default=True,
            confidence="high",
            state_label="High-confidence suggestion",
            reason=classification.reason or "Clear direct texture slot with a matching replacement source.",
            advanced=False,
        )
    return TextureAssignmentGuidance(
        checked_by_default=False,
        confidence="suggested",
        state_label="Suggested manual",
        reason=classification.reason or "Slot type is not specific enough for automatic assignment.",
        advanced=True,
    )


def _should_replace_original_texture_reference(reference: object, target_path: str) -> bool:
    if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
        return False
    if not str(target_path or "").lower().endswith(".dds"):
        return False
    parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
    basename = PurePosixPath(str(target_path or "").replace("\\", "/")).name.lower()

    # These are shared dye/grime/detail layers used by many materials. Replacing
    # them for one imported OBJ causes broad side effects and also tricks missing
    # base-color detection into thinking a material already has a direct diffuse.
    if _is_shared_material_layer_texture(target_path):
        return False

    if parameter in {
        "_normaltexture",
        "_heighttexture",
        "_overlaycolortexture",
        "_basecolortexture",
        "_diffusetexture",
        "_albedotexture",
        "_colorblendingmasktexture",
        "_detailmasktexture",
    }:
        return True
    if parameter.startswith("_grime") or parameter.startswith("_detail"):
        return False
    if not parameter:
        return any(token in basename for token in ("_o.dds", "_n.dds", "_disp.dds"))
    return False


def _reference_belongs_to_active_static_target(
    reference: object,
    target_path: str,
    target_to_source_material: Mapping[str, str],
) -> bool:
    """Keep texture generation scoped to original slots that receive replacement geometry.

    Static replacement mappings may intentionally leave original draw sections empty.
    Sidecar discovery can still expose those sections, and some recovered preview
    metadata can assign the replacement material name to unrelated texture paths.
    The texture path itself is therefore used as a second guard so a blade-only
    replacement does not generate acc/guard/handle DDS payloads.
    """
    if not target_to_source_material:
        return False
    material_name = str(getattr(reference, "material_name", "") or "").strip()
    path_text = PurePosixPath(str(target_path or "").replace("\\", "/")).stem
    for active_target in target_to_source_material.keys():
        active_name = str(active_target or "").strip()
        if not active_name:
            continue
        path_matches_active = _sidecar_material_names_match(path_text, active_name) or _active_target_tokens_match_path(active_name, path_text)
        path_conflicts_active = _active_target_tokens_conflict_path(active_name, path_text)
        if material_name and _sidecar_material_names_match(material_name, active_name) and not path_conflicts_active:
            return True
        if path_matches_active:
            return True
    return False


def _important_material_tokens(value: str) -> set[str]:
    return _semantic_tokens(value) & {
        "acc",
        "accessory",
        "blade",
        "body",
        "cape",
        "cloth",
        "edge",
        "guard",
        "handle",
        "helmet",
        "hilt",
        "plate",
        "trim",
    }


def _active_target_tokens_conflict_path(active_target: str, path_text: str) -> bool:
    path_tokens = _important_material_tokens(path_text)
    active_tokens = _important_material_tokens(active_target)
    return bool(path_tokens and active_tokens and not (path_tokens & active_tokens))


def _active_target_tokens_match_path(active_target: str, path_text: str) -> bool:
    active_tokens = _semantic_tokens(active_target)
    path_tokens = _semantic_tokens(path_text)
    if not active_tokens or not path_tokens:
        return False
    important_path_tokens = _important_material_tokens(path_text)
    important_active_tokens = _important_material_tokens(active_target)
    if important_path_tokens and important_active_tokens:
        return bool(important_path_tokens & important_active_tokens)
    return bool(path_tokens & active_tokens)


def _is_direct_base_color_mapping(mapping: TextureSlotMapping) -> bool:
    if str(mapping.slot_kind or "").strip().lower() != "base":
        return False
    target_path = str(mapping.target_texture_path or "").replace("\\", "/").strip()
    if not target_path:
        return False
    if target_path.startswith("("):
        return True
    if _is_shared_material_layer_texture(target_path):
        return False
    basename = PurePosixPath(target_path).name.lower()
    return (
        basename.endswith("_o.dds")
        or "base" in basename
        or "diffuse" in basename
        or "albedo" in basename
        or "color" in basename
    )


def _needs_missing_base_color_parameter_payloads(
    *,
    texture_sets: Mapping[str, ReplacementTextureSet],
    target_to_source_material: Mapping[str, str],
    existing_slot_mappings: Sequence[TextureSlotMapping],
    original_sidecars: Sequence[tuple[object, str]],
) -> bool:
    if not original_sidecars:
        return False
    base_mapped_targets = {
        str(mapping.target_material_name or "").strip().lower()
        for mapping in existing_slot_mappings
        if _is_direct_base_color_mapping(mapping)
    }
    for target_material_name, source_material_name in target_to_source_material.items():
        target_key = str(target_material_name or "").strip().lower()
        if not target_key or target_key in base_mapped_targets:
            continue
        texture_set = texture_sets.get(str(source_material_name or "").strip().lower())
        if texture_set is not None and texture_set.slots.get("base") is not None:
            return True
    return False


def _infer_slot_kind(parameter_name: str, texture_path: str) -> str:
    return classify_texture_binding(parameter_name, texture_path).slot_kind or "material"


def _slot_for_target(texture_set: ReplacementTextureSet, slot_kind: str) -> Optional[ReplacementTextureSlot]:
    if slot_kind in texture_set.slots:
        return texture_set.slots[slot_kind]
    if slot_kind == "material_mask":
        return texture_set.slots.get("material_mask")
    if slot_kind == "detail_mask":
        return texture_set.slots.get("detail_mask")
    if slot_kind == "material":
        return texture_set.slots.get("material") or texture_set.slots.get("material_mask") or texture_set.slots.get("detail_mask")
    if slot_kind == "base":
        return texture_set.slots.get("base")
    return None


def _build_missing_base_color_parameter_payloads(
    *,
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    original_texture_refs: Sequence[object],
    target_to_source_material: Mapping[str, str],
    existing_slot_mappings: Sequence[TextureSlotMapping],
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str,
) -> tuple[list[TextureReplacementPayload], list[SidecarTextureParameterInjection]]:
    del obj_mesh
    base_mapped_targets = {
        str(mapping.target_material_name or "").strip().lower()
        for mapping in existing_slot_mappings
        if _is_direct_base_color_mapping(mapping)
    }
    template_reference = _base_color_template_reference(original_texture_refs)
    if template_reference is None or getattr(template_reference, "resolved_entry", None) is None:
        report.warnings.append(
            "Missing base-color parameter injection was requested, but no existing base/overlay texture parameter was available to clone."
        )
        return [], []

    generated_payloads: list[TextureReplacementPayload] = []
    injections: list[SidecarTextureParameterInjection] = []
    emitted_targets: set[str] = set()
    for target_material_name, source_material_name in target_to_source_material.items():
        target_key = str(target_material_name or "").strip().lower()
        if not target_key or target_key in base_mapped_targets or target_key in emitted_targets:
            continue
        texture_set = texture_sets.get(str(source_material_name or "").strip().lower())
        base_slot = texture_set.slots.get("base") if texture_set is not None else None
        if base_slot is None:
            continue
        output_texture_path = _infer_base_color_path_for_material(
            original_texture_refs,
            target_material_name,
            fallback_parent=_reference_target_parent(template_reference),
        )
        if not output_texture_path:
            report.warnings.append(
                f"Could not infer an original-style base color path for {target_material_name}; skipping injected _overlayColorTexture."
            )
            continue
        try:
            payload = _build_texture_payload(
                base_slot,
                target_entry=getattr(template_reference, "resolved_entry", None),
                texconv_path=texconv_path,
                read_original_texture_bytes=read_original_texture_bytes,
                original_texture_source_path=original_texture_source_path,
                report=report,
                on_log=on_log,
                texture_output_size_mode=texture_output_size_mode,
            )
        except Exception as exc:
            report.errors.append(
                f"Failed to build injected base-color texture for {target_material_name}: {exc}"
            )
            continue
        generated_payloads.append(
            TextureReplacementPayload(
                target_path=output_texture_path,
                payload_data=payload,
                kind="texture_generated",
                source_path=base_slot.source_path,
                note=f"Injected _overlayColorTexture for {target_material_name}: {base_slot.source_path.name}",
            )
        )
        report.slot_mappings.append(
            TextureSlotMapping(
                target_material_name=target_material_name,
                target_texture_path="(injected _overlayColorTexture)",
                slot_kind="base",
                source_material_name=base_slot.material_name,
                source_path=base_slot.source_path,
                output_texture_path=output_texture_path,
                normal_space=base_slot.normal_space,
            )
        )
        injections.append(
            SidecarTextureParameterInjection(
                target_material_name=target_material_name,
                parameter_name="_overlayColorTexture",
                texture_path=output_texture_path,
            )
        )
        emitted_targets.add(target_key)
        report.warnings.append(
            f"Sidecar patch: added _overlayColorTexture for {target_material_name} using {base_slot.source_path.name}."
        )
    return generated_payloads, injections


def _base_color_template_reference(original_texture_refs: Sequence[object]) -> Optional[object]:
    best: Optional[object] = None
    best_score = -1
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path or getattr(reference, "resolved_entry", None) is None:
            continue
        if _is_shared_material_layer_texture(target_path):
            continue
        slot_kind = _infer_slot_kind(str(getattr(reference, "sidecar_parameter_name", "") or ""), target_path)
        if slot_kind != "base":
            continue
        parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
        score = 10
        if parameter == "_overlaycolortexture":
            score += 20
        elif parameter in {"_basecolortexture", "_diffusetexture", "_albedotexture"}:
            score += 15
        if score > best_score:
            best = reference
            best_score = score
    return best


def _reference_target_parent(reference: object) -> str:
    target_path = _reference_target_path(reference)
    parent = PurePosixPath(target_path.replace("\\", "/")).parent
    return "" if str(parent) in {"", "."} else parent.as_posix()


def _infer_base_color_path_for_material(
    original_texture_refs: Sequence[object],
    target_material_name: str,
    *,
    fallback_parent: str = "character/texture",
) -> str:
    target_key = _normalize_sidecar_material_name(target_material_name)
    preferred_base_suffix = _preferred_base_color_suffix(original_texture_refs)
    support_candidates: list[str] = []
    fuzzy_support_candidates: list[str] = []
    base_candidates: list[str] = []
    fuzzy_base_candidates: list[str] = []
    for reference in original_texture_refs:
        material_name = str(getattr(reference, "material_name", "") or "")
        material_key = _normalize_sidecar_material_name(material_name)
        exact_material_match = bool(target_key and material_key and target_key == material_key)
        fuzzy_material_match = bool(
            target_key
            and material_name
            and not exact_material_match
            and _sidecar_material_names_match(target_material_name, material_name)
        )
        if target_key and material_name and not exact_material_match and not fuzzy_material_match:
            continue
        target_path = _reference_target_path(reference)
        if not target_path.lower().endswith(".dds"):
            continue
        slot_kind = _infer_slot_kind(str(getattr(reference, "sidecar_parameter_name", "") or ""), target_path)
        if slot_kind == "base" and not _is_shared_material_layer_texture(target_path):
            if exact_material_match:
                base_candidates.append(target_path)
            else:
                fuzzy_base_candidates.append(target_path)
        elif exact_material_match:
            support_candidates.append(target_path)
        else:
            fuzzy_support_candidates.append(target_path)
    if base_candidates:
        return base_candidates[0].replace("\\", "/")
    for candidate in support_candidates:
        inferred = _infer_base_color_path_from_support_texture(candidate, preferred_base_suffix=preferred_base_suffix)
        if inferred:
            return inferred
    if fuzzy_base_candidates:
        return fuzzy_base_candidates[0].replace("\\", "/")
    for candidate in fuzzy_support_candidates:
        inferred = _infer_base_color_path_from_support_texture(candidate, preferred_base_suffix=preferred_base_suffix)
        if inferred:
            return inferred
    material_token = re.sub(r"[^a-z0-9]+", "_", str(target_material_name or "").lower()).strip("_")
    if not material_token:
        return ""
    parent = str(fallback_parent or "character/texture").replace("\\", "/").strip("/")
    return f"{parent}/{material_token}.dds" if parent else f"{material_token}.dds"


def _preferred_base_color_suffix(original_texture_refs: Sequence[object]) -> str:
    suffix_counts: dict[str, int] = {}
    for reference in original_texture_refs:
        target_path = _reference_target_path(reference)
        if not target_path.lower().endswith(".dds") or _is_shared_material_layer_texture(target_path):
            continue
        slot_kind = _infer_slot_kind(str(getattr(reference, "sidecar_parameter_name", "") or ""), target_path)
        if slot_kind != "base":
            continue
        suffix = _base_color_suffix_from_path(target_path)
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    if not suffix_counts:
        return ""
    return max(suffix_counts.items(), key=lambda item: (item[1], len(item[0])))[0]


def _base_color_suffix_from_path(texture_path: str) -> str:
    stem = Path(PurePosixPath(str(texture_path or "").replace("\\", "/")).name).stem.lower()
    for suffix in ("_o", "_base_color", "_basecolor", "_albedo", "_diffuse", "_color"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return suffix
    return ""


def _infer_base_color_path_from_support_texture(texture_path: str, *, preferred_base_suffix: str = "") -> str:
    normalized = str(texture_path or "").replace("\\", "/").strip()
    if not normalized.lower().endswith(".dds"):
        return ""
    parent = PurePosixPath(normalized).parent
    stem = Path(PurePosixPath(normalized).name).stem
    lowered_stem = stem.lower()
    suffixes = (
        "_normal",
        "_n",
        "_disp",
        "_height",
        "_d",
        "_ma",
        "_mg",
        "_sp",
        "_m",
        "_mask",
        "_roughness",
        "_metallic",
    )
    for suffix in suffixes:
        if lowered_stem.endswith(suffix) and len(stem) > len(suffix):
            base_stem = stem[: -len(suffix)]
            base_name = base_stem + str(preferred_base_suffix or "") + ".dds"
            return f"{parent.as_posix()}/{base_name}" if str(parent) not in {"", "."} else base_name
    return ""


def _inject_sidecar_texture_parameter(
    sidecar_text: str,
    injection: SidecarTextureParameterInjection,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    target_name = str(injection.target_material_name or "").strip()
    texture_path = str(injection.texture_path or "").strip()
    parameter_name = str(injection.parameter_name or "_overlayColorTexture").strip() or "_overlayColorTexture"
    if not target_name or not texture_path:
        return sidecar_text, False
    wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
    if wrapper_match is None:
        wrapper_match = _find_sidecar_material_wrapper_by_texture_paths(
            sidecar_text,
            getattr(injection, "anchor_texture_paths", ()) or (),
        )
    if wrapper_match is None:
        report.warnings.append(f"Could not find sidecar material wrapper for injected texture target: {target_name}")
        return sidecar_text, False
    wrapper_text = wrapper_match.group(0)
    if re.search(
        rf'(?:_name|StringItemID|Name|name)="{re.escape(parameter_name)}"',
        wrapper_text,
        flags=re.IGNORECASE,
    ):
        report.unchanged_count += 1
        return sidecar_text, False
    template = _sidecar_texture_parameter_template(sidecar_text, parameter_name)
    parameter_vector_match = re.search(
        r'(<Vector\b[^>]*(?:Name|name|_name)="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        wrapper_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if parameter_vector_match is None:
        report.warnings.append(f"Could not find _parameters vector for injected texture target: {target_name}")
        return sidecar_text, False
    parameter_body = parameter_vector_match.group(2)
    insert_offset_in_body, insert_index = _sidecar_texture_injection_position(parameter_body, parameter_name)
    if insert_index is None:
        insert_index = _next_material_parameter_index(wrapper_text)
    parameter_text = _retarget_texture_parameter_template(template, parameter_name, texture_path, insert_index)
    if insert_offset_in_body is not None:
        parameter_body = _shift_sidecar_parameter_indexes(parameter_body, insert_index)
        new_parameter_body = (
            parameter_body[:insert_offset_in_body]
            + "\n\t\t\t\t\t\t\t"
            + parameter_text
            + parameter_body[insert_offset_in_body:]
        )
    else:
        new_parameter_body = parameter_body + "\n\t\t\t\t\t\t\t" + parameter_text
    new_wrapper_text = (
        wrapper_text[: parameter_vector_match.start(2)]
        + new_parameter_body
        + wrapper_text[parameter_vector_match.end(2) :]
    )
    return (
        sidecar_text[: wrapper_match.start()]
        + new_wrapper_text
        + sidecar_text[wrapper_match.end() :],
        True,
    )


def _find_sidecar_material_wrapper_by_texture_paths(
    sidecar_text: str,
    texture_paths: Sequence[str],
) -> Optional[re.Match[str]]:
    normalized_paths = {
        _normalize_texture_path(texture_path)
        for texture_path in texture_paths
        if _normalize_texture_path(texture_path)
    }
    if not normalized_paths:
        return None
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    best_match: Optional[re.Match[str]] = None
    best_score = 0
    for match in wrapper_pattern.finditer(sidecar_text):
        wrapper_paths = {
            _normalize_texture_path(path)
            for path in re.findall(r'\b_path="([^"]*)"', match.group(0), flags=re.IGNORECASE)
            if _normalize_texture_path(path)
        }
        score = len(normalized_paths & wrapper_paths)
        if score > best_score:
            best_match = match
            best_score = score
    return best_match if best_score > 0 else None


def _rename_sidecar_texture_parameter(
    sidecar_text: str,
    rename: SidecarTextureParameterRename,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    target_name = str(rename.target_material_name or "").strip()
    texture_path = str(rename.texture_path or "").replace("\\", "/").strip()
    old_parameter_name = str(rename.old_parameter_name or "").strip()
    new_parameter_name = str(rename.new_parameter_name or "").strip()
    if not target_name or not texture_path or not old_parameter_name or not new_parameter_name:
        return sidecar_text, False
    wrapper_match = _find_sidecar_material_wrapper(sidecar_text, target_name)
    if wrapper_match is None:
        return _rename_sidecar_texture_parameter_by_path(sidecar_text, rename, report)
    wrapper_text = wrapper_match.group(0)
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(wrapper_text):
        block = match.group(0)
        block_path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        block_path = str(block_path_match.group(1) if block_path_match else "").replace("\\", "/").strip()
        block_name = _sidecar_parameter_name(block)
        if block_path != texture_path:
            continue
        if block_name.lower() == new_parameter_name.lower():
            report.unchanged_count += 1
            return sidecar_text, False
        if block_name.lower() != old_parameter_name.lower():
            continue
        renamed_block = _rename_sidecar_parameter_name(block, new_parameter_name)
        new_wrapper_text = wrapper_text[: match.start()] + renamed_block + wrapper_text[match.end() :]
        return (
            sidecar_text[: wrapper_match.start()]
            + new_wrapper_text
            + sidecar_text[wrapper_match.end() :],
            True,
        )
    report.warnings.append(
        f"Could not find {old_parameter_name} texture parameter for {target_name}: {texture_path}"
    )
    return sidecar_text, False


def _rename_sidecar_texture_parameter_by_path(
    sidecar_text: str,
    rename: SidecarTextureParameterRename,
    report: SidecarPatchReport,
) -> tuple[str, bool]:
    texture_path = str(rename.texture_path or "").replace("\\", "/").strip()
    old_parameter_name = str(rename.old_parameter_name or "").strip()
    new_parameter_name = str(rename.new_parameter_name or "").strip()
    if not texture_path or not old_parameter_name or not new_parameter_name:
        return sidecar_text, False
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(sidecar_text):
        block = match.group(0)
        block_path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        block_path = str(block_path_match.group(1) if block_path_match else "").replace("\\", "/").strip()
        if block_path != texture_path:
            continue
        block_name = _sidecar_parameter_name(block)
        if block_name.lower() == new_parameter_name.lower():
            report.unchanged_count += 1
            return sidecar_text, False
        if block_name.lower() != old_parameter_name.lower():
            continue
        renamed_block = _rename_sidecar_parameter_name(block, new_parameter_name)
        return sidecar_text[: match.start()] + renamed_block + sidecar_text[match.end() :], True
    report.warnings.append(
        f"Could not find {old_parameter_name} texture parameter by path for {rename.target_material_name}: {texture_path}"
    )
    return sidecar_text, False


def _prune_unmapped_sidecar_texture_parameters(
    sidecar_text: str,
    keep_rules: Sequence[tuple[str, str]],
) -> tuple[str, int]:
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in keep_rules
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    removed_count = 0

    def replace_parameter(match: re.Match[str]) -> str:
        nonlocal removed_count
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block).lower()
        path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
        if (parameter_name, texture_path) in keep:
            return block
        removed_count += 1
        return ""

    patched = texture_pattern.sub(replace_parameter, sidecar_text)
    if removed_count:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, removed_count


def _prune_unmapped_sidecar_texture_parameters_for_materials(
    sidecar_text: str,
    *,
    material_names: Sequence[str],
    keep_rules: Sequence[tuple[str, str]],
) -> tuple[str, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    if not target_keys:
        return sidecar_text, 0
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    removed_count = 0

    def wrapper_selected(attrs: str, body: str) -> bool:
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
            attrs + " " + body[:400],
            flags=re.IGNORECASE,
        )
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def prune_wrapper(match: re.Match[str]) -> str:
        nonlocal removed_count
        attrs = match.group("attrs")
        body = match.group("body")
        if not wrapper_selected(attrs, body):
            return match.group(0)

        def replace_parameter(texture_match: re.Match[str]) -> str:
            nonlocal removed_count
            block = texture_match.group(0)
            parameter_name = _sidecar_parameter_name(block).lower()
            path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
            texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
            if (parameter_name, texture_path) in keep:
                return block
            removed_count += 1
            return ""

        patched_body = texture_pattern.sub(replace_parameter, body)
        if patched_body != body:
            patched_body = _renumber_sidecar_parameter_indexes(patched_body)
        return f"{match.group(1)}{patched_body}{match.group(5)}"

    return wrapper_pattern.sub(prune_wrapper, sidecar_text), removed_count


def _apply_source_pbr_scalar_parameters(
    sidecar_text: str,
    *,
    material_names: Sequence[str],
    roughness_value: int,
    metallic_value: int,
) -> tuple[str, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    if not target_keys:
        return sidecar_text, 0
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    edited_wrappers = 0

    def wrapper_selected(attrs: str) -> bool:
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def set_or_insert_byte4(body: str, parameter_name: str, item_id: str, value: int) -> tuple[str, bool]:
        parameter_pattern = re.compile(
            rf'(<MaterialParameterByte4\b[^>]*_name="{re.escape(parameter_name)}"[^>]*_value=")([^"]*)(")',
            flags=re.IGNORECASE | re.DOTALL,
        )
        replaced_body, replace_count = parameter_pattern.subn(rf"\g<1>{int(value)}\3", body)
        if replace_count:
            return replaced_body, True
        insertion = (
            f'\n\t\t\t\t\t\t\t<MaterialParameterByte4 StringItemID="{parameter_name}" '
            f'ItemID="{item_id}" _name="{parameter_name}" _value="{int(value)}" Index="0"/>'
        )
        vector_close = re.search(r"</Vector>", body, flags=re.IGNORECASE)
        if vector_close:
            insert_at = vector_close.start()
            return body[:insert_at] + insertion + body[insert_at:], True
        return body + insertion, True

    def patch_wrapper(match: re.Match[str]) -> str:
        nonlocal edited_wrappers
        attrs = match.group("attrs")
        if not wrapper_selected(attrs):
            return match.group(0)
        body = match.group("body")
        body, rough_changed = set_or_insert_byte4(body, "_scratchRoughness", "638052851515390", roughness_value)
        body, metal_changed = set_or_insert_byte4(body, "_scratchMetallic", "488189023223806", metallic_value)
        if rough_changed or metal_changed:
            edited_wrappers += 1
            body = _renumber_sidecar_parameter_indexes(body)
        return f"{match.group(1)}{body}{match.group(5)}"

    return wrapper_pattern.sub(patch_wrapper, sidecar_text), edited_wrappers


def _neutralize_inherited_material_layers(
    sidecar_text: str,
    *,
    material_names: Sequence[str] = (),
    keep_rules: Sequence[tuple[str, str]] = (),
    complete_external_reset: bool = False,
) -> tuple[str, int, int]:
    target_keys = {
        _normalize_sidecar_material_name(str(name or ""))
        for name in tuple(material_names or ())
        if str(name or "").strip()
    }
    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    keep_paths = {texture_path for _parameter, texture_path in keep if texture_path}
    wrapper_pattern = re.compile(
        r"(<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    neutral_texture_tokens = (
        "colorblendingmasktexture",
        "detailmasktexture",
        "grime",
        "detail",
        "damage",
        "heighttexture",
        "materialtexture",
        "layer",
    )
    neutral_color_tokens = ("tintcolor", "dyeing", "scratchtint", "baseheighttint")
    neutral_byte_tokens = ("grime", "dyeing")
    neutral_flag_names = {"_colorblendingflag"}
    reset_remove_parameter_tokens = (
        "clothcategory",
        "clothmaskbit",
        "sheen",
        "scratchroughness",
        "scratchmetallic",
    )
    reset_zero_float_tokens = (
        "screenspacedisplacementscale",
        "detailscreenspacedisplacementscale",
    )
    reset_one_float_tokens = (
        "brightness",
    )
    edited_wrappers = 0
    edited_parameters = 0

    def wrapper_selected(attrs: str) -> bool:
        if not target_keys:
            return True
        name_match = re.search(r'\b_subMeshName="([^"]*)"', attrs, flags=re.IGNORECASE)
        wrapper_name = str(name_match.group(1) if name_match else "")
        wrapper_key = _normalize_sidecar_material_name(wrapper_name)
        if wrapper_key in target_keys:
            return True
        return any(_sidecar_material_names_match(wrapper_name, target_name) for target_name in target_keys)

    def neutralize_wrapper(match: re.Match[str]) -> str:
        nonlocal edited_wrappers, edited_parameters
        attrs = match.group("attrs")
        body = match.group("body")
        if not wrapper_selected(attrs):
            return match.group(0)
        wrapper_edits = 0
        if complete_external_reset:
            patched_body, material_name_edits = re.subn(
                r'(<Material\b[^>]*\b_materialName=")(SkinnedMesh(?:Cloth|Skin|Hair)[^"]*)(")',
                r"\1SkinnedMeshStandard_Ver2\3",
                body,
                flags=re.IGNORECASE | re.DOTALL,
            )
            wrapper_edits += material_name_edits
        else:
            patched_body = body

        def replace_texture(texture_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            block = texture_match.group(0)
            parameter_name = _sidecar_parameter_name(block).strip().lower()
            path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
            texture_path = _normalize_texture_path(path_match.group(1) if path_match else "")
            if (parameter_name, texture_path) in keep or texture_path in keep_paths:
                return block
            if any(token in parameter_name for token in neutral_texture_tokens):
                wrapper_edits += 1
                return ""
            return block

        patched_body = texture_pattern.sub(replace_texture, patched_body)

        def replace_flag(flag_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(flag_match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if complete_external_reset and parameter_name == "_rendersettingflag":
                if str(flag_match.group(3) or "") == "4":
                    return flag_match.group(0)
                wrapper_edits += 1
                return f"{flag_match.group(1)}4{flag_match.group(4)}"
            if parameter_name not in neutral_flag_names:
                return flag_match.group(0)
            wrapper_edits += 1
            return f"{flag_match.group(1)}0{flag_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterBitFlag32\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_flag,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if complete_external_reset and not re.search(
            r'<MaterialParameterBitFlag32\b[^>]*_name="_renderSettingFlag"',
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            render_flag = (
                '\n\t\t\t\t\t\t\t<MaterialParameterBitFlag32 StringItemID="_renderSettingFlag" '
                'ItemID="8" _name="_renderSettingFlag" _value="4" Index="0"/>'
            )
            vector_match = re.search(r"</Vector>", patched_body, flags=re.IGNORECASE)
            if vector_match:
                patched_body = patched_body[: vector_match.start()] + render_flag + patched_body[vector_match.start() :]
            else:
                patched_body += render_flag
            wrapper_edits += 1

        def replace_float(float_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(float_match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if not complete_external_reset:
                return float_match.group(0)
            if any(token in normalized_parameter for token in reset_zero_float_tokens):
                replacement_value = "0.000000"
            elif any(token in normalized_parameter for token in reset_one_float_tokens):
                replacement_value = "1.000000"
            else:
                return float_match.group(0)
            if str(float_match.group(3) or "") == replacement_value:
                return float_match.group(0)
            wrapper_edits += 1
            return f"{float_match.group(1)}{replacement_value}{float_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterFloat\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_float,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if complete_external_reset:
            def remove_reset_parameter(parameter_match: re.Match[str]) -> str:
                nonlocal wrapper_edits
                block = parameter_match.group(0)
                parameter_name = _sidecar_parameter_name(block).strip().lower()
                normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
                if any(token in normalized_parameter for token in reset_remove_parameter_tokens):
                    wrapper_edits += 1
                    return ""
                return block

            patched_body = re.sub(
                r"\s*<MaterialParameter(?:Float|Byte4|BitFlag32|ClothCategory)\b[^>]*/>",
                remove_reset_parameter,
                patched_body,
                flags=re.IGNORECASE | re.DOTALL,
            )

        def replace_color(color_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(color_match.group(2) or "").strip().lower()
            if not any(token in parameter_name for token in neutral_color_tokens):
                return color_match.group(0)
            original_value = str(color_match.group(3) or "").strip()
            replacement_value = "#ffffff00" if original_value.startswith("#") else "1.000000 1.000000 1.000000"
            if original_value == replacement_value:
                return color_match.group(0)
            wrapper_edits += 1
            return f"{color_match.group(1)}{replacement_value}{color_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterColor\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_color,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )

        def replace_byte(byte_match: re.Match[str]) -> str:
            nonlocal wrapper_edits
            parameter_name = str(byte_match.group(2) or "").strip().lower()
            if not any(token in parameter_name for token in neutral_byte_tokens):
                return byte_match.group(0)
            wrapper_edits += 1
            return f"{byte_match.group(1)}0{byte_match.group(4)}"

        patched_body = re.sub(
            r'(<MaterialParameterByte4\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            replace_byte,
            patched_body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if wrapper_edits <= 0:
            return match.group(0)
        edited_wrappers += 1
        edited_parameters += wrapper_edits
        return match.group(1) + patched_body + match.group(5)

    patched = wrapper_pattern.sub(neutralize_wrapper, str(sidecar_text or ""))
    if edited_parameters <= 0 and complete_external_reset and not wrapper_pattern.search(str(sidecar_text or "")):
        patched, flat_wrappers, flat_parameters = _neutralize_flat_material_instance_parameters(
            patched,
            keep_rules=keep_rules,
            complete_external_reset=complete_external_reset,
        )
        edited_wrappers += flat_wrappers
        edited_parameters += flat_parameters
    if complete_external_reset and edited_parameters:
        patched, pbd_property_edits = re.subn(
            r"\s*<OverridedPbdMaterialProperty\b[^>]*/>",
            "",
            patched,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if pbd_property_edits:
            edited_parameters += pbd_property_edits
        patched, pbd_name_edits = re.subn(
            r'\s*_pbdSimulationMaterialName="[^"]*"',
            "",
            patched,
            flags=re.IGNORECASE,
        )
        if pbd_name_edits:
            edited_parameters += pbd_name_edits
    if edited_parameters:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, edited_wrappers, edited_parameters


def _neutralize_flat_material_instance_parameters(
    sidecar_text: str,
    *,
    keep_rules: Sequence[tuple[str, str]] = (),
    complete_external_reset: bool = False,
) -> tuple[str, int, int]:
    """Neutralize PAMI/static-style flat material parameters for complete swaps."""

    keep = {
        (str(parameter or "").strip().lower(), _normalize_texture_path(texture_path))
        for parameter, texture_path in tuple(keep_rules or ())
        if str(parameter or "").strip() and _normalize_texture_path(texture_path)
    }
    keep_paths = {texture_path for _parameter, texture_path in keep if texture_path}
    if "<MaterialParameter" not in str(sidecar_text or ""):
        return sidecar_text, 0, 0

    edited = 0
    texture_pattern = re.compile(
        r"\s*<MaterialParameterTexture\b[^>]*/>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    remove_texture_tokens = (
        "colorblendingmasktexture",
        "detailmasktexture",
        "grime",
        "detail",
        "damage",
        "heighttexture",
        "materialtexture",
        "layer",
    )

    def flat_parameter_name(block: str) -> str:
        match = re.search(r'\b(?:_name|Name)="([^"]*)"', block, flags=re.IGNORECASE)
        return str(match.group(1) if match else "").strip()

    def flat_parameter_value(block: str) -> str:
        match = re.search(r'\b(?:_value|Value)="([^"]*)"', block, flags=re.IGNORECASE)
        return str(match.group(1) if match else "").strip()

    def replace_texture(match: re.Match[str]) -> str:
        nonlocal edited
        block = match.group(0)
        parameter_name = flat_parameter_name(block).lower()
        texture_path = _normalize_texture_path(flat_parameter_value(block))
        if (parameter_name, texture_path) in keep or texture_path in keep_paths:
            return block
        if any(token in parameter_name for token in remove_texture_tokens):
            edited += 1
            return ""
        return block

    patched = texture_pattern.sub(replace_texture, str(sidecar_text or ""))

    def replace_named_value(pattern: str, tokens: Sequence[str], replacement_for: Callable[[str], str]) -> None:
        nonlocal patched, edited

        def replace(match: re.Match[str]) -> str:
            nonlocal edited
            parameter_name = str(match.group(2) or "").strip().lower()
            normalized_parameter = re.sub(r"[^a-z0-9]+", "", parameter_name)
            if not any(token in normalized_parameter for token in tokens):
                return match.group(0)
            replacement_value = replacement_for(str(match.group(3) or ""))
            if str(match.group(3) or "") == replacement_value:
                return match.group(0)
            edited += 1
            return f"{match.group(1)}{replacement_value}{match.group(4)}"

        patched = re.sub(pattern, replace, patched, flags=re.IGNORECASE | re.DOTALL)

    if complete_external_reset:
        replace_named_value(
            r'(<MaterialParameterFloat\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("brightness",),
            lambda _value: "1.000000",
        )
        replace_named_value(
            r'(<MaterialParameterColor\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("tintcolor", "dyeing", "scratchtint", "baseheighttint"),
            lambda value: "#ffffff00" if str(value or "").strip().startswith("#") else "1.000000 1.000000 1.000000",
        )
        replace_named_value(
            r'(<MaterialParameterBitFlag32\b[^>]*(?:_name|Name)="([^"]*)"[^>]*(?:_value|Value)=")([^"]*)(")',
            ("colorblendingflag",),
            lambda _value: "0",
        )

    if edited:
        patched = _renumber_sidecar_parameter_indexes(patched)
    return patched, 1 if edited else 0, edited


def _renumber_sidecar_parameter_indexes(sidecar_text: str) -> str:
    vector_pattern = re.compile(
        r'(<Vector\b[^>]*(?:Name|name|_name)="_parameters"[^>]*>)(.*?)(\s*</Vector>)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    parameter_index_pattern = re.compile(
        r'(<MaterialParameter[A-Za-z0-9_:.-]*\b[^>]*\bIndex=")(\d+)(")',
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace_vector(match: re.Match[str]) -> str:
        next_index = 0

        def replace_index(index_match: re.Match[str]) -> str:
            nonlocal next_index
            replacement = f"{index_match.group(1)}{next_index}{index_match.group(3)}"
            next_index += 1
            return replacement

        body = parameter_index_pattern.sub(replace_index, match.group(2))
        return f"{match.group(1)}{body}{match.group(3)}"

    return vector_pattern.sub(replace_vector, sidecar_text)


def _rename_sidecar_parameter_name(parameter_text: str, new_parameter_name: str) -> str:
    start_tag_match = re.match(r"(<MaterialParameterTexture\b[^>]*>)", parameter_text, flags=re.IGNORECASE | re.DOTALL)
    if start_tag_match is None:
        return parameter_text
    start_tag = start_tag_match.group(1)
    patched_start = start_tag
    for attr in ("StringItemID", "_name"):
        patched_start = re.sub(
            rf'\b{re.escape(attr)}="[^"]*"',
            f'{attr}="{_escape_xml_attr(new_parameter_name)}"',
            patched_start,
            count=1,
        )
    if patched_start == start_tag:
        patched_start = re.sub(
            r'\b(Name|name)="[^"]*"',
            lambda match: f'{match.group(1)}="{_escape_xml_attr(new_parameter_name)}"',
            patched_start,
            count=1,
        )
    return patched_start + parameter_text[start_tag_match.end() :]


def _sidecar_texture_injection_position(parameter_body: str, parameter_name: str) -> tuple[Optional[int], Optional[int]]:
    normalized_parameter = str(parameter_name or "").strip().lower()
    if normalized_parameter not in {"_overlaycolortexture", "_basecolortexture", "_diffusetexture", "_albedotexture"}:
        return None, None
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    fallback: Optional[tuple[int, int]] = None
    for match in texture_pattern.finditer(parameter_body):
        block = match.group(0)
        block_name = _sidecar_parameter_name(block).lower()
        block_index = _sidecar_parameter_index(block)
        if block_index is None:
            continue
        if block_name == "_normaltexture":
            return match.end(), block_index + 1
        if block_name == "_heighttexture" and fallback is None:
            fallback = (match.start(), block_index)
        elif block_name in {"_colorblendingmasktexture", "_detailmasktexture"} and fallback is None:
            fallback = (match.start(), block_index)
    if fallback is not None:
        return fallback
    return None, None


def _sidecar_parameter_name(parameter_text: str) -> str:
    name_match = re.search(
        r'(?:StringItemID|_name|Name|name)="([^"]+)"',
        parameter_text,
        flags=re.IGNORECASE,
    )
    return str(name_match.group(1) if name_match else "").strip()


def _sidecar_parameter_index(parameter_text: str) -> Optional[int]:
    index_match = re.search(r'\bIndex="(\d+)"', parameter_text)
    if index_match is None:
        return None
    try:
        return int(index_match.group(1))
    except ValueError:
        return None


def _shift_sidecar_parameter_indexes(parameter_body: str, start_index: int) -> str:
    def replace_index(match: re.Match[str]) -> str:
        try:
            value = int(match.group(1))
        except ValueError:
            return match.group(0)
        if value < start_index:
            return match.group(0)
        return f'Index="{value + 1}"'

    return re.sub(r'\bIndex="(\d+)"', replace_index, parameter_body)


def _find_sidecar_material_wrapper(sidecar_text: str, target_name: str) -> Optional[re.Match[str]]:
    normalized_target = _normalize_sidecar_material_name(target_name)
    fallback: Optional[tuple[float, re.Match[str]]] = None
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b[^>]*>.*?</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in wrapper_pattern.finditer(sidecar_text):
        name_match = re.search(
            r'(?:_subMeshName|subMeshName|SubMeshName|_submesh|submesh|MaterialName|materialName|Name|name)="([^"]+)"',
            match.group(0),
            flags=re.IGNORECASE,
        )
        if name_match and _normalize_sidecar_material_name(name_match.group(1)) == normalized_target:
            return match
        if name_match:
            score = _sidecar_material_match_score(target_name, name_match.group(1))
            if score > 0 and (fallback is None or score > fallback[0]):
                fallback = (score, match)
    if fallback is not None and fallback[0] >= 6.0:
        return fallback[1]
    return None


def _sidecar_material_names_match(left: str, right: str) -> bool:
    left_normalized = _normalize_sidecar_material_name(left)
    right_normalized = _normalize_sidecar_material_name(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if len(left_normalized) >= 8 and left_normalized in right_normalized:
        return True
    if len(right_normalized) >= 8 and right_normalized in left_normalized:
        return True
    return _sidecar_material_match_score(left, right) >= 6.0


def _sidecar_material_match_score(left: str, right: str) -> float:
    left_tokens = _material_tokens(left)
    right_tokens = _material_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    score = float(len(overlap) * 4)
    for token in overlap:
        score += min(4.0, len(token) * 0.5)
        if token in {"acc", "accessory", "blade", "body", "guard", "handle", "hilt", "tail"}:
            score += 4.0
    if "blade" in left_tokens and "sword" in right_tokens:
        score += 6.0
    if "sword" in left_tokens and "blade" in right_tokens:
        score += 6.0
    return score


def _normalize_sidecar_material_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _sidecar_texture_parameter_template(sidecar_text: str, parameter_name: str) -> str:
    parameter_match = re.search(
        rf"<MaterialParameterTexture\b[^>]*(?:StringItemID|_name|Name|name)=\"{re.escape(parameter_name)}\"[^>]*>.*?</MaterialParameterTexture>",
        sidecar_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if parameter_match is not None:
        return parameter_match.group(0).strip()
    item_id = "1" if parameter_name == "_overlayColorTexture" else "0"
    return (
        f'<MaterialParameterTexture StringItemID="{parameter_name}" ItemID="{item_id}" _name="{parameter_name}" Index="0">\n'
        f'\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path=""/>\n'
        f"\t\t\t\t\t\t\t</MaterialParameterTexture>"
    )


def _next_material_parameter_index(wrapper_text: str) -> int:
    indexes = []
    for raw_index in re.findall(r'\bIndex="(\d+)"', wrapper_text):
        try:
            indexes.append(int(raw_index))
        except ValueError:
            continue
    return max(indexes, default=-1) + 1


def _retarget_texture_parameter_template(
    template: str,
    parameter_name: str,
    texture_path: str,
    index: int,
) -> str:
    patched = template.strip()
    if re.search(r'StringItemID="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'StringItemID="[^"]*"', f'StringItemID="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    if re.search(r'_name="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'_name="[^"]*"', f'_name="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    elif re.search(r'\bName="[^"]*"', patched, flags=re.IGNORECASE):
        patched = re.sub(r'\bName="[^"]*"', f'Name="{parameter_name}"', patched, count=1, flags=re.IGNORECASE)
    patched = re.sub(r'Index="\d+"', f'Index="{int(index)}"', patched, count=1)
    if re.search(r'\b(?:_path|path|Path|_value|Value|value)="[^"]*"', patched):
        patched = re.sub(
            r'\b(_path|path|Path|_value|Value|value)="[^"]*"',
            lambda match: f'{match.group(1)}="{_escape_xml_attr(texture_path)}"',
            patched,
            count=1,
        )
    else:
        patched = patched.replace(
            "</MaterialParameterTexture>",
            f'\n\t\t\t\t\t\t\t\t<ResourceReferencePath_ITexture Name="_value" _path="{_escape_xml_attr(texture_path)}"/>\n\t\t\t\t\t\t\t</MaterialParameterTexture>',
        )
    return patched


def _escape_xml_attr(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _append_unused_texture_warnings(
    texture_sets: Mapping[str, ReplacementTextureSet],
    report: TextureReplacementReport,
) -> None:
    used = {
        (
            str(mapping.source_material_name or "").strip().lower(),
            str(mapping.source_path.name or "").strip().lower(),
        )
        for mapping in report.slot_mappings
    }
    for texture_set in texture_sets.values():
        unused_slots = [
            slot
            for slot in texture_set.slots.values()
            if (
                str(slot.material_name or "").strip().lower(),
                str(slot.source_path.name or "").strip().lower(),
            )
            not in used
        ]
        if unused_slots:
            pbr_slots = [
                slot
                for slot in unused_slots
                if str(slot.slot_kind or "").strip().lower() in {"metallic", "roughness", "ao"}
            ]
            if pbr_slots and len(pbr_slots) == len(unused_slots):
                report.warnings.append(
                    f"{texture_set.material_name}: {len(pbr_slots)} standalone PBR source map(s) were detected but not auto-bound "
                    "because Crimson Desert material sidecars expect packed game mask textures such as _ma/_mg/_sp. "
                    + ", ".join(slot.source_path.name for slot in pbr_slots[:6])
                    + (" ..." if len(pbr_slots) > 6 else "")
                )
                continue
            report.warnings.append(
                f"{texture_set.material_name}: {len(unused_slots)} source texture(s) were not mapped to existing material parameters: "
                + ", ".join(slot.source_path.name for slot in unused_slots[:6])
                + (" ..." if len(unused_slots) > 6 else "")
            )


def _warn_once(report: TextureReplacementReport, message: str) -> None:
    text = str(message or "").strip()
    if text and text not in report.warnings:
        report.warnings.append(text)


def _looks_like_normal_texture_path(texture_path: str) -> bool:
    basename = PurePosixPath(str(texture_path or "").replace("\\", "/")).name.lower()
    stem = PurePosixPath(basename).stem.lower()
    if not basename:
        return False
    if "normal" in stem or stem.endswith(("_n", "_wn", "_nm", "_nrm", "_nor", "_no")):
        return True
    if re.search(r"(?:^|[_\-.])n(?:$|[_\-.])", stem):
        return True
    return False


def _sidecar_texture_parameter_rows(sidecar_text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    texture_pattern = re.compile(
        r"<MaterialParameterTexture\b[^>]*>.*?</MaterialParameterTexture>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in texture_pattern.finditer(str(sidecar_text or "")):
        block = match.group(0)
        parameter_name = _sidecar_parameter_name(block)
        path_match = re.search(r'\b_path="([^"]*)"', block, flags=re.IGNORECASE)
        texture_path = str(path_match.group(1) if path_match else "").replace("\\", "/").strip()
        if parameter_name or texture_path:
            rows.append((parameter_name, texture_path))
    return rows


def _append_texture_contract_warnings(
    *,
    texture_payloads: Sequence[TextureReplacementPayload],
    sidecar_payloads: Sequence[TextureReplacementPayload],
    report: TextureReplacementReport,
) -> None:
    texture_paths = {
        _normalize_texture_path(payload.target_path)
        for payload in texture_payloads
        if str(payload.kind or "").lower().startswith("texture")
    }
    if not texture_paths:
        return

    for payload in texture_payloads:
        target_path = str(payload.target_path or "").replace("\\", "/").strip()
        if _is_shared_material_layer_texture(target_path):
            _warn_once(
                report,
                f"Texture contract warning: generated payload overrides stock/shared shader texture {target_path}; "
                "this can tint the model, add grime/speckles, or affect shared material layers. "
                "This is manual-only and should not be produced by conservative auto-routing.",
            )

    if not sidecar_payloads:
        return

    generated_role_by_path: dict[str, TextureSlotMapping] = {
        _normalize_texture_path(mapping.output_texture_path): mapping
        for mapping in report.slot_mappings
        if str(mapping.output_texture_path or "").strip()
    }

    sidecar_rows: list[tuple[str, str]] = []
    sidecar_text = ""
    for payload in sidecar_payloads:
        try:
            text = bytes(payload.payload_data or b"").decode("utf-8", errors="replace")
        except Exception:
            text = ""
        sidecar_text += "\n" + text
        sidecar_rows.extend(_sidecar_texture_parameter_rows(text))

    referenced_paths = {
        _normalize_texture_path(texture_path)
        for _parameter_name, texture_path in sidecar_rows
        if str(texture_path or "").strip()
    }
    for texture_path in sorted(texture_paths - referenced_paths):
        _warn_once(
            report,
            f"Texture contract warning: generated DDS is not referenced by the patched material sidecar: {texture_path}.",
        )

    for parameter_name, texture_path in sidecar_rows:
        parameter_key = str(parameter_name or "").strip().lower()
        expected_role = _texture_role_for_parameter_and_path(parameter_name, texture_path)
        generated_mapping = generated_role_by_path.get(_normalize_texture_path(texture_path))
        generated_role = str(getattr(generated_mapping, "slot_kind", "") or "").strip().lower() if generated_mapping else ""
        if parameter_key == "_normaltexture" and texture_path and not _looks_like_normal_texture_path(texture_path):
            _warn_once(
                report,
                f"Texture contract warning: _normalTexture points at a non-normal-looking DDS path: {texture_path}.",
            )
        if (
            expected_role in {"base", "normal", "height", "material_mask", "detail_mask"}
            and generated_role in {"base", "normal", "height", "material_mask", "detail_mask"}
            and expected_role != generated_role
        ):
            source_name = PurePosixPath(str(getattr(generated_mapping, "source_path", "") or "")).name if generated_mapping else ""
            source_note = f" from {source_name}" if source_name else ""
            _warn_once(
                report,
                f"Texture contract warning: {parameter_name or 'material parameter'} expects {expected_role.replace('_', ' ')}, "
                f"but the generated DDS at {texture_path} came from a {generated_role.replace('_', ' ')} source{source_note}.",
            )


def _append_crimson_dds_validation_warnings(
    dds_source: Path,
    *,
    vpath: str,
    report: TextureReplacementReport,
) -> None:
    from cdmw.core.pipeline import inspect_crimson_dds

    try:
        crimson_info = inspect_crimson_dds(dds_source, vpath=vpath)
    except Exception as exc:
        _warn_once(report, f"Crimson DDS warning for {vpath or dds_source.name}: could not inspect DDS quirks: {exc}")
        return

    fatal_messages = [finding.message for finding in crimson_info.findings if finding.severity == "fatal"]
    if fatal_messages:
        raise ValueError("; ".join(fatal_messages))

    label = str(vpath or dds_source.name).replace("\\", "/").strip()
    for finding in crimson_info.findings:
        if finding.severity == "warning":
            _warn_once(report, f"Crimson DDS warning for {label}: {finding.message}")
        elif finding.severity == "info" and finding.code == "requires_pathc":
            _warn_once(report, f"Crimson DDS note for {label}: {finding.message}")


def _build_texture_payload(
    source_slot: ReplacementTextureSlot,
    *,
    target_entry: object,
    texconv_path: Optional[Path],
    read_original_texture_bytes: Callable[[object], bytes],
    original_texture_source_path: Callable[[object], Path],
    report: TextureReplacementReport,
    on_log: Optional[Callable[[str], None]],
    texture_output_size_mode: str = "source",
) -> bytes:
    from cdmw.core.pipeline import build_texconv_command, max_mips_for_size, parse_dds, read_png_dimensions
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.core.common import run_process_with_cancellation

    def _source_image_dimensions(path: Path) -> tuple[int, int]:
        if path.suffix.lower() == ".png":
            return read_png_dimensions(path)
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)

    if source_slot.source_path.suffix.lower() == ".dds":
        target_vpath = str(getattr(target_entry, "path", "") or "").replace("\\", "/").strip()
        _append_crimson_dds_validation_warnings(source_slot.source_path, vpath=target_vpath, report=report)
        source_info = parse_dds(source_slot.source_path)
        original_info = parse_dds(original_texture_source_path(target_entry))
        mismatch_parts: list[str] = []
        if (source_info.width, source_info.height) != (original_info.width, original_info.height):
            mismatch_parts.append(
                f"size {source_info.width}x{source_info.height} != original {original_info.width}x{original_info.height}"
            )
        if source_info.texconv_format != original_info.texconv_format:
            mismatch_parts.append(f"format {source_info.texconv_format} != original {original_info.texconv_format}")
        if int(source_info.mip_count or 1) != int(original_info.mip_count or 1):
            mismatch_parts.append(f"mips {source_info.mip_count or 1} != original {original_info.mip_count or 1}")
        if mismatch_parts:
            report.warnings.append(
                f"DDS replacement {source_slot.source_path.name} differs from target template: {', '.join(mismatch_parts)}."
            )
        return source_slot.source_path.read_bytes()
    original_source = original_texture_source_path(target_entry)
    original_info = parse_dds(original_source)
    resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    with tempfile.TemporaryDirectory(prefix="cdmw_static_texture_") as temp_text:
        temp_dir = Path(temp_text)
        source_png = source_slot.source_path
        prepared_png = temp_dir / source_png.name
        if source_slot.slot_kind == "normal" and source_slot.normal_space == "opengl":
            _copy_png_with_inverted_green(source_png, prepared_png)
            report.warnings.append(f"Inverted green channel for OpenGL normal map: {source_png.name}")
        else:
            shutil.copy2(source_png, prepared_png)
        out_dir = temp_dir / "dds"
        out_dir.mkdir(parents=True, exist_ok=True)
        source_width, source_height = _source_image_dimensions(prepared_png)
        normalized_size_mode = str(texture_output_size_mode or "source").strip().lower()
        if normalized_size_mode == "original":
            output_width = int(original_info.width)
            output_height = int(original_info.height)
            mip_count = max(1, min(max_mips_for_size(output_width, output_height), int(original_info.mip_count or 1)))
        else:
            output_width = int(source_width)
            output_height = int(source_height)
            mip_count = max_mips_for_size(output_width, output_height)
        if (
            output_width < int(float(source_width) * 0.75)
            or output_height < int(float(source_height) * 0.75)
        ):
            report.warnings.append(
                f"{source_png.name}: output DDS size {output_width}x{output_height} is smaller than source "
                f"{source_width}x{source_height}."
            )
        output_format = str(original_info.texconv_format or "").strip() or "BC7_UNORM"
        if str(source_slot.slot_kind or "").strip().lower() == "normal":
            if output_format.upper() not in {"BC5_UNORM", "BC5_SNORM"}:
                _warn_once(
                    report,
                    f"{source_png.name}: normal map output uses BC5_UNORM instead of template format {output_format}.",
                )
                output_format = "BC5_UNORM"
        if on_log:
            on_log(f"Converting {source_png.name} -> {getattr(target_entry, 'path', 'texture')} ({output_format})")
        produced = out_dir / f"{prepared_png.stem}.dds"
        native_report = encode_dds_with_directxtex(
            prepared_png,
            produced,
            dds_format=output_format,
            width=output_width,
            height=output_height,
            mip_count=mip_count,
        )
        if native_report and produced.is_file() and produced.stat().st_size > 0:
            if on_log:
                on_log(f"Encoded {source_png.name} with DirectXTex native DDS encode.")
        else:
            if resolved_texconv is None:
                raise FileNotFoundError(
                    "DirectXTex native DDS encode failed and no optional legacy texconv fallback is configured."
                )
            cmd = build_texconv_command(
                resolved_texconv,
                prepared_png,
                out_dir,
                output_format,
                mip_count,
                output_width,
                output_height,
                overwrite_existing_dds=True,
            )
            return_code, stdout, stderr = run_process_with_cancellation(cmd)
            if return_code != 0:
                raise RuntimeError(stderr.strip() or stdout.strip() or f"texconv exited with code {return_code}")
        if not produced.is_file():
            raise FileNotFoundError(f"DDS encoder did not produce {produced.name}")
        target_vpath = str(getattr(target_entry, "path", "") or "").replace("\\", "/").strip()
        _append_crimson_dds_validation_warnings(produced, vpath=target_vpath, report=report)
        return produced.read_bytes()


def _copy_png_with_inverted_green(source_path: Path, target_path: Path) -> None:
    from PIL import Image

    with Image.open(source_path) as image:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        g = g.point(lambda value: 255 - int(value))
        Image.merge("RGBA", (r, g, b, a)).save(target_path)
