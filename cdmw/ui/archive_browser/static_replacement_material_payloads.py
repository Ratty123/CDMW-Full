"""Pure material override payload helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.services.mesh_workflow_service import ReplacementTextureSet, ReplacementTextureSlot

from cdmw.services.mesh_workflow_service import (
    StaticDonorMaterialPlan,
    StaticSourceMaterialTextureOverride,
)


def current_source_material_texture_overrides(
    assignments: Mapping[tuple[str, str], object],
) -> list[StaticSourceMaterialTextureOverride]:
    overrides: list[StaticSourceMaterialTextureOverride] = []
    for (material_key, slot_kind), source_path in sorted(assignments.items()):
        material_name = str(material_key or "").strip()
        normalized_slot = str(slot_kind or "").strip().lower()
        normalized_source_path = str(source_path or "").strip()
        if not material_name or not normalized_slot or not normalized_source_path:
            continue
        overrides.append(
            StaticSourceMaterialTextureOverride(
                source_material_name=material_name,
                slot_kind=normalized_slot,
                source_path=normalized_source_path,
                enabled=True,
            )
        )
    return overrides


def source_material_texture_override_payload(
    overrides: Sequence[StaticSourceMaterialTextureOverride],
) -> list[tuple[str, str, str]]:
    return [
        (
            override.source_material_name,
            override.slot_kind,
            override.source_path,
        )
        for override in overrides
    ]


def current_donor_material_plans(
    donor_material_plans_by_target: Mapping[object, object],
) -> list[StaticDonorMaterialPlan]:
    return [
        plan
        for _target_index, plan in sorted(donor_material_plans_by_target.items())
        if isinstance(plan, StaticDonorMaterialPlan) and bool(plan.enabled)
    ]


def donor_material_plan_payload(
    donor_material_plans: Sequence[StaticDonorMaterialPlan],
) -> list[tuple[object, ...]]:
    payload: list[tuple[object, ...]] = []
    for plan in donor_material_plans:
        payload.append(
            (
                plan.target_material_name,
                plan.donor_sidecar_path,
                plan.donor_material_name,
                plan.donor_submesh_name,
                plan.donor_shader_family,
                plan.patch_mode,
                tuple(
                    (
                        binding.parameter_name,
                        binding.texture_path,
                        binding.slot_kind,
                        binding.semantic_subtype,
                    )
                    for binding in tuple(plan.texture_bindings or ())
                ),
            )
        )
    return payload


def apply_source_material_texture_overrides_to_texture_sets(
    texture_sets_by_key: dict[str, ReplacementTextureSet],
    overrides: Sequence[StaticSourceMaterialTextureOverride],
    *,
    replacement_mesh: object | None = None,
    source_part_adjustments: Mapping[object, object] | Sequence[object] = (),
    apply_source_part_role_overrides: Callable[[dict[str, ReplacementTextureSet], object, tuple[object, ...]], None]
    | None = None,
) -> None:
    for override in tuple(overrides or ()):
        material_name = str(override.source_material_name or "").strip()
        slot_kind = str(override.slot_kind or "").strip().lower()
        source_path_text = str(override.source_path or "").strip()
        if not material_name or not slot_kind or not source_path_text:
            continue
        source_path = Path(source_path_text).expanduser()
        try:
            source_path = source_path.resolve()
        except Exception:
            pass
        if not source_path.is_file():
            continue
        texture_set = texture_sets_by_key.setdefault(
            material_name.lower(),
            ReplacementTextureSet(material_name=material_name),
        )
        normal_space = ""
        if slot_kind == "normal":
            stem = source_path.stem.lower()
            if "green_up" in stem:
                normal_space = "green_up"
            elif "directx" in stem or "_dx" in stem:
                normal_space = "directx"
        texture_set.slots[slot_kind] = ReplacementTextureSlot(
            material_name=texture_set.material_name,
            slot_kind=slot_kind,
            source_path=source_path,
            normal_space=normal_space,
        )
    adjustment_values = (
        tuple(source_part_adjustments.values())
        if isinstance(source_part_adjustments, Mapping)
        else tuple(source_part_adjustments or ())
    )
    if replacement_mesh is not None and adjustment_values and apply_source_part_role_overrides is not None:
        apply_source_part_role_overrides(
            texture_sets_by_key,
            replacement_mesh,
            adjustment_values,
        )


__all__ = [
    "apply_source_material_texture_overrides_to_texture_sets",
    "current_donor_material_plans",
    "current_source_material_texture_overrides",
    "donor_material_plan_payload",
    "source_material_texture_override_payload",
]
