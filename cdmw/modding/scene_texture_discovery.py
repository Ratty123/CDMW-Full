"""Texture discovery and local sidecar helpers for scene imports."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence
from urllib.parse import unquote

from cdmw.models import PreviewMaterialParameterInput

from .logging import get_logger
from .mesh_parser import ParsedMesh
from .scene_collada_import import _collada_image_paths
from .scene_geometry_utils import _dedupe_paths
from .scene_gltf_import import _gltf_material_info, _load_gltf_payload
from .scene_material_audit import (
    SceneMaterialTextureSlot,
    _apply_scene_material_slots_to_submesh,
    _scene_material_slot,
    _scene_preview_color_parameter,
    _scene_preview_float_parameter,
    _scene_preview_string_parameter,
    _scene_slot_semantics,
    _visible_texture_score,
)

logger = get_logger("core.scene_importer")

LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS = {".pac", ".pam", ".pamlod"}
SCENE_TEXTURE_SOURCE_EXTENSIONS = {".png", ".dds", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".webp"}
SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS = {".ktx", ".ktx2"}
SCENE_SIDECAR_SOURCE_EXTENSIONS = {
    ".xml",
    ".pami",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".app_xml",
    ".prefabdata_xml",
}
SCENE_COMPANION_SOURCE_EXTENSIONS = {
    ".prefab",
    ".meshinfo",
    ".material",
    ".paa_metabin",
}
_SCENE_TEXTURE_DISCOVERY_MAX_FILES = 5000
_SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES = 256


def _attach_fallback_texture_references(mesh: ParsedMesh, texture_files: Sequence[Path]) -> None:
    """Attach colocated texture-folder images to unreferenced scene submeshes when safe."""
    if not isinstance(mesh, ParsedMesh):
        return
    submeshes = [submesh for submesh in getattr(mesh, "submeshes", ()) or () if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)]
    if not submeshes:
        return
    if all(str(getattr(submesh, "texture", "") or "").strip() for submesh in submeshes):
        return
    visible_textures = sorted(
        (path for path in tuple(texture_files or ()) if isinstance(path, Path) and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS),
        key=lambda path: (_visible_texture_score(path), -len(path.name)),
        reverse=True,
    )
    visible_textures = [path for path in visible_textures if _visible_texture_score(path) > 0]
    if not visible_textures:
        return
    if len(visible_textures) == 1:
        texture_name = visible_textures[0].name
    else:
        best_score = _visible_texture_score(visible_textures[0])
        second_score = _visible_texture_score(visible_textures[1])
        if best_score < 80 or best_score <= second_score:
            return
        texture_name = visible_textures[0].name
    for submesh in submeshes:
        if not str(getattr(submesh, "texture", "") or "").strip():
            submesh.texture = texture_name


def _scene_texture_fallback_slot_kind(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    if any(token in stem for token in ("basecolor", "basecolour", "albedo", "diffuse", "diffusemap", "colormap")):
        return "base"
    if any(token in stem for token in ("normalmap", "normalgl", "normaldx", "normal", "nrm")):
        return "normal"
    if any(token in stem for token in ("heightmap", "height", "displacement", "disp", "depth", "bump")):
        return "height"
    if any(token in stem for token in ("emissive", "emission", "glow", "illumination", "illum")):
        return "emissive"
    if any(token in stem for token in ("specularglossiness", "specgloss", "speculargloss")):
        return "specular_glossiness"
    if "glossiness" in stem or "gloss" in stem:
        return "glossiness"
    if any(token in stem for token in ("metallicroughness", "roughnessmetallic", "metalrough", "metallicrough")):
        return "material"
    if "roughness" in stem or "rough" in stem:
        return "roughness"
    if any(token in stem for token in ("metallic", "metalness", "metal")):
        return "metalness"
    if any(token in stem for token in ("ambientocclusion", "occlusion", "mixedao")) or stem.endswith("ao"):
        return "occlusion"
    if "specular" in stem or stem.endswith("spec"):
        return "specular"
    if any(token in stem for token in ("opacity", "alpha", "transparent")):
        return "opacity"
    return ""


def _scene_texture_group_key(path: Path) -> str:
    stem = re.sub(r"[^a-z0-9]+", "", path.stem.lower())
    for token in (
        "metallicroughness",
        "roughnessmetallic",
        "occlusionroughnessmetallic",
        "specularglossiness",
        "basecolor",
        "basecolour",
        "diffusemap",
        "diffuse",
        "albedo",
        "colormap",
        "normalmap",
        "normalgl",
        "normaldx",
        "normal",
        "nrm",
        "heightmap",
        "height",
        "displacement",
        "disp",
        "depth",
        "ambientocclusion",
        "occlusion",
        "mixedao",
        "ao",
        "roughness",
        "rough",
        "metallic",
        "metalness",
        "metal",
        "glossiness",
        "gloss",
        "specular",
        "spec",
        "emissive",
        "emission",
        "glow",
        "illumination",
        "illum",
        "opacity",
        "alpha",
        "transparent",
        "base",
        "color",
        "colour",
    ):
        stem = stem.replace(token, "")
    return stem or re.sub(r"[^a-z0-9]+", "", path.stem.lower())


def _scene_texture_candidate_priority(path: Path) -> tuple[int, int]:
    suffix_priority = {
        ".png": 90,
        ".webp": 80,
        ".tga": 70,
        ".tif": 65,
        ".tiff": 65,
        ".dds": 60,
        ".bmp": 45,
        ".jpg": 35,
        ".jpeg": 35,
    }.get(path.suffix.lower(), 0)
    return (suffix_priority, -len(path.name))


def _resolve_scene_texture_path_reference(value: object, texture_files: Sequence[Path]) -> Optional[Path]:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_file():
        try:
            return candidate.resolve()
        except OSError:
            return candidate
    name = PurePosixPath(text).name.lower()
    stem = PurePosixPath(text).stem.lower()
    normalized = text.lower()
    for texture_path in tuple(texture_files or ()):
        try:
            resolved = texture_path.resolve()
        except OSError:
            resolved = texture_path
        path_text = resolved.as_posix().lower()
        if path_text == normalized or resolved.name.lower() == name or resolved.stem.lower() == stem:
            return resolved
    return None


def _attach_sibling_material_texture_slots(mesh: ParsedMesh, texture_files: Sequence[Path]) -> int:
    """Attach same-stem support maps when explicit material slots did not provide them."""
    if not isinstance(mesh, ParsedMesh):
        return 0
    candidate_files = list(texture_files or ())
    source_text = str(getattr(mesh, "path", "") or "").strip()
    source_path = Path(source_text) if source_text else None
    search_roots: list[Path] = []
    if source_path is not None:
        search_roots.extend([source_path.parent, source_path.parent / "textures", source_path.parent.parent / "textures"])
    for root in search_roots:
        if not root.is_dir():
            continue
        try:
            candidate_files.extend(
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
            )
        except OSError:
            continue
    candidate_files = _dedupe_paths([path for path in candidate_files if isinstance(path, Path)])
    texture_paths = tuple(
        path.resolve()
        for path in tuple(candidate_files or ())
        if isinstance(path, Path) and path.is_file() and path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
    )
    if not texture_paths:
        return 0
    grouped: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for texture_path in texture_paths:
        slot_kind = _scene_texture_fallback_slot_kind(texture_path)
        if not slot_kind:
            continue
        grouped[_scene_texture_group_key(texture_path)][slot_kind].append(texture_path)
    for group in grouped.values():
        for candidates in group.values():
            candidates.sort(key=_scene_texture_candidate_priority, reverse=True)

    attached = 0
    support_order = (
        "normal",
        "material",
        "occlusion",
        "roughness",
        "metalness",
        "specular_glossiness",
        "specular",
        "glossiness",
        "emissive",
        "height",
        "opacity",
    )
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        base_path = _resolve_scene_texture_path_reference(
            str(getattr(submesh, "preview_texture_path", "") or "") or str(getattr(submesh, "texture", "") or ""),
            texture_paths,
        )
        if base_path is None:
            continue
        base_path_text = base_path.as_posix()
        if not str(getattr(submesh, "preview_texture_path", "") or "").strip():
            submesh.preview_texture_path = base_path_text
            submesh.preview_texture_name = base_path.name
        if not str(getattr(submesh, "texture", "") or "").strip():
            submesh.texture = base_path_text
        sibling_group = grouped.get(_scene_texture_group_key(base_path), {})
        if not sibling_group:
            continue
        existing = tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ())
        existing_keys = {
            (
                str(getattr(item, "slot_kind", "") or "").strip().lower(),
                str(getattr(item, "semantic_subtype", "") or "").strip().lower(),
            )
            for item in existing
        }
        slots: list[SceneMaterialTextureSlot] = []
        for slot_kind in support_order:
            candidates = tuple(sibling_group.get(slot_kind, ()) or ())
            if not candidates:
                continue
            semantic_slot, _semantic_type, semantic_subtype, _channels = _scene_slot_semantics(slot_kind)
            if (semantic_slot, semantic_subtype) in existing_keys:
                continue
            if slot_kind == "normal" and str(getattr(submesh, "preview_normal_texture_path", "") or "").strip():
                continue
            if slot_kind == "height" and str(getattr(submesh, "preview_height_texture_path", "") or "").strip():
                continue
            if slot_kind in {"material", "roughness", "metalness", "specular_glossiness", "specular", "glossiness", "occlusion"}:
                material_subtype = str(getattr(submesh, "preview_material_texture_subtype", "") or "").strip().lower()
                if material_subtype and semantic_subtype == material_subtype:
                    continue
            slots.append(
                _scene_material_slot(
                    slot_kind,
                    candidates[0].as_posix(),
                    source="filename",
                )
            )
        if not slots:
            continue
        before_count = len(tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()))
        _apply_scene_material_slots_to_submesh(submesh, slots, confidence="filename")
        after_count = len(tuple(getattr(submesh, "preview_material_texture_inputs", ()) or ()))
        attached += max(0, after_count - before_count)
    return attached

def _obj_material_library_paths(obj_path: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()
    try:
        with obj_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or not line.lower().startswith("mtllib "):
                    continue
                for raw_value in line[7:].split():
                    candidate = (obj_path.parent / raw_value).expanduser().resolve()
                    key = str(candidate).lower()
                    if key not in seen:
                        seen.add(key)
                        candidates.append(candidate)
    except OSError:
        pass
    fallback = obj_path.with_suffix(".mtl").expanduser().resolve()
    if str(fallback).lower() not in seen:
        candidates.append(fallback)
    return tuple(candidates)


def _obj_material_texture_references(obj_path: Path) -> tuple[str, ...]:
    references: list[str] = []
    seen: set[str] = set()
    texture_keys = {
        "map_kd",
        "map_ka",
        "map_ks",
        "map_ke",
        "map_bump",
        "bump",
        "norm",
        "map_ns",
        "map_pr",
        "map_pm",
        "map_d",
        "map_tr",
        "disp",
        "map_pbr",
        "map_orm",
        "map_roughness",
        "map_metallic",
    }
    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 2 or parts[0].lower() not in texture_keys:
                        continue
                    reference = _obj_map_reference_from_parts(parts[1:])
                    if not reference:
                        continue
                    key = reference.replace("\\", "/").lower()
                    if reference and key not in seen:
                        seen.add(key)
                        references.append(reference)
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
    return tuple(references)


def _obj_map_reference_from_parts(parts: Sequence[str]) -> str:
    value_parts = list(parts)
    option_value_counts = {
        "-blendu": 1,
        "-blendv": 1,
        "-boost": 1,
        "-mm": 2,
        "-o": 3,
        "-s": 3,
        "-t": 3,
        "-texres": 1,
        "-clamp": 1,
        "-bm": 1,
        "-imfchan": 1,
        "-type": 1,
        "-cc": 1,
    }
    output: list[str] = []
    index = 0
    while index < len(value_parts):
        item = value_parts[index]
        if item.startswith("-"):
            skip = option_value_counts.get(item.lower(), 1)
            index += 1 + skip
            continue
        output.extend(value_parts[index:])
        break
    return " ".join(output).strip().strip('"')


def _obj_material_texture_slots(obj_path: Path) -> dict[str, tuple[SceneMaterialTextureSlot, ...]]:
    texture_kind_by_key = {
        "map_kd": "base",
        "map_ka": "base",
        "map_bump": "normal",
        "bump": "normal",
        "norm": "normal",
        "disp": "height",
        "map_ks": "specular",
        "map_ns": "glossiness",
        "map_pr": "roughness",
        "map_roughness": "roughness",
        "map_pm": "metalness",
        "map_metallic": "metalness",
        "map_ke": "emissive",
        "map_d": "opacity",
        "map_tr": "opacity",
        "map_orm": "material",
        "map_pbr": "material",
    }
    output: dict[str, list[SceneMaterialTextureSlot]] = {}
    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        current_material = ""
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) < 1:
                        continue
                    key = parts[0].lower()
                    if key == "newmtl":
                        current_material = " ".join(parts[1:]).strip()
                        continue
                    if not current_material or key not in texture_kind_by_key or len(parts) < 2:
                        continue
                    reference = _obj_map_reference_from_parts(parts[1:])
                    if not reference:
                        continue
                    resolved = _resolve_local_texture_reference(obj_path, reference)
                    if resolved is None:
                        continue
                    slot_kind = texture_kind_by_key[key]
                    output.setdefault(current_material, []).append(
                        _scene_material_slot(
                            slot_kind,
                            resolved.as_posix(),
                            parameter_name={
                                "map_kd": "_objMapKd",
                                "map_ka": "_objMapKa",
                                "map_bump": "_objMapBump",
                                "bump": "_objBump",
                                "norm": "_objNormal",
                                "disp": "_objDisplacement",
                                "map_ks": "_objMapKs",
                                "map_ns": "_objMapNs",
                                "map_pr": "_objMapPr",
                                "map_roughness": "_objMapRoughness",
                                "map_pm": "_objMapPm",
                                "map_metallic": "_objMapMetallic",
                                "map_ke": "_objMapKe",
                                "map_d": "_objMapD",
                                "map_tr": "_objMapTr",
                                "map_orm": "_objMapOrm",
                                "map_pbr": "_objMapPbr",
                            }.get(key, ""),
                            source="obj_mtl",
                            reference_path=reference,
                        )
                    )
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
            continue
    return {material: tuple(slots) for material, slots in output.items()}


def _obj_material_parameters(obj_path: Path) -> dict[str, tuple[PreviewMaterialParameterInput, ...]]:
    output: dict[str, list[PreviewMaterialParameterInput]] = {}

    def parse_float(parts: Sequence[str]) -> Optional[float]:
        if not parts:
            return None
        try:
            return float(parts[0])
        except (TypeError, ValueError, OverflowError):
            return None

    def parse_color(parts: Sequence[str]) -> tuple[float, float, float]:
        if len(parts) < 3:
            return ()
        try:
            return tuple(max(0.0, min(1.0, float(value))) for value in parts[:3])  # type: ignore[return-value]
        except (TypeError, ValueError, OverflowError):
            return ()

    def add_parameter(material: str, parameter: Optional[PreviewMaterialParameterInput]) -> None:
        if parameter is not None:
            output.setdefault(material, []).append(parameter)

    for material_path in _obj_material_library_paths(obj_path):
        if not material_path.is_file():
            continue
        current_material = ""
        try:
            with material_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    if not parts:
                        continue
                    key = parts[0].lower()
                    values = parts[1:]
                    if key == "newmtl":
                        current_material = " ".join(values).strip()
                        continue
                    if not current_material:
                        continue
                    if key == "kd":
                        add_parameter(current_material, _scene_preview_color_parameter("_diffuseFactor", parse_color(values)))
                    elif key == "ks":
                        add_parameter(current_material, _scene_preview_color_parameter("_specularColorFactor", parse_color(values)))
                    elif key == "ke":
                        color = parse_color(values)
                        add_parameter(current_material, _scene_preview_color_parameter("_emissiveColor", color))
                        if color and any(component > 0.003 for component in color):
                            add_parameter(current_material, _scene_preview_float_parameter("_emissiveIntensity", 1.0))
                    elif key == "ns":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_glossinessFactor", max(0.0, min(1.0, numeric / 1000.0))))
                    elif key in {"pr", "roughness"}:
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_roughnessFactor", max(0.0, min(1.0, numeric))))
                    elif key in {"pm", "metallic"}:
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_metallicFactor", max(0.0, min(1.0, numeric))))
                    elif key == "d":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_alphaFactor", max(0.0, min(1.0, numeric))))
                    elif key == "tr":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_alphaFactor", 1.0 - max(0.0, min(1.0, numeric))))
                    elif key == "ni":
                        numeric = parse_float(values)
                        if numeric is not None:
                            add_parameter(current_material, _scene_preview_float_parameter("_ior", max(0.0, numeric)))
                    elif key == "illum":
                        add_parameter(current_material, _scene_preview_string_parameter("_objIlluminationModel", " ".join(values)))
        except OSError as exc:
            logger.warning("Failed to read OBJ material library %s: %s", material_path, exc)
            continue
    return {material: tuple(parameters) for material, parameters in output.items()}


def _obj_material_texture_paths(obj_path: Path) -> list[Path]:
    discovered: list[Path] = []
    for reference in _obj_material_texture_references(obj_path):
        resolved = _resolve_local_texture_reference(obj_path, reference)
        if resolved is not None:
            discovered.append(resolved)
    return discovered


def discover_scene_texture_files(path: str | Path, mesh: Optional[ParsedMesh] = None) -> tuple[Path, ...]:
    scene_path = Path(path).expanduser().resolve()
    discovered: list[Path] = []
    if scene_path.suffix.lower() == ".obj":
        discovered.extend(_obj_material_texture_paths(scene_path))
    elif scene_path.suffix.lower() == ".dae":
        discovered.extend(_collada_image_paths(scene_path))
    elif scene_path.suffix.lower() in {".gltf", ".glb"}:
        try:
            payload = _load_gltf_payload(scene_path)
            _gltf_material_info(payload)
            discovered.extend(payload.discovered_texture_files)
            discovered.extend(payload.extracted_embedded_files)
        except Exception as exc:
            logger.warning("Failed to discover glTF texture files for %s: %s", scene_path, exc)
    elif scene_path.suffix.lower() in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        discovered.extend(
            path
            for path in discover_local_mesh_supplemental_files(scene_path, mesh)
            if path.suffix.lower() in SCENE_TEXTURE_SOURCE_EXTENSIONS
        )
    material_names = {
        str(submesh.material or submesh.name or "").strip().lower()
        for submesh in (mesh.submeshes if mesh is not None else [])
        if str(submesh.material or submesh.name or "").strip()
    }
    explicit_texture_references = {
        str(getattr(submesh, "texture", "") or "").strip()
        for submesh in (mesh.submeshes if mesh is not None else [])
        if str(getattr(submesh, "texture", "") or "").strip()
    }
    for texture_reference in explicit_texture_references:
        resolved_reference = _resolve_local_texture_reference(scene_path, texture_reference)
        if resolved_reference is not None:
            discovered.append(resolved_reference)
    discovered.extend(_discover_material_named_texture_files(scene_path, material_names))
    if not discovered or not explicit_texture_references:
        discovered.extend(_discover_nearby_scene_texture_files(scene_path))
    unique: dict[str, Path] = {}
    for candidate in discovered:
        if candidate.is_file():
            unique.setdefault(str(candidate.resolve()).lower(), candidate.resolve())
    return tuple(unique.values())


def discover_local_mesh_supplemental_files(path: str | Path, mesh: Optional[ParsedMesh] = None) -> tuple[Path, ...]:
    source_path = Path(path).expanduser().resolve()
    if source_path.suffix.lower() not in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        return ()
    discovered: list[Path] = []
    sidecars = _discover_local_mesh_sidecars(source_path)
    discovered.extend(sidecars)
    discovered.extend(_discover_local_mesh_companion_files(source_path))
    for texture_reference in _local_sidecar_texture_references(sidecars):
        texture_path = _resolve_local_texture_reference(source_path, texture_reference)
        if texture_path is not None:
            discovered.append(texture_path)
    if mesh is not None:
        material_names = {
            str(value or "").strip().lower()
            for submesh in mesh.submeshes
            for value in (submesh.texture, submesh.material, submesh.name)
            if str(value or "").strip()
        }
        discovered.extend(_discover_material_named_texture_files(source_path, material_names))
    return tuple(_dedupe_paths(discovered))


def _local_package_root(source_path: Path) -> Path:
    for parent in (source_path.parent, *source_path.parents):
        if parent.name.lower() == "files":
            return parent
    return source_path.parent


def _scene_texture_search_roots(scene_path: Path) -> list[Path]:
    candidates = [
        scene_path.parent,
        scene_path.parent / "textures",
        scene_path.parent / "texture",
        scene_path.parent.parent / "textures",
        scene_path.parent.parent / "texture",
    ]
    package_root = _local_package_root(scene_path)
    if package_root != scene_path.parent:
        candidates.extend([package_root, package_root / "textures", package_root / "texture"])
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _discover_material_named_texture_files(scene_path: Path, material_names: set[str]) -> list[Path]:
    names = {name for name in material_names if name}
    if not names:
        return []
    discovered: list[Path] = []
    scanned_files = 0
    search_limited = False
    for root in _scene_texture_search_roots(scene_path):
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            scanned_files += 1
            if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                search_limited = True
                break
            if not candidate.is_file() or candidate.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                continue
            stem = candidate.stem.lower()
            if any(stem.startswith(material_name) or material_name in stem for material_name in names):
                discovered.append(candidate)
        if search_limited:
            break
    if search_limited:
        logger.info(
            "Stopped scene texture discovery for %s after scanning %d filesystem entries. "
            "Add additional textures through Supplemental Files if needed.",
            scene_path,
            _SCENE_TEXTURE_DISCOVERY_MAX_FILES,
        )
    return discovered


def _nearby_scene_texture_roots(scene_path: Path) -> list[Path]:
    candidates = [
        scene_path.parent / "textures",
        scene_path.parent / "texture",
        scene_path.parent,
        scene_path.parent.parent / "textures",
        scene_path.parent.parent / "texture",
    ]
    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _discover_nearby_scene_texture_files(scene_path: Path) -> list[Path]:
    """Find likely colocated source textures when OBJ/scene material names are incomplete."""
    discovered: list[Path] = []
    seen: set[str] = set()
    scanned_files = 0
    search_limited = False
    for root in _nearby_scene_texture_roots(scene_path):
        if not root.is_dir():
            continue
        try:
            for candidate in root.rglob("*"):
                scanned_files += 1
                if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                    search_limited = True
                    break
                if not candidate.is_file() or candidate.suffix.lower() not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
                    continue
                try:
                    resolved = candidate.expanduser().resolve()
                except Exception:
                    continue
                key = str(resolved).lower()
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(resolved)
                if len(discovered) >= _SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES:
                    search_limited = True
                    break
        except OSError:
            continue
        if search_limited:
            break
    if search_limited:
        logger.info(
            "Stopped fallback scene texture discovery for %s after %d filesystem entries or %d texture files. "
            "Add additional textures through Supplemental Files if needed.",
            scene_path,
            scanned_files,
            _SCENE_TEXTURE_DISCOVERY_FALLBACK_MAX_TEXTURES,
        )
    return discovered


def _discover_local_mesh_sidecars(source_path: Path) -> tuple[Path, ...]:
    suffix = source_path.suffix.lower()
    direct_candidates = [
        source_path.with_suffix(f"{suffix}_xml"),
        source_path.with_name(f"{source_path.name}.xml"),
        source_path.with_suffix(".xml"),
    ]
    if suffix in {".pam", ".pamlod"}:
        direct_candidates.append(source_path.with_suffix(".pami"))

    discovered: list[Path] = []
    for candidate in direct_candidates:
        if candidate.is_file() and candidate.suffix.lower() in SCENE_SIDECAR_SOURCE_EXTENSIONS:
            discovered.append(candidate)

    stem_key = source_path.stem.lower()
    try:
        for candidate in source_path.parent.iterdir():
            if not candidate.is_file() or candidate.suffix.lower() not in SCENE_SIDECAR_SOURCE_EXTENSIONS:
                continue
            candidate_name = candidate.name.lower()
            candidate_stem = candidate.stem.lower()
            if candidate_stem.startswith(stem_key) or candidate_name.startswith(f"{stem_key}{suffix}"):
                discovered.append(candidate)
    except OSError:
        pass
    return tuple(_dedupe_paths(discovered))


def _discover_local_mesh_companion_files(source_path: Path) -> tuple[Path, ...]:
    """Find non-texture Crimson companion files that may affect a complete swap."""
    if source_path.suffix.lower() not in LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS:
        return ()
    stem_key = source_path.stem.lower()
    discovered: list[Path] = []
    for extension in SCENE_COMPANION_SOURCE_EXTENSIONS:
        candidate = source_path.with_suffix(extension)
        if candidate.is_file():
            discovered.append(candidate)

    search_roots = [source_path.parent]
    package_root = _local_package_root(source_path)
    if package_root != source_path.parent:
        search_roots.append(package_root)
    seen_roots: set[str] = set()
    scanned = 0
    for root in search_roots:
        if not root.is_dir():
            continue
        root_key = str(root).lower()
        if root_key in seen_roots:
            continue
        seen_roots.add(root_key)
        try:
            iterator = root.rglob("*") if root == package_root else root.iterdir()
            for candidate in iterator:
                scanned += 1
                if scanned > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                    logger.info(
                        "Stopped local Crimson companion discovery for %s after scanning %d filesystem entries.",
                        source_path,
                        _SCENE_TEXTURE_DISCOVERY_MAX_FILES,
                    )
                    return tuple(_dedupe_paths(discovered))
                if not candidate.is_file() or candidate.suffix.lower() not in SCENE_COMPANION_SOURCE_EXTENSIONS:
                    continue
                if candidate.stem.lower().startswith(stem_key):
                    discovered.append(candidate)
        except OSError:
            continue
    return tuple(_dedupe_paths(discovered))


def _local_sidecar_texture_references(sidecar_paths: Sequence[Path]) -> tuple[str, ...]:
    try:
        from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings
    except Exception:
        return ()

    references: list[str] = []
    seen: set[str] = set()
    for sidecar_path in sidecar_paths:
        try:
            sidecar_text = _read_local_sidecar_text(sidecar_path)
        except Exception:
            continue
        try:
            bindings = parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path.name)
        except Exception:
            bindings = ()
        for binding in bindings:
            texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            if not texture_path:
                continue
            key = texture_path.lower()
            if key in seen:
                continue
            seen.add(key)
            references.append(texture_path)
    return tuple(references)


def _read_local_sidecar_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "utf-8", "cp1252"):
        try:
            return data.decode(encoding).replace("\ufeff", "")
        except UnicodeError:
            continue
    return data.decode("utf-8", errors="replace").replace("\ufeff", "")


def _find_first_local_file_by_basename(root: Path, basename: str) -> Optional[Path]:
    if not root.is_dir() or not basename:
        return None
    scanned_files = 0
    lowered_basename = basename.lower()
    try:
        for candidate in root.rglob("*"):
            scanned_files += 1
            if scanned_files > _SCENE_TEXTURE_DISCOVERY_MAX_FILES:
                break
            if candidate.is_file() and candidate.name.lower() == lowered_basename:
                return candidate.resolve()
    except OSError:
        return None
    return None


def _resolve_local_texture_reference(source_path: Path, texture_reference: str) -> Optional[Path]:
    normalized_reference = unquote(str(texture_reference or "").replace("\\", "/")).strip().strip("/")
    if not normalized_reference:
        return None
    reference_suffix = PurePosixPath(normalized_reference).suffix.lower()
    if reference_suffix not in SCENE_TEXTURE_SOURCE_EXTENSIONS:
        return None

    direct_candidate = Path(normalized_reference).expanduser()
    if direct_candidate.is_absolute() and direct_candidate.is_file():
        return direct_candidate.resolve()

    package_root = _local_package_root(source_path)
    reference_parts = PurePosixPath(normalized_reference).parts
    basename = PurePosixPath(normalized_reference).name
    candidates: list[Path] = []
    if reference_parts:
        candidates.append(source_path.parent.joinpath(*reference_parts))
        candidates.append(package_root.joinpath(*reference_parts))
        collapsed_parts = tuple(part for part in reference_parts if part.lower() not in {"texture", "textures"})
        if collapsed_parts and collapsed_parts != reference_parts:
            candidates.append(package_root.joinpath(*collapsed_parts))
    if basename:
        candidates.extend(
            [
                source_path.parent / basename,
                source_path.parent / "texture" / basename,
                source_path.parent / "textures" / basename,
            ]
        )
        if reference_parts:
            candidates.append(package_root / reference_parts[0] / basename)

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved

    for root in (source_path.parent, package_root):
        found = _find_first_local_file_by_basename(root, basename)
    if found is not None:
        return found
    return None

__all__ = [
    "LOCAL_ARCHIVE_MESH_IMPORT_EXTENSIONS",
    "SCENE_COMPANION_SOURCE_EXTENSIONS",
    "SCENE_SIDECAR_SOURCE_EXTENSIONS",
    "SCENE_TEXTURE_DIAGNOSTIC_ONLY_EXTENSIONS",
    "SCENE_TEXTURE_SOURCE_EXTENSIONS",
    "_attach_fallback_texture_references",
    "_attach_sibling_material_texture_slots",
    "_discover_local_mesh_companion_files",
    "_discover_local_mesh_sidecars",
    "_discover_material_named_texture_files",
    "_discover_nearby_scene_texture_files",
    "_find_first_local_file_by_basename",
    "_local_package_root",
    "_local_sidecar_texture_references",
    "_nearby_scene_texture_roots",
    "_obj_map_reference_from_parts",
    "_obj_material_library_paths",
    "_obj_material_parameters",
    "_obj_material_texture_paths",
    "_obj_material_texture_references",
    "_obj_material_texture_slots",
    "_read_local_sidecar_text",
    "_resolve_local_texture_reference",
    "_resolve_scene_texture_path_reference",
    "_scene_texture_candidate_priority",
    "_scene_texture_fallback_slot_kind",
    "_scene_texture_group_key",
    "_scene_texture_search_roots",
    "discover_local_mesh_supplemental_files",
    "discover_scene_texture_files",
]
