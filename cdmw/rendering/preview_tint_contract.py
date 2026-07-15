"""Shared Archive Browser and .NET preview tint contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Sequence, Tuple

from cdmw.rendering.native_preview_material_contract import (
    sidecar_preview_texture_tint_for_batch,
)
from cdmw.rendering.native_preview_payloads import _safe_float


@dataclass(frozen=True)
class PreviewTintContract:
    base_color: Tuple[float, ...]
    texture_tint: Tuple[float, ...]
    base_tint_strength: float
    texture_tint_active: bool
    sidecar_texture_tint_promoted: bool


def _uses_multiplicative_gltf_base_color_factor(batch: object) -> bool:
    """Return whether ``preview_texture_tint`` is a glTF baseColorFactor.

    Scene import deliberately keeps the factor both as the representative
    ``preview_color`` and as the multiplicative texture tint.  It must not also
    enable Crimson's luma-preserving base-tint branch.
    """

    for parameter in tuple(getattr(batch, "preview_material_parameters", ()) or ()):
        if isinstance(parameter, Mapping):
            parameter_name = parameter.get("parameter_name", "")
        else:
            parameter_name = getattr(parameter, "parameter_name", "")
        normalized = "".join(
            character
            for character in str(parameter_name or "").strip().casefold()
            if character.isalnum()
        )
        if normalized == "basecolorfactor":
            return True
    return False


def resolve_preview_tint_contract(
    batch: object,
    *,
    base_color: Sequence[object] = (),
    base_tint_strength: object | None = None,
    source_path: object = "",
) -> PreviewTintContract:
    """Resolve the exact tint inputs consumed by both preview renderers."""

    resolved_base_color = tuple(base_color or ())[:3]
    texture_tint = tuple(
        max(0.0, min(2.0, _safe_float(value, 1.0)))
        for value in tuple(getattr(batch, "preview_texture_tint", ()) or ())[:3]
    )
    tint_active = len(texture_tint) >= 3 and any(
        abs(float(value) - 1.0) > 1e-4 for value in texture_tint
    )
    sidecar_promoted = False
    if not tint_active:
        sidecar_texture_tint = sidecar_preview_texture_tint_for_batch(
            batch,
            source_path=source_path,
        )
        if sidecar_texture_tint:
            texture_tint = sidecar_texture_tint
            tint_active = True
            sidecar_promoted = True
    resolved_strength = 0.85 if tint_active else 0.0
    if _uses_multiplicative_gltf_base_color_factor(batch):
        resolved_strength = 0.0
    if base_tint_strength is not None:
        resolved_strength = max(0.0, min(1.0, _safe_float(base_tint_strength, resolved_strength)))
    return PreviewTintContract(
        base_color=resolved_base_color,
        texture_tint=texture_tint,
        base_tint_strength=resolved_strength,
        texture_tint_active=tint_active,
        sidecar_texture_tint_promoted=sidecar_promoted,
    )
