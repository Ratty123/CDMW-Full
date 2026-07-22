from __future__ import annotations

import hashlib
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_model_references import _find_archive_model_sidecar_entries
from cdmw.core.upscale_profiles import MaterialSidecarProfile, parse_material_sidecar_profile
from cdmw.domain.pac_xml_editor import decode_pac_xml_payload
from cdmw.models import ArchiveEntry
from tools.mesh_harness.real_common import _archive_key, _read_archive_payload


VISUAL_AUDIT_V2_CATEGORY_COUNTS: Mapping[str, int] = {
    "weapon_sword": 24,
    "weapon_other": 16,
    "weapon_shield": 12,
    "armor_body": 24,
    "helmet_mask": 16,
    "equipment_small": 12,
    "equipment_soft": 8,
    "regression_control": 8,
}

VISUAL_AUDIT_V2_GRAPH_MINIMUMS: Mapping[str, int] = {
    "layered_dye_grime_graph": 30,
    "mixed_hard_soft_candidate": 20,
    "true_metal_control_candidate": 20,
    "soft_control_candidate": 20,
}

VISUAL_AUDIT_V2_EXPANSION_RULES_VERSION = "coverage-aware-pac-graph-v1"

REQUIRED_SWORD_PATH = (
    "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
    "cd_phm_02_sword_0014.pac"
)
PRIOR_CONCERN_SWORD_PATH = (
    "character/model/1_pc/1_phm/weapon/1_onehandweapon/"
    "cd_phm_01_sword_0059.pac"
)


@dataclass(frozen=True, slots=True)
class VisualAuditV2Candidate:
    virtual_path: str
    category: str
    graph_complexity: int
    graph_tags: tuple[str, ...]
    pac_xml_virtual_path: str = ""
    pac_xml_sha256: str = ""
    wrapper_count: int = 0
    parameter_count: int = 0
    texture_parameter_count: int = 0
    shader_families: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _VisualAuditV2GraphField:
    parameter_name: str
    value: str
    shader_name: str
    group_label: str


def build_visual_audit_v2_candidates(game_root: Path) -> tuple[VisualAuditV2Candidate, ...]:
    _pamt_path, resolved = _visual_audit_v2_candidate_sources(game_root)
    unique_sidecars = {
        _sidecar_identity(sidecar): sidecar
        for _path, _category, sidecar, _sidecar_path in resolved
        if sidecar is not None
    }
    with ThreadPoolExecutor(max_workers=min(16, max(1, len(unique_sidecars)))) as pool:
        metadata_rows = pool.map(_sidecar_graph_metadata, unique_sidecars.values())
        metadata_by_identity = dict(zip(unique_sidecars, metadata_rows))
    candidates = [
        _candidate_from_metadata(
            virtual_path,
            category,
            sidecar_path=sidecar_path,
            metadata=(
                metadata_by_identity.get(_sidecar_identity(sidecar))
                if sidecar is not None
                else None
            ),
        )
        for virtual_path, category, sidecar, sidecar_path in resolved
    ]
    return tuple(candidates)


def visual_audit_v2_archive_paths(game_root: Path) -> tuple[Path, ...]:
    pamt_path, resolved = _visual_audit_v2_candidate_sources(game_root)
    paths = {
        pamt_path,
        *(
            Path(sidecar.paz_file).resolve()
            for _path, _category, sidecar, _sidecar_path in resolved
            if sidecar is not None
        ),
    }
    return tuple(sorted(paths, key=lambda path: str(path).casefold()))


def _visual_audit_v2_candidate_sources(
    game_root: Path,
) -> tuple[Path, tuple[tuple[str, str, ArchiveEntry | None, str], ...]]:
    pamt_path = Path(game_root).resolve() / "0009" / "0.pamt"
    entries = parse_archive_pamt(pamt_path)
    entries_by_basename: dict[str, list[ArchiveEntry]] = {}
    pac_entries: list[ArchiveEntry] = []
    for entry in entries:
        key = _archive_key(entry.path)
        entries_by_basename.setdefault(key.rsplit("/", 1)[-1], []).append(entry)
        if str(entry.extension or "").casefold() == ".pac":
            pac_entries.append(entry)
    basename_index = {key: tuple(values) for key, values in entries_by_basename.items()}

    resolved: list[tuple[str, str, ArchiveEntry | None, str]] = []
    for entry in pac_entries:
        virtual_path = str(entry.path or "").replace("\\", "/")
        category = classify_visual_audit_v2_path(virtual_path)
        if not category:
            continue
        sidecar_entries = _find_archive_model_sidecar_entries(
            entry,
            basename_index,
        )
        sidecar_entry = sidecar_entries[0] if sidecar_entries else None
        sidecar_path = str(getattr(sidecar_entry, "path", "") or "")
        resolved.append((virtual_path, category, sidecar_entry, sidecar_path))
    return pamt_path, tuple(resolved)


