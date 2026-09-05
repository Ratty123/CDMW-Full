from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tools.mesh_harness.real_common import _archive_key
from tools.mesh_harness.visual_audit_corpus import VisualAuditAssetSpec
from tools.mesh_harness.visual_audit_manifest_v2 import (
    PRIOR_CONCERN_SWORD_PATH,
    REQUIRED_SWORD_PATH,
)


MODIFY_ORIGINAL_SUBSET_SCHEMA = "cdmw_mesh_modify_original_material_subset_v1"
MODIFY_ORIGINAL_SUBSET_ROLES = (
    "reported_sword",
    "representative_guard",
    "mixed_armor",
    "true_metal_helmet",
    "soft_helmet",
    "boots",
    "shield",
    "belt_or_glove",
    "cloak_or_vest",
    "other_weapon",
    "hair_control",
    "glass_control",
)


@dataclass(frozen=True, slots=True)
class ModifyOriginalSubsetAsset:
    role: str
    spec: VisualAuditAssetSpec


def select_modify_original_subset(
    specs: Sequence[VisualAuditAssetSpec],
) -> tuple[ModifyOriginalSubsetAsset, ...]:
    """Select twelve unique deterministic roles from the canonical 120 corpus."""

    ordered = tuple(specs)
    used: set[str] = set()
    selected: list[ModifyOriginalSubsetAsset] = []

    def choose(
        role: str,
        predicate: Callable[[VisualAuditAssetSpec], bool],
        *,
        preferred_path: str = "",
    ) -> None:
        preferred = _archive_key(preferred_path) if preferred_path else ""
        candidates = [
            spec
            for spec in ordered
            if _archive_key(spec.virtual_path) not in used and predicate(spec)
        ]
        match = next(
            (spec for spec in candidates if preferred and _archive_key(spec.virtual_path) == preferred),
            candidates[0] if candidates else None,
        )
        if match is None:
            raise ValueError(f"Modify Original subset cannot satisfy role {role}.")
        used.add(_archive_key(match.virtual_path))
        selected.append(ModifyOriginalSubsetAsset(role, match))

    choose(
        "reported_sword",
        lambda spec: spec.model_category == "weapon_sword",
        preferred_path=REQUIRED_SWORD_PATH,
    )
    choose(
        "representative_guard",
        lambda spec: spec.model_category == "weapon_sword",
        preferred_path=PRIOR_CONCERN_SWORD_PATH,
    )
    choose(
        "mixed_armor",
        lambda spec: spec.model_category == "armor_body"
        and "mixed_hard_soft_candidate" in spec.graph_tags,
    )
    choose(
        "true_metal_helmet",
        lambda spec: spec.model_category == "helmet_mask"
        and "true_metal_control_candidate" in spec.graph_tags
        and "soft_control_candidate" not in spec.graph_tags,
    )
    choose(
        "soft_helmet",
        lambda spec: spec.model_category == "helmet_mask"
        and "soft_control_candidate" in spec.graph_tags,
    )
    choose(
        "boots",
        lambda spec: spec.model_category == "equipment_small"
        and any(token in _archive_key(spec.virtual_path) for token in ("foot", "boot")),
    )
    choose(
        "shield",
        lambda spec: spec.model_category == "weapon_shield",
    )
    choose(
        "belt_or_glove",
        lambda spec: spec.model_category == "equipment_small"
        and any(
            token in _archive_key(spec.virtual_path)
            for token in ("belt", "glove", "gauntlet", "/11_hand/")
        ),
    )
    choose(
        "cloak_or_vest",
        lambda spec: spec.model_category == "equipment_soft"
        and any(token in _archive_key(spec.virtual_path) for token in ("cloak", "cape", "vest")),
    )
    choose("other_weapon", lambda spec: spec.model_category == "weapon_other")
    choose(
        "hair_control",
        lambda spec: spec.model_category == "regression_control"
        and "hair" in _archive_key(spec.virtual_path),
    )
    choose(
        "glass_control",
        lambda spec: spec.model_category == "regression_control"
        and "glass" in _archive_key(spec.virtual_path),
    )
    if tuple(row.role for row in selected) != MODIFY_ORIGINAL_SUBSET_ROLES:
        raise AssertionError("Modify Original subset role order drifted.")
    if len(used) != len(MODIFY_ORIGINAL_SUBSET_ROLES):
        raise AssertionError("Modify Original subset assets must be unique.")
    return tuple(selected)








__all__ = ['MODIFY_ORIGINAL_SUBSET_ROLES', 'MODIFY_ORIGINAL_SUBSET_SCHEMA', 'ModifyOriginalSubsetAsset', 'select_modify_original_subset']
