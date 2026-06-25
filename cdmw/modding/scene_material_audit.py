from __future__ import annotations

import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput

from .mesh_parser import ParsedMesh, SubMesh
from .scene_geometry_utils import _bbox, _dedupe_text, _safe_int

SCENE_TEXTURE_SOURCE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}

_MATERIAL_CLASS_TEXTURE_ROLE_TOKENS = (
    "metallicroughness",
    "metallic_roughness",
    "roughnessmetallic",
    "roughness_metallic",
    "metalnessroughness",
    "metalness_roughness",
    "roughnessmetalness",
    "roughness_metalness",
    "occlusionroughnessmetallic",
    "occlusion_roughness_metallic",
    "orm",
    "mro",
    "rma",
    "arm",
    "basecolor",
    "base_color",
    "diffuse",
    "albedo",
    "normal",
    "roughness",
    "metallic",
    "metalness",
    "specular",
    "glossiness",
    "emissive",
    "emission",
    "opacity",
    "alpha",
    "transmission",
    "occlusion",
    "ao",
    "height",
)


_SCENE_TEXTURE_FACT_CHANNEL_STATS_MAX_PIXELS = 64 * 1024 * 1024


@dataclass(slots=True)
class ImportedMaterialBinding:
    material_index: int = -1
    material_name: str = ""
    submesh_index: int = -1
    submesh_name: str = ""
    texture_slots: tuple[tuple[str, Path], ...] = ()
    pbr_workflow: str = ""
    alpha_mode: str = ""
    double_sided: bool = False


@dataclass(slots=True, frozen=True)
class SceneMaterialTextureSlot:
    slot_kind: str
    path: str = ""
    parameter_name: str = ""
    semantic_type: str = ""
    semantic_subtype: str = ""
    packed_channels: tuple[str, ...] = ()
    shader_family: str = ""
    srgb_mode: str = ""
    texcoord: int = 0
    transform: tuple[float, ...] = ()
    source: str = ""
    parameters: tuple[PreviewMaterialParameterInput, ...] = ()
    reference_path: str = ""


@dataclass(slots=True, frozen=True)
class ExternalMaterialTextureInventory:
    slot_kind: str = ""
    parameter_name: str = ""
    texture_path: str = ""
    texture_name: str = ""
    image_format: str = ""
    resolution: tuple[int, int] = ()
    channel_stats: tuple[tuple[str, float], ...] = ()
    semantic_type: str = ""
    semantic_subtype: str = ""
    packed_channels: tuple[str, ...] = ()
    color_space: str = ""
    texcoord: int = 0
    uv_transform: tuple[float, ...] = ()
    source: str = ""
    confidence: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialClassEvidence:
    material_class: str = "unknown"
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialSectionInventory:
    section_index: int = -1
    section_name: str = ""
    material_name: str = ""
    vertex_count: int = 0
    face_count: int = 0
    has_uvs: bool = False
    has_normals: bool = False
    has_tangents: bool = False
    has_skinning: bool = False
    texture_texcoord_sets: tuple[int, ...] = ()
    bounds_min: tuple[float, ...] = ()
    bounds_max: tuple[float, ...] = ()


@dataclass(slots=True, frozen=True)
class ExternalMaterialInventory:
    material_index: int = -1
    material_name: str = ""
    submesh_indices: tuple[int, ...] = ()
    submesh_names: tuple[str, ...] = ()
    sections: tuple[ExternalMaterialSectionInventory, ...] = ()
    texture_slots: tuple[ExternalMaterialTextureInventory, ...] = ()
    pbr_workflow: str = ""
    alpha_mode: str = ""
    double_sided: bool = False
    scalar_hints: tuple[tuple[str, float], ...] = ()
    color_factor: tuple[float, float, float] = ()
    vertex_color_factor: tuple[float, float, float] = ()
    vertex_alpha: tuple[float, float] = ()
    emissive_color: tuple[float, float, float] = ()
    material_classes: tuple[ExternalMaterialClassEvidence, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(slots=True)
class ExternalModelAudit:
    source_path: str = ""
    verified_category: str = "unknown"
    confidence: float = 0.0
    mesh_count: int = 0
    material_count: int = 0
    texture_slots: tuple[str, ...] = ()
    pbr_workflows: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    false_positive: bool = False
    mixed_model: bool = False
    evidence: tuple[str, ...] = ()
    material_inventory: tuple[ExternalMaterialInventory, ...] = ()
    material_classes: tuple[ExternalMaterialClassEvidence, ...] = ()


_SCENE_SLOT_PARAMETER_NAMES = {
    "base": "_baseColorTexture",
    "normal": "_normalTexture",
    "occlusion": "_occlusionTexture",
    "ao": "_occlusionTexture",
    "material": "_metallicRoughnessTexture",
    "roughness": "_roughnessTexture",
    "metalness": "_metallicTexture",
    "metallic": "_metallicTexture",
    "specular": "_specularTexture",
    "glossiness": "_glossinessTexture",
    "specular_glossiness": "_specularGlossinessTexture",
    "emissive": "_emissiveTexture",
    "opacity": "_opacityTexture",
    "height": "_heightTexture",
    "clearcoat": "_clearcoatTexture",
    "clearcoat_roughness": "_clearcoatRoughnessTexture",
    "clearcoat_normal": "_clearcoatNormalTexture",
    "sheen": "_sheenColorTexture",
    "sheen_roughness": "_sheenRoughnessTexture",
    "transmission": "_transmissionTexture",
    "volume": "_thicknessTexture",
    "anisotropy": "_anisotropyTexture",
    "iridescence": "_iridescenceTexture",
}


def _scene_slot_semantics(slot_kind: str) -> tuple[str, str, str, tuple[str, ...]]:
    slot = str(slot_kind or "").strip().lower()
    if slot == "base":
        return "base", "color", "albedo", ()
    if slot == "normal":
        return "normal", "normal", "normal", ()
    if slot in {"occlusion", "ao"}:
        return "occlusion", "ao", "ao", ("ao",)
    if slot == "material":
        return "material", "material", "metallic_roughness", ("roughness", "metallic")
    if slot in {"metalness", "metallic"}:
        return "metalness", "metallic", "metallic", ("metallic",)
    if slot == "roughness":
        return "roughness", "roughness", "roughness", ("roughness",)
    if slot == "glossiness":
        return "glossiness", "roughness", "glossiness", ("glossiness",)
    if slot == "specular":
        return "specular", "specular", "specular", ("specular",)
    if slot == "specular_glossiness":
        return "material", "specular", "specular_glossiness", ("specular", "glossiness")
    if slot == "emissive":
        return "emissive", "emissive", "emissive", ()
    if slot == "opacity":
        return "opacity", "opacity", "opacity", ("alpha",)
    if slot == "height":
        return "height", "height", "height", ("height",)
    if slot == "clearcoat_roughness":
        return "roughness", "roughness", "clearcoat_roughness", ("roughness",)
    if slot == "clearcoat_normal":
        return "normal", "normal", "clearcoat_normal", ()
    if slot == "clearcoat":
        return "specular", "specular", "clearcoat", ("clearcoat",)
    if slot == "sheen_roughness":
        return "roughness", "roughness", "sheen_roughness", ("roughness",)
    if slot == "sheen":
        return "specular", "specular", "sheen", ("sheen",)
    if slot in {"transmission", "volume", "anisotropy", "iridescence"}:
        return "material", "material", slot, (slot,)
    return slot, slot, slot, ()


def _scene_material_slot(
    slot_kind: str,
    path_text: str = "",
    *,
    parameter_name: str = "",
    texcoord: int = 0,
    transform: Sequence[float] = (),
    source: str = "",
    parameters: Sequence[PreviewMaterialParameterInput] = (),
    reference_path: str = "",
) -> SceneMaterialTextureSlot:
    input_slot, semantic_type, semantic_subtype, packed_channels = _scene_slot_semantics(slot_kind)
    parameter = str(parameter_name or "").strip() or _SCENE_SLOT_PARAMETER_NAMES.get(str(slot_kind or "").strip().lower(), "")
    return SceneMaterialTextureSlot(
        slot_kind=input_slot,
        path=str(path_text or "").strip(),
        parameter_name=parameter,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        shader_family="SkinnedMeshEmissive_Ver2" if input_slot == "emissive" else "",
        texcoord=max(0, int(texcoord or 0)),
        transform=tuple(float(value) for value in tuple(transform or ())[:5]),
        source=str(source or "").strip(),
        parameters=tuple(parameters),
        reference_path=str(reference_path or "").strip(),
    )


def _scene_preview_float_parameter(name: str, value: object) -> Optional[PreviewMaterialParameterInput]:
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return PreviewMaterialParameterInput(
        parameter_kind="float",
        parameter_name=str(name or ""),
        value=f"{numeric:.6f}",
        numeric_value=numeric,
    )


def _scene_preview_string_parameter(name: str, value: object) -> Optional[PreviewMaterialParameterInput]:
    text = str(value or "").strip()
    if not text:
        return None
    return PreviewMaterialParameterInput(parameter_kind="string", parameter_name=str(name or ""), value=text)


def _scene_preview_color_parameter(name: str, values: object) -> Optional[PreviewMaterialParameterInput]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)) or len(values) < 3:
        return None
    try:
        rgb = tuple(max(0.0, min(1.0, float(value))) for value in values[:3])
    except (TypeError, ValueError, OverflowError):
        return None
    return PreviewMaterialParameterInput(
        parameter_kind="color",
        parameter_name=str(name or ""),
        value="#" + "".join(f"{int(round(component * 255)):02x}" for component in rgb),
        color_value=rgb,
    )