def select_visual_audit_v2_candidates(
    candidates: Sequence[VisualAuditV2Candidate],
    *,
    priority_paths: Iterable[str] = (REQUIRED_SWORD_PATH, PRIOR_CONCERN_SWORD_PATH),
    excluded_paths: Iterable[str] = (),
    allowed_repeat_paths: Iterable[str] = (),
    selection_seed: str | None = None,
) -> tuple[VisualAuditV2Candidate, ...]:
    ordered_candidates = tuple(sorted(candidates, key=_candidate_identity_key))
    candidates_by_path: dict[str, VisualAuditV2Candidate] = {}
    for candidate in ordered_candidates:
        normalized_path = normalize_visual_audit_virtual_path(candidate.virtual_path)
        existing = candidates_by_path.get(normalized_path)
        if existing is not None and existing != candidate:
            raise ValueError(
                "Visual-audit candidate metadata is ambiguous for normalized PAC path: "
                f"{normalized_path}"
            )
        candidates_by_path[normalized_path] = candidate

    normalized_exclusions = {
        normalize_visual_audit_virtual_path(path)
        for path in excluded_paths
        if str(path or "").strip()
    }
    normalized_repeats = {
        normalize_visual_audit_virtual_path(path)
        for path in allowed_repeat_paths
        if str(path or "").strip()
    }
    effective_exclusions = normalized_exclusions - normalized_repeats
    eligible_candidates = tuple(
        candidate
        for normalized_path, candidate in candidates_by_path.items()
        if normalized_path not in effective_exclusions
    )
    candidate_sort_key = _candidate_sort_key
    if selection_seed is not None:
        candidate_sort_key = _expansion_candidate_sort_key(
            eligible_candidates,
            selection_seed=selection_seed,
        )

    by_category: dict[str, list[VisualAuditV2Candidate]] = {
        category: [] for category in VISUAL_AUDIT_V2_CATEGORY_COUNTS
    }
    for candidate in eligible_candidates:
        if candidate.category in by_category:
            by_category[candidate.category].append(candidate)
    for rows in by_category.values():
        rows.sort(key=candidate_sort_key)

    normalized_priorities = tuple(
        normalize_visual_audit_virtual_path(path) for path in priority_paths
    )
    selected: list[VisualAuditV2Candidate] = []
    selected_paths: set[str] = set()
    for priority in normalized_priorities:
        match = next(
            (
                candidate
                for candidate in eligible_candidates
                if normalize_visual_audit_virtual_path(candidate.virtual_path) == priority
            ),
            None,
        )
        if match is None:
            if priority in effective_exclusions:
                raise ValueError(
                    "Required visual-audit PAC is excluded without repeat permission: "
                    f"{priority}"
                )
            raise ValueError(f"Required visual-audit PAC is unavailable: {priority}")
        selected.append(match)
        selected_paths.add(priority)

    for category, required_count in VISUAL_AUDIT_V2_CATEGORY_COUNTS.items():
        current = sum(candidate.category == category for candidate in selected)
        available = [
            candidate
            for candidate in by_category[category]
            if normalize_visual_audit_virtual_path(candidate.virtual_path) not in selected_paths
        ]
        if current + len(available) < required_count:
            raise ValueError(
                f"Visual-audit v2 category {category} requires {required_count} PACs; "
                f"only {current + len(available)} are available."
            )
        for candidate in available[: required_count - current]:
            selected.append(candidate)
            selected_paths.add(normalize_visual_audit_virtual_path(candidate.virtual_path))

    selected = _improve_graph_constraint_coverage(
        selected,
        by_category,
        selected_paths,
        protected_paths=set(normalized_priorities),
    )
    selected.sort(
        key=lambda candidate: (
            tuple(VISUAL_AUDIT_V2_CATEGORY_COUNTS).index(candidate.category),
            candidate_sort_key(candidate),
        )
    )
    unexpected_overlap = sorted(
        {
            normalize_visual_audit_virtual_path(candidate.virtual_path)
            for candidate in selected
        }
        & normalized_exclusions
        - normalized_repeats
    )
    if unexpected_overlap:
        raise ValueError(
            f"Visual-audit v2 selection reuses excluded PAC paths: {unexpected_overlap}"
        )
    validate_visual_audit_v2_selection(selected)
    return tuple(selected)


