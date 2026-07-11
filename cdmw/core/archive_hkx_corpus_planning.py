from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from cdmw.core.common import raise_if_cancelled

def _hkx_corpus_role_for_document(path: Path, document: Mapping[str, object], report: Mapping[str, object]) -> str:
    path_text = str(path).replace("\\", "/").casefold()
    type_names: set[str] = set()
    type_registry = document.get("type_registry")
    if isinstance(type_registry, Mapping):
        raw_type_names = type_registry.get("type_names")
        if isinstance(raw_type_names, list):
            type_names.update(str(value) for value in raw_type_names if str(value))
    collision_shapes = document.get("collision_shapes")
    shape_types: set[str] = set()
    if isinstance(collision_shapes, list):
        for shape in collision_shapes:
            if isinstance(shape, Mapping):
                shape_types.add(str(shape.get("shape_type") or ""))
    physics_constraint_summary = document.get("physics_constraint_summary")
    constraint_count = (
        int(physics_constraint_summary.get("constraint_count") or 0)
        if isinstance(physics_constraint_summary, Mapping)
        else 0
    )
    if "meshphysics" in path_text or "/cloak/" in path_text or "cloak" in path_text:
        return "cloak_or_meshphysics"
    if "havokphysics" in path_text or "ragdoll" in path_text or constraint_count > 0 or "hknpRagdollData" in type_names:
        return "character_havokphysics_or_ragdoll"
    has_mesh_shape = "hknpMeshShape" in type_names or "hknpMeshShape" in shape_types
    has_convex_or_simple_shape = any(
        type_name in type_names or type_name in shape_types
        for type_name in ("hknpConvexShape", "hknpBoxShape", "hknpSphereShape", "hknpCapsuleShape")
    )
    if has_mesh_shape:
        return "mesh_shape_heavy"
    if has_convex_or_simple_shape and "/object/" in path_text:
        return "small_object_convex"
    if "animation" in path_text or "/motion/" in path_text or "hka" in " ".join(type_names).casefold():
        return "animation_or_metadata"
    if has_convex_or_simple_shape:
        return "small_object_convex"
    if any(type_name.startswith("hknp") for type_name in type_names):
        return "generic_hknp_physics"
    return "unknown_or_nonphysics_hkx"


def _hkx_corpus_role_hint_from_path(path: Path) -> str:
    path_text = str(path).replace("\\", "/").casefold()
    if "meshphysics" in path_text or "/cloak/" in path_text or "cloak" in path_text:
        return "cloak_or_meshphysics"
    if "havokphysics" in path_text or "ragdoll" in path_text:
        return "character_havokphysics_or_ragdoll"
    if "meshshape" in path_text or "mesh_shape" in path_text:
        return "mesh_shape_heavy"
    if "animation" in path_text or "/motion/" in path_text or "/anim" in path_text:
        return "animation_or_metadata"
    if "/object/" in path_text or path_text.endswith(".hkx"):
        return "small_object_convex"
    return "unknown_or_nonphysics_hkx"


