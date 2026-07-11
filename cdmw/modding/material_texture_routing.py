"""Texture grouping and source-material routing helpers."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.domain.textures.material_parameters import evaluate_material_parameters, source_emissive_strength

from .asset_replacement import classify_texture_binding, infer_cd_texture_role_from_path
from .mesh_parser import ParsedMesh
from .static_mesh_replacer import StaticOutputDrawSection, StaticSubmeshMapping, _semantic_tokens
from .material_profiles import SourceMaterialRoutingResult, TextureAssignmentGuidance
from .material_replacer import (
    ReplacementTextureSet,
    ReplacementTextureSlot,
    TextureReplacementReport,
    _SOURCE_TEXTURE_IMAGE_EXTENSIONS,
    _normalize_sidecar_material_name,
    _source_owned_material_name_for_output_section,
    _warn_once,
    is_static_replacement_helper_material_name,
)
from .material_source_driven import _normalized_accent_glow_rgb, _sanitize_texture_component

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
    ("normal", "Normal_GreenUp", "green_up"),
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
        if path.suffix.lower() not in _SOURCE_TEXTURE_IMAGE_EXTENSIONS:
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
                source_authority="filename",
            )
    _attach_source_texture_reference_base_slots(grouped, texture_files, source_submeshes)
    _attach_source_material_factor_slots(grouped, source_submeshes)
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
            normal_space = hint if slot_kind == "normal" and hint in {"green_up", "directx"} else ""
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

    if not source_submeshes:
        return
    texture_files_by_key: dict[str, Path] = {}
    for raw_path in texture_files:
        path = raw_path.expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if path.suffix.lower() not in _SOURCE_TEXTURE_IMAGE_EXTENSIONS:
            continue
        for key in _texture_reference_keys(path):
            texture_files_by_key.setdefault(key, path)
    for source_submesh in tuple(source_submeshes or ()):
        for raw_path in (
            getattr(source_submesh, "texture", ""),
            *tuple(slot_path for _slot_kind, slot_path in tuple(getattr(source_submesh, "texture_slots", ()) or ())),
            *tuple(getattr(texture_input, "source_texture_path", "") or getattr(texture_input, "preview_texture_path", "") for texture_input in tuple(getattr(source_submesh, "preview_material_texture_inputs", ()) or ())),
        ):
            text = str(raw_path or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            if path.suffix.lower() not in _SOURCE_TEXTURE_IMAGE_EXTENSIONS or not path.is_file():
                continue
            for key in _texture_reference_keys(path):
                texture_files_by_key.setdefault(key, path)
    if not texture_files_by_key:
        return

    def attach_slot(
        material_name: str,
        slot_kind: str,
        texture_reference: object,
        *,
        visible_base_guard: bool = False,
        semantic_subtype: str = "",
        packed_channels: Sequence[str] = (),
        source_authority: str = "metadata",
    ) -> None:
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
        new_authority = str(source_authority or "metadata").strip().lower()
        allow_shared_explicit_texture = new_authority in {"gltf", "metadata", "manual"}
        for current_material_key, current_texture_set in tuple(grouped.items()):
            for current_slot_key, current_slot in tuple((current_texture_set.slots or {}).items()):
                if not _paths_match(current_slot.source_path, matched_path):
                    continue
                same_material = str(current_material_key or "").strip().lower() == str(material_name or "").strip().lower()
                same_slot = str(current_slot_key or "").strip().lower() == normalized_slot
                if same_material and same_slot:
                    continue
                if allow_shared_explicit_texture:
                    # glTF/scene metadata may legitimately bind one image to
                    # several materials, or to both visible base and packed PBR
                    # slots. Do not let filename grouping steal that explicit
                    # material contract from later source-owned sections.
                    continue
                if _source_authority_priority(new_authority) <= _source_authority_priority(current_slot.source_authority):
                    return
                current_texture_set.slots.pop(current_slot_key, None)
        texture_set = grouped.setdefault(material_name.lower(), ReplacementTextureSet(material_name=material_name))
        existing = texture_set.slots.get(normalized_slot)
        should_replace = existing is None
        if existing is not None:
            existing_authority = str(getattr(existing, "source_authority", "") or "").strip().lower()
            if _source_authority_priority(new_authority) > _source_authority_priority(existing_authority):
                should_replace = True
            elif _source_authority_priority(new_authority) == _source_authority_priority(existing_authority):
                should_replace = _texture_slot_priority(matched_path, normalized_slot) > _texture_slot_priority(
                    existing.source_path,
                    existing.slot_kind,
                )
        if should_replace:
            texture_set.slots[normalized_slot] = ReplacementTextureSlot(
                material_name=material_name,
                slot_kind=normalized_slot,
                source_path=matched_path,
                normal_space="",
                semantic_subtype=str(semantic_subtype or ""),
                packed_channels=tuple(str(channel or "").strip().lower() for channel in tuple(packed_channels or ()) if str(channel or "").strip()),
                source_authority=new_authority,
            )
        elif existing is not None and _paths_match(existing.source_path, matched_path):
            if semantic_subtype and not existing.semantic_subtype:
                existing.semantic_subtype = str(semantic_subtype or "")
            if packed_channels and not existing.packed_channels:
                existing.packed_channels = tuple(
                    str(channel or "").strip().lower()
                    for channel in tuple(packed_channels or ())
                    if str(channel or "").strip()
                )
            if new_authority and _source_authority_priority(new_authority) > _source_authority_priority(existing.source_authority):
                existing.source_authority = new_authority

    for source_submesh in source_submeshes:
        material_name = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip()
        if not material_name:
            continue
        attach_slot(
            material_name,
            "base",
            getattr(source_submesh, "texture", ""),
            visible_base_guard=True,
            source_authority="metadata",
        )
        for slot_kind, slot_path in tuple(getattr(source_submesh, "texture_slots", ()) or ()):
            raw_slot_kind = str(slot_kind or "")
            normalized_raw_slot = _sanitize_texture_component(raw_slot_kind)
            if normalized_raw_slot in {"metallicroughness", "metallic_roughness"}:
                attach_slot(
                    material_name,
                    raw_slot_kind,
                    slot_path,
                    semantic_subtype="metallic_roughness",
                    packed_channels=("roughness", "metallic"),
                    source_authority="gltf",
                )
            elif normalized_raw_slot in {"specularglossiness", "specular_glossiness", "speculargloss"}:
                attach_slot(
                    material_name,
                    raw_slot_kind,
                    slot_path,
                    semantic_subtype="specular_glossiness",
                    packed_channels=("specular", "glossiness"),
                    source_authority="gltf",
                )
            else:
                attach_slot(material_name, raw_slot_kind, slot_path, source_authority="metadata")
        for texture_input in tuple(getattr(source_submesh, "preview_material_texture_inputs", ()) or ()):
            slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip()
            texture_reference = (
                str(getattr(texture_input, "source_texture_path", "") or "").strip()
                or str(getattr(texture_input, "preview_texture_path", "") or "").strip()
                or str(getattr(texture_input, "source_dds_path", "") or "").strip()
            )
            input_material_name = (
                str(getattr(texture_input, "material_name", "") or "").strip()
                or material_name
            )
            confidence = str(getattr(texture_input, "confidence", "") or "").strip().lower()
            semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip().lower()
            authority = (
                "gltf"
                if confidence == "gltf"
                or semantic_subtype in {"metallic_roughness", "specular_glossiness", "occlusion", "normal", "emissive"}
                else "metadata"
            )
            attach_slot(
                input_material_name,
                slot_kind,
                texture_reference,
                semantic_subtype=semantic_subtype,
                packed_channels=tuple(getattr(texture_input, "packed_channels", ()) or ()),
                source_authority=authority,
            )


def _attach_source_material_factor_slots(
    grouped: dict[str, ReplacementTextureSet],
    source_submeshes: Sequence[object],
) -> None:
    """Promote scene material constants and role hints into source-owned slots."""

    for source_submesh in tuple(source_submeshes or ()):
        material_name = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip()
        if not material_name:
            continue
        role_tags = _source_material_role_tags(source_submesh)
        existing_texture_set = grouped.get(material_name.lower())
        if existing_texture_set is not None and role_tags:
            _merge_source_role_tags(existing_texture_set, role_tags)
        preview_color = _source_preview_rgb(source_submesh)
        preview_alpha = _source_preview_alpha(source_submesh)
        emissive_color = _source_emissive_rgb(source_submesh)
        emissive_strength = source_emissive_strength(source_submesh)
        roughness_factor = _source_material_numeric_parameter(source_submesh, "_roughnessFactor")
        metallic_factor = _source_material_numeric_parameter(source_submesh, "_metallicFactor")
        specular_factor = _source_material_specular_factor(source_submesh)
        glossiness_factor = _source_material_numeric_parameter(source_submesh, "_glossinessFactor")
        occlusion_strength = _source_material_numeric_parameter(
            source_submesh,
            "_gltfTextureStrength_occlusion",
            "_occlusionStrength",
        )
        if (
            preview_color is None
            and preview_alpha is None
            and emissive_color is None
            and emissive_strength is None
            and roughness_factor is None
            and metallic_factor is None
            and specular_factor is None
            and glossiness_factor is None
            and occlusion_strength is None
        ):
            continue
        texture_set = grouped.setdefault(material_name.lower(), ReplacementTextureSet(material_name=material_name))
        if role_tags:
            _merge_source_role_tags(texture_set, role_tags)
        if emissive_strength is not None:
            texture_set.emissive_strength = emissive_strength
        if roughness_factor is not None:
            texture_set.roughness_factor = roughness_factor
        if metallic_factor is not None:
            texture_set.metallic_factor = metallic_factor
        if specular_factor is not None:
            texture_set.specular_factor = specular_factor
        if glossiness_factor is not None:
            texture_set.glossiness_factor = glossiness_factor
        if occlusion_strength is not None:
            texture_set.occlusion_strength = occlusion_strength
        if preview_color is not None:
            texture_set.base_color_factor = preview_color
            existing_base = texture_set.slots.get("base")
            if existing_base is not None:
                existing_base.base_color_factor = preview_color
                existing_base.source_authority = existing_base.source_authority or "gltf"
        if preview_alpha is not None:
            existing_base = texture_set.slots.get("base")
            if existing_base is not None:
                existing_base.base_alpha_factor = preview_alpha
                existing_base.source_authority = existing_base.source_authority or "gltf"
        base_color = preview_color if "base" not in texture_set.slots else None
        if base_color is not None and "base" not in texture_set.slots:
            source_path = _solid_material_factor_png_path(material_name, "base", base_color)
            texture_set.slots["base"] = ReplacementTextureSlot(
                material_name=texture_set.material_name,
                slot_kind="base",
                source_path=source_path,
                normal_space="",
                source_authority="synthetic",
                base_color_factor=base_color,
                base_alpha_factor=preview_alpha,
            )
        if emissive_color is not None and "emissive" not in texture_set.slots:
            source_path = _solid_material_factor_png_path(material_name, "emissive", emissive_color)
            texture_set.slots["emissive"] = ReplacementTextureSlot(
                material_name=texture_set.material_name,
                slot_kind="emissive",
                source_path=source_path,
                normal_space="",
                source_authority="synthetic",
            )


def _merge_source_role_tags(texture_set: ReplacementTextureSet, role_tags: Sequence[str]) -> None:
    existing = tuple(
        str(tag or "").strip().lower()
        for tag in tuple(getattr(texture_set, "source_role_tags", ()) or ())
        if str(tag or "").strip()
    )
    merged = list(existing)
    for tag in tuple(role_tags or ()):
        normalized = _normalized_source_part_material_role(tag)
        if normalized and normalized not in merged:
            merged.append(normalized)
    texture_set.source_role_tags = tuple(merged)


def _source_material_role_tags(source_submesh: object) -> tuple[str, ...]:
    text_parts: list[str] = [
        str(getattr(source_submesh, "name", "") or ""),
        str(getattr(source_submesh, "material", "") or ""),
        str(getattr(source_submesh, "texture", "") or ""),
        str(getattr(source_submesh, "preview_sidecar_shader_family", "") or ""),
    ]
    slot_kinds: set[str] = set()
    for slot_kind, slot_path in tuple(getattr(source_submesh, "texture_slots", ()) or ()):
        slot_text = str(slot_kind or "")
        slot_kinds.add(_normalize_source_texture_slot_kind(slot_text) or _sanitize_texture_component(slot_text))
        text_parts.extend((slot_text, str(slot_path or "")))
    for texture_input in tuple(getattr(source_submesh, "preview_material_texture_inputs", ()) or ()):
        for attr_name in (
            "slot_kind",
            "parameter_name",
            "semantic_type",
            "semantic_subtype",
            "shader_family",
            "source_texture_path",
            "texture_name",
            "preview_texture_path",
        ):
            text_parts.append(str(getattr(texture_input, attr_name, "") or ""))
        slot_kinds.add(
            _normalize_source_texture_slot_kind(str(getattr(texture_input, "slot_kind", "") or ""))
            or _sanitize_texture_component(str(getattr(texture_input, "slot_kind", "") or ""))
        )
    parameters = _source_material_parameters(source_submesh)
    for parameter in parameters:
        text_parts.extend(
            (
                str(getattr(parameter, "parameter_name", "") or ""),
                str(getattr(parameter, "tag_name", "") or ""),
                str(getattr(parameter, "value", "") or ""),
            )
        )
    compact = _sanitize_texture_component(" ".join(text_parts))
    tokens = {token for token in re.split(r"[^a-z0-9]+", " ".join(text_parts).lower()) if token}
    tags: list[str] = []

    def add(tag: str) -> None:
        normalized = _normalized_source_part_material_role(tag)
        if normalized and normalized not in tags:
            tags.append(normalized)

    if (
        tokens & {"glow", "emissive", "emission", "illum", "light", "lamp", "rune"}
        or "emissive" in slot_kinds
        or any(marker in compact for marker in ("glow", "emissive", "emission", "illumination"))
    ):
        add("glow")
    if tokens & {"cloth", "fabric", "cape", "cloak", "flag", "velvet", "linen", "cotton", "silk", "torncloth"} or any(
        marker in compact for marker in ("cloth", "fabric", "cloak", "cape", "velvet", "linen", "cotton", "silk")
    ):
        add("cloth")
    if tokens & {"wood", "oak", "pine", "bark", "timber", "plank"} or any(
        marker in compact for marker in ("wood", "oak", "pine", "bark", "timber", "plank")
    ):
        add("wood")
    if tokens & {"leather", "hide", "strap", "belt"} or any(marker in compact for marker in ("leather", "hide", "strap", "belt")):
        add("leather")
    if tokens & {"stone", "rock", "granite", "marble", "slate"} or any(
        marker in compact for marker in ("stone", "rock", "granite", "marble", "slate")
    ):
        add("stone")
    if tokens & {"glass", "crystal", "lens", "gem", "jewel"} or any(marker in compact for marker in ("glass", "crystal", "lens", "gem", "jewel")):
        add("glass")
    if (
        tokens & {"metal", "metallic", "metalness", "steel", "iron", "gold", "silver", "bronze", "copper"}
        or any(marker in compact for marker in ("metal", "steel", "iron", "gold", "silver", "bronze", "copper"))
        or slot_kinds & {"metallic", "metalness", "material"}
    ):
        add("metal")
    roughness_factor = _source_material_numeric_parameter(source_submesh, "_roughnessFactor")
    metallic_factor = _source_material_numeric_parameter(source_submesh, "_metallicFactor")
    glossiness_factor = _source_material_numeric_parameter(source_submesh, "_glossinessFactor")
    specular_factor = _source_material_numeric_parameter(source_submesh, "_specularFactor")
    clearcoat_factor = _source_material_numeric_parameter(source_submesh, "_clearcoatFactor")
    if (
        (roughness_factor is not None and roughness_factor <= 0.35)
        or (glossiness_factor is not None and glossiness_factor >= 0.55)
        or (specular_factor is not None and specular_factor >= 0.5)
        or (clearcoat_factor is not None and clearcoat_factor > 0.0)
        or slot_kinds & {"specular", "glossiness", "clearcoat"}
        or any(token in compact for token in ("shiny", "glossy", "polished", "mirror"))
    ):
        add("shiny")
    if metallic_factor is not None and metallic_factor >= 0.45:
        add("metal")
    return tuple(tags)


def _source_material_numeric_parameter(source_submesh: object, parameter_name: str, *alternate_names: str) -> Optional[float]:
    wanted_names = {
        str(name or "").strip().lower()
        for name in (parameter_name, *alternate_names)
        if str(name or "").strip()
    }
    if not wanted_names:
        return None
    for parameter in _source_material_parameters(source_submesh):
        current = str(getattr(parameter, "parameter_name", "") or "").strip().lower()
        if current not in wanted_names:
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            try:
                return max(0.0, min(1.0, float(numeric_value)))
            except (TypeError, ValueError, OverflowError):
                return None
        value_text = str(getattr(parameter, "value", "") or "").strip()
        if not value_text:
            return None
        try:
            return max(0.0, min(1.0, float(value_text)))
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _source_material_color_luminance_parameter(source_submesh: object, *parameter_names: str) -> Optional[float]:
    wanted_names = {
        str(name or "").strip().lower()
        for name in tuple(parameter_names or ())
        if str(name or "").strip()
    }
    if not wanted_names:
        return None
    for parameter in _source_material_parameters(source_submesh):
        current = str(getattr(parameter, "parameter_name", "") or "").strip().lower()
        if current not in wanted_names:
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if len(color) < 3:
            continue
        try:
            r, g, b = (max(0.0, min(1.0, float(component))) for component in color[:3])
        except (TypeError, ValueError, OverflowError):
            continue
        return max(0.0, min(1.0, (0.299 * r) + (0.587 * g) + (0.114 * b)))
    return None


def _source_material_specular_factor(source_submesh: object) -> Optional[float]:
    scalar = _source_material_numeric_parameter(source_submesh, "_specularFactor")
    color = _source_material_color_luminance_parameter(source_submesh, "_specularFactor", "_specularColorFactor")
    if scalar is None:
        return color
    if color is None:
        return scalar
    return max(0.0, min(1.0, scalar * color))


def _source_preview_rgb(source_submesh: object) -> Optional[tuple[float, float, float]]:
    color = tuple(getattr(source_submesh, "preview_color", ()) or ())
    vertex_color = tuple(getattr(source_submesh, "preview_vertex_color_mean", ()) or ())
    if len(color) < 3 and len(vertex_color) < 3:
        return None
    try:
        if len(color) >= 3:
            rgb = tuple(max(0.0, min(1.0, float(component))) for component in color[:3])
        else:
            rgb = (1.0, 1.0, 1.0)
        if len(vertex_color) >= 3:
            vertex_rgb = tuple(max(0.0, min(1.0, float(component))) for component in vertex_color[:3])
            rgb = tuple(max(0.0, min(1.0, rgb[index] * vertex_rgb[index])) for index in range(3))
    except (TypeError, ValueError, OverflowError):
        return None
    if all(abs(component - 1.0) <= 0.003 for component in rgb):
        return None
    return rgb  # type: ignore[return-value]


def _source_preview_alpha(source_submesh: object) -> Optional[float]:
    alpha = getattr(source_submesh, "preview_vertex_alpha_mean", None)
    if alpha is None:
        return None
    try:
        scalar = max(0.0, min(1.0, float(alpha)))
    except (TypeError, ValueError, OverflowError):
        return None
    if abs(scalar - 1.0) <= 0.003:
        return None
    return scalar


def _source_material_parameters(source_submesh: object) -> tuple[object, ...]:
    direct = list(getattr(source_submesh, "preview_material_parameters", ()) or ())
    for texture_input in tuple(getattr(source_submesh, "preview_material_texture_inputs", ()) or ()):
        direct.extend(tuple(getattr(texture_input, "material_parameters", ()) or ()))
    return tuple(direct)


def _source_emissive_rgb(source_submesh: object) -> Optional[tuple[float, float, float]]:
    emissive_rgb: Optional[tuple[float, float, float]] = None
    for parameter in _source_material_parameters(source_submesh):
        parameter_name = str(getattr(parameter, "parameter_name", "") or "").strip().lower()
        if parameter_name == "_emissivecolor":
            color = tuple(getattr(parameter, "color_value", ()) or ())
            if len(color) >= 3:
                try:
                    emissive_rgb = tuple(max(0.0, min(1.0, float(component))) for component in color[:3])  # type: ignore[assignment]
                except (TypeError, ValueError, OverflowError):
                    pass
    if emissive_rgb is None:
        return None
    if all(component <= 0.003 for component in emissive_rgb):
        return None
    return emissive_rgb


def _solid_material_factor_png_path(
    material_name: str,
    slot_kind: str,
    rgb: Sequence[float],
) -> Path:
    components = tuple(max(0, min(255, int(round(float(component) * 255.0)))) for component in tuple(rgb[:3]))
    digest = hashlib.sha1(f"{material_name}|{slot_kind}|{components}".encode("utf-8", errors="ignore")).hexdigest()[:12]
    safe_material = _sanitize_texture_component(material_name) or "material"
    safe_slot = _sanitize_texture_component(slot_kind) or "slot"
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_material}_{safe_slot}_{digest}.png"
    if not path.is_file():
        from PIL import Image

        Image.new("RGBA", (16, 16), (components[0], components[1], components[2], 255)).save(path)
    return path


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
        "metallic": "metallic",
        "metalness": "metalness",
        "specular": "specular",
        "gloss": "glossiness",
        "glossiness": "glossiness",
        "smoothness": "glossiness",
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
        "metalness",
        "roughness",
        "specular",
        "glossiness",
        "ao",
        "emissive",
        "opacity",
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


def _paths_match(left: Path, right: Path) -> bool:
    try:
        return str(left.expanduser().resolve()).lower() == str(right.expanduser().resolve()).lower()
    except Exception:
        return str(left).lower() == str(right).lower()


def _texture_path_already_grouped_for_other_slot(
    grouped: Mapping[str, ReplacementTextureSet],
    path: Path,
    material_name: str,
    slot_kind: str,
) -> bool:
    material_key = str(material_name or "").strip().lower()
    slot_key = str(slot_kind or "").strip().lower()
    for current_material_key, texture_set in grouped.items():
        for current_slot_key, slot in (texture_set.slots or {}).items():
            if not _paths_match(slot.source_path, path):
                continue
            if str(current_material_key or "").strip().lower() == material_key and str(current_slot_key or "").strip().lower() == slot_key:
                continue
            return True
    return False


def _source_authority_priority(authority: str) -> int:
    normalized = str(authority or "").strip().lower()
    return {
        "gltf": 90,
        "metadata": 80,
        "manual": 75,
        "synthetic": 70,
        "filename": 30,
    }.get(normalized, 0)


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
        ".webp": 20,
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
        if any(marker in normalized for marker in ("normalgreenup", "normaldirectx", "normaldx")):
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


def _normalized_source_part_material_role(raw_role: object) -> str:
    value = str(raw_role or "").strip().lower().replace("_", " ").replace("-", " ")
    if not value:
        return ""
    tokens = {token for token in re.split(r"[^a-z0-9]+", value) if token}
    if tokens & {"glow", "emissive", "emission", "accent"}:
        return "glow"
    if tokens & {"blade"}:
        return "blade"
    if tokens & {"handle", "grip"}:
        return "handle"
    if tokens & {"guard", "crossguard"}:
        return "guard"
    if tokens & {"cloth", "fabric"}:
        return "cloth"
    if tokens & {"wood", "oak", "pine", "bark", "timber", "plank"}:
        return "wood"
    if tokens & {"leather", "hide"}:
        return "leather"
    if tokens & {"stone", "rock", "granite", "marble", "slate"}:
        return "stone"
    if tokens & {"metal", "metallic", "metalness", "steel", "iron", "gold", "silver", "bronze", "copper"}:
        return "metal"
    if tokens & {"shiny", "glossy", "polished", "mirror", "clearcoat"}:
        return "shiny"
    if tokens & {"glass", "crystal", "lens", "gem", "jewel"}:
        return "glass"
    return value.replace(" ", "/")


def _source_part_has_texture_adjustment(adjustment: object) -> bool:
    values = evaluate_material_parameters(part_adjustment=adjustment)
    return (
        abs(values.brightness_percent) > 0.0001
        or abs(values.contrast_percent) > 0.0001
        or abs(values.saturation_percent) > 0.0001
        or abs(values.gamma_multiplier - 1.0) > 0.0001
        or any(abs(component - 1.0) > 0.0001 for component in values.tint_adjustment)
    )


def _source_part_adjusted_slot(source_slot: ReplacementTextureSlot, adjustment: object) -> ReplacementTextureSlot:
    slot_kind = str(getattr(source_slot, "slot_kind", "") or "").strip().lower()
    if slot_kind not in {"base", "emissive"}:
        return source_slot
    values = evaluate_material_parameters(source_slot=source_slot, part_adjustment=adjustment)
    return replace(
        source_slot,
        base_color_factor=values.tint_color,
        base_color_scale=values.base_color_scale,
        base_color_gamma=values.gamma,
        base_color_saturation=values.saturation,
        base_color_tone_contrast=values.tone_contrast,
    )


def _apply_source_part_texture_adjustment(texture_set: ReplacementTextureSet, adjustment: object) -> None:
    if not _source_part_has_texture_adjustment(adjustment):
        return
    texture_set.slots = {
        slot_kind: _source_part_adjusted_slot(slot, adjustment)
        for slot_kind, slot in tuple((texture_set.slots or {}).items())
    }


def _apply_source_part_role_overrides(
    texture_sets: Mapping[str, ReplacementTextureSet],
    obj_mesh: ParsedMesh,
    source_part_adjustments: Sequence[object],
) -> None:
    if not texture_sets or not source_part_adjustments:
        return
    submeshes = tuple(getattr(obj_mesh, "submeshes", ()) or ())
    material_key_counts: dict[str, int] = {}
    for source_submesh in submeshes:
        key = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip().lower()
        if key:
            material_key_counts[key] = int(material_key_counts.get(key, 0) or 0) + 1
    for adjustment in tuple(source_part_adjustments or ()):
        role = _normalized_source_part_material_role(getattr(adjustment, "material_role", ""))
        has_texture_adjustment = _source_part_has_texture_adjustment(adjustment)
        if not role and not has_texture_adjustment:
            continue
        try:
            source_index = int(getattr(adjustment, "source_submesh_index"))
        except (TypeError, ValueError):
            continue
        if source_index < 0 or source_index >= len(submeshes):
            continue
        submesh = submeshes[source_index]
        material_key = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip().lower()
        texture_set = texture_sets.get(material_key)
        if texture_set is None:
            texture_set = _texture_set_for_source_texture_reference(submesh, texture_sets)
        if texture_set is None:
            continue
        if isinstance(texture_sets, dict) and (has_texture_adjustment or int(material_key_counts.get(material_key, 0) or 0) > 1):
            alias_key = f"__source_part_{source_index}_{str(texture_set.material_name or material_key or 'material').strip().lower()}"
            cloned_slots = {
                slot_kind: replace(slot, material_name=alias_key)
                for slot_kind, slot in tuple((texture_set.slots or {}).items())
            }
            texture_set = ReplacementTextureSet(
                material_name=alias_key,
                slots=cloned_slots,
                source_face_count=len(tuple(getattr(submesh, "faces", ()) or ())) or int(getattr(texture_set, "source_face_count", 0) or 0),
                roughness_factor=texture_set.roughness_factor,
                metallic_factor=texture_set.metallic_factor,
                specular_factor=texture_set.specular_factor,
                glossiness_factor=texture_set.glossiness_factor,
                occlusion_strength=texture_set.occlusion_strength,
                base_color_factor=texture_set.base_color_factor,
                source_role_tags=texture_set.source_role_tags,
                accent_glow_color_rgb=texture_set.accent_glow_color_rgb,
                emissive_strength=texture_set.emissive_strength,
            )
            texture_sets[alias_key] = texture_set
            try:
                setattr(submesh, "cdmw_source_texture_set_key", alias_key)
            except Exception:
                pass
        _apply_source_part_texture_adjustment(texture_set, adjustment)
        if role:
            existing = tuple(str(tag or "").strip().lower() for tag in (texture_set.source_role_tags or ()) if str(tag or "").strip())
            if role not in existing:
                texture_set.source_role_tags = (*existing, role)
            if role == "glow":
                part_strength = source_emissive_strength(adjustment)
                if part_strength is not None:
                    texture_set.emissive_strength = part_strength
                glow_rgb = _normalized_accent_glow_rgb(getattr(adjustment, "emissive_color_rgb", ()))
                if glow_rgb:
                    texture_set.accent_glow_color_rgb = glow_rgb


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


def _choose_source_materials_for_output_draw_sections(
    obj_mesh: ParsedMesh,
    texture_sets: Mapping[str, ReplacementTextureSet],
    output_draw_sections: Sequence[StaticOutputDrawSection],
    report: TextureReplacementReport,
) -> dict[str, str]:
    """Route complete source-owned PAC sections by their emitted material names."""
    result: dict[str, str] = {}
    routes: list[SourceMaterialRoutingResult] = []
    for section in tuple(output_draw_sections or ()):
        source_indices = tuple(int(index) for index in tuple(getattr(section, "source_submesh_indices", ()) or ()))
        if not source_indices:
            continue
        target_name = _source_owned_material_name_for_output_section(section)
        if not target_name:
            continue
        atlas_material_names = tuple(
            str(name or "").strip()
            for name in tuple(getattr(section, "atlas_source_material_names", ()) or ())
            if str(name or "").strip()
        )
        if atlas_material_names:
            roles = tuple(
                sorted(
                    {
                        role
                        for material_name in atlas_material_names
                        for role in _texture_set_detected_roles(
                            texture_sets.get(material_name.lower(), ReplacementTextureSet(material_name))
                        )
                    }
                    | {"base", "normal", "height", "material_mask", "detail_mask"}
                )
            )
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_material_name=" + ".join(atlas_material_names),
                    source_part_names=atlas_material_names,
                    detected_roles=roles,
                    status="Ready",
                    reason="Source-owned PAC draw section will bake multiple replacement material sets into one runtime atlas.",
                )
            )
            continue
        source_part_names: list[str] = []
        candidates_by_key: dict[str, ReplacementTextureSet] = {}
        for source_index in source_indices:
            if source_index < 0 or source_index >= len(obj_mesh.submeshes):
                continue
            source_submesh = obj_mesh.submeshes[source_index]
            source_part_names.append(_source_submesh_display_name(source_submesh, source_index))
            texture_set = _texture_set_for_source_submesh(source_submesh, target_name, texture_sets)
            if texture_set is not None:
                candidates_by_key.setdefault(str(texture_set.material_name or "").strip().lower(), texture_set)
        candidates = list(candidates_by_key.values())
        if len(candidates) > 1:
            candidate_names = [str(candidate.material_name or "").strip() for candidate in candidates if str(candidate.material_name or "").strip()]
            reason = (
                f"Texture routing blocker: source-owned draw section {target_name} still contains multiple replacement "
                f"material sets ({', '.join(candidate_names)}). Draw-section cloning must split these before export."
            )
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_material_name=", ".join(candidate_names),
                    source_part_names=tuple(source_part_names),
                    detected_roles=tuple(sorted({role for candidate in candidates for role in _texture_set_detected_roles(candidate)})),
                    status="Blocked",
                    reason=reason,
                    blocker=True,
                )
            )
            _warn_once(report, reason)
            continue
        if not candidates:
            routes.append(
                SourceMaterialRoutingResult(
                    target_material_name=target_name,
                    source_part_names=tuple(source_part_names),
                    status="Ignored",
                    reason=f"Texture routing ignored source-owned draw section {target_name}: no source material texture/factor set was detected.",
                )
            )
            continue
        chosen = candidates[0]
        roles = _texture_set_detected_roles(chosen)
        source_name = str(chosen.material_name or "").strip()
        for key in {target_name.lower(), _normalize_sidecar_material_name(target_name)}:
            if key:
                result[key] = source_name
        routes.append(
            SourceMaterialRoutingResult(
                target_material_name=target_name,
                source_material_name=source_name,
                source_part_names=tuple(source_part_names),
                detected_roles=roles,
                status="Ready" if "base" in roles else "Review",
                reason="Source-owned PAC draw section will bind this replacement material set exactly.",
            )
        )
    report.material_routes = routes
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
    source_alias_key = str(getattr(source_submesh, "cdmw_source_texture_set_key", "") or "").strip().lower()
    if source_alias_key:
        texture_set = texture_sets.get(source_alias_key)
        if texture_set is not None:
            return texture_set
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
    order = (
        "base",
        "normal",
        "height",
        "material_mask",
        "detail_mask",
        "emissive",
        "material",
        "metallic",
        "metalness",
        "roughness",
        "glossiness",
        "specular",
        "ao",
        "opacity",
    )
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


from . import material_replacer as _material_replacer_facade

_material_replacer_facade._bind_lazy_material_exports(__name__, globals())
del _material_replacer_facade
