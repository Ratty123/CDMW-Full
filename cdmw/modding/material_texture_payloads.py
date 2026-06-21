"""Texture payload, manual override, and material preview texture helpers."""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Optional, Sequence

from .asset_replacement import classify_texture_binding, infer_cd_texture_role_from_path
from .material_profiles import (
    CDMaterialRuntimeProfile,
    get_complete_swap_material_profile,
    normalize_tone_contrast,
    _profile_mask_binding_mode,
)
from .material_sidecar_patching import (
    _SOURCE_MATERIAL_OVERRIDE_SLOT_ALIASES,
    _normalize_sidecar_material_name,
    _normalize_texture_path,
    _sidecar_material_names_match,
    _sidecar_parameter_name,
)

_SOURCE_TEXTURE_IMAGE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}


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
    from .material_replacer import ReplacementTextureSet, ReplacementTextureSlot

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
        if source_path.suffix.lower() not in _SOURCE_TEXTURE_IMAGE_EXTENSIONS:
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
    from .material_texture_routing import _parse_replacement_texture_filename

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
    if "green_up" in stem:
        return "green_up"
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
    from .material_replacer import TextureReplacementPayload, TextureSlotMapping
    from .material_texture_routing import _is_shared_material_layer_texture, _replacement_output_texture_path

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
    from .material_replacer import ReplacementTextureSlot

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
    normal_space = "green_up" if "green_up" in resolved_source.stem.lower() else ("directx" if "directx" in resolved_source.stem.lower() or "_dx" in resolved_source.stem.lower() else "")
    return ReplacementTextureSlot(
        material_name=material_name,
        slot_kind=slot_kind or "material",
        source_path=resolved_source,
        normal_space=normal_space,
    )


def _manual_source_material_name(source_path: Path) -> str:
    from .material_texture_routing import _parse_replacement_texture_filename

    parsed = _parse_replacement_texture_filename(source_path, set())
    if parsed is not None:
        return parsed[0]
    stem = source_path.stem
    return re.sub(
        r"_(base|base_color|basecolor|bc|bcol|diffuse|dif|di|albedo|alb|color|colour|col|c|o|emissive|emission|emi|em|glow|illum|illumination|detaildiffuse|detailcolor|decalbasecolor|waterfoam|normal|normalmap|normal_green_up|normal_directx|normal_dx|norm|nrm|nm|wn|n|detailnormal|wrinklenormal|damagenormal|height|hgt|hei|he|h|d|dmap|depth|disp|displacement|bump|pom|ssdm|wrinkledisplacement|metallicroughness|metallic_roughness|metalrough|metallicrough|roughnessmetallic|roughmetal|metallic|metalness|roughness|rough|rgh|gloss|gls|smooth|smoothness|mixed_ao|ambientocclusion|occlusion|ao|reflection|reflect|ref|material|mat|m|ma|mg|sp|spec|specular|specularglossiness|specular_glossiness|specgloss|clearcoat|clear_coat|orm|rma|mra|arm|opacity|alpha|op|subsurface|flow|vector|dr|rgb|mask|masks|mask_1bit|mask_amg|layermask|detailmask|detailmaterial|colorblendingmask|skindetailmask|grimediffuse|grimenormal|grimematerial|damagediffuse|damagematerial)$",
        "",
        stem,
        flags=re.IGNORECASE,
    ) or stem