def validate_visual_audit_v2_selection(
    candidates: Sequence[VisualAuditV2Candidate],
) -> dict[str, object]:
    if len(candidates) != sum(VISUAL_AUDIT_V2_CATEGORY_COUNTS.values()):
        raise ValueError(f"Visual-audit v2 requires exactly 120 PACs; found {len(candidates)}.")
    paths = [_archive_key(candidate.virtual_path) for candidate in candidates]
    if len(set(paths)) != len(paths):
        raise ValueError("Visual-audit v2 PAC paths must be unique.")
    if _archive_key(REQUIRED_SWORD_PATH) not in paths:
        raise ValueError("Visual-audit v2 must include cd_phm_02_sword_0014.pac.")
    if _archive_key(PRIOR_CONCERN_SWORD_PATH) not in paths:
        raise ValueError("Visual-audit v2 must retain the prior in-scope concern sword.")
    category_counts = Counter(candidate.category for candidate in candidates)
    category_short = {
        key: (category_counts[key], expected)
        for key, expected in VISUAL_AUDIT_V2_CATEGORY_COUNTS.items()
        if category_counts[key] != expected
    }
    if category_short:
        raise ValueError(f"Visual-audit v2 category counts are invalid: {category_short}")
    graph_counts = {
        tag: sum(tag in candidate.graph_tags for candidate in candidates)
        for tag in VISUAL_AUDIT_V2_GRAPH_MINIMUMS
    }
    graph_short = {
        key: (graph_counts[key], minimum)
        for key, minimum in VISUAL_AUDIT_V2_GRAPH_MINIMUMS.items()
        if graph_counts[key] < minimum
    }
    if graph_short:
        raise ValueError(f"Visual-audit v2 graph coverage is incomplete: {graph_short}")
    return {
        "asset_count": len(candidates),
        "category_counts": dict(category_counts),
        "graph_coverage": graph_counts,
    }


def normalize_visual_audit_virtual_path(virtual_path: str) -> str:
    return _archive_key(str(virtual_path or "").strip())


def classify_visual_audit_v2_path(virtual_path: str) -> str:
    path = _archive_key(virtual_path)
    name = path.rsplit("/", 1)[-1]
    if not path.endswith(".pac") or "/character/model/" not in f"/{path}":
        return ""
    if "_sword_" in name:
        return "weapon_sword"
    if "_shield_" in name or "/3_shield/" in path:
        return "weapon_shield"
    if "/weapon/" in path:
        return "weapon_other"
    if _contains_any(path, ("/13_hel/", "/helmet/", "/head/mask/")) or _token(name, "hel") or _token(name, "helmet") or _token(name, "mask"):
        return "helmet_mask"
    if _contains_any(path, ("/11_hand/", "/12_foot/")) or any(
        _token(name, token) for token in ("belt", "boot", "foot", "glove", "hand", "gauntlet", "greave")
    ):
        return "equipment_small"
    if any(_token(name, token) for token in ("cloak", "cape", "vest", "mantle", "scarf")):
        return "equipment_soft"
    if "/armor/" in path and (
        _contains_any(path, ("/9_upperbody/", "/10_lowerbody/"))
        or _token(name, "ub")
        or _token(name, "lb")
        or _token(name, "upperbody")
        or _token(name, "lowerbody")
    ):
        return "armor_body"
    if (
        "/nude/" in path
        or "/hair/" in path
        or _token(name, "hair")
        or _token(name, "glasses")
        or "glass" in name
    ):
        return "regression_control"
    return ""


def _sidecar_graph_metadata(sidecar_entry: ArchiveEntry) -> dict[str, object] | None:
    try:
        payload = _read_archive_payload(sidecar_entry)
        sidecar_text, _source_format = decode_pac_xml_payload(payload)
        profile = parse_material_sidecar_profile(
            sidecar_text,
            sidecar_path=str(sidecar_entry.path or ""),
        )
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError):
        return None
    if not profile.materials:
        return None
    fields = _material_profile_graph_fields(profile)
    return {
        "fields": fields,
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "wrapper_count": len(profile.materials),
        "parameter_count": len(fields),
        "texture_parameter_count": profile.texture_count,
    }


