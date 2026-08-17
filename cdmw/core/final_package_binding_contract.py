"""Per-binding package-contract errors and warnings for the final preview.

Lifted out of `build_final_package_preview` unchanged. These rules read one
binding row at a time and nothing else from that function's state, which is why
they were the only part of it that could leave without carrying context along.

They fall into two groups, and the split here is that boundary rather than an
arbitrary halving. One group asks whether the package resolves the references it
carries: a path that matches only by basename, a visible colour that nothing in
the package satisfies, a support map wired into a colour slot, and -- where the
operation owns every texture -- any reference at all with no file behind it. The
other asks whether a swap that claims to be source-owned really is, which is a
question about authority rather than about files existing.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import List, Sequence, Tuple


_SUPPORT_MAP_STEMS = ("_mg", "_sp", "_n", "_normal", "_disp", "_height")
_VISIBLE_COLOR_ROLES = {"Base / Color", "Emissive"}
_COLOR_PARAMETER_TOKENS = ("basecolor", "overlaycolor", "diffuse", "albedo", "colortexture")


def _texture_resolution_messages(
    row: object,
    *,
    row_is_planned_placeholder: bool,
    row_is_planned_source_owned: bool,
    parameter_key: str,
    stem: str,
    require_source_owned_colors: bool,
    require_complete_texture_payload: bool,
    strict_source_owned_material_contract: bool,
) -> Tuple[List[str], List[str]]:
    """Whether the package actually resolves what this row references."""

    from .final_package_preview import (
        FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC,
        FINAL_PREVIEW_DECODE_FAILED,
        FINAL_PREVIEW_MISSING_DDS,
        SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS,
    )

    errors: List[str] = []
    warnings: List[str] = []
    unresolved = row.status in {FINAL_PREVIEW_MISSING_DDS, FINAL_PREVIEW_DECODE_FAILED}
    if row.binding_source == FINAL_PREVIEW_BINDING_BASENAME_DIAGNOSTIC:
        errors.append(
            f"Exact texture path mismatch: {row.sidecar_path} -> {row.texture_path}. A same-basename DDS exists, but the packaged path does not match."
        )
    if not row_is_planned_placeholder and row.role in _VISIBLE_COLOR_ROLES and unresolved:
        message = (
            f"Visible color texture is not package-resolved: "
            f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
        )
        if (
            require_source_owned_colors
            and row_is_planned_source_owned
            and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
            and not strict_source_owned_material_contract
        ):
            warnings.append(message)
        else:
            errors.append(message)
    if (
        require_complete_texture_payload
        and not row_is_planned_placeholder
        # Visible colour already blocks above; this is the rest of the sidecar.
        # An operation that owns every texture cannot be committed with a
        # normal, mask, or material reference resolving to nothing: that is a
        # package with new bindings and no files behind them.
        and row.role not in _VISIBLE_COLOR_ROLES
        and unresolved
    ):
        errors.append(
            f"Full replacement is missing a required texture: "
            f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}. "
            f"This operation owns every texture in the package, so committing it would write a binding with no file behind it."
        )
    if (
        not row_is_planned_placeholder
        and row.role == "Base / Color"
        and stem.endswith(_SUPPORT_MAP_STEMS)
    ):
        errors.append(
            f"Support map is bound as visible base color: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
        )
    if (
        not row_is_planned_placeholder
        and any(token in parameter_key for token in _COLOR_PARAMETER_TOKENS)
        and stem.endswith(_SUPPORT_MAP_STEMS)
    ):
        errors.append(
            f"Support map path is assigned to a visible color parameter: {row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
        )
    return errors, warnings


def _source_owned_authority_messages(
    row: object,
    *,
    row_is_planned_placeholder: bool,
    row_is_planned_source_owned: bool,
    parameter_key: str,
    strict_source_owned_material_contract: bool,
    allow_inherited_layer_color_bindings: bool,
    source_owned_binding_contract_enabled: bool,
    relief_support_allowed: bool,
    true_source_authority_contract: bool,
    runtime_xml_preserve_contract: bool,
) -> Tuple[List[str], List[str]]:
    """Whether a swap that claims to be source-owned still inherits the target's."""

    from .final_package_preview import (
        FINAL_PREVIEW_BINDING_GENERATED,
        FINAL_PREVIEW_BINDING_ORIGINAL,
        FINAL_PREVIEW_READY,
        SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS,
        _binding_row_is_preserved_layer_color,
        _binding_row_is_relief_support_only,
    )

    errors: List[str] = []
    warnings: List[str] = []
    if not (source_owned_binding_contract_enabled and not row_is_planned_placeholder):
        return errors, warnings
    if (
        row.role in _VISIBLE_COLOR_ROLES
        and row.status == FINAL_PREVIEW_READY
        and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
        and row_is_planned_source_owned
        and not (
            allow_inherited_layer_color_bindings
            and _binding_row_is_preserved_layer_color(row)
        )
    ):
        message = (
            f"Complete source-owned swap still inherits visible color from the game archive: "
            f"{row.material_name} -> {row.texture_path}."
        )
        if true_source_authority_contract:
            errors.append(message)
        else:
            warnings.append(message)
    if (
        row_is_planned_source_owned
        and row.role in {"Base / Color", "Emissive", "Normal", "Height", "Material / Mask", "Detail Mask"}
        and row.binding_source == FINAL_PREVIEW_BINDING_ORIGINAL
    ):
        message = (
            f"Complete source-owned slot still inherits original {row.role} binding: "
            f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
        )
        if (
            allow_inherited_layer_color_bindings
            and _binding_row_is_preserved_layer_color(row)
            and not strict_source_owned_material_contract
        ):
            warnings.append(message)
        elif runtime_xml_preserve_contract:
            warnings.append(message)
        elif relief_support_allowed and _binding_row_is_relief_support_only(row):
            warnings.append(message)
        elif strict_source_owned_material_contract:
            errors.append(message)
        else:
            warnings.append(message)
    if (
        row_is_planned_source_owned
        and row.binding_source != FINAL_PREVIEW_BINDING_GENERATED
        and any(token in parameter_key for token in SOURCE_OWNED_FORBIDDEN_ORIGINAL_PARAMETER_TOKENS)
    ):
        message = (
            f"Complete source-owned wrapper still has non-generated original/support material parameter: "
            f"{row.material_name} {row.parameter_name or row.role} -> {row.texture_path}."
        )
        if relief_support_allowed and _binding_row_is_relief_support_only(row):
            warnings.append(message)
        elif strict_source_owned_material_contract:
            errors.append(message)
        else:
            warnings.append(message)
    return errors, warnings