def _should_replace_original_texture_reference(reference: object, target_path: str) -> bool:
    if str(getattr(reference, "reference_kind", "texture") or "texture").strip().lower() != "texture":
        return False
    if not str(target_path or "").lower().endswith(".dds"):
        return False
    parameter = str(getattr(reference, "sidecar_parameter_name", "") or "").strip().lower()
    basename = PurePosixPath(str(target_path or "").replace("\\", "/")).name.lower()

    from .material_texture_routing import _is_shared_material_layer_texture

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
    from .material_texture_routing import _semantic_tokens

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
    from .material_texture_routing import _semantic_tokens

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
    from .material_texture_routing import _semantic_tokens

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
    from .material_texture_routing import _is_shared_material_layer_texture, _reference_target_path

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
    from .material_texture_routing import _is_shared_material_layer_texture, _reference_target_path

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
    materials_with_generated_runtime_mask = {
        str(mapping.source_material_name or "").strip().lower()
        for mapping in report.slot_mappings
        if str(mapping.slot_kind or "").strip().lower() == "material_mask"
        and "_material_mask_" in str(mapping.source_path.name or "").strip().lower()
        and "cdmw_synthetic_materials" in str(mapping.source_path.parent).lower()
    }
    for texture_set in texture_sets.values():
        material_key = str(texture_set.material_name or "").strip().lower()
        unused_slots = [
            slot
            for slot in texture_set.slots.values()
            if (
                str(slot.material_name or "").strip().lower(),
                str(slot.source_path.name or "").strip().lower(),
            )
            not in used
            and not (
                material_key in materials_with_generated_runtime_mask
                and str(slot.slot_kind or "").strip().lower() in {"material", "metallic", "metalness", "roughness", "glossiness", "specular", "ao", "occlusion"}
            )
        ]
        if unused_slots:
            pbr_slots = [
                slot
                for slot in unused_slots
                if str(slot.slot_kind or "").strip().lower() in {"metallic", "metalness", "roughness", "glossiness", "specular", "ao", "occlusion"}
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
    from .material_source_driven import _texture_role_for_parameter_and_path
    from .material_texture_routing import _is_shared_material_layer_texture

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
    from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds

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
    from cdmw.core.texture_native import encode_dds_with_directxtex
    from cdmw.core.texture_pipeline.inspection import parse_dds, read_png_dimensions
    from cdmw.core.texture_pipeline.texconv import build_texconv_command
    from cdmw.domain.textures.output import max_mips_for_size
    from cdmw.core.common import run_process_with_cancellation

    def _source_image_dimensions(path: Path) -> tuple[int, int]:
        if path.suffix.lower() == ".png":
            return read_png_dimensions(path)
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)

    source_is_dds = source_slot.source_path.suffix.lower() == ".dds"
    needs_source_color_bake = (
        _source_slot_needs_base_color_factor(source_slot)
        or _source_slot_needs_base_alpha_factor(source_slot)
        or _source_slot_needs_base_color_adjustment(source_slot)
    )
    if source_is_dds and not needs_source_color_bake:
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
    if source_is_dds:
        _warn_once(
            report,
            f"{source_slot.source_path.name}: baking source color adjustment by re-encoding DDS source.",
        )
    original_source = original_texture_source_path(target_entry)
    original_info = parse_dds(original_source)
    resolved_texconv = texconv_path.expanduser().resolve() if texconv_path is not None and texconv_path.expanduser().is_file() else None
    with tempfile.TemporaryDirectory(prefix="cdmw_static_texture_") as temp_text:
        temp_dir = Path(temp_text)
        source_png = _source_slot_png_with_base_color_factor_path(source_slot)
        prepared_png = temp_dir / source_png.name
        if source_slot.slot_kind == "normal" and source_slot.normal_space == "green_up":
            _copy_png_with_inverted_green(source_png, prepared_png)
            report.warnings.append(f"Inverted green channel for green-up normal map: {source_png.name}")
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
        if str(source_slot.slot_kind or "").strip().lower() == "material_mask" and _dds_format_is_bc1(output_format):
            _force_png_alpha_opaque(prepared_png)
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
        native_encode_ok = False
        native_encode_error = ""
        if native_report and produced.is_file() and produced.stat().st_size > 0:
            try:
                parse_dds(produced)
                native_encode_ok = True
            except Exception as exc:
                native_encode_error = str(exc) or exc.__class__.__name__
                _warn_once(
                    report,
                    f"{source_png.name}: DirectXTex native DDS encode produced an invalid DDS "
                    f"({native_encode_error}); falling back to texconv.",
                )
                try:
                    produced.unlink()
                except OSError:
                    pass
        if native_encode_ok:
            if on_log:
                on_log(f"Encoded {source_png.name} with DirectXTex native DDS encode.")
        else:
            if resolved_texconv is None:
                detail = f": {native_encode_error}" if native_encode_error else ""
                raise FileNotFoundError(
                    "DirectXTex native DDS encode failed or produced an invalid DDS"
                    f"{detail}; no optional legacy texconv fallback is configured."
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


def _source_slot_needs_base_color_factor(source_slot: ReplacementTextureSlot) -> bool:
    if str(source_slot.slot_kind or "").strip().lower() not in {"base", "emissive"}:
        return False
    factor = tuple(getattr(source_slot, "base_color_factor", ()) or ())
    if len(factor) < 3:
        return False
    try:
        rgb = tuple(max(0.0, min(1.0, float(component))) for component in factor[:3])
    except (TypeError, ValueError, OverflowError):
        return False
    return any(abs(component - 1.0) > 0.003 for component in rgb)


def _source_slot_needs_base_alpha_factor(source_slot: ReplacementTextureSlot) -> bool:
    if str(source_slot.slot_kind or "").strip().lower() != "base":
        return False
    alpha = getattr(source_slot, "base_alpha_factor", None)
    if alpha is None:
        return False
    try:
        scalar = max(0.0, min(1.0, float(alpha)))
    except (TypeError, ValueError, OverflowError):
        return False
    return abs(scalar - 1.0) > 0.003


def _source_slot_needs_base_color_adjustment(source_slot: ReplacementTextureSlot) -> bool:
    from .material_source_driven import _source_slot_is_real_texture, _source_slot_is_synthetic_factor_authority

    if str(source_slot.slot_kind or "").strip().lower() not in {"base", "emissive"}:
        return False
    if not (_source_slot_is_real_texture(source_slot) or _source_slot_is_synthetic_factor_authority(source_slot)):
        return False
    try:
        scale = max(0.0, min(4.0, float(getattr(source_slot, "base_color_scale", 1.0) or 1.0)))
        lift = max(0, min(254, int(getattr(source_slot, "base_color_lift", 0) or 0)))
        gamma = max(0.1, min(4.0, float(getattr(source_slot, "base_color_gamma", 1.0) or 1.0)))
        saturation = max(0.0, min(4.0, float(getattr(source_slot, "base_color_saturation", 1.0) or 1.0)))
        value_max = max(0, min(255, int(getattr(source_slot, "base_color_value_max", 255) or 255)))
        auto_balance = max(0, min(100, int(getattr(source_slot, "base_color_auto_balance", 0) or 0)))
        shadow_lift = max(0, min(100, int(getattr(source_slot, "base_color_shadow_lift", 0) or 0)))
        tone_contrast = normalize_tone_contrast(getattr(source_slot, "base_color_tone_contrast", 0.0))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        abs(scale - 1.0) > 0.0001
        or lift > 0
        or abs(gamma - 1.0) > 0.0001
        or abs(saturation - 1.0) > 0.0001
        or value_max < 255
        or auto_balance > 0
        or shadow_lift > 0
        or abs(tone_contrast) > 0.0001
    )


