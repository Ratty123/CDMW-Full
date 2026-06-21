"""Static mesh replacement submesh mapping and semantic role helpers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .mesh_parser import ParsedMesh, SubMesh
from .static_mesh_geometry import _bbox, _center, _dims, _is_marker_submesh
from .static_mesh_types import StaticMeshReplacementOptions, StaticMeshReplacementReport, StaticSubmeshMapping

_PART_HINTS: dict[str, tuple[str, ...]] = {
    "acc": ("acc", "accessory", "accent", "ornament", "spike", "trim", "detail", "circular", "circulares"),
    "accessory": ("acc", "accessory", "accent", "ornament", "spike", "trim", "detail", "circular", "circulares"),
    "armor": ("armor", "armour", "plate", "mail", "body", "chest", "torso"),
    "blade": ("blade", "edge", "body", "sword", "spike", "tip", "main", "cuchilla", "hoja"),
    "body": ("body", "main", "base", "core", "shell", "torso", "mesh"),
    "cape": ("cape", "cloth", "fabric", "cloak", "mantle"),
    "cloth": ("cloth", "fabric", "cape", "cloak", "skirt", "sleeve"),
    "edge": ("blade", "edge", "rim", "border", "trim", "borde"),
    "guard": ("guard", "crossguard", "handguard", "protector", "soporte"),
    "handle": ("handle", "hilt", "grip", "pommel", "shaft", "mango", "empunadura"),
    "helmet": ("helmet", "helm", "head", "mask", "face"),
    "hilt": ("handle", "hilt", "grip", "pommel"),
    "metal": ("metal", "steel", "iron", "armor", "plate", "trim"),
    "plate": ("plate", "armor", "armour", "metal", "shell"),
    "trim": ("trim", "edge", "accent", "acc", "border", "ornament"),
}

_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "borde": ("edge", "trim"),
    "bordecuadrado": ("edge", "trim"),
    "circular": ("acc", "detail"),
    "circulares": ("acc", "detail"),
    "cuchilla": ("blade",),
    "dtcirculares": ("acc", "detail"),
    "empunadura": ("handle", "hilt", "grip"),
    "hoja": ("blade",),
    "mango": ("handle", "hilt", "grip"),
    "punta": ("tip", "edge"),
    "soporte": ("guard", "support"),
    "soporteespada": ("guard", "support"),
}

_TOKEN_STOP_WORDS = {
    "cd",
    "phm",
    "pc",
    "sword",
    "weapon",
    "onehandweapon",
    "twohandweapon",
    "low",
    "high",
    "mesh",
    "mat",
    "material",
    "object",
    "cube",
    "default",
}

_SPECIAL_RUNTIME_SLOT_TOKENS = {
    "banner",
    "cape",
    "cloth",
    "cloak",
    "fabric",
    "flag",
    "flap",
    "mantle",
    "ribbon",
    "sash",
    "skirt",
    "sleeve",
    "tassel",
}

def suggest_static_submesh_mappings(
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
) -> list[StaticSubmeshMapping]:
    """Suggest source-to-target draw-section mappings using metadata and geometry.

    The first pass is intentionally generic: exact names/materials, token overlap,
    broad part aliases, relative position, and size similarity. Weapon-specific
    words are only one hint family among armor, cloth, trim, accessory, body, etc.
    """
    render_source_indices = [
        index
        for index, submesh in enumerate(replacement_mesh.submeshes)
        if not _is_marker_submesh(submesh)
    ]
    if not original_mesh.submeshes or not render_source_indices:
        return []
    if len(original_mesh.submeshes) == 1:
        return [
            StaticSubmeshMapping(
                target_submesh_index=0,
                target_submesh_name=original_mesh.submeshes[0].material or original_mesh.submeshes[0].name,
                source_submesh_indices=render_source_indices,
                target_material_slot_index=0,
                merge_sources=True,
            )
        ]

    spatial_cache = _StaticMappingSpatialCache()
    assignments: dict[int, list[int]] = {index: [] for index in range(len(original_mesh.submeshes))}
    for source_index in render_source_indices:
        source = replacement_mesh.submeshes[source_index]
        best_target, best_score = _best_target_match_for_source(
            source,
            original_mesh.submeshes,
            source_mesh=replacement_mesh,
            target_mesh=original_mesh,
            spatial_cache=spatial_cache,
        )
        assignments.setdefault(best_target, []).append(source_index)
    confidence_by_target_source: dict[tuple[int, int], float] = {}
    for target_index, source_indices in assignments.items():
        if target_index < 0 or target_index >= len(original_mesh.submeshes):
            continue
        target = original_mesh.submeshes[target_index]
        for source_index in source_indices:
            if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
                continue
            confidence_by_target_source[(target_index, source_index)] = _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )

    for target_index, target in enumerate(original_mesh.submeshes):
        if assignments.get(target_index):
            continue
        donor_index = max(assignments, key=lambda index: len(assignments.get(index, ())))
        donor_sources = assignments.get(donor_index, [])
        if len(donor_sources) <= 1:
            continue
        stolen_source = max(
            donor_sources,
            key=lambda source_index: _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            ),
        )
        donor_sources.remove(stolen_source)
        assignments[target_index] = [stolen_source]
        confidence_by_target_source[(target_index, stolen_source)] = _token_score(
            _name_text(replacement_mesh.submeshes[stolen_source]),
            _name_text(target),
            source_submesh=replacement_mesh.submeshes[stolen_source],
            target_submesh=target,
            source_mesh=replacement_mesh,
            target_mesh=original_mesh,
            spatial_cache=spatial_cache,
        )

    _rebalance_duplicate_material_assignments(
        assignments,
        confidence_by_target_source,
        original_mesh,
        replacement_mesh,
        spatial_cache=spatial_cache,
    )

    mappings: list[StaticSubmeshMapping] = []
    used_sources: set[int] = set()
    for target_index, target in enumerate(original_mesh.submeshes):
        source_indices = assignments.get(target_index, [])
        used_sources.update(source_indices)
        mappings.append(
            StaticSubmeshMapping(
                target_submesh_index=target_index,
                target_submesh_name=target.material or target.name,
                source_submesh_indices=source_indices,
                target_material_slot_index=target_index,
                merge_sources=True,
                confidence_score=_mapping_confidence_score(target_index, source_indices, confidence_by_target_source),
                confidence_label=_confidence_label(
                    _mapping_confidence_score(target_index, source_indices, confidence_by_target_source)
                ),
            )
        )

    unassigned = [
        index
        for index in render_source_indices
        if index not in used_sources
    ]
    if unassigned:
        largest_target = max(
            range(len(original_mesh.submeshes)),
            key=lambda index: len(original_mesh.submeshes[index].faces),
        )
        mappings[largest_target].source_submesh_indices.extend(unassigned)
        scores = [
            _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(original_mesh.submeshes[largest_target]),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=original_mesh.submeshes[largest_target],
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )
            for source_index in unassigned
        ]
        if scores:
            mappings[largest_target].confidence_score = min(mappings[largest_target].confidence_score or scores[0], *scores)
            mappings[largest_target].confidence_label = _confidence_label(mappings[largest_target].confidence_score)
    return mappings


def _rebalance_duplicate_material_assignments(
    assignments: dict[int, list[int]],
    confidence_by_target_source: dict[tuple[int, int], float],
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    *,
    spatial_cache: "_StaticMappingSpatialCache | None" = None,
) -> None:
    targets_by_material: dict[str, list[int]] = {}
    for target_index, target in enumerate(original_mesh.submeshes):
        key = re.sub(r"[^a-z0-9]+", "", str(target.material or target.name or "").lower())
        if not key:
            continue
        targets_by_material.setdefault(key, []).append(target_index)

    for target_indices in targets_by_material.values():
        if len(target_indices) < 2:
            continue
        source_indices: list[int] = []
        seen_sources: set[int] = set()
        for target_index in target_indices:
            for source_index in assignments.get(target_index, []):
                if source_index not in seen_sources:
                    seen_sources.add(source_index)
                    source_indices.append(source_index)
        if len(source_indices) < 2:
            continue

        representative_target = original_mesh.submeshes[target_indices[0]]
        source_indices.sort(
            key=lambda source_index: _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(representative_target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=representative_target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            ),
            reverse=True,
        )

        for target_index in target_indices:
            assignments[target_index] = []
        for ordinal, source_index in enumerate(source_indices):
            target_index = target_indices[min(ordinal, len(target_indices) - 1)]
            assignments.setdefault(target_index, []).append(source_index)
            target = original_mesh.submeshes[target_index]
            confidence_by_target_source[(target_index, source_index)] = _token_score(
                _name_text(replacement_mesh.submeshes[source_index]),
                _name_text(target),
                source_submesh=replacement_mesh.submeshes[source_index],
                target_submesh=target,
                source_mesh=replacement_mesh,
                target_mesh=original_mesh,
                spatial_cache=spatial_cache,
            )

def _append_special_runtime_slot_mapping_findings(
    report: StaticMeshReplacementReport,
    original_mesh: ParsedMesh,
    replacement_mesh: ParsedMesh,
    mappings: list[StaticSubmeshMapping],
    options: StaticMeshReplacementOptions,
) -> None:
    findings: list[str] = []
    for mapping in mappings:
        target_index = int(mapping.target_submesh_index)
        if target_index < 0 or target_index >= len(original_mesh.submeshes):
            continue
        target = original_mesh.submeshes[target_index]
        slot_tokens = _special_runtime_slot_tokens(target)
        if not slot_tokens:
            continue
        for source_index in mapping.source_submesh_indices:
            if source_index < 0 or source_index >= len(replacement_mesh.submeshes):
                continue
            source = replacement_mesh.submeshes[source_index]
            if _source_matches_special_runtime_slot(source):
                continue
            source_label = source.material or source.name or f"source {source_index}"
            target_label = target.material or target.name or f"target {target_index}"
            findings.append(f"{source_label} -> {target_label} ({', '.join(sorted(slot_tokens))})")
    if not findings:
        return
    message = (
        "Unsafe runtime draw-slot mapping: non-cloth/non-flag source geometry is routed into a special "
        f"cloth/flag-style target slot: {'; '.join(findings[:4])}. "
        "This can look correct in preview but deform or explode in game; route the source into Blade/Handle/Guard/Acc instead."
    )
    if bool(getattr(options, "complete_external_swap", False)) and not bool(
        getattr(options, "allow_unsafe_material_preflight_export", False)
    ):
        report.errors.append(message)
    else:
        report.warnings.append(message)

def _best_target_index_for_source(
    source: SubMesh,
    targets: list[SubMesh],
    *,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: "_StaticMappingSpatialCache | None" = None,
) -> int:
    best_index, _best_score = _best_target_match_for_source(
        source,
        targets,
        source_mesh=source_mesh,
        target_mesh=target_mesh,
        spatial_cache=spatial_cache,
    )
    return best_index


@dataclass
class _StaticMappingSpatialCache:
    mesh_bounds_by_id: dict[int, tuple[tuple[float, float, float], tuple[float, float, float]]] = field(default_factory=dict)
    submesh_center_by_id: dict[tuple[int, int], tuple[float, float, float] | None] = field(default_factory=dict)


def _best_target_match_for_source(
    source: SubMesh,
    targets: list[SubMesh],
    *,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> tuple[int, float]:
    source_text = _name_text(source)
    best_index = 0
    best_score = float("-inf")
    for target_index, target in enumerate(targets):
        target_text = _name_text(target)
        score = _token_score(
            source_text,
            target_text,
            source_submesh=source,
            target_submesh=target,
            source_mesh=source_mesh,
            target_mesh=target_mesh,
            spatial_cache=spatial_cache,
        )
        if score > best_score:
            best_score = score
            best_index = target_index
    return best_index, best_score


def _mapping_confidence_score(
    target_index: int,
    source_indices: list[int],
    confidence_by_target_source: dict[tuple[int, int], float],
) -> float:
    scores = [
        confidence_by_target_source.get((target_index, source_index), 0.0)
        for source_index in source_indices
    ]
    return min(scores) if scores else 0.0


def _confidence_label(score: float) -> str:
    if score >= 18.0:
        return "high"
    if score >= 10.0:
        return "medium"
    return "low"


def _name_text(submesh: SubMesh) -> str:
    return f"{submesh.name} {submesh.material} {submesh.texture}".replace("_", " ").replace(".", " ").lower()


def _special_runtime_slot_tokens(submesh: SubMesh) -> set[str]:
    return _semantic_tokens(_name_text(submesh)) & _SPECIAL_RUNTIME_SLOT_TOKENS


def _source_matches_special_runtime_slot(source: SubMesh) -> bool:
    return bool(_special_runtime_slot_tokens(source))


def _token_score(
    source_text: str,
    target_text: str,
    *,
    source_submesh: SubMesh | None = None,
    target_submesh: SubMesh | None = None,
    source_mesh: ParsedMesh | None = None,
    target_mesh: ParsedMesh | None = None,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> float:
    source_tokens = _semantic_tokens(source_text)
    target_tokens = _semantic_tokens(target_text)
    score = 0.0
    if (
        source_submesh is not None
        and target_submesh is not None
        and (target_tokens & _SPECIAL_RUNTIME_SLOT_TOKENS)
        and not _source_matches_special_runtime_slot(source_submesh)
    ):
        score -= 24.0
    if source_text.strip() and target_text.strip() and source_text.strip() == target_text.strip():
        score += 80.0
    if source_submesh is not None and target_submesh is not None:
        if _normalized_label(source_submesh.name) and _normalized_label(source_submesh.name) == _normalized_label(target_submesh.name):
            score += 60.0
        if _normalized_label(source_submesh.material) and _normalized_label(source_submesh.material) == _normalized_label(target_submesh.material):
            score += 70.0
    overlap = source_tokens & target_tokens
    score += float(len(overlap) * 8)
    if overlap:
        score += min(10.0, sum(len(token) for token in overlap) * 0.5)
    for target_token in target_tokens:
        hints = _PART_HINTS.get(target_token, ())
        if hints and any(hint in source_tokens or hint in source_text for hint in hints):
            score += 9.0
    for source_token in source_tokens:
        hints = _PART_HINTS.get(source_token, ())
        if hints and any(hint in target_tokens or hint in target_text for hint in hints):
            score += 5.0
    if source_submesh is not None and target_submesh is not None:
        score += _submesh_size_similarity_score(source_submesh, target_submesh)
    if source_submesh is not None and target_submesh is not None and source_mesh is not None and target_mesh is not None:
        score += _submesh_spatial_similarity_score(
            source_submesh,
            source_mesh,
            target_submesh,
            target_mesh,
            spatial_cache=spatial_cache,
        )
    return score


def _normalized_label(value: str) -> str:
    return " ".join(_semantic_tokens(value))


def infer_static_replacement_part_role(text: str) -> str:
    """Return a compact, human-facing role hint for replacement routing tables."""
    tokens = _semantic_tokens(text)

    def has_any(*needles: str) -> bool:
        return any(needle in tokens for needle in needles)

    if has_any("hand", "glove", "gauntlet", "forearm", "arm"):
        return "hand/arm"
    if has_any("head", "face", "eye", "eyes", "mouth", "jaw"):
        return "head/face"
    if has_any("hair", "beard", "moustache", "mustache"):
        return "hair"
    if has_any("foot", "feet", "boot", "boots", "shoe", "shoes", "leg"):
        return "foot/leg"
    if has_any("nude", "body", "torso", "chest", "upperbody", "lowerbody", "upper", "lower", "ub", "lb"):
        return "body"
    if has_any("helmet", "helm", "mask"):
        return "helmet"
    if has_any("cloth", "cape", "fabric", "cloak", "mantle", "skirt", "sleeve"):
        return "cloth"
    if has_any("armor", "armour", "plate", "mail"):
        return "armor/body"
    if has_any("blade", "edge", "tip", "sword", "cuchilla", "hoja"):
        return "blade"
    if has_any("handle", "hilt", "grip", "pommel", "shaft", "mango", "empunadura"):
        return "handle"
    if has_any("guard", "crossguard", "handguard", "protector", "soporte"):
        return "guard"
    if has_any("acc", "accessory", "detail", "trim", "spike", "ornament", "accent", "horn"):
        return "accessory/detail"
    return "unknown"


def _semantic_tokens(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())
    tokens: set[str] = set()
    for raw_token in normalized.split():
        token = raw_token.strip()
        if not token or token in _TOKEN_STOP_WORDS or token.isdigit():
            continue
        token = re.sub(r"\d+$", "", token)
        if len(token) <= 1 or token in _TOKEN_STOP_WORDS:
            continue
        tokens.add(token)
        for alias, expanded_tokens in _TOKEN_ALIASES.items():
            if alias in token:
                tokens.update(expanded_tokens)
    return tokens


def _submesh_size_similarity_score(source: SubMesh, target: SubMesh) -> float:
    source_faces = max(1, len(source.faces) or source.face_count)
    target_faces = max(1, len(target.faces) or target.face_count)
    face_ratio = min(source_faces, target_faces) / max(source_faces, target_faces)
    source_vertices = max(1, len(source.vertices) or source.vertex_count)
    target_vertices = max(1, len(target.vertices) or target.vertex_count)
    vertex_ratio = min(source_vertices, target_vertices) / max(source_vertices, target_vertices)
    return (face_ratio * 3.0) + (vertex_ratio * 2.0)


def _submesh_spatial_similarity_score(
    source: SubMesh,
    source_mesh: ParsedMesh,
    target: SubMesh,
    target_mesh: ParsedMesh,
    *,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> float:
    source_center = _normalized_submesh_center(source, source_mesh, spatial_cache=spatial_cache)
    target_center = _normalized_submesh_center(target, target_mesh, spatial_cache=spatial_cache)
    if source_center is None or target_center is None:
        return 0.0
    distance = math.sqrt(sum((source_center[index] - target_center[index]) ** 2 for index in range(3)))
    return max(0.0, 8.0 - distance * 10.0)


def _normalized_submesh_center(
    submesh: SubMesh,
    mesh: ParsedMesh,
    *,
    spatial_cache: _StaticMappingSpatialCache | None = None,
) -> tuple[float, float, float] | None:
    if not submesh.vertices:
        return None
    cache_key = (id(mesh), id(submesh))
    if spatial_cache is not None and cache_key in spatial_cache.submesh_center_by_id:
        return spatial_cache.submesh_center_by_id[cache_key]
    mesh_bounds_key = id(mesh)
    if spatial_cache is not None and mesh_bounds_key in spatial_cache.mesh_bounds_by_id:
        mesh_min, mesh_max = spatial_cache.mesh_bounds_by_id[mesh_bounds_key]
    else:
        mesh_vertices = [
            vertex
            for candidate in mesh.submeshes
            if not _is_marker_submesh(candidate)
            for vertex in candidate.vertices
        ]
        if not mesh_vertices:
            if spatial_cache is not None:
                spatial_cache.submesh_center_by_id[cache_key] = None
            return None
        mesh_min, mesh_max = _bbox(mesh_vertices)
        if spatial_cache is not None:
            spatial_cache.mesh_bounds_by_id[mesh_bounds_key] = (mesh_min, mesh_max)
    mesh_dims = _dims(mesh_min, mesh_max)
    submesh_min, submesh_max = _bbox(submesh.vertices)
    center = _center(submesh_min, submesh_max)
    normalized_center = tuple(
        0.5 if mesh_dims[index] <= 1e-8 else (center[index] - mesh_min[index]) / mesh_dims[index]
        for index in range(3)
    )
    if spatial_cache is not None:
        spatial_cache.submesh_center_by_id[cache_key] = normalized_center
    return normalized_center