def _append_scene_parameter(target: list[PreviewMaterialParameterInput], parameter: Optional[PreviewMaterialParameterInput]) -> None:
    if parameter is not None:
        target.append(parameter)


def _result_with_external_audit(
    source_path: Path,
    result: SceneImportResult,
    *,
    enabled: bool = True,
) -> SceneImportResult:
    from .scene_importer import SceneImportResult

    if not isinstance(result, SceneImportResult):
        return result
    if not enabled:
        return result
    if result.external_audit is None:
        result.external_audit = audit_external_model(source_path, result)
    return result


def audit_external_model(source_path: str | Path, scene_result: SceneImportResult) -> ExternalModelAudit:
    """Classify an imported model using geometry, material, and texture evidence."""
    source = Path(source_path)
    mesh = scene_result.mesh
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    material_inventory = _build_external_material_inventory(scene_result)
    material_names = {
        str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
        for submesh in submeshes
        if str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or "").strip()
    }
    texture_paths = tuple(
        path
        for path in tuple(scene_result.discovered_texture_files or ())
        + tuple(scene_result.extracted_embedded_files or ())
        + tuple(scene_result.discovered_supplemental_files or ())
        if isinstance(path, Path) and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
    )
    binding_slots = [
        slot_kind
        for binding in tuple(getattr(scene_result, "material_bindings", ()) or ())
        for slot_kind, _path in tuple(getattr(binding, "texture_slots", ()) or ())
    ]
    inventory_slots = [
        slot.slot_kind
        for material in material_inventory
        for slot in tuple(material.texture_slots or ())
        if str(slot.slot_kind or "").strip()
    ]
    texture_slots = tuple(
        sorted(
            set(
                binding_slots
                + inventory_slots
                + [_audit_texture_slot_from_path(path) for path in texture_paths if _audit_texture_slot_from_path(path)]
            )
        )
    )
    workflows = tuple(
        sorted(
            {
                str(getattr(binding, "pbr_workflow", "") or "").strip()
                for binding in tuple(getattr(scene_result, "material_bindings", ()) or ())
                if str(getattr(binding, "pbr_workflow", "") or "").strip()
            }
        )
    )
    text = " ".join(
        [str(source), str(getattr(mesh, "path", "") or "")]
        + [str(name) for name in material_names]
        + [path.stem for path in texture_paths]
    ).lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    extent = _mesh_extent(mesh)
    longest = max(extent) if extent else 0.0
    shortest = max(min(value for value in extent if value > 1e-8), 1e-8) if extent else 1e-8
    slender_ratio = longest / shortest if shortest > 0.0 else 0.0
    scores = {"sword": 0.0, "axe": 0.0, "helmet": 0.0}
    if tokens & {"sword", "blade", "dagger", "katana", "scimitar", "greatsword", "longsword"}:
        scores["sword"] += 0.50
    if tokens & {"axe", "hatchet", "halberd", "ax"}:
        scores["axe"] += 0.48
    if tokens & {"helmet", "helm", "mask", "visor"}:
        scores["helmet"] += 0.55
    if slender_ratio >= 5.0:
        scores["sword"] += 0.22
        scores["axe"] += 0.10
    if 1.1 <= slender_ratio <= 3.2 and tokens & {"helmet", "helm", "mask", "visor"}:
        scores["helmet"] += 0.18
    if any(slot in texture_slots for slot in ("base", "normal")):
        for key in scores:
            scores[key] += 0.06
    character_tokens = {"character", "body", "head", "hair", "skin", "arm", "hand", "leg", "foot", "nude", "torso"}
    false_positive = bool((tokens & {"axem", "axe"}) and len(tokens & character_tokens) >= 2)
    if "axem" in text.replace("-", "").replace("_", ""):
        false_positive = True
    if false_positive:
        scores["axe"] *= 0.30
    category, confidence = max(scores.items(), key=lambda item: item[1])
    if confidence < 0.35:
        category = "unknown"
    mixed_categories = [name for name, score in scores.items() if score >= 0.35]
    warnings: list[str] = []
    evidence: list[str] = []
    if false_positive:
        warnings.append("Filename/tag evidence looks like an axe, but mesh/material evidence looks like a mixed character asset.")
    if len(mixed_categories) > 1:
        warnings.append("Model has mixed category evidence; verify the intended subpart before replacement.")
    if texture_paths and "base" not in texture_slots:
        warnings.append("Textures were found but no clear visible base/diffuse texture was identified.")
    if not texture_paths:
        warnings.append("No external texture files were discovered.")
    if slender_ratio:
        evidence.append(f"shape ratio {slender_ratio:.1f}:1")
    if texture_slots:
        evidence.append("texture roles " + ", ".join(texture_slots[:8]))
    if workflows:
        evidence.append("PBR " + ", ".join(workflows))
    material_classes = _aggregate_external_material_classes(material_inventory)
    if material_classes:
        evidence.append(
            "material classes "
            + ", ".join(f"{item.material_class}:{item.confidence:.0%}" for item in material_classes[:6])
        )
    return ExternalModelAudit(
        source_path=str(source),
        verified_category=category,
        confidence=max(0.0, min(1.0, float(confidence))),
        mesh_count=len(submeshes),
        material_count=len(material_names),
        texture_slots=texture_slots,
        pbr_workflows=workflows,
        warnings=tuple(warnings),
        false_positive=false_positive,
        mixed_model=len(mixed_categories) > 1 or false_positive,
        evidence=tuple(evidence),
        material_inventory=material_inventory,
        material_classes=material_classes,
    )


def _build_external_material_inventory(scene_result: SceneImportResult) -> tuple[ExternalMaterialInventory, ...]:
    mesh = getattr(scene_result, "mesh", None)
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    bindings = tuple(getattr(scene_result, "material_bindings", ()) or ())
    if bindings:
        groups: OrderedDict[tuple[int, str], list[ImportedMaterialBinding]] = OrderedDict()
        for binding in bindings:
            material_index = _safe_int(getattr(binding, "material_index", -1), -1)
            material_name = str(getattr(binding, "material_name", "") or "").strip()
            key = (material_index, material_name.casefold())
            groups.setdefault(key, []).append(binding)
        return tuple(
            _external_material_inventory_from_binding_group(group, submeshes)
            for group in groups.values()
        )

    by_material: OrderedDict[str, list[tuple[int, SubMesh]]] = OrderedDict()
    for index, submesh in enumerate(submeshes):
        material_name = str(getattr(submesh, "material", "") or getattr(submesh, "name", "") or f"submesh_{index}").strip()
        by_material.setdefault(material_name.casefold(), []).append((index, submesh))
    return tuple(
        _external_material_inventory_from_submesh_group(group, material_index=index)
        for index, group in enumerate(by_material.values())
    )