def _auto_balance_source_base_rgb(rgb: object, alpha: object, strength_percent: int) -> object:
    strength = max(0.0, min(1.0, float(strength_percent or 0) / 100.0))
    if strength <= 0.0:
        return rgb
    from PIL import ImageEnhance, ImageStat

    sample_rgb = rgb
    sample_alpha = alpha
    width, height = getattr(sample_rgb, "size", (0, 0))
    max_dimension = max(int(width or 0), int(height or 0))
    if max_dimension > 96:
        scale = 96.0 / float(max_dimension)
        sample_size = (max(1, int(round(float(width) * scale))), max(1, int(round(float(height) * scale))))
        sample_rgb = sample_rgb.resize(sample_size)
        sample_alpha = sample_alpha.resize(sample_size)
    luma = sample_rgb.convert("L")
    alpha_mask = sample_alpha.point(lambda value: 255 if int(value) >= 24 else 0)
    visible = ImageStat.Stat(luma, mask=alpha_mask).mean
    if not visible:
        return rgb
    mean_luma = float(visible[0])
    if 96.0 <= mean_luma <= 158.0:
        return rgb
    target_luma = 116.0 if mean_luma < 96.0 else 138.0
    correction = (target_luma / max(1.0, mean_luma)) ** strength
    correction = max(0.68, min(1.42, correction))
    if abs(correction - 1.0) <= 0.015:
        return rgb
    return ImageEnhance.Brightness(rgb).enhance(correction)