def binding_row_preflight_messages(
    binding_rows: Sequence[object],
    *,
    planned_placeholder_material_keys: object,
    planned_source_owned_material_keys: object,
    require_source_owned_colors: bool = False,
    require_complete_texture_payload: bool = False,
    strict_source_owned_material_contract: bool = False,
    allow_inherited_layer_color_bindings: bool = False,
    source_owned_binding_contract_enabled: bool = False,
    relief_support_allowed: bool = False,
    true_source_authority_contract: bool = False,
    runtime_xml_preserve_contract: bool = False,
) -> Tuple[List[str], List[str]]:
    """Errors and warnings for every binding row, in that order."""

    from .final_package_preview import _material_key

    errors: List[str] = []
    warnings: List[str] = []
    for row in binding_rows:
        row_material_key = _material_key(getattr(row, "material_name", ""))
        row_is_planned_placeholder = bool(row_material_key and row_material_key in planned_placeholder_material_keys)
        row_is_planned_source_owned = bool(row_material_key and row_material_key in planned_source_owned_material_keys)
        basename = PurePosixPath(str(row.texture_path or "").replace("\\", "/")).name.lower()
        stem = PurePosixPath(basename).stem.lower()
        parameter_key = re.sub(r"[^a-z0-9]+", "", str(row.parameter_name or "").lower())
        resolution_errors, resolution_warnings = _texture_resolution_messages(
            row,
            row_is_planned_placeholder=row_is_planned_placeholder,
            row_is_planned_source_owned=row_is_planned_source_owned,
            parameter_key=parameter_key,
            stem=stem,
            require_source_owned_colors=require_source_owned_colors,
            require_complete_texture_payload=require_complete_texture_payload,
            strict_source_owned_material_contract=strict_source_owned_material_contract,
        )
        authority_errors, authority_warnings = _source_owned_authority_messages(
            row,
            row_is_planned_placeholder=row_is_planned_placeholder,
            row_is_planned_source_owned=row_is_planned_source_owned,
            parameter_key=parameter_key,
            strict_source_owned_material_contract=strict_source_owned_material_contract,
            allow_inherited_layer_color_bindings=allow_inherited_layer_color_bindings,
            source_owned_binding_contract_enabled=source_owned_binding_contract_enabled,
            relief_support_allowed=relief_support_allowed,
            true_source_authority_contract=true_source_authority_contract,
            runtime_xml_preserve_contract=runtime_xml_preserve_contract,
        )
        errors.extend(resolution_errors)
        errors.extend(authority_errors)
        warnings.extend(resolution_warnings)
        warnings.extend(authority_warnings)
    return errors, warnings


__all__ = ["binding_row_preflight_messages"]