def _external_material_inventory_from_binding_group(
    bindings: Sequence[ImportedMaterialBinding],
    submeshes: Sequence[SubMesh],
) -> ExternalMaterialInventory:
    binding_tuple = tuple(bindings or ())
    first = binding_tuple[0] if binding_tuple else ImportedMaterialBinding()
    submesh_indices = tuple(
        _safe_int(getattr(binding, "submesh_index", -1), -1)
        for binding in binding_tuple
        if _safe_int(getattr(binding, "submesh_index", -1), -1) >= 0
    )
    group_submeshes = tuple(
        submeshes[index]
        for index in submesh_indices
        if 0 <= index < len(submeshes)
    )
    section_pairs = tuple((index, submeshes[index]) for index in submesh_indices if 0 <= index < len(submeshes))
    material_name = str(getattr(first, "material_name", "") or "").strip()
    if not material_name and group_submeshes:
        material_name = str(getattr(group_submeshes[0], "material", "") or getattr(group_submeshes[0], "name", "") or "").strip()
    texture_slots = _external_inventory_texture_slots(group_submeshes, binding_tuple)
    sections = _external_material_section_inventory(section_pairs)
    workflow = _normalize_external_pbr_workflow(
        next((str(getattr(binding, "pbr_workflow", "") or "") for binding in binding_tuple if str(getattr(binding, "pbr_workflow", "") or "").strip()), "")
    )
    alpha_mode = _external_inventory_alpha_mode(group_submeshes, binding_tuple)
    double_sided = any(bool(getattr(binding, "double_sided", False)) for binding in binding_tuple) or any(
        bool(getattr(submesh, "preview_double_sided", False)) for submesh in group_submeshes
    )
    scalar_hints = _external_inventory_scalar_hints(group_submeshes)
    color_factor = _external_inventory_color_factor(group_submeshes)
    vertex_color_factor = _external_inventory_vertex_color_factor(group_submeshes)
    vertex_alpha = _external_inventory_vertex_alpha(group_submeshes)
    emissive_color = _external_inventory_emissive_color(group_submeshes)
    classes = _classify_external_material(
        material_name=material_name,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
    )
    warnings = _external_inventory_warnings(texture_slots, workflow, alpha_mode, classes)
    return ExternalMaterialInventory(
        material_index=_safe_int(getattr(first, "material_index", -1), -1),
        material_name=material_name,
        submesh_indices=submesh_indices,
        submesh_names=tuple(_dedupe_text([str(getattr(binding, "submesh_name", "") or "") for binding in binding_tuple])),
        sections=sections,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
        material_classes=classes,
        warnings=warnings,
    )


def _external_material_inventory_from_submesh_group(
    group: Sequence[tuple[int, SubMesh]],
    *,
    material_index: int,
) -> ExternalMaterialInventory:
    group_tuple = tuple(group or ())
    submesh_indices = tuple(index for index, _submesh in group_tuple)
    submeshes = tuple(submesh for _index, submesh in group_tuple)
    material_name = ""
    if submeshes:
        material_name = str(getattr(submeshes[0], "material", "") or getattr(submeshes[0], "name", "") or "").strip()
    texture_slots = _external_inventory_texture_slots(submeshes, ())
    sections = _external_material_section_inventory(group_tuple)
    alpha_mode = _external_inventory_alpha_mode(submeshes, ())
    double_sided = any(bool(getattr(submesh, "preview_double_sided", False)) for submesh in submeshes)
    scalar_hints = _external_inventory_scalar_hints(submeshes)
    workflow = _external_inventory_workflow_from_slots(texture_slots, scalar_hints)
    color_factor = _external_inventory_color_factor(submeshes)
    vertex_color_factor = _external_inventory_vertex_color_factor(submeshes)
    vertex_alpha = _external_inventory_vertex_alpha(submeshes)
    emissive_color = _external_inventory_emissive_color(submeshes)
    classes = _classify_external_material(
        material_name=material_name,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
    )
    return ExternalMaterialInventory(
        material_index=material_index,
        material_name=material_name,
        submesh_indices=submesh_indices,
        submesh_names=tuple(_dedupe_text([str(getattr(submesh, "name", "") or "") for submesh in submeshes])),
        sections=sections,
        texture_slots=texture_slots,
        pbr_workflow=workflow,
        alpha_mode=alpha_mode,
        double_sided=double_sided,
        scalar_hints=scalar_hints,
        color_factor=color_factor,
        vertex_color_factor=vertex_color_factor,
        vertex_alpha=vertex_alpha,
        emissive_color=emissive_color,
        material_classes=classes,
        warnings=_external_inventory_warnings(texture_slots, workflow, alpha_mode, classes),
    )


def _external_inventory_texture_slots(
    submeshes: Sequence[SubMesh],
    bindings: Sequence[ImportedMaterialBinding],
) -> tuple[ExternalMaterialTextureInventory, ...]:
    output: list[ExternalMaterialTextureInventory] = []
    seen: set[tuple[str, str, str]] = set()

    def add(slot: ExternalMaterialTextureInventory) -> None:
        key = (
            str(slot.slot_kind or "").strip().lower(),
            str(slot.parameter_name or "").strip().lower(),
            str(slot.texture_path or "").replace("\\", "/").lower(),
        )
        if not key[0] or not key[2] or key in seen:
            return
        seen.add(key)
        output.append(slot)

    for submesh in tuple(submeshes or ()):
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if isinstance(texture_input, PreviewMaterialTextureInput):
                add(_external_texture_inventory_from_input(texture_input))
    for binding in tuple(bindings or ()):
        for slot_kind, path in tuple(getattr(binding, "texture_slots", ()) or ()):
            path_text = str(path or "").strip()
            if not path_text:
                continue
            add(_external_texture_inventory_from_path(str(slot_kind or ""), path_text, source="binding"))
    return tuple(sorted(output, key=lambda item: (item.slot_kind, item.semantic_subtype, item.texture_name.lower())))


def _external_material_section_inventory(
    section_pairs: Sequence[tuple[int, SubMesh]],
) -> tuple[ExternalMaterialSectionInventory, ...]:
    sections: list[ExternalMaterialSectionInventory] = []
    seen: set[int] = set()
    for section_index, submesh in tuple(section_pairs or ()):
        index = _safe_int(section_index, -1)
        if index in seen:
            continue
        seen.add(index)
        vertices = list(getattr(submesh, "vertices", ()) or ())
        faces = list(getattr(submesh, "faces", ()) or ())
        uvs = list(getattr(submesh, "uvs", ()) or ())
        normals = list(getattr(submesh, "normals", ()) or ())
        tangents = list(getattr(submesh, "tangents", ()) or ())
        bone_indices = list(getattr(submesh, "bone_indices", ()) or ())
        bone_weights = list(getattr(submesh, "bone_weights", ()) or ())
        bounds_min, bounds_max = _bbox(vertices)
        texcoord_sets = sorted(
            {
                _external_texture_input_texcoord(texture_input)
                for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
                if isinstance(texture_input, PreviewMaterialTextureInput)
            }
        )
        sections.append(
            ExternalMaterialSectionInventory(
                section_index=index,
                section_name=str(getattr(submesh, "name", "") or ""),
                material_name=str(getattr(submesh, "material", "") or ""),
                vertex_count=len(vertices) or _safe_int(getattr(submesh, "vertex_count", 0), 0),
                face_count=len(faces) or _safe_int(getattr(submesh, "face_count", 0), 0),
                has_uvs=bool(uvs and (not vertices or len(uvs) == len(vertices))),
                has_normals=bool(normals and (not vertices or len(normals) == len(vertices))),
                has_tangents=bool(tangents and (not vertices or len(tangents) == len(vertices))),
                has_skinning=bool((bone_indices or bone_weights) and (not vertices or len(bone_indices) == len(vertices) or len(bone_weights) == len(vertices))),
                texture_texcoord_sets=tuple(texcoord_sets),
                bounds_min=tuple(round(float(value), 6) for value in bounds_min),
                bounds_max=tuple(round(float(value), 6) for value in bounds_max),
            )
        )
    return tuple(sections)


