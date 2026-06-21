"""Donor material state helpers for static replacement."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace

from cdmw.core.upscale_profiles import parse_material_sidecar_profile
from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.static_mesh_replacer import (
    StaticDonorMaterialPlan,
    StaticDonorMaterialTextureBinding,
)


@dataclass(frozen=True, slots=True)
class DonorTextureBindingDisplayState:
    slot_label: str
    parameter_name: str
    texture_path: str
    state: str


@dataclass(frozen=True, slots=True)
class DonorMaterialPlanTreeSizeState:
    has_rows: bool
    group_max_height: int
    tree_max_height: int


@dataclass(frozen=True, slots=True)
class DonorMaterialPlanBuildState:
    message_key: str
    plan: StaticDonorMaterialPlan | None
    donor_part_name: str


def donor_material_plan_tree_size_state(row_count: object) -> DonorMaterialPlanTreeSizeState:
    try:
        count = int(row_count)
    except (TypeError, ValueError, OverflowError):
        count = 0
    has_rows = count > 0
    return DonorMaterialPlanTreeSizeState(
        has_rows=has_rows,
        group_max_height=190 if has_rows else 126,
        tree_max_height=140 if has_rows else 92,
    )


def donor_mesh_picker_candidates(
    archive_entries: Sequence[object],
    current_entry: object,
    *,
    same_entry: Callable[[object, object], bool],
    mesh_extensions: set[str] | frozenset[str],
    archive_entry_type: type,
) -> tuple[object, ...]:
    return tuple(
        candidate
        for candidate in tuple(archive_entries or ())
        if isinstance(candidate, archive_entry_type)
        and str(getattr(candidate, "extension", "") or "") in mesh_extensions
        and not same_entry(candidate, current_entry)
    )


def donor_bindings_from_sidecar_profiles(
    donor_sidecar_texts: Mapping[str, str],
) -> tuple[object, ...]:
    fallback_bindings: list[object] = []
    for sidecar_path, sidecar_text in donor_sidecar_texts.items():
        try:
            profile = parse_material_sidecar_profile(sidecar_text, sidecar_path=sidecar_path)
        except Exception:
            continue
        for material in tuple(getattr(profile, "materials", ()) or ()):
            part_name = str(
                getattr(material, "part_name", "")
                or getattr(material, "material_name", "")
                or "Material"
            ).strip()
            shader_family = str(getattr(material, "shader_family", "") or "")
            texture_parameters = tuple(getattr(material, "texture_parameters", ()) or ())
            if not texture_parameters:
                fallback_bindings.append(
                    SimpleNamespace(
                        sidecar_path=sidecar_path,
                        sidecar_kind=str(getattr(profile, "sidecar_kind", "") or ""),
                        linked_mesh_path=str(getattr(profile, "linked_mesh_path", "") or ""),
                        part_name=part_name,
                        submesh_name=part_name,
                        material_name=str(getattr(material, "material_name", "") or part_name),
                        shader_family=shader_family,
                        parameter_name="",
                        texture_path="",
                    )
                )
                continue
            for parameter in texture_parameters:
                fallback_bindings.append(
                    SimpleNamespace(
                        sidecar_path=sidecar_path,
                        sidecar_kind=str(getattr(profile, "sidecar_kind", "") or ""),
                        linked_mesh_path=str(getattr(profile, "linked_mesh_path", "") or ""),
                        part_name=part_name,
                        submesh_name=part_name,
                        material_name=str(getattr(material, "material_name", "") or part_name),
                        shader_family=shader_family,
                        parameter_name=str(getattr(parameter, "parameter_name", "") or ""),
                        texture_path=str(getattr(parameter, "texture_path", "") or "").replace("\\", "/"),
                    )
                )
    return tuple(fallback_bindings)


def donor_binding_part_name(binding: object) -> str:
    return str(
        getattr(binding, "part_name", "")
        or getattr(binding, "submesh_name", "")
        or getattr(binding, "material_name", "")
        or "Material"
    ).strip()


def donor_binding_is_emissive(binding: object) -> bool:
    parameter_name = str(getattr(binding, "parameter_name", "") or "")
    texture_path = str(getattr(binding, "texture_path", "") or "")
    classification = classify_texture_binding(parameter_name, texture_path)
    return (
        str(getattr(classification, "semantic_subtype", "") or "").lower() == "emissive"
        or any(token in parameter_name.lower() for token in ("emissive", "glow", "illum"))
        or "emissive" in str(getattr(binding, "shader_family", "") or "").lower()
    )


def donor_part_rows(bindings: Sequence[object]) -> tuple[dict[str, object], ...]:
    rows: "OrderedDict[str, dict[str, object]]" = OrderedDict()
    for binding in tuple(bindings or ()):
        part_name = donor_binding_part_name(binding)
        row = rows.setdefault(
            part_name.lower(),
            {
                "part_name": part_name,
                "shader": str(getattr(binding, "shader_family", "") or ""),
                "bindings": [],
                "emissive": False,
            },
        )
        row["bindings"].append(binding)  # type: ignore[union-attr]
        if donor_binding_is_emissive(binding):
            row["emissive"] = True
    return tuple(rows.values())


def donor_texture_binding_display_state(binding: object) -> DonorTextureBindingDisplayState:
    texture_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
    parameter_name = str(getattr(binding, "parameter_name", "") or "")
    classification = classify_texture_binding(parameter_name, texture_path)
    subtype = str(getattr(classification, "semantic_subtype", "") or "").lower()
    state = (
        "emissive/glow"
        if subtype == "emissive" or any(token in parameter_name.lower() for token in ("emissive", "glow", "illum"))
        else str(getattr(classification, "visual_state", "") or "texture")
    )
    return DonorTextureBindingDisplayState(
        slot_label=str(
            getattr(classification, "slot_label", "")
            or getattr(classification, "slot_kind", "")
            or "Texture"
        ),
        parameter_name=parameter_name,
        texture_path=texture_path,
        state=state,
    )


def selected_donor_bindings_for_plan(
    texture_bindings: Sequence[object],
    part_bindings: Sequence[object],
) -> tuple[object, ...]:
    selected_texture_bindings = tuple(binding for binding in tuple(texture_bindings or ()) if binding is not None)
    if selected_texture_bindings:
        return selected_texture_bindings
    return tuple(part_bindings or ())


def donor_anchor_texture_paths(
    sidecar_bindings: Sequence[object],
    target_material_name: object,
) -> tuple[str, ...]:
    target_key = str(target_material_name or "").strip().lower()
    if not target_key:
        return ()
    return tuple(
        str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
        for binding in tuple(sidecar_bindings or ())
        if str(getattr(binding, "submesh_name", "") or getattr(binding, "part_name", "") or "").strip().lower()
        == target_key
    )


def donor_material_plan_build_state(
    bindings_for_plan: Sequence[object],
    donor_sidecar_texts: Mapping[str, str],
    *,
    target_material_name: object,
    patch_mode: object,
    sidecar_bindings_for_advanced: Sequence[object],
) -> DonorMaterialPlanBuildState:
    bindings = tuple(bindings_for_plan or ())
    if not bindings:
        return DonorMaterialPlanBuildState(message_key="select_binding", plan=None, donor_part_name="")
    first_binding = bindings[0]
    donor_part_name = donor_binding_part_name(first_binding)
    donor_sidecar_path = str(getattr(first_binding, "sidecar_path", "") or "").replace("\\", "/").strip()
    donor_sidecar_text = donor_sidecar_texts.get(donor_sidecar_path, "")
    if not donor_sidecar_text:
        return DonorMaterialPlanBuildState(
            message_key="unreadable_sidecar",
            plan=None,
            donor_part_name=donor_part_name,
        )
    texture_bindings: list[StaticDonorMaterialTextureBinding] = []
    for binding in bindings:
        display_state = donor_texture_binding_display_state(binding)
        classification = classify_texture_binding(display_state.parameter_name, display_state.texture_path)
        texture_bindings.append(
            StaticDonorMaterialTextureBinding(
                parameter_name=display_state.parameter_name,
                texture_path=display_state.texture_path,
                slot_kind=str(getattr(classification, "slot_kind", "") or ""),
                semantic_subtype=str(getattr(classification, "semantic_subtype", "") or ""),
            )
        )
    plan = StaticDonorMaterialPlan(
        target_material_name=str(target_material_name or ""),
        donor_sidecar_path=donor_sidecar_path,
        donor_sidecar_text=donor_sidecar_text,
        donor_sidecar_kind=str(getattr(first_binding, "sidecar_kind", "") or ""),
        donor_material_name=donor_part_name,
        donor_submesh_name=str(getattr(first_binding, "submesh_name", "") or donor_part_name),
        donor_shader_family=str(getattr(first_binding, "shader_family", "") or ""),
        patch_mode=str(patch_mode or "material_behavior"),
        texture_bindings=texture_bindings,
        target_anchor_texture_paths=donor_anchor_texture_paths(sidecar_bindings_for_advanced, target_material_name),
        donor_anchor_texture_paths=[binding.texture_path for binding in texture_bindings],
        enabled=True,
    )
    return DonorMaterialPlanBuildState(message_key="", plan=plan, donor_part_name=donor_part_name)


def donor_material_status_text(
    control_text: Mapping[str, object],
    *,
    donor_bindings_from_profile: bool,
) -> str:
    return str(
        control_text["profile_fallback_status"]
        if donor_bindings_from_profile
        else control_text["default_status"]
    )


__all__ = [
    "DonorMaterialPlanBuildState",
    "DonorMaterialPlanTreeSizeState",
    "DonorTextureBindingDisplayState",
    "donor_anchor_texture_paths",
    "donor_binding_is_emissive",
    "donor_binding_part_name",
    "donor_bindings_from_sidecar_profiles",
    "donor_material_plan_build_state",
    "donor_material_plan_tree_size_state",
    "donor_material_status_text",
    "donor_mesh_picker_candidates",
    "donor_part_rows",
    "donor_texture_binding_display_state",
    "selected_donor_bindings_for_plan",
]