def _material_profile_graph_fields(
    profile: MaterialSidecarProfile,
) -> tuple[_VisualAuditV2GraphField, ...]:
    fields: list[_VisualAuditV2GraphField] = []
    for material in profile.materials:
        parameters = (
            *material.texture_parameters,
            *material.color_parameters,
            *material.float_parameters,
            *material.flag_parameters,
            *material.byte4_parameters,
        )
        fields.extend(
            _VisualAuditV2GraphField(
                parameter_name=parameter.parameter_name,
                value=parameter.texture_path or parameter.value,
                shader_name=material.shader_family,
                group_label=material.part_name,
            )
            for parameter in parameters
        )
    return tuple(fields)


def _candidate_from_metadata(
    virtual_path: str,
    category: str,
    *,
    sidecar_path: str,
    metadata: Mapping[str, object] | None,
) -> VisualAuditV2Candidate:
    if metadata is None:
        tags = _path_fallback_tags(virtual_path, category)
        return VisualAuditV2Candidate(virtual_path, category, 0, tags)
    fields = tuple(metadata.get("fields", ()) or ())
    tags = _graph_tags(fields, virtual_path=virtual_path, category=category)
    complexity = (
        len(fields)
        + int(metadata.get("texture_parameter_count", 0) or 0) * 4
        + int(metadata.get("wrapper_count", 0) or 0) * 8
        + sum(tag in tags for tag in VISUAL_AUDIT_V2_GRAPH_MINIMUMS) * 20
    )
    return VisualAuditV2Candidate(
        virtual_path=virtual_path,
        category=category,
        graph_complexity=complexity,
        graph_tags=tags,
        pac_xml_virtual_path=sidecar_path,
        pac_xml_sha256=str(metadata.get("source_sha256", "") or ""),
        wrapper_count=int(metadata.get("wrapper_count", 0) or 0),
        parameter_count=int(metadata.get("parameter_count", 0) or 0),
        texture_parameter_count=int(metadata.get("texture_parameter_count", 0) or 0),
        shader_families=tuple(
            sorted(
                {
                    str(field.shader_name or "").strip().casefold()
                    for field in fields
                    if str(field.shader_name or "").strip()
                }
            )
        ),
    )


def _sidecar_identity(entry: ArchiveEntry) -> tuple[str, int, int, int]:
    return (
        str(entry.paz_file).casefold(),
        int(entry.offset),
        int(entry.comp_size),
        int(entry.orig_size),
    )


def _graph_tags(
    fields: Sequence[_VisualAuditV2GraphField],
    *,
    virtual_path: str,
    category: str,
) -> tuple[str, ...]:
    text = " ".join(
        " ".join((field.parameter_name, field.value, field.shader_name, field.group_label))
        for field in fields
    ).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "", text)
    tags: set[str] = set()
    layered = any(token in normalized for token in ("texturelayer", "layerblend", "dye", "grime", "dirtmask", "colormask", "blendingmask"))
    metal = any(token in normalized for token in ("metalness", "metallic", "standardv2", "speculargloss"))
    soft = any(token in normalized for token in ("cloth", "fabric", "leather", "hide", "fur", "hair", "wrap", "strap"))
    if category == "equipment_soft":
        soft = True
    if layered:
        tags.add("layered_dye_grime_graph")
    if metal:
        tags.add("true_metal_control_candidate")
    if soft:
        tags.add("soft_control_candidate")
    if metal and soft:
        tags.add("mixed_hard_soft_candidate")
    return tuple(sorted(tags | set(_path_fallback_tags(virtual_path, category))))


def _path_fallback_tags(virtual_path: str, category: str) -> tuple[str, ...]:
    # These are selection hints only. PAC authority and the human visual review
    # remain mandatory before any material verdict is accepted.
    tags: set[str] = set()
    path = _archive_key(virtual_path)
    if category in {"weapon_sword", "weapon_shield"}:
        tags.add("true_metal_control_candidate")
    if category == "equipment_soft" or any(token in path for token in ("cloak", "vest", "hair", "nude")):
        tags.add("soft_control_candidate")
    return tuple(sorted(tags))