def _external_texture_inventory_from_input(texture_input: PreviewMaterialTextureInput) -> ExternalMaterialTextureInventory:
    path_text = str(
        getattr(texture_input, "preview_texture_path", "")
        or getattr(texture_input, "source_texture_path", "")
        or getattr(texture_input, "source_dds_path", "")
        or ""
    ).strip()
    slot_kind = str(getattr(texture_input, "slot_kind", "") or "").strip().lower()
    parameter_name = str(getattr(texture_input, "parameter_name", "") or "").strip()
    semantic_type = str(getattr(texture_input, "semantic_type", "") or "").strip()
    semantic_subtype = str(getattr(texture_input, "semantic_subtype", "") or "").strip()
    packed_channels = tuple(str(value or "").strip().lower() for value in tuple(getattr(texture_input, "packed_channels", ()) or ()) if str(value or "").strip())
    texcoord = _external_texture_input_texcoord(texture_input)
    uv_transform = _external_texture_input_uv_transform(texture_input)
    resolution, channel_stats = _texture_image_facts(path_text)
    evidence = [
        f"slot:{slot_kind}",
        f"parameter:{parameter_name}" if parameter_name else "",
        f"semantic:{semantic_type}/{semantic_subtype}" if semantic_type or semantic_subtype else "",
        f"packed:{','.join(packed_channels)}" if packed_channels else "",
        f"texcoord:{texcoord}" if texcoord else "",
        "uv_transform" if uv_transform else "",
        _channel_stats_evidence(channel_stats),
        f"confidence:{getattr(texture_input, 'confidence', '')}" if str(getattr(texture_input, "confidence", "") or "").strip() else "",
    ]
    return ExternalMaterialTextureInventory(
        slot_kind=slot_kind,
        parameter_name=parameter_name,
        texture_path=path_text,
        texture_name=str(getattr(texture_input, "texture_name", "") or Path(path_text).name),
        image_format=Path(path_text).suffix.lower().lstrip("."),
        resolution=resolution,
        channel_stats=channel_stats,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        color_space=_external_slot_color_space(slot_kind, semantic_subtype, str(getattr(texture_input, "srgb_mode", "") or "")),
        texcoord=texcoord,
        uv_transform=uv_transform,
        source=_external_texture_input_source(texture_input),
        confidence=str(getattr(texture_input, "confidence", "") or ""),
        evidence=tuple(item for item in evidence if item),
    )


def _external_texture_inventory_from_path(slot_kind: str, path_text: str, *, source: str) -> ExternalMaterialTextureInventory:
    slot, semantic_type, semantic_subtype, packed_channels = _scene_slot_semantics(slot_kind)
    resolution, channel_stats = _texture_image_facts(path_text)
    return ExternalMaterialTextureInventory(
        slot_kind=slot,
        parameter_name=_SCENE_SLOT_PARAMETER_NAMES.get(slot_kind.strip().lower(), ""),
        texture_path=path_text,
        texture_name=Path(path_text).name,
        image_format=Path(path_text).suffix.lower().lstrip("."),
        resolution=resolution,
        channel_stats=channel_stats,
        semantic_type=semantic_type,
        semantic_subtype=semantic_subtype,
        packed_channels=packed_channels,
        color_space=_external_slot_color_space(slot, semantic_subtype, ""),
        texcoord=0,
        uv_transform=(),
        source=source,
        confidence="binding",
        evidence=tuple(item for item in (f"slot:{slot}", f"source:{source}", _channel_stats_evidence(channel_stats)) if item),
    )


def _external_texture_input_source(texture_input: PreviewMaterialTextureInput) -> str:
    for flag in tuple(getattr(texture_input, "blend_flags", ()) or ()):
        text = str(flag or "").strip()
        if text.startswith("source:"):
            return text.split(":", 1)[1]
    sidecar_kind = str(getattr(texture_input, "sidecar_kind", "") or "").strip()
    if sidecar_kind:
        return sidecar_kind
    return str(getattr(texture_input, "confidence", "") or "scene")


def _external_texture_input_texcoord(texture_input: PreviewMaterialTextureInput) -> int:
    for flag in tuple(getattr(texture_input, "blend_flags", ()) or ()):
        match = re.match(r"texcoord:(\d+)\s*$", str(flag or "").strip(), flags=re.IGNORECASE)
        if match:
            return max(0, _safe_int(match.group(1), 0))
    for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
        name = str(getattr(parameter, "parameter_name", "") or "")
        if "_gltfTexCoord" not in name:
            continue
        value = getattr(parameter, "numeric_value", None)
        if value is None:
            value = getattr(parameter, "value", 0)
        return max(0, _safe_int(value, 0))
    return 0


def _external_texture_input_uv_transform(texture_input: PreviewMaterialTextureInput) -> tuple[float, ...]:
    for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
        name = str(getattr(parameter, "parameter_name", "") or "")
        if "_gltfTextureTransform" not in name:
            continue
        raw_values = re.split(r"[\s,]+", str(getattr(parameter, "value", "") or "").strip())
        try:
            values = tuple(float(value) for value in raw_values if value)
        except (TypeError, ValueError, OverflowError):
            return ()
        return tuple(round(float(value), 6) for value in values[:5]) if len(values) >= 5 else ()
    return ()


def _texture_image_facts(path_text: str) -> tuple[tuple[int, int], tuple[tuple[str, float], ...]]:
    if not str(path_text or "").strip():
        return (), ()
    try:
        from PIL import Image, ImageStat

        previous_max_pixels = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = None
            with Image.open(path_text) as image:
                resolution = (int(image.width), int(image.height))
                if int(image.width) * int(image.height) > _SCENE_TEXTURE_FACT_CHANNEL_STATS_MAX_PIXELS:
                    return resolution, ()
                rgba = image.convert("RGBA")
        finally:
            Image.MAX_IMAGE_PIXELS = previous_max_pixels
        try:
            if max(rgba.size or (0, 0)) > 64:
                rgba.thumbnail((64, 64))
            stat = ImageStat.Stat(rgba)
            means = [max(0.0, min(1.0, float(value) / 255.0)) for value in stat.mean[:4]]
            extrema = rgba.getextrema()
            alpha_min = max(0.0, min(1.0, float(extrema[3][0]) / 255.0))
            alpha_max = max(0.0, min(1.0, float(extrema[3][1]) / 255.0))
            luma = max(0.0, min(1.0, 0.2126 * means[0] + 0.7152 * means[1] + 0.0722 * means[2]))
            return resolution, (
                ("r_mean", round(means[0], 4)),
                ("g_mean", round(means[1], 4)),
                ("b_mean", round(means[2], 4)),
                ("a_mean", round(means[3], 4)),
                ("a_min", round(alpha_min, 4)),
                ("a_max", round(alpha_max, 4)),
                ("luma_mean", round(luma, 4)),
            )
        finally:
            try:
                rgba.close()
            except Exception:
                pass
    except Exception:
        return (), ()


def _texture_resolution(path_text: str) -> tuple[int, int]:
    resolution, _stats = _texture_image_facts(path_text)
    return resolution


def _channel_stats_evidence(channel_stats: Sequence[tuple[str, float]]) -> str:
    stats = {str(key): float(value) for key, value in tuple(channel_stats or ())}
    if not stats:
        return ""
    return (
        "channels:"
        f"r={stats.get('r_mean', 0.0):.2f},"
        f"g={stats.get('g_mean', 0.0):.2f},"
        f"b={stats.get('b_mean', 0.0):.2f},"
        f"a={stats.get('a_mean', 0.0):.2f}"
    )