def _source_slot_png_with_base_color_factor_path(source_slot: ReplacementTextureSlot) -> Path:
    from .material_source_driven import _sanitize_texture_component

    if (
        not _source_slot_needs_base_color_factor(source_slot)
        and not _source_slot_needs_base_alpha_factor(source_slot)
        and not _source_slot_needs_base_color_adjustment(source_slot)
    ):
        return source_slot.source_path
    factor = tuple(max(0.0, min(1.0, float(component))) for component in tuple(source_slot.base_color_factor[:3]))
    if len(factor) < 3:
        factor = (1.0, 1.0, 1.0)
    alpha_factor = 1.0
    if _source_slot_needs_base_alpha_factor(source_slot):
        alpha_factor = max(0.0, min(1.0, float(getattr(source_slot, "base_alpha_factor", 1.0) or 1.0)))
    scale_rgb = max(0.0, min(4.0, float(getattr(source_slot, "base_color_scale", 1.0) or 1.0)))
    lift = max(0, min(254, int(getattr(source_slot, "base_color_lift", 0) or 0)))
    gamma = max(0.1, min(4.0, float(getattr(source_slot, "base_color_gamma", 1.0) or 1.0)))
    saturation = max(0.0, min(4.0, float(getattr(source_slot, "base_color_saturation", 1.0) or 1.0)))
    value_max = max(0, min(255, int(getattr(source_slot, "base_color_value_max", 255) or 255)))
    auto_balance = max(0, min(100, int(getattr(source_slot, "base_color_auto_balance", 0) or 0)))
    shadow_lift = max(0, min(100, int(getattr(source_slot, "base_color_shadow_lift", 0) or 0)))
    tone_contrast = normalize_tone_contrast(getattr(source_slot, "base_color_tone_contrast", 0.0))
    source_path = source_slot.source_path
    try:
        stat = source_path.stat()
        fingerprint = (
            f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}|{factor}|{alpha_factor:.6f}|"
            f"{scale_rgb:.6f}|{lift}|{gamma:.6f}|{saturation:.6f}|{value_max}|"
            f"{auto_balance}|{shadow_lift}|{tone_contrast:.6f}"
        )
    except OSError:
        fingerprint = (
            f"{source_path}|{factor}|{alpha_factor:.6f}|{scale_rgb:.6f}|{lift}|{gamma:.6f}|{saturation:.6f}|{value_max}|"
            f"{auto_balance}|{shadow_lift}|{tone_contrast:.6f}"
        )
    digest = hashlib.sha1(fingerprint.encode("utf-8", errors="ignore")).hexdigest()[:12]
    root = Path(tempfile.gettempdir()) / "cdmw_synthetic_materials"
    root.mkdir(parents=True, exist_ok=True)
    suffix = (
        "basecolorfactor"
        if _source_slot_needs_base_color_factor(source_slot) or _source_slot_needs_base_alpha_factor(source_slot)
        else "basecolorprofile"
    )
    path = root / f"{_sanitize_texture_component(source_path.stem) or 'base'}_{suffix}_{digest}.png"
    if path.is_file():
        return path
    from PIL import Image, ImageChops, ImageEnhance

    with Image.open(source_path) as image:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        r = r.point(lambda value: max(0, min(255, int(round(int(value) * factor[0] * scale_rgb)))))
        g = g.point(lambda value: max(0, min(255, int(round(int(value) * factor[1] * scale_rgb)))))
        b = b.point(lambda value: max(0, min(255, int(round(int(value) * factor[2] * scale_rgb)))))
        if _source_slot_needs_base_alpha_factor(source_slot):
            a = a.point(lambda value: max(0, min(255, int(round(int(value) * alpha_factor)))))
        if abs(gamma - 1.0) > 0.0001:
            r = r.point(lambda value: max(0, min(255, int(round(((int(value) / 255.0) ** gamma) * 255.0)))))
            g = g.point(lambda value: max(0, min(255, int(round(((int(value) / 255.0) ** gamma) * 255.0)))))
            b = b.point(lambda value: max(0, min(255, int(round(((int(value) / 255.0) ** gamma) * 255.0)))))
        if lift > 0:
            scale = (255.0 - float(lift)) / 255.0
            r = r.point(lambda value: max(0, min(255, int(round(float(lift) + int(value) * scale)))))
            g = g.point(lambda value: max(0, min(255, int(round(float(lift) + int(value) * scale)))))
            b = b.point(lambda value: max(0, min(255, int(round(float(lift) + int(value) * scale)))))
        if abs(saturation - 1.0) > 0.0001:
            rgb = Image.merge("RGB", (r, g, b))
            rgb = ImageEnhance.Color(rgb).enhance(saturation)
            r, g, b = rgb.split()
        if auto_balance > 0:
            rgb = _auto_balance_source_base_rgb(Image.merge("RGB", (r, g, b)), a, auto_balance)
            r, g, b = rgb.split()
        if shadow_lift > 0:
            rgb = Image.merge("RGB", (r, g, b))
            luma = rgb.convert("L")
            shadow_mask = luma.point(
                lambda value: (
                    max(
                        0,
                        min(
                            255,
                            int(round((((96.0 - float(value)) / 96.0) ** 1.5) * 255.0)),
                        ),
                    )
                    if int(value) < 96
                    else 0
                )
            )
            boost = int(round(72.0 * (float(shadow_lift) / 100.0)))
            if boost > 0:
                r = Image.composite(ImageChops.add(r, Image.new("L", r.size, boost)), r, shadow_mask)
                g = Image.composite(ImageChops.add(g, Image.new("L", g.size, boost)), g, shadow_mask)
                b = Image.composite(ImageChops.add(b, Image.new("L", b.size, boost)), b, shadow_mask)
        if abs(tone_contrast) > 0.0001:
            rgb = Image.merge("RGB", (r, g, b))
            if tone_contrast < 0.0:
                factor_contrast = max(0.35, 1.0 + 0.55 * (tone_contrast / 100.0))
                rgb = ImageEnhance.Contrast(rgb).enhance(factor_contrast)
                rgb = ImageEnhance.Brightness(rgb).enhance(1.0 + 0.10 * (-tone_contrast / 100.0))
            else:
                rgb = ImageEnhance.Contrast(rgb).enhance(1.0 + 0.75 * (tone_contrast / 100.0))
            r, g, b = rgb.split()
        if value_max < 255:
            r = r.point(lambda value: min(value_max, int(value)))
            g = g.point(lambda value: min(value_max, int(value)))
            b = b.point(lambda value: min(value_max, int(value)))
        Image.merge("RGBA", (r, g, b, a)).save(path)
    return path