def _improve_graph_constraint_coverage(
    selected: list[VisualAuditV2Candidate],
    by_category: Mapping[str, Sequence[VisualAuditV2Candidate]],
    selected_paths: set[str],
    *,
    protected_paths: set[str] | None = None,
) -> list[VisualAuditV2Candidate]:
    protected = protected_paths or {
        normalize_visual_audit_virtual_path(REQUIRED_SWORD_PATH),
        normalize_visual_audit_virtual_path(PRIOR_CONCERN_SWORD_PATH),
    }
    for tag, minimum in VISUAL_AUDIT_V2_GRAPH_MINIMUMS.items():
        while sum(tag in candidate.graph_tags for candidate in selected) < minimum:
            replacement: tuple[int, VisualAuditV2Candidate] | None = None
            for index, current in enumerate(selected):
                if (
                    tag in current.graph_tags
                    or normalize_visual_audit_virtual_path(current.virtual_path) in protected
                ):
                    continue
                candidate = next(
                    (
                        row
                        for row in by_category[current.category]
                        if tag in row.graph_tags
                        and normalize_visual_audit_virtual_path(row.virtual_path)
                        not in selected_paths
                    ),
                    None,
                )
                if candidate is not None:
                    replacement = (index, candidate)
                    break
            if replacement is None:
                break
            index, candidate = replacement
            selected_paths.remove(
                normalize_visual_audit_virtual_path(selected[index].virtual_path)
            )
            selected[index] = candidate
            selected_paths.add(normalize_visual_audit_virtual_path(candidate.virtual_path))
    return selected


def _candidate_sort_key(candidate: VisualAuditV2Candidate) -> tuple[int, str]:
    return (-candidate.graph_complexity, _archive_key(candidate.virtual_path))


def _candidate_identity_key(candidate: VisualAuditV2Candidate) -> tuple[object, ...]:
    return (
        normalize_visual_audit_virtual_path(candidate.virtual_path),
        candidate.category,
        -candidate.graph_complexity,
        candidate.graph_tags,
        candidate.pac_xml_virtual_path.casefold(),
        candidate.pac_xml_sha256.casefold(),
        -candidate.wrapper_count,
        -candidate.parameter_count,
        -candidate.texture_parameter_count,
        candidate.shader_families,
    )


def _expansion_candidate_sort_key(
    candidates: Sequence[VisualAuditV2Candidate],
    *,
    selection_seed: str,
):
    fingerprint_counts = Counter(
        candidate.pac_xml_sha256.casefold()
        for candidate in candidates
        if candidate.pac_xml_sha256
    )
    shader_family_counts = Counter(
        family
        for candidate in candidates
        for family in candidate.shader_families
    )
    graph_tag_counts = Counter(
        tag
        for candidate in candidates
        for tag in candidate.graph_tags
    )
    seed = str(selection_seed).encode("utf-8")

    def key(candidate: VisualAuditV2Candidate) -> tuple[object, ...]:
        fingerprint = candidate.pac_xml_sha256.casefold()
        fingerprint_frequency = (
            fingerprint_counts[fingerprint] if fingerprint else len(candidates) + 1
        )
        shader_rarity = sum(
            1_000_000 // shader_family_counts[family]
            for family in candidate.shader_families
            if shader_family_counts[family]
        )
        tag_rarity = sum(
            1_000_000 // graph_tag_counts[tag]
            for tag in candidate.graph_tags
            if graph_tag_counts[tag]
        )
        normalized_path = normalize_visual_audit_virtual_path(candidate.virtual_path)
        seeded_tie_breaker = hashlib.sha256(
            seed + b"\0" + normalized_path.encode("utf-8")
        ).hexdigest()
        return (
            0 if fingerprint else 1,
            fingerprint_frequency,
            -shader_rarity,
            -tag_rarity,
            -len(candidate.shader_families),
            -len(candidate.graph_tags),
            -candidate.wrapper_count,
            -candidate.texture_parameter_count,
            -candidate.parameter_count,
            -candidate.graph_complexity,
            seeded_tie_breaker,
            normalized_path,
        )

    return key


def _token(text: str, token: str) -> bool:
    return re.search(rf"(?:^|[_/]){re.escape(token)}(?:[_./]|$)", text) is not None


def _contains_any(text: str, values: Sequence[str]) -> bool:
    return any(value in text for value in values)


__all__ = [
    "PRIOR_CONCERN_SWORD_PATH",
    "REQUIRED_SWORD_PATH",
    "VISUAL_AUDIT_V2_CATEGORY_COUNTS",
    "VISUAL_AUDIT_V2_EXPANSION_RULES_VERSION",
    "VISUAL_AUDIT_V2_GRAPH_MINIMUMS",
    "VisualAuditV2Candidate",
    "build_visual_audit_v2_candidates",
    "classify_visual_audit_v2_path",
    "normalize_visual_audit_virtual_path",
    "select_visual_audit_v2_candidates",
    "validate_visual_audit_v2_selection",
    "visual_audit_v2_archive_paths",
]