def _external_slot_color_space(slot_kind: str, semantic_subtype: str, srgb_mode: str) -> str:
    mode = str(srgb_mode or "").strip().lower()
    if mode in {"srgb", "s_rgb", "true", "1", "yes"}:
        return "srgb"
    if mode in {"linear", "false", "0", "no"}:
        return "linear"
    slot = str(slot_kind or "").strip().lower()
    subtype = str(semantic_subtype or "").strip().lower()
    if slot in {"base", "emissive"} or subtype in {"albedo", "emissive", "specular"}:
        return "srgb"
    return "linear"


def _normalize_external_pbr_workflow(value: object) -> str:
    text = str(value or "").strip()
    compact = re.sub(r"[^a-z0-9]+", "", text.lower())
    if compact in {"metallicroughness", "metalnessroughness", "pbrmetallicroughness"}:
        return "metallic_roughness"
    if compact in {"specularglossiness", "specgloss", "pbrspecularglossiness"}:
        return "specular_glossiness"
    if compact == "unlit":
        return "unlit"
    return text


def _external_inventory_workflow_from_slots(
    slots: Sequence[ExternalMaterialTextureInventory],
    scalar_hints: Sequence[tuple[str, float]] = (),
) -> str:
    subtypes = {str(slot.semantic_subtype or "").strip().lower() for slot in tuple(slots or ())}
    kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(slots or ())}
    scalar_keys = {str(key or "").strip().lower() for key, _value in tuple(scalar_hints or ())}
    if "specular_glossiness" in subtypes or {"specular", "glossiness"} <= kinds:
        return "specular_glossiness"
    if {"specular", "glossiness"} <= scalar_keys and "metalness" not in scalar_keys:
        return "specular_glossiness"
    if "metallic_roughness" in subtypes or "metalness" in kinds or "roughness" in kinds:
        return "metallic_roughness"
    if "metalness" in scalar_keys or "roughness" in scalar_keys:
        return "metallic_roughness"
    return ""


def _external_inventory_alpha_mode(
    submeshes: Sequence[SubMesh],
    bindings: Sequence[ImportedMaterialBinding],
) -> str:
    for binding in tuple(bindings or ()):
        alpha_mode = str(getattr(binding, "alpha_mode", "") or "").strip()
        if alpha_mode:
            return alpha_mode
    for submesh in tuple(submeshes or ()):
        alpha_mode = str(getattr(submesh, "preview_alpha_mode", "") or "").strip()
        if alpha_mode:
            return alpha_mode
    return ""


def _external_inventory_scalar_hints(submeshes: Sequence[SubMesh]) -> tuple[tuple[str, float], ...]:
    values: OrderedDict[str, float] = OrderedDict()
    for submesh in tuple(submeshes or ()):
        for parameter in tuple(getattr(submesh, "preview_material_parameters", ()) or ()):
            normalized = _normalized_material_scalar_name(getattr(parameter, "parameter_name", ""))
            if not normalized:
                continue
            numeric = getattr(parameter, "numeric_value", None)
            if numeric is None:
                numeric = _safe_float_or_none(getattr(parameter, "value", ""))
            else:
                numeric = _safe_float_or_none(numeric)
            if numeric is not None:
                values.setdefault(normalized, numeric)
        overrides = getattr(submesh, "preview_native_material_overrides", {}) or {}
        if isinstance(overrides, Mapping):
            for key, value in overrides.items():
                normalized = _normalized_material_scalar_name(key)
                if not normalized:
                    continue
                numeric = _safe_float_or_none(value)
                if numeric is not None:
                    values.setdefault(normalized, numeric)
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if not isinstance(texture_input, PreviewMaterialTextureInput):
                continue
            for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
                normalized = _normalized_material_scalar_name(getattr(parameter, "parameter_name", ""))
                if not normalized:
                    continue
                numeric = getattr(parameter, "numeric_value", None)
                if numeric is None:
                    numeric = _safe_float_or_none(getattr(parameter, "value", ""))
                else:
                    numeric = _safe_float_or_none(numeric)
                if numeric is not None:
                    values.setdefault(normalized, numeric)
    return tuple(values.items())


def _safe_float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _normalized_material_scalar_name(value: object) -> str:
    key = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if "roughness" in key:
        return "roughness"
    if "metallic" in key or "metalness" in key:
        return "metalness"
    if "glossiness" in key or key == "gloss":
        return "glossiness"
    if "specular" in key:
        return "specular"
    if "emissiveintensity" in key or key == "emissive":
        return "emissive_intensity"
    if "transmission" in key or "thickness" in key or "attenuation" in key:
        return "transmission"
    if "alphacutoff" in key or "alphathreshold" in key:
        return "alpha_cutoff"
    if "clearcoat" in key:
        return "clearcoat"
    if key == "ior":
        return "ior"
    return ""