def material_authority_preview_texture_slots(
    texture_set: ReplacementTextureSet,
    material_profile: Optional[CDMaterialRuntimeProfile] = None,
    *,
    enabled: bool = True,
) -> dict[str, ReplacementTextureSlot]:
    from .material_replacer import ReplacementTextureSlot
    from .material_source_driven import (
        _complete_swap_accent_emissive_slot,
        _complete_swap_runtime_material_mask_png_path,
        _source_driven_slots,
    )

    preview_slots: dict[str, ReplacementTextureSlot] = {
        str(slot_name or "").strip().lower(): slot
        for slot_name, slot in (getattr(texture_set, "slots", {}) or {}).items()
        if str(slot_name or "").strip()
    }
    if not enabled:
        return preview_slots

    profile = material_profile or get_complete_swap_material_profile()

    def adjusted_slot(source_slot: ReplacementTextureSlot) -> ReplacementTextureSlot:
        slot_kind = str(getattr(source_slot, "slot_kind", "") or "").strip().lower()
        if slot_kind not in {"base", "emissive"}:
            return source_slot
        try:
            preview_path = _source_slot_png_with_base_color_factor_path(source_slot)
        except Exception:
            return source_slot
        if preview_path == source_slot.source_path:
            return source_slot
        return replace(source_slot, source_path=preview_path)

    for source_slot in _source_driven_slots(
        texture_set,
        include_pbr_material_fallback=True,
        include_complete_support_fallbacks=True,
        material_profile=profile,
    ):
        slot_kind = str(getattr(source_slot, "slot_kind", "") or "").strip().lower()
        if slot_kind:
            preview_slots[slot_kind] = adjusted_slot(source_slot)

    if "emissive" not in preview_slots:
        accent_slot = _complete_swap_accent_emissive_slot(
            texture_set,
            str(getattr(texture_set, "material_name", "") or ""),
            profile,
        )
        if accent_slot is not None:
            preview_slots["emissive"] = adjusted_slot(accent_slot)

    if "material_mask" not in preview_slots or _profile_mask_binding_mode(profile) != "detail_mask_material":
        preview_slots["material_mask"] = ReplacementTextureSlot(
            str(getattr(texture_set, "material_name", "") or "material"),
            "material_mask",
            _complete_swap_runtime_material_mask_png_path(texture_set, profile),
            source_authority="synthetic",
        )
    return preview_slots


def _dds_format_is_bc1(dds_format: str) -> bool:
    normalized = str(dds_format or "").strip().upper()
    return normalized == "DXT1" or normalized.startswith("BC1_")


def _force_png_alpha_opaque(path: Path) -> None:
    from PIL import Image

    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
    except Exception:
        return
    alpha = rgba.getchannel("A")
    extrema = alpha.getextrema()
    if extrema == (255, 255):
        return
    r, g, b, _a = rgba.split()
    Image.merge("RGBA", (r, g, b, Image.new("L", rgba.size, 255))).save(path)


def _copy_png_with_inverted_green(source_path: Path, target_path: Path) -> None:
    from PIL import Image

    with Image.open(source_path) as image:
        rgba = image.convert("RGBA")
        r, g, b, a = rgba.split()
        g = g.point(lambda value: 255 - int(value))
        Image.merge("RGBA", (r, g, b, a)).save(target_path)
