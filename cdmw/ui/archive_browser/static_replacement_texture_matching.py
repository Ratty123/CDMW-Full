"""Pure texture matching helpers for static replacement."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from cdmw.modding.static_mesh_replacer import _semantic_tokens


_IMPORTANT_STATIC_TEXTURE_TOKENS = {
    "acc",
    "accessory",
    "blade",
    "body",
    "cape",
    "cloth",
    "edge",
    "guard",
    "handle",
    "hand",
    "arm",
    "forearm",
    "head",
    "face",
    "hair",
    "foot",
    "feet",
    "leg",
    "boot",
    "nude",
    "helmet",
    "hilt",
    "plate",
    "spike",
    "trim",
}


def important_static_texture_tokens(value: str) -> set[str]:
    return _semantic_tokens(value) & _IMPORTANT_STATIC_TEXTURE_TOKENS


def part_specific_tokens(value: str) -> set[str]:
    tokens = _semantic_tokens(value)
    result: set[str] = set()
    if tokens & {"hand", "glove", "gauntlet", "arm", "forearm"}:
        result.add("hand")
    if tokens & {"head", "face", "eye", "mouth", "jaw"}:
        result.add("head")
    if tokens & {"hair", "beard"}:
        result.add("hair")
    if tokens & {"foot", "feet", "boot", "boots", "shoe", "leg"}:
        result.add("foot")
    if not result and tokens & {"body", "torso", "nude", "skin", "chest", "waist"}:
        result.add("body")
    return result


def binding_matches_target(binding: object, target_name: str) -> bool:
    target_key = str(target_name or "").strip().lower()
    for raw_candidate in (
        str(getattr(binding, "submesh_name", "") or ""),
        str(getattr(binding, "texture_path", "") or ""),
    ):
        candidate_key = raw_candidate.strip().lower()
        if target_key and candidate_key and (target_key in candidate_key or candidate_key in target_key):
            return True
    target_tokens = important_static_texture_tokens(target_name)
    path_tokens = important_static_texture_tokens(str(getattr(binding, "texture_path", "") or ""))
    submesh_tokens = important_static_texture_tokens(str(getattr(binding, "submesh_name", "") or ""))
    if path_tokens and target_tokens:
        return bool(path_tokens & target_tokens)
    if submesh_tokens and target_tokens:
        return bool(submesh_tokens & target_tokens)
    return False


def source_texture_evidence_by_local_path(source_texture_evidence: Sequence[object]) -> dict[str, list[Mapping[str, object]]]:
    evidence_by_path: dict[str, list[Mapping[str, object]]] = {}
    for evidence in tuple(source_texture_evidence or ()):
        if not isinstance(evidence, Mapping):
            continue
        local_path_text = str(evidence.get("local_path") or "").strip()
        if not local_path_text:
            continue
        try:
            local_key = str(Path(local_path_text).expanduser().resolve()).lower()
        except Exception:
            local_key = local_path_text.lower()
        evidence_by_path.setdefault(local_key, []).append(evidence)
    return evidence_by_path


def texture_file_lookup_maps(
    texture_files_for_mapping: Sequence[Path],
    evidence_by_local_path: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    normalize_texture_reference: Callable[[str], str],
) -> tuple[dict[str, Path], dict[str, Path]]:
    texture_files_by_basename: dict[str, Path] = {}
    texture_files_by_normalized_source_path: dict[str, Path] = {}
    for texture_file in tuple(texture_files_for_mapping or ()):
        texture_files_by_basename.setdefault(texture_file.name.lower(), texture_file)
        try:
            texture_key = str(texture_file.expanduser().resolve()).lower()
        except Exception:
            texture_key = str(texture_file).lower()
        for evidence in tuple(evidence_by_local_path.get(texture_key, ()) or ()):
            for evidence_key in ("archive_path", "texture_path", "resolved_archive_path"):
                normalized_evidence_path = normalize_texture_reference(str(evidence.get(evidence_key) or ""))
                if normalized_evidence_path:
                    texture_files_by_normalized_source_path.setdefault(normalized_evidence_path, texture_file)
    return texture_files_by_basename, texture_files_by_normalized_source_path


def best_source_for_slot(
    target_name: str,
    source_indices: Sequence[int],
    slot_kind: str,
    texture_sets_by_key: Mapping[str, object],
    *,
    parameter_name: str = "",
    target_texture_path: str = "",
    target_shader_family: str = "",
    texture_files_for_mapping: Sequence[Path],
    texture_files_by_basename: Mapping[str, Path],
    texture_files_by_normalized_source_path: Mapping[str, Path],
    source_texture_evidence_by_local_path_map: Mapping[str, Sequence[Mapping[str, object]]],
    replacement_mesh: object | None,
    classify_texture_binding: Callable[[str, str], object],
    normalize_texture_reference: Callable[[str], str],
    looks_like_standalone_pbr_source: Callable[[Path], bool],
) -> str:
    parameter_classification = classify_texture_binding(parameter_name, target_texture_path)
    parameter_subtype = str(getattr(parameter_classification, "semantic_subtype", "") or "").strip().lower()
    normalized_target_texture_path = normalize_texture_reference(target_texture_path)
    exact_source_path = texture_files_by_normalized_source_path.get(normalized_target_texture_path)
    if exact_source_path is None:
        exact_source_path = texture_files_by_basename.get(PurePosixPath(target_texture_path.replace("\\", "/")).name.lower())
    if exact_source_path is not None:
        return str(exact_source_path)
    if parameter_subtype == "emissive":
        best_emissive_path = ""
        best_emissive_score = 0.0
        target_tokens = _semantic_tokens(target_name)
        for texture_file in tuple(texture_files_for_mapping or ()):
            file_classification = classify_texture_binding("", texture_file.name)
            file_subtype = str(getattr(file_classification, "semantic_subtype", "") or "").strip().lower()
            file_tokens = _semantic_tokens(texture_file.stem)
            if file_subtype != "emissive" and not ({"emi", "emissive", "glow", "illum"} & file_tokens):
                continue
            score = 40.0 + float(len(target_tokens & file_tokens) * 8)
            if score > best_emissive_score:
                best_emissive_score = score
                best_emissive_path = str(texture_file)
        return best_emissive_path
    source_material_tokens: set[str] = set()
    candidates: list[Path] = []
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    for source_index in tuple(source_indices or ()):
        if source_index < 0 or source_index >= len(submeshes):
            continue
        source_submesh = submeshes[source_index]
        source_material_name = str(getattr(source_submesh, "material", "") or getattr(source_submesh, "name", "") or "").strip()
        source_material_tokens.update(_semantic_tokens(source_material_name))
        material_key = source_material_name.lower()
        texture_set = texture_sets_by_key.get(material_key)
        slot = getattr(texture_set, "slots", {}).get(slot_kind) if texture_set is not None else None
        source_path = getattr(slot, "source_path", None)
        if isinstance(source_path, Path):
            candidates.append(source_path)
    if len(candidates) == 1 and slot_kind in {"base", "normal", "height", "material_mask", "detail_mask"}:
        target_important = important_static_texture_tokens(target_name)
        candidate_important = important_static_texture_tokens(candidates[0].stem)
        target_specific = part_specific_tokens(f"{target_name} {target_texture_path}")
        candidate_specific = part_specific_tokens(candidates[0].stem)
        if target_specific and candidate_specific and not (target_specific & candidate_specific):
            return ""
        if (
            len(tuple(source_indices or ())) == 1
            or not target_important
            or not candidate_important
            or bool(target_important & candidate_important)
        ):
            return str(candidates[0])
    best_direct_path = ""
    best_direct_score = 0.0
    parameter_compact = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
    target_tokens = _semantic_tokens(target_name)
    target_important = important_static_texture_tokens(target_name)
    target_part_specific = part_specific_tokens(f"{target_name} {target_texture_path}")
    desired_terms = {
        token
        for token in (
            "base",
            "basecolor",
            "basecolour",
            "overlay",
            "diffuse",
            "albedo",
            "tint",
            "normal",
            "height",
            "displacement",
            "depth",
            "bump",
            "parallax",
            "material",
            "roughness",
            "gloss",
            "smoothness",
            "metallic",
            "specular",
            "opacity",
            "alpha",
            "ao",
            "occlusion",
            "emissive",
            "grime",
            "detail",
            "colorblending",
            "subsurface",
        )
        if token in parameter_compact
    }

    def source_sidecar_evidence_score(texture_file: Path, file_tokens: set[str], file_important: set[str]) -> float:
        try:
            evidence_key = str(texture_file.expanduser().resolve()).lower()
        except Exception:
            evidence_key = str(texture_file).lower()
        evidence_rows = source_texture_evidence_by_local_path_map.get(evidence_key, ())
        if not evidence_rows:
            return 0.0
        best_score = 0.0
        parameter_tokens = _semantic_tokens(parameter_name)
        target_path_tokens = _semantic_tokens(PurePosixPath(target_texture_path.replace("\\", "/")).stem)
        target_path_specific = part_specific_tokens(target_texture_path)
        target_shader_key = re.sub(r"[^a-z0-9]+", "", str(target_shader_family or "").lower())
        for evidence in evidence_rows:
            evidence_slot_kind = str(evidence.get("slot_kind") or "").strip().lower()
            evidence_subtype = str(evidence.get("semantic_subtype") or "").strip().lower()
            evidence_text = " ".join(
                str(evidence.get(key) or "")
                for key in (
                    "archive_path",
                    "texture_path",
                    "parameter_name",
                    "part_name",
                    "submesh_name",
                    "shader_family",
                    "material_profile_label",
                    "material_profile_part",
                    "material_profile_shader",
                    "material_profile_parameter",
                    "material_profile_flags",
                    "material_profile_colors",
                    "material_profile_floats",
                )
            )
            evidence_tokens = _semantic_tokens(evidence_text)
            evidence_important = important_static_texture_tokens(evidence_text)
            evidence_specific = part_specific_tokens(evidence_text)
            evidence_shader_key = re.sub(
                r"[^a-z0-9]+",
                "",
                str(evidence.get("material_profile_shader") or evidence.get("shader_family") or "").lower(),
            )
            evidence_parameter_key = re.sub(
                r"[^a-z0-9]+",
                "",
                str(evidence.get("material_profile_parameter") or evidence.get("parameter_name") or "").lower(),
            )
            score = 0.0
            required_specific = target_part_specific or target_path_specific
            if required_specific:
                if evidence_specific and not (required_specific & evidence_specific):
                    score -= 80.0
                elif not evidence_specific:
                    score -= 90.0
                elif required_specific & evidence_specific:
                    score += 48.0
            if evidence_slot_kind == slot_kind:
                score += 42.0
            elif evidence_slot_kind:
                score -= 34.0
            if target_shader_key and evidence_shader_key:
                if target_shader_key == evidence_shader_key:
                    score += 18.0
                elif "emissive" in target_shader_key and "emissive" not in evidence_shader_key:
                    score -= 14.0
            if parameter_compact and evidence_parameter_key == parameter_compact:
                score += 28.0
            if evidence_subtype and evidence_subtype == parameter_subtype:
                score += 18.0
            if target_important and evidence_important:
                overlap = target_important & evidence_important
                if overlap:
                    score += float(len(overlap) * 34)
                else:
                    score -= 12.0
            if target_tokens and evidence_tokens:
                score += float(len(target_tokens & evidence_tokens) * 8)
            if target_path_tokens and evidence_tokens:
                score += float(len(target_path_tokens & evidence_tokens) * 6)
            if parameter_tokens and evidence_tokens:
                score += float(len(parameter_tokens & evidence_tokens) * 6)
            if file_important and evidence_important:
                score += float(len(file_important & evidence_important) * 4)
            best_score = max(best_score, score)
        return best_score

    for texture_file in tuple(texture_files_for_mapping or ()):
        file_tokens = _semantic_tokens(texture_file.stem)
        file_important = important_static_texture_tokens(texture_file.stem)
        file_part_specific = part_specific_tokens(texture_file.stem)
        file_compact = re.sub(r"[^a-z0-9]+", "", texture_file.stem.lower())
        file_classification = classify_texture_binding("", texture_file.name)
        if slot_kind in {"base", "normal", "height", "material_mask", "detail_mask"} and file_classification.slot_kind != slot_kind:
            continue
        standalone_pbr = slot_kind in {"material", "material_mask", "detail_mask"} and looks_like_standalone_pbr_source(texture_file)
        if standalone_pbr:
            continue
        score = 0.0
        if target_part_specific:
            if file_part_specific and not (target_part_specific & file_part_specific):
                continue
            if not file_part_specific:
                score -= 60.0
            else:
                score += 42.0
        if file_classification.slot_kind == slot_kind:
            score += 30.0
        if file_classification.semantic_subtype == parameter_classification.semantic_subtype:
            score += 18.0
        if source_material_tokens and file_tokens:
            score += float(len(source_material_tokens & file_tokens) * 4)
        if target_important and file_important:
            important_overlap = target_important & file_important
            if important_overlap:
                score += float(len(important_overlap) * 28)
            else:
                score -= 18.0
        if target_tokens and file_tokens:
            score += float(len(target_tokens & file_tokens) * 8)
        for term in desired_terms:
            if term in file_compact:
                score += 10.0
        suffix_bonus = {
            "normal": ("_n", "_wn", "_nm", "_nrm", "_normal", "_normalmap"),
            "height": ("_h", "_d", "_dmap", "_disp", "_height", "_bump"),
            "base": ("_o", "_c", "_cd", "_col", "_color", "_base", "_basecolor", "_diffuse", "_albedo", "_em", "_emi", "_emissive"),
            "material": ("_m", "_ma", "_mg", "_sp", "_spec", "_orm", "_rma", "_mra", "_arm", "_ao", "_op", "_alpha", "_mask", "_gloss", "_gls", "_smooth", "_subsurface"),
        }.get(slot_kind, ())
        if texture_file.stem.lower().endswith(suffix_bonus):
            score += 12.0
        score += source_sidecar_evidence_score(texture_file, file_tokens, file_important)
        if score > best_direct_score:
            best_direct_score = score
            best_direct_path = str(texture_file)
    if best_direct_score >= 30.0:
        return best_direct_path
    if candidates:
        return str(candidates[0])
    best_path = ""
    best_score = 0.0
    for texture_set in texture_sets_by_key.values():
        slot = getattr(texture_set, "slots", {}).get(slot_kind)
        source_path = getattr(slot, "source_path", None)
        if not isinstance(source_path, Path):
            continue
        material_tokens = _semantic_tokens(str(getattr(texture_set, "material_name", "") or ""))
        score = float(len(target_tokens & material_tokens) * 10)
        if "blade" in target_tokens and "cuchilla" in material_tokens:
            score += 20.0
        if "handle" in target_tokens and "mango" in material_tokens:
            score += 20.0
        if score > best_score:
            best_score = score
            best_path = str(source_path)
    return best_path if best_score >= 10.0 else ""


__all__ = [
    "best_source_for_slot",
    "binding_matches_target",
    "important_static_texture_tokens",
    "part_specific_tokens",
    "source_texture_evidence_by_local_path",
    "texture_file_lookup_maps",
]