def _hkx_path_contains_binary_marker(
    path: Path,
    marker: bytes,
    *,
    chunk_size: int = 262_144,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    if not marker:
        return False
    overlap = max(0, len(marker) - 1)
    previous_tail = b""
    try:
        with path.open("rb") as handle:
            while True:
                raise_if_cancelled(stop_event)
                chunk = handle.read(chunk_size)
                if not chunk:
                    return False
                haystack = previous_tail + chunk
                if marker in haystack:
                    return True
                previous_tail = haystack[-overlap:] if overlap else b""
    except OSError:
        return False


def _hkx_enrich_balanced_corpus_content_hints(
    by_role: MutableMapping[str, List[Path]],
    paths: Sequence[Path],
    *,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Promote likely mesh-shape files into the limited representative sample.

    Path names alone cannot reliably distinguish small convex object HKX from object HKX that carry
    hknpMeshShape topology. This bounded marker pass keeps limited corpus reports representative
    without requiring a full Python decode of every file.
    """

    scan_limit = 2048
    try:
        env_limit = os.environ.get("CDMW_HKX_CORPUS_BALANCE_CONTENT_LIMIT")
        if env_limit is not None and str(env_limit).strip():
            scan_limit = max(0, int(str(env_limit).strip()))
    except (TypeError, ValueError, OverflowError):
        scan_limit = 2048
    if scan_limit <= 0:
        return
    scanned = 0
    promoted: List[Path] = []
    for path in paths:
        raise_if_cancelled(stop_event)
        hint = _hkx_corpus_role_hint_from_path(path)
        if hint not in {"small_object_convex", "unknown_or_nonphysics_hkx", "generic_hknp_physics"}:
            continue
        scanned += 1
        if _hkx_path_contains_binary_marker(path, b"hknpMeshShape", stop_event=stop_event):
            promoted.append(path)
            if len(promoted) >= 8:
                break
        if scanned >= scan_limit:
            break
    if promoted:
        existing_mesh_paths = [path for path in by_role.get("mesh_shape_heavy", []) if path not in set(promoted)]
        by_role["mesh_shape_heavy"] = list(promoted) + existing_mesh_paths
        promoted_set = set(promoted)
        for role in ("small_object_convex", "unknown_or_nonphysics_hkx", "generic_hknp_physics"):
            if role in by_role:
                by_role[role] = [path for path in by_role[role] if path not in promoted_set]


def _hkx_select_balanced_corpus_paths(
    paths: Sequence[Path],
    limit: int,
    *,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    if limit <= 0 or len(paths) <= limit:
        return list(paths)
    by_role: Dict[str, List[Path]] = defaultdict(list)
    for path in paths:
        raise_if_cancelled(stop_event)
        by_role[_hkx_corpus_role_hint_from_path(path)].append(path)
    _hkx_enrich_balanced_corpus_content_hints(by_role, paths, stop_event=stop_event)
    selected: List[Path] = []
    selected_set: set[Path] = set()
    role_order = list(_HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES) + [
        "generic_hknp_physics",
        "unknown_or_nonphysics_hkx",
    ]
    while len(selected) < limit:
        raise_if_cancelled(stop_event)
        added = False
        for role in role_order:
            candidates = by_role.get(role)
            if not candidates:
                continue
            while candidates and candidates[0] in selected_set:
                candidates.pop(0)
            if not candidates:
                continue
            candidate = candidates.pop(0)
            selected.append(candidate)
            selected_set.add(candidate)
            added = True
            if len(selected) >= limit:
                break
        if not added:
            break
    for path in paths:
        raise_if_cancelled(stop_event)
        if len(selected) >= limit:
            break
        if path not in selected_set:
            selected.append(path)
            selected_set.add(path)
    return sorted(selected, key=lambda item: str(item).casefold())


_HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES = (
    "small_object_convex",
    "cloak_or_meshphysics",
    "character_havokphysics_or_ragdoll",
    "mesh_shape_heavy",
    "animation_or_metadata",
)


_HKX_CORPUS_ROLE_LABELS = {
    "small_object_convex": "Small object convex HKX",
    "cloak_or_meshphysics": "Cloak / meshphysics HKX",
    "character_havokphysics_or_ragdoll": "Character havokphysics / ragdoll HKX",
    "mesh_shape_heavy": "Mesh-shape-heavy HKX",
    "animation_or_metadata": "Animation / metadata HKX",
    "generic_hknp_physics": "Generic hknp physics HKX",
    "unknown_or_nonphysics_hkx": "Unknown / non-physics HKX",
}


_HKX_REPRESENTATIVE_REAL_CORPUS_REQUIREMENTS: Tuple[Dict[str, object], ...] = (
    {
        "key": "object_hkx",
        "label": "Object HKX",
        "description": "Object physics sample, ideally a small convex/simple object with stable no-edit roundtrip.",
        "path_hints": ("object/", "object\\"),
        "legacy_roles": ("small_object_convex",),
        "type_hints": ("hknpConvexShape", "hknpBoxShape", "hknpSphereShape", "hknpCapsuleShape"),
    },
    {
        "key": "cloak_meshphysics_hkx",
        "label": "Cloak / meshphysics HKX",
        "description": "Character attachment or cloak meshphysics sample with cloth/attachment style body data.",
        "path_hints": ("meshphysics", "cloak"),
        "legacy_roles": ("cloak_or_meshphysics",),
        "type_hints": ("hknpPhysicsSystemData", "hknpConstraintCinfo"),
    },
    {
        "key": "character_havokphysics_hkx",
        "label": "Character havokphysics HKX",
        "description": "Character havokphysics sample, separate from meshphysics and preferably not only a ragdoll/body file.",
        "path_hints": ("havokphysics",),
        "legacy_roles": ("character_havokphysics_or_ragdoll",),
        "type_hints": ("hknpPhysicsSystemData", "hknpPhysicsSceneData"),
    },
    {
        "key": "ragdoll_body_hkx",
        "label": "Ragdoll / body HKX",
        "description": "Ragdoll/body sample with constraints, body infos, motors, and ragdoll-specific records.",
        "path_hints": ("ragdoll", "/body", "\\body", "body.hkx"),
        "legacy_roles": ("character_havokphysics_or_ragdoll",),
        "type_hints": ("hknpRagdollConstraintData", "hknpRagdollData", "hknpConstraintCinfo"),
    },
    {
        "key": "mesh_heavy_hkx",
        "label": "Mesh-heavy HKX",
        "description": "Mesh-shape-heavy sample for primitive bit layout, AABB tree, shape tags, and mesh buffers.",
        "path_hints": ("meshshape", "mesh_shape", "mesh-heavy", "mesh_heavy"),
        "legacy_roles": ("mesh_shape_heavy",),
        "type_hints": ("hknpMeshShape",),
    },
    {
        "key": "animation_hkx",
        "label": "Animation HKX",
        "description": "Animation/skeleton metadata sample for hka containers, skeleton arrays, and animation refs.",
        "path_hints": ("animation", "/motion/", "\\motion\\", "/anim", "\\anim"),
        "legacy_roles": ("animation_or_metadata",),
        "type_hints": ("hka", "hkRootLevelContainer"),
    },
)


def _hkx_representative_real_role_matches(row: Mapping[str, object], requirement: Mapping[str, object]) -> bool:
    path_text = str(row.get("path") or "").replace("\\", "/").casefold()
    role = str(row.get("corpus_role") or "")
    key = str(requirement.get("key") or "")
    legacy_roles = {str(value) for value in requirement.get("legacy_roles", ()) if str(value)}
    path_hints = tuple(str(value).replace("\\", "/").casefold() for value in requirement.get("path_hints", ()) if str(value))
    raw_type_names = row.get("type_names")
    type_name_values = raw_type_names if isinstance(raw_type_names, list) else ()
    type_names = {str(value) for value in type_name_values if str(value)}
    type_text = " ".join(type_names).casefold()

    if role in legacy_roles:
        if key == "character_havokphysics_hkx":
            return "havokphysics" in path_text and "meshphysics" not in path_text
        if key == "ragdoll_body_hkx":
            if "ragdoll" in path_text or path_text.endswith("/body.hkx") or "/body/" in path_text:
                return True
            try:
                return int(row.get("physics_constraint_summary_count") or 0) > 0
            except (TypeError, ValueError, OverflowError):
                return False
        return True
    if path_hints and any(hint in path_text for hint in path_hints):
        return True
    type_hints = tuple(str(value) for value in requirement.get("type_hints", ()) if str(value))
    if key == "animation_hkx":
        return any(hint.casefold() in type_text for hint in type_hints)
    if any(hint in type_names for hint in type_hints):
        return True
    if key == "mesh_heavy_hkx":
        try:
            return int(row.get("mesh_shape_count") or 0) > 0 or int(row.get("mesh_detail_shape_count") or 0) > 0
        except (TypeError, ValueError, OverflowError):
            return False
    return False


def _hkx_row_is_generated_hkx_sample(row: Mapping[str, object]) -> bool:
    path_text = str(row.get("path") or "").replace("\\", "/").casefold()
    generated_fragments = (
        "/native/cd_hkx/target/",
        "/target/test-modern.hkx",
        "/target/smoke/",
    )
    return any(fragment in path_text for fragment in generated_fragments)


def _hkx_representative_real_corpus_plan_document(
    *,
    discovered_hkx_file_count: int,
    scanned_file_count: int,
    rows: Sequence[Mapping[str, object]],
    ptch_semantics_proof: Optional[Mapping[str, object]],
    hard_decoder_corpus_proof: Optional[Mapping[str, object]],
) -> Dict[str, object]:
    eligible_rows = [
        row for row in rows if row.get("ok") is True and not _hkx_row_is_generated_hkx_sample(row)
    ]
    role_status: Dict[str, Dict[str, object]] = {}
    missing_roles: List[str] = []
    incomplete_roundtrip_roles: List[str] = []
    for requirement in _HKX_REPRESENTATIVE_REAL_CORPUS_REQUIREMENTS:
        key = str(requirement.get("key") or "")
        matches = [
            row
            for row in eligible_rows
            if _hkx_representative_real_role_matches(row, requirement)
        ]
        roundtrip_matches = [
            row
            for row in matches
            if row.get("no_edit_json_roundtrip_identical") is True
            and row.get("no_edit_xml_roundtrip_identical") is True
        ]
        covered = bool(matches)
        roundtrip_complete = covered and len(roundtrip_matches) == len(matches)
        if not covered:
            missing_roles.append(key)
        elif not roundtrip_complete:
            incomplete_roundtrip_roles.append(key)
        role_status[key] = {
            "label": str(requirement.get("label") or key),
            "description": str(requirement.get("description") or ""),
            "covered": covered,
            "file_count": len(matches),
            "roundtrip_identical_count": len(roundtrip_matches),
            "roundtrip_complete": roundtrip_complete,
            "examples": [str(row.get("path") or "") for row in matches[:5]],
            "path_hints": list(requirement.get("path_hints", ())),
            "type_hints": list(requirement.get("type_hints", ())),
            "legacy_coverage_roles": list(requirement.get("legacy_roles", ())),
        }
    ignored_generated_count = sum(
        1 for row in rows if row.get("ok") is True and _hkx_row_is_generated_hkx_sample(row)
    )
    if int(discovered_hkx_file_count) <= 0:
        status = "blocked_no_local_hkx_corpus"
        blocker = "No local .hkx corpus was found in the scanned path."
    elif not eligible_rows:
        status = "blocked_no_representative_real_hkx_corpus"
        blocker = "Only generated/build-artifact HKX samples were found; real game HKX files are still required."
    elif missing_roles:
        status = "needs_representative_real_hkx_files"
        blocker = "The scan is missing one or more representative real HKX roles needed for decoder proof."
    elif incomplete_roundtrip_roles:
        status = "needs_no_edit_roundtrip_clean_samples"
        blocker = "Representative files exist, but at least one role does not pass no-edit CDMW JSON/XML roundtrip."
    else:
        ptch_status = str(ptch_semantics_proof.get("status") or "") if isinstance(ptch_semantics_proof, Mapping) else ""
        hard_status = (
            str(hard_decoder_corpus_proof.get("status") or "")
            if isinstance(hard_decoder_corpus_proof, Mapping)
            else ""
        )
        if ptch_status not in {"", "corpus_proof_ready"} or hard_status not in {"", "corpus_proof_ready"}:
            status = "representative_files_present_semantics_unproven"
            blocker = "Representative roles are covered, but PTCH/fixup or hard-internal semantics still need proof."
        else:
            status = "representative_real_corpus_ready"
            blocker = ""
    ptch_missing = (
        list(ptch_semantics_proof.get("missing_observations") or [])
        if isinstance(ptch_semantics_proof, Mapping)
        else []
    )
    hard_missing = (
        list(hard_decoder_corpus_proof.get("missing_observations") or [])
        if isinstance(hard_decoder_corpus_proof, Mapping)
        else []
    )
    return {
        "format": "cdmw_hkx_representative_real_corpus_plan_v1",
        "status": status,
        "description": (
            "Concrete local corpus checklist for proving full HKX/Havok XML parity. These are real game HKX "
            "roles, separate from generated unit-test samples."
        ),
        "local_hkx_corpus_available": int(discovered_hkx_file_count) > 0,
        "representative_real_hkx_corpus_available": bool(eligible_rows),
        "discovered_hkx_file_count": int(discovered_hkx_file_count),
        "scanned_hkx_file_count": int(scanned_file_count),
        "eligible_real_hkx_file_count": len(eligible_rows),
        "ignored_generated_or_build_artifact_count": int(ignored_generated_count),
        "required_roles": [str(requirement.get("key") or "") for requirement in _HKX_REPRESENTATIVE_REAL_CORPUS_REQUIREMENTS],
        "role_status": role_status,
        "missing_roles": missing_roles,
        "incomplete_roundtrip_roles": incomplete_roundtrip_roles,
        "blocker": blocker,
        "ptch_semantics_status": str(ptch_semantics_proof.get("status") or "")
        if isinstance(ptch_semantics_proof, Mapping)
        else "",
        "ptch_missing_observations": ptch_missing,
        "hard_decoder_status": str(hard_decoder_corpus_proof.get("status") or "")
        if isinstance(hard_decoder_corpus_proof, Mapping)
        else "",
        "hard_decoder_missing_observations": hard_missing,
        "next_action": (
            "Scan representative real HKX folders for object, cloak/meshphysics, character havokphysics, "
            "ragdoll/body, mesh-heavy, and animation files; then review PTCH missing observations and hard "
            "decoder missing observations."
        ),
    }


_HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS: Tuple[Tuple[str, str, str], ...] = (
    (
        "object_or_null_patch_sites",
        "PTCH object/null patch sites",
        "Confirms the currently modeled PTCH patch-site path can resolve real hkRefPtr-style object and null references.",
    ),
    (
        "data_references",
        "PTCH data-reference candidates",
        "Needed to separate object references from array/data buffer fixups and other DATA-relative relocations.",
    ),
    (
        "string_references",
        "PTCH string-reference candidates",
        "Needed to prove string-table and hkStringPtr fixups instead of treating them as offset guesses.",
    ),
    (
        "type_references",
        "PTCH type/class-reference candidates",
        "Needed to prove hkClass/type references used by real Havok XML class and member metadata.",
    ),
    (
        "section_local_or_packed_indexes",
        "Section-local or packed index variants",
        "Needed to prove whether PTCH/INDX entries can address section-local records or packed indexes.",
    ),
    (
        "packed_or_varuint_variants",
        "Packed/varuint fixup variants",
        "Needed to prove whether additional packed or variable-length reference streams exist in representative files.",
    ),
)


def _hkx_ptch_semantics_proof_document(
    *,
    discovered_hkx_file_count: int,
    scanned_file_count: int,
    representative_gate_passed: bool,
    aggregate_ptch_tuple_shape_counts: Mapping[str, int],
    aggregate_ptch_payload_match_kind_counts: Mapping[str, int],
    aggregate_ptch_reference_category_counts: Mapping[str, int],
    aggregate_ptch_varuint_status_counts: Mapping[str, int],
    aggregate_tagfile_ptch_target_status_counts: Mapping[str, int],
    aggregate_ptch_remaining_case_priorities: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    def _count_from(mapping: Mapping[str, int], *keys: str) -> int:
        total = 0
        for key in keys:
            try:
                total += int(mapping.get(key, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
        return total

    def _count_matching(mapping: Mapping[str, int], fragments: Sequence[str]) -> int:
        total = 0
        for key, value in mapping.items():
            key_text = str(key).casefold()
            if any(fragment in key_text for fragment in fragments):
                try:
                    total += int(value or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
        return total

    object_or_null_count = _count_from(aggregate_tagfile_ptch_target_status_counts, "object", "null")
    data_reference_count = _count_from(
        aggregate_ptch_payload_match_kind_counts,
        "ptch_data_offset",
        "ptch_absolute_offset",
    ) + _count_from(aggregate_ptch_reference_category_counts, "data_reference_candidate")
    string_reference_count = _count_from(
        aggregate_ptch_payload_match_kind_counts,
        "ptch_string_table_index",
    ) + _count_from(aggregate_ptch_reference_category_counts, "string_reference")
    type_reference_count = _count_from(
        aggregate_ptch_payload_match_kind_counts,
        "ptch_type_index",
    ) + _count_from(aggregate_ptch_reference_category_counts, "type_reference", "type_class_reference")
    section_local_or_packed_count = _count_matching(
        aggregate_ptch_payload_match_kind_counts,
        ("section_local", "section-local", "packed_index", "packed-index"),
    ) + _count_matching(
        aggregate_ptch_reference_category_counts,
        ("section_local", "section-local", "packed_index", "packed-index"),
    )
    packed_or_varuint_count = sum(
        int(count or 0)
        for status, count in aggregate_ptch_varuint_status_counts.items()
        if str(status or "") not in {"", "not_decoded", "native_not_decoded"}
    )
    observed_counts = {
        "object_or_null_patch_sites": object_or_null_count,
        "data_references": data_reference_count,
        "string_references": string_reference_count,
        "type_references": type_reference_count,
        "section_local_or_packed_indexes": section_local_or_packed_count,
        "packed_or_varuint_variants": packed_or_varuint_count,
    }
    requirements = [
        {
            "key": key,
            "label": label,
            "observed": int(observed_counts.get(key, 0)) > 0,
            "observation_count": int(observed_counts.get(key, 0)),
            "description": description,
        }
        for key, label, description in _HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS
    ]
    missing = [row["key"] for row in requirements if not bool(row["observed"])]
    nonstandard_tuple_shapes = {
        str(shape): int(count)
        for shape, count in aggregate_ptch_tuple_shape_counts.items()
        if str(shape) != "1,1,0,2"
    }
    unresolved_case_count = sum(
        int(case.get("count") or 0)
        for case in aggregate_ptch_remaining_case_priorities
        if isinstance(case, Mapping)
    )
    local_corpus_available = int(discovered_hkx_file_count) > 0
    if not local_corpus_available:
        status = "blocked_no_local_hkx_corpus"
        blocker = "No local .hkx corpus was found in the scanned path, so PTCH semantics cannot be proven."
    elif missing or not representative_gate_passed:
        status = "needs_more_corpus_observations"
        blocker = (
            "Local HKX files were scanned, but the corpus does not yet prove every PTCH semantic class "
            "needed for full HKX parity."
        )
    elif unresolved_case_count:
        status = "blocked_unresolved_ptch_cases"
        blocker = "Representative PTCH samples exist, but unresolved PTCH/fixup cases still need decoding."
    else:
        status = "corpus_proof_ready"
        blocker = ""
    return {
        "format": "cdmw_hkx_ptch_semantics_proof_v1",
        "status": status,
        "description": (
            "Corpus proof gate for PTCH/fixup semantics. Native and Python reports can classify tuple shapes "
            "and unresolved cases, but full parity requires representative HKX samples that exercise object, data, "
            "string, type, section-local, and packed/varuint reference variants."
        ),
        "local_hkx_corpus_available": local_corpus_available,
        "discovered_hkx_file_count": int(discovered_hkx_file_count),
        "scanned_hkx_file_count": int(scanned_file_count),
        "representative_corpus_gate_passed": bool(representative_gate_passed),
        "proven": status == "corpus_proof_ready",
        "blocker": blocker,
        "requirements": requirements,
        "missing_observations": missing,
        "observed_ptch_tuple_shape_counts": dict(sorted((str(k), int(v)) for k, v in aggregate_ptch_tuple_shape_counts.items())),
        "observed_nonstandard_tuple_shape_counts": dict(sorted(nonstandard_tuple_shapes.items())),
        "observed_ptch_payload_match_kind_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_ptch_payload_match_kind_counts.items())
        ),
        "observed_ptch_reference_category_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_ptch_reference_category_counts.items())
        ),
        "observed_ptch_target_status_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_tagfile_ptch_target_status_counts.items())
        ),
        "observed_varuint_status_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_ptch_varuint_status_counts.items())
        ),
        "remaining_case_count": int(unresolved_case_count),
        "remaining_case_priorities": list(aggregate_ptch_remaining_case_priorities),
        "next_action": (
            "Scan representative object, cloak/meshphysics, character havokphysics, ragdoll/body, mesh-shape-heavy, "
            "and animation HKX files, then review missing_observations and remaining_case_priorities."
        ),
    }


def _hkx_hard_decoder_corpus_proof_document(
    *,
    discovered_hkx_file_count: int,
    scanned_file_count: int,
    representative_gate_passed: bool,
    aggregate_hard_decoder_target_counts: Mapping[str, int],
    aggregate_hard_decoder_target_byte_counts: Mapping[str, int],
    aggregate_hard_decoder_target_status_counts: Mapping[str, int],
    native_fast_scan: Optional[Mapping[str, object]],
) -> Dict[str, object]:
    from cdmw.core import archive_hkx as hkx

    native_target_counts = (
        native_fast_scan.get("aggregate_hard_internal_target_counts")
        if isinstance(native_fast_scan, Mapping)
        else None
    )
    native_status_counts = (
        native_fast_scan.get("aggregate_hard_internal_status_counts")
        if isinstance(native_fast_scan, Mapping)
        else None
    )
    requirements: List[Dict[str, object]] = []
    for key, label, description, _prefixes in hkx._HKX_HARD_DECODER_TARGETS:
        try:
            detail_count = int(aggregate_hard_decoder_target_counts.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            detail_count = 0
        native_count = 0
        if isinstance(native_target_counts, Mapping):
            try:
                native_count = int(native_target_counts.get(key, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                native_count = 0
        try:
            byte_count = int(aggregate_hard_decoder_target_byte_counts.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            byte_count = 0
        requirements.append(
            {
                "key": key,
                "label": label,
                "observed": detail_count > 0 or native_count > 0,
                "observation_count": detail_count,
                "native_fast_scan_observation_count": native_count,
                "observed_byte_count": byte_count,
                "resolved": False,
                "proof_status": "needs_semantic_decode_and_rebuild_rules"
                if (detail_count > 0 or native_count > 0)
                else "needs_corpus_sample",
                "description": description,
            }
        )
    missing = [row["key"] for row in requirements if not bool(row["observed"])]
    observed_unresolved = [row["key"] for row in requirements if bool(row["observed"]) and not bool(row["resolved"])]
    local_corpus_available = int(discovered_hkx_file_count) > 0
    if not local_corpus_available:
        status = "blocked_no_local_hkx_corpus"
        blocker = "No local .hkx corpus was found in the scanned path, so hard class internals cannot be proven."
    elif missing or not representative_gate_passed:
        status = "needs_more_corpus_observations"
        blocker = (
            "Local HKX files were scanned, but the corpus does not yet cover every hard decoder target "
            "across representative object, meshphysics, character/ragdoll, mesh-heavy, and animation files."
        )
    elif observed_unresolved:
        status = "blocked_unresolved_hard_decoder_targets"
        blocker = (
            "Representative hard-target samples were observed, but their semantic layouts and rebuild rules are "
            "not proven yet."
        )
    else:
        status = "corpus_proof_ready"
        blocker = ""
    return {
        "format": "cdmw_hkx_hard_decoder_corpus_proof_v1",
        "status": status,
        "description": (
            "Corpus proof gate for hard HKX internals: mesh primitive bits, AABB nodes, shape tags, compound "
            "children, compressed mass, materials/free-lists, and skeleton/animation containers."
        ),
        "local_hkx_corpus_available": local_corpus_available,
        "discovered_hkx_file_count": int(discovered_hkx_file_count),
        "scanned_hkx_file_count": int(scanned_file_count),
        "representative_corpus_gate_passed": bool(representative_gate_passed),
        "proven": status == "corpus_proof_ready",
        "blocker": blocker,
        "requirements": requirements,
        "missing_observations": missing,
        "observed_unresolved_targets": observed_unresolved,
        "aggregate_target_counts": dict(sorted((str(k), int(v)) for k, v in aggregate_hard_decoder_target_counts.items())),
        "aggregate_target_byte_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_hard_decoder_target_byte_counts.items())
        ),
        "aggregate_target_status_counts": dict(
            sorted((str(k), int(v)) for k, v in aggregate_hard_decoder_target_status_counts.items())
        ),
        "native_fast_scan_target_counts": dict(native_target_counts)
        if isinstance(native_target_counts, Mapping)
        else {},
        "native_fast_scan_status_counts": dict(native_status_counts)
        if isinstance(native_status_counts, Mapping)
        else {},
        "next_action": (
            "Scan a representative corpus, then prioritize observed_unresolved_targets by byte count and implement "
            "semantic decoders/rebuild rules one target at a time."
        ),
    }