def _external_inventory_color_factor(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        for attr_name in ("preview_texture_tint", "preview_color"):
            values = tuple(getattr(submesh, attr_name, ()) or ())
            if len(values) >= 3:
                try:
                    return tuple(max(0.0, min(1.0, float(value))) for value in values[:3])  # type: ignore[return-value]
                except (TypeError, ValueError, OverflowError):
                    continue
    return ()


def _external_inventory_vertex_color_factor(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        values = tuple(getattr(submesh, "preview_vertex_color_mean", ()) or ())
        if len(values) >= 3:
            try:
                return tuple(max(0.0, min(1.0, float(value))) for value in values[:3])  # type: ignore[return-value]
            except (TypeError, ValueError, OverflowError):
                continue
    return ()


def _external_inventory_vertex_alpha(submeshes: Sequence[SubMesh]) -> tuple[float, float]:
    for submesh in tuple(submeshes or ()):
        mean_value = getattr(submesh, "preview_vertex_alpha_mean", None)
        min_value = getattr(submesh, "preview_vertex_alpha_min", None)
        if mean_value is None and min_value is None:
            continue
        try:
            alpha_mean = max(0.0, min(1.0, float(1.0 if mean_value is None else mean_value)))
            alpha_min = max(0.0, min(1.0, float(alpha_mean if min_value is None else min_value)))
            return (alpha_mean, alpha_min)
        except (TypeError, ValueError, OverflowError):
            continue
    return ()


def _external_inventory_emissive_color(submeshes: Sequence[SubMesh]) -> tuple[float, float, float]:
    for submesh in tuple(submeshes or ()):
        overrides = getattr(submesh, "preview_native_material_overrides", {}) or {}
        if isinstance(overrides, Mapping):
            color = _hex_color_to_rgb(overrides.get("emissive_color"))
            if color:
                return color
        for texture_input in tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()):
            if not isinstance(texture_input, PreviewMaterialTextureInput):
                continue
            for parameter in tuple(getattr(texture_input, "material_parameters", ()) or ()):
                key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
                if "emissivecolor" not in key:
                    continue
                color = tuple(getattr(parameter, "color_value", ()) or ())
                if len(color) >= 3:
                    try:
                        return tuple(max(0.0, min(1.0, float(value))) for value in color[:3])  # type: ignore[return-value]
                    except (TypeError, ValueError, OverflowError):
                        pass
                color = _hex_color_to_rgb(getattr(parameter, "value", ""))
                if color:
                    return color
    return ()


def _hex_color_to_rgb(value: object) -> tuple[float, float, float]:
    text = str(value or "").strip().lstrip("#")
    if len(text) < 6:
        return ()
    try:
        return (int(text[0:2], 16) / 255.0, int(text[2:4], 16) / 255.0, int(text[4:6], 16) / 255.0)
    except ValueError:
        return ()


def _classify_external_material(
    *,
    material_name: str,
    texture_slots: Sequence[ExternalMaterialTextureInventory],
    pbr_workflow: str,
    alpha_mode: str,
    double_sided: bool,
    scalar_hints: Sequence[tuple[str, float]],
    color_factor: Sequence[float],
    vertex_color_factor: Sequence[float],
    vertex_alpha: Sequence[float],
    emissive_color: Sequence[float],
) -> tuple[ExternalMaterialClassEvidence, ...]:
    evidence_by_class: dict[str, list[str]] = defaultdict(list)
    scores: dict[str, float] = defaultdict(float)
    raw_text = " ".join(
        [material_name]
        + [_material_class_texture_token_text(slot.texture_name) for slot in tuple(texture_slots or ())]
    )
    split_text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_text)
    text = split_text.lower()
    tokens = set(re.findall(r"[a-z0-9]+", text))
    compact_tokens = {
        re.sub(r"[^a-z0-9]+", "", token)
        for token in re.split(r"[\s._/\-\\]+", raw_text.lower())
        if re.sub(r"[^a-z0-9]+", "", token)
    }
    tokens.update(compact_tokens)
    scalar_map = {str(key): float(value) for key, value in tuple(scalar_hints or ())}
    slot_kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(texture_slots or ())}
    slot_subtypes = {str(slot.semantic_subtype or "").strip().lower() for slot in tuple(texture_slots or ())}
    slots = tuple(texture_slots or ())

    def slot_stats(slot: ExternalMaterialTextureInventory) -> dict[str, float]:
        return {str(key): float(value) for key, value in tuple(getattr(slot, "channel_stats", ()) or ())}

    def first_stats_for(*slot_names: str) -> dict[str, float]:
        wanted = {str(name or "").strip().lower() for name in slot_names if str(name or "").strip()}
        for slot in slots:
            if (
                str(slot.slot_kind or "").strip().lower() in wanted
                or str(slot.semantic_subtype or "").strip().lower() in wanted
            ):
                stats = slot_stats(slot)
                if stats:
                    return stats
        return {}

    def add(material_class: str, amount: float, reason: str) -> None:
        if amount <= 0.0:
            return
        scores[material_class] += amount
        if reason not in evidence_by_class[material_class]:
            evidence_by_class[material_class].append(reason)

    def has_any(*terms: str) -> bool:
        wanted = {str(term or "").strip().lower() for term in terms if str(term or "").strip()}
        if tokens & wanted:
            return True
        for token in tokens:
            for term in wanted:
                if len(term) >= 5 and (token.startswith(term) or token.endswith(term)):
                    return True
        return False

    metalness = float(scalar_map.get("metalness", 0.0) or 0.0)
    roughness = float(scalar_map.get("roughness", 0.0) or 0.0)
    if metalness >= 0.5:
        add("metal", 0.55 + min(0.25, metalness * 0.25), f"metallic factor {metalness:.2f}")
    material_stats = first_stats_for("material", "metallic_roughness")
    metallic_channel = material_stats.get("b_mean")
    if metallic_channel is not None and "metallic_roughness" in slot_subtypes:
        if metallic_channel >= 0.45:
            add("metal", 0.35 + min(0.25, metallic_channel * 0.25), f"metallic-roughness B channel mean {metallic_channel:.2f}")
    metalness_stats = first_stats_for("metalness", "metallic")
    metalness_luma = metalness_stats.get("luma_mean")
    if metalness_luma is not None and metalness_luma >= 0.45:
        add("metal", 0.35 + min(0.25, metalness_luma * 0.25), f"metalness texture mean {metalness_luma:.2f}")
    if has_any("metal", "steel", "iron", "silver", "chrome", "blade", "sword", "armor", "armour"):
        add("metal", 0.35, "metal material/name token")
    if has_any("painted", "paint", "paintjob", "coated", "enamel") and (metalness >= 0.2 or "metal" in scores):
        add("painted_metal", 0.70, "painted/coated token with metal evidence")

    rgb = tuple(float(value) for value in tuple(color_factor or ())[:3]) if len(tuple(color_factor or ())) >= 3 else ()
    rgb_source = "base factor"
    base_stats = first_stats_for("base", "albedo")
    if base_stats and (not rgb or all(abs(value - 1.0) <= 1e-6 for value in rgb)):
        if {"r_mean", "g_mean", "b_mean"} <= set(base_stats):
            rgb = (base_stats["r_mean"], base_stats["g_mean"], base_stats["b_mean"])
            rgb_source = "base texture mean"
    vertex_rgb = (
        tuple(float(value) for value in tuple(vertex_color_factor or ())[:3])
        if len(tuple(vertex_color_factor or ())) >= 3
        else ()
    )
    if vertex_rgb and (not rgb or all(abs(value - 1.0) <= 1e-6 for value in rgb)):
        rgb = vertex_rgb
        rgb_source = "vertex color mean"
    if has_any("gold", "gilded"):
        add("gold", 0.90, "gold material/name token")
    if has_any("bronze", "brass"):
        add("bronze", 0.88, "bronze/brass material/name token")
    if has_any("copper"):
        add("copper", 0.88, "copper material/name token")
    if rgb and (metalness >= 0.35 or scores.get("metal", 0.0) >= 0.35):
        r, g, b = rgb
        if r >= 0.65 and g >= 0.45 and b <= 0.38:
            add("gold", 0.60, f"metallic yellow {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.55 and 0.20 <= g <= 0.55 and b <= 0.35:
            add("copper", 0.50, f"warm metallic {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        elif r >= 0.45 and g >= 0.25 and b <= 0.30:
            add("bronze", 0.45, f"bronze-like metallic {rgb_source} {r:.2f},{g:.2f},{b:.2f}")

    if has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment"):
        add("cloth", 0.80, "cloth/fabric material/name token")
    if double_sided and has_any("cloth", "fabric", "linen", "cotton", "canvas", "textile", "garment", "cape", "flag"):
        add("cloth", 0.18, "double-sided fabric surface")
    if has_any("leather", "hide", "suede"):
        add("leather", 0.85, "leather material/name token")
    if has_any("wood", "wooden", "timber", "oak", "pine", "walnut", "bark"):
        add("wood", 0.85, "wood material/name token")
    if has_any("stone", "rock", "granite", "marble", "concrete", "slate", "ceramic"):
        add("stone", 0.85, "stone/rock material/name token")
    if has_any("skin", "organic", "flesh", "body", "face", "hand", "arm", "leg", "head"):
        add("skin_organic", 0.82, "skin/organic material/name token")
    if rgb and metalness < 0.2:
        r, g, b = rgb
        spread = max(rgb) - min(rgb)
        if r >= 0.22 and g >= 0.12 and b <= 0.18 and r >= g >= b:
            if roughness >= 0.55:
                add("leather", 0.28, f"rough warm brown {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
            add("wood", 0.24, f"warm brown {rgb_source} {r:.2f},{g:.2f},{b:.2f}")
        if spread <= 0.12 and 0.20 <= max(rgb) <= 0.75 and roughness >= 0.45:
            add("stone", 0.22, f"rough neutral {rgb_source} {r:.2f},{g:.2f},{b:.2f}")

    alpha_text = str(alpha_mode or "").strip().upper()
    transmission = float(scalar_map.get("transmission", 0.0) or 0.0)
    if has_any("glass", "crystal", "gem", "lens", "transparent", "translucent", "transmission"):
        add("glass_crystal", 0.86, "glass/crystal material/name token")
    if transmission > 0.0 or "transmission" in slot_subtypes:
        add("glass_crystal", 0.62, f"transmission evidence {transmission:.2f}")
    if alpha_text in {"BLEND", "MASK"} or "opacity" in slot_kinds:
        add("glass_crystal", 0.24, f"alpha mode {alpha_text or 'opacity texture'}")
    alpha_stats = first_stats_for("base", "opacity")
    if alpha_stats.get("a_min", 1.0) < 0.98 or alpha_stats.get("a_mean", 1.0) < 0.98:
        add(
            "glass_crystal",
            0.22,
            f"source alpha channel mean {alpha_stats.get('a_mean', 1.0):.2f} min {alpha_stats.get('a_min', 1.0):.2f}",
        )
    vertex_alpha_values = tuple(float(value) for value in tuple(vertex_alpha or ())[:2]) if len(tuple(vertex_alpha or ())) >= 2 else ()
    if vertex_alpha_values and (vertex_alpha_values[0] < 0.98 or vertex_alpha_values[1] < 0.98):
        add(
            "glass_crystal",
            0.16,
            f"vertex alpha mean {vertex_alpha_values[0]:.2f} min {vertex_alpha_values[1]:.2f}",
        )

    emissive_intensity = float(scalar_map.get("emissive_intensity", 0.0) or 0.0)
    emissive_stats = first_stats_for("emissive")
    if "emissive" in slot_kinds or emissive_intensity > 0.0 or len(tuple(emissive_color or ())) >= 3 or emissive_stats.get("luma_mean", 0.0) > 0.03:
        reasons = []
        if "emissive" in slot_kinds:
            reasons.append("emissive texture slot")
        if emissive_intensity > 0.0:
            reasons.append(f"emissive intensity {emissive_intensity:.2f}")
        if len(tuple(emissive_color or ())) >= 3:
            reasons.append("emissive color factor")
        if emissive_stats.get("luma_mean", 0.0) > 0.03:
            reasons.append(f"emissive texture luma {emissive_stats.get('luma_mean', 0.0):.2f}")
        add("emissive", 0.90, ", ".join(reasons))

    if not scores:
        return (
            ExternalMaterialClassEvidence(
                material_class="unknown",
                confidence=0.0,
                evidence=("no decisive material-class evidence",),
            ),
        )
    results = [
        ExternalMaterialClassEvidence(
            material_class=material_class,
            confidence=max(0.0, min(1.0, score)),
            evidence=tuple(evidence_by_class.get(material_class, ())),
        )
        for material_class, score in scores.items()
    ]
    return tuple(sorted(results, key=lambda item: (-item.confidence, item.material_class)))


def _material_class_texture_token_text(texture_name: object) -> str:
    stem = PurePosixPath(str(texture_name or "").replace("\\", "/")).stem
    if not stem:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem).lower()
    for token in _MATERIAL_CLASS_TEXTURE_ROLE_TOKENS:
        text = re.sub(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", " ", text)
    return text


def _external_inventory_warnings(
    texture_slots: Sequence[ExternalMaterialTextureInventory],
    workflow: str,
    alpha_mode: str,
    material_classes: Sequence[ExternalMaterialClassEvidence],
) -> tuple[str, ...]:
    warnings: list[str] = []
    slot_kinds = {str(slot.slot_kind or "").strip().lower() for slot in tuple(texture_slots or ())}
    if texture_slots and "base" not in slot_kinds:
        warnings.append("Material has support textures but no explicit base/albedo slot.")
    if workflow == "specular_glossiness" and "material" in slot_kinds and "roughness" not in slot_kinds:
        warnings.append("Specular-glossiness workflow needs conversion before Crimson metallic/roughness export.")
    if str(alpha_mode or "").strip().upper() in {"MASK", "BLEND"} and "opacity" not in slot_kinds:
        warnings.append("Alpha mode is active without a separate opacity texture; base alpha must be preserved.")
    if material_classes and material_classes[0].material_class == "unknown":
        warnings.append("Material class is ambiguous; keep evidence in the authority report.")
    return tuple(warnings)


def _aggregate_external_material_classes(
    inventory: Sequence[ExternalMaterialInventory],
) -> tuple[ExternalMaterialClassEvidence, ...]:
    by_class: dict[str, ExternalMaterialClassEvidence] = {}
    for material in tuple(inventory or ()):
        for item in tuple(material.material_classes or ()):
            current = by_class.get(item.material_class)
            if current is None or item.confidence > current.confidence:
                by_class[item.material_class] = item
    return tuple(sorted(by_class.values(), key=lambda item: (-item.confidence, item.material_class)))


def _mesh_extent(mesh: ParsedMesh) -> tuple[float, float, float]:
    vertices = [vertex for submesh in tuple(getattr(mesh, "submeshes", ()) or ()) for vertex in tuple(getattr(submesh, "vertices", ()) or ())]
    if not vertices:
        return (0.0, 0.0, 0.0)
    xs = [float(vertex[0]) for vertex in vertices]
    ys = [float(vertex[1]) for vertex in vertices]
    zs = [float(vertex[2]) for vertex in vertices]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _audit_texture_slot_from_path(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "color", "colour")):
        return "base"
    if any(token in stem for token in ("normal", "normalmap", "nrm")):
        return "normal"
    if any(token in stem for token in ("metallicroughness", "roughnessmetallic", "metalrough")):
        return "roughness"
    if "roughness" in stem:
        return "roughness"
    if any(token in stem for token in ("metallic", "metalness")):
        return "metallic"
    if any(token in stem for token in ("specularglossiness", "specular", "glossiness")):
        return "specular"
    if any(token in stem for token in ("emissive", "emission", "glow")):
        return "emissive"
    if any(token in stem for token in ("height", "displacement", "bump")):
        return "height"
    if any(token in stem for token in ("ao", "occlusion")):
        return "ao"
    return ""


def _visible_texture_score(path: Path) -> int:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(
        token in stem
        for token in (
            "normal",
            "normalmap",
            "nrm",
            "roughness",
            "metallic",
            "height",
            "displacement",
            "ambientocclusion",
            "mixedao",
            "occlusion",
            "emissive",
            "emission",
        )
    ):
        return 0
    if any(token in stem for token in ("basecolor", "basecolour", "basecol")):
        return 100
    if any(token in stem for token in ("albedo", "diffuse")):
        return 90
    if any(token in stem for token in ("color", "colour", "base")):
        return 80
    return 45

def _scene_parameter_numeric(parameters: Sequence[PreviewMaterialParameterInput], *names: str) -> Optional[float]:
    normalized_names = tuple(re.sub(r"[^a-z0-9]+", "", str(name or "").lower()) for name in names if str(name or "").strip())
    if not normalized_names:
        return None
    for parameter in tuple(parameters or ()):
        key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
        if not key or not any(name in key for name in normalized_names):
            continue
        numeric_value = getattr(parameter, "numeric_value", None)
        if numeric_value is not None:
            try:
                return float(numeric_value)
            except (TypeError, ValueError, OverflowError):
                pass
        try:
            return float(str(getattr(parameter, "value", "") or ""))
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def _scene_parameter_color(parameters: Sequence[PreviewMaterialParameterInput], *names: str) -> tuple[float, float, float]:
    normalized_names = tuple(re.sub(r"[^a-z0-9]+", "", str(name or "").lower()) for name in names if str(name or "").strip())
    if not normalized_names:
        return ()
    for parameter in tuple(parameters or ()):
        key = re.sub(r"[^a-z0-9]+", "", str(getattr(parameter, "parameter_name", "") or "").lower())
        if not key or not any(name in key for name in normalized_names):
            continue
        color = tuple(getattr(parameter, "color_value", ()) or ())
        if len(color) >= 3:
            try:
                return tuple(max(0.0, min(2.0, float(value))) for value in color[:3])  # type: ignore[return-value]
            except (TypeError, ValueError, OverflowError):
                return ()
    return ()


def _apply_scene_material_parameters_to_submesh(
    submesh: SubMesh,
    parameters: Sequence[PreviewMaterialParameterInput],
) -> None:
    parameter_tuple = tuple(parameters or ())
    if parameter_tuple:
        existing = tuple(getattr(submesh, "preview_material_parameters", ()) or ())
        submesh.preview_material_parameters = tuple(existing + tuple(parameter for parameter in parameter_tuple if parameter not in existing))
    base_tint = _scene_parameter_color(parameter_tuple, "basecolorfactor") or _scene_parameter_color(parameter_tuple, "diffusefactor")
    if base_tint:
        submesh.preview_texture_tint = base_tint
    alpha_cutoff = _scene_parameter_numeric(parameter_tuple, "gltfalphacutoff")
    native_overrides = dict(getattr(submesh, "preview_native_material_overrides", {}) or {})
    if alpha_cutoff is not None:
        native_overrides["alpha_threshold"] = max(0.0, min(0.95, float(alpha_cutoff)))
    alpha_factor = _scene_parameter_numeric(parameter_tuple, "alphafactor", "opacityfactor")
    if alpha_factor is not None:
        alpha_value = max(0.0, min(1.0, float(alpha_factor)))
        if alpha_value < 0.999:
            submesh.preview_alpha_mode = "BLEND"
            submesh.preview_vertex_alpha_mean = alpha_value
            submesh.preview_vertex_alpha_min = alpha_value
    if _scene_parameter_numeric(parameter_tuple, "gltfunlit") is not None:
        native_overrides.setdefault("material_shader_family", "gltf_unlit")
        native_overrides.setdefault("roughness", 1.0)
        native_overrides.setdefault("specular", 0.0)
    roughness_factor = _scene_parameter_numeric(parameter_tuple, "roughnessfactor")
    if roughness_factor is not None:
        native_overrides.setdefault("roughness", max(0.0, min(1.0, float(roughness_factor))))
    glossiness_factor = _scene_parameter_numeric(parameter_tuple, "glossinessfactor")
    if glossiness_factor is not None:
        native_overrides.setdefault("roughness", max(0.0, min(1.0, 1.0 - float(glossiness_factor))))
    metallic_factor = _scene_parameter_numeric(parameter_tuple, "metallicfactor")
    if metallic_factor is not None:
        native_overrides.setdefault("metalness", max(0.0, min(1.0, float(metallic_factor))))
    specular_factor = _scene_parameter_numeric(parameter_tuple, "specularfactor")
    specular_color = _scene_parameter_color(parameter_tuple, "specularcolorfactor", "specularfactor")
    if specular_factor is not None or specular_color:
        specular_value = max(0.0, min(1.0, float(specular_factor))) if specular_factor is not None else 1.0
        if specular_color:
            specular_value *= max(0.0, min(1.0, (0.299 * specular_color[0]) + (0.587 * specular_color[1]) + (0.114 * specular_color[2])))
        native_overrides.setdefault("specular", max(0.0, min(1.0, specular_value)))
    clearcoat_factor = _scene_parameter_numeric(parameter_tuple, "clearcoatfactor")
    if clearcoat_factor is not None and clearcoat_factor > 0.0:
        native_overrides["specular"] = max(float(native_overrides.get("specular", 0.0) or 0.0), max(0.0, min(1.0, float(clearcoat_factor))))
    sheen_color = _scene_parameter_color(parameter_tuple, "sheencolorfactor")
    if sheen_color:
        sheen_luma = max(0.0, min(1.0, (0.299 * sheen_color[0]) + (0.587 * sheen_color[1]) + (0.114 * sheen_color[2])))
        native_overrides["specular"] = max(float(native_overrides.get("specular", 0.0) or 0.0), sheen_luma * 0.5)
    emissive_intensity = _scene_parameter_numeric(parameter_tuple, "emissiveintensity")
    emissive_color = _scene_parameter_color(parameter_tuple, "emissivecolor")
    if emissive_intensity is not None and emissive_intensity > 0.0:
        native_overrides["emissive_intensity"] = max(0.0, min(32.0, float(emissive_intensity)))
    if emissive_color:
        native_overrides["emissive_color"] = "#" + "".join(
            f"{max(0, min(255, int(round(component * 255)))):02x}"
            for component in emissive_color[:3]
        )
    if native_overrides:
        submesh.preview_native_material_overrides = native_overrides


def _apply_scene_material_slots_to_submesh(
    submesh: SubMesh,
    slots: Sequence[SceneMaterialTextureSlot],
    *,
    material_parameters: Sequence[PreviewMaterialParameterInput] = (),
    confidence: str = "scene",
) -> None:
    parameter_tuple = tuple(material_parameters or ())
    _apply_scene_material_parameters_to_submesh(submesh, parameter_tuple)
    normalized_slots = tuple(slot for slot in tuple(slots or ()) if isinstance(slot, SceneMaterialTextureSlot) and str(slot.path or "").strip())
    if not normalized_slots:
        return
    material_inputs: list[PreviewMaterialTextureInput] = []

    def add_input(slot: SceneMaterialTextureSlot) -> None:
        material_inputs.append(
            PreviewMaterialTextureInput(
                slot_kind=slot.slot_kind,
                parameter_name=slot.parameter_name,
                source_texture_path=slot.path,
                texture_name=Path(slot.path).name,
                preview_texture_path=slot.path,
                semantic_type=slot.semantic_type,
                semantic_subtype=slot.semantic_subtype,
                packed_channels=tuple(slot.packed_channels),
                material_name=str(submesh.material or submesh.name or "").strip(),
                shader_family=slot.shader_family,
                confidence=confidence,
                visualized=True,
                srgb_mode=slot.srgb_mode,
                blend_flags=tuple(
                    value
                    for value in (
                        f"texcoord:{slot.texcoord}" if slot.texcoord else "",
                        "texture_transform" if slot.transform else "",
                        f"source:{slot.source}" if slot.source else "",
                    )
                    if value
                ),
                material_parameters=tuple(parameter_tuple + tuple(slot.parameters or ())),
            )
        )

    for slot in normalized_slots:
        path_text = str(slot.path or "").strip()
        if not path_text:
            continue
        reference_text = str(getattr(slot, "reference_path", "") or "").strip() or path_text
        add_input(slot)
        slot_kind = str(slot.slot_kind or "").strip().lower()
        subtype = str(slot.semantic_subtype or "").strip().lower()
        if slot_kind == "base":
            submesh.texture = reference_text
            submesh.preview_texture_path = path_text
            submesh.preview_texture_name = Path(path_text).name
            if len(slot.transform) >= 5:
                offset_u, offset_v, scale_u, scale_v, rotation = slot.transform[:5]
                if abs(offset_u) <= 1e-6 and abs(offset_v) <= 1e-6 and abs(rotation) <= 1e-6:
                    submesh.preview_texture_uv_scale = (float(scale_u), float(scale_v))
        elif slot_kind == "normal" and subtype != "clearcoat_normal":
            submesh.preview_normal_texture_path = path_text
            submesh.preview_normal_texture_name = Path(path_text).name
            submesh.preview_normal_texture_strength = max(
                0.0,
                min(
                    2.0,
                    _scene_parameter_numeric(slot.parameters, "gltftexturescale", "normaltexturescale")
                    or float(getattr(submesh, "preview_normal_texture_strength", 0.0) or 0.75),
                ),
            )
        elif slot_kind == "height":
            submesh.preview_height_texture_path = path_text
            submesh.preview_height_texture_name = Path(path_text).name
    material_priority = {
        "metallic_roughness": 100,
        "specular_glossiness": 98,
        "roughness": 84,
        "glossiness": 83,
        "metallic": 82,
        "specular": 80,
        "ao": 76,
        "clearcoat": 62,
        "clearcoat_roughness": 61,
        "sheen": 58,
        "transmission": 40,
        "volume": 38,
        "anisotropy": 36,
        "iridescence": 34,
    }
    material_slot = max(
        (
            slot
            for slot in normalized_slots
            if str(slot.slot_kind or "").strip().lower() in {"material", "roughness", "metalness", "specular", "glossiness", "occlusion"}
        ),
        key=lambda slot: material_priority.get(str(slot.semantic_subtype or slot.slot_kind or "").strip().lower(), 0),
        default=None,
    )
    if material_slot is not None:
        submesh.preview_material_texture_path = material_slot.path
        submesh.preview_material_texture_name = Path(material_slot.path).name
        submesh.preview_material_texture_type = material_slot.semantic_type
        submesh.preview_material_texture_subtype = material_slot.semantic_subtype
        submesh.preview_material_texture_packed_channels = tuple(material_slot.packed_channels)
    if material_inputs:
        existing = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        merged: list[PreviewMaterialTextureInput] = []
        seen_inputs: set[tuple[str, str, str]] = set()
        for item in existing + tuple(material_inputs):
            key = (
                str(getattr(item, "slot_kind", "") or "").strip().lower(),
                str(getattr(item, "parameter_name", "") or "").strip().lower(),
                str(getattr(item, "preview_texture_path", "") or getattr(item, "source_texture_path", "") or "").replace("\\", "/").lower(),
            )
            if key in seen_inputs:
                continue
            seen_inputs.add(key)
            merged.append(item)
        submesh.preview_material_texture_inputs = tuple(merged)
    if any(str(slot.slot_kind or "").strip().lower() == "emissive" for slot in normalized_slots):
        submesh.preview_sidecar_shader_family = "SkinnedMeshEmissive_Ver2"
