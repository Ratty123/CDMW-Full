"""Texture workflow policy helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from cdmw.domain.textures.material_authority import (
    complete_swap_material_allows_inherited_layer_color_bindings,
    complete_swap_material_authority_contract,
    complete_swap_material_requires_true_source_authority,
)
from cdmw.domain.textures.profiles import get_texture_processing_profile_keys


@dataclass(frozen=True, slots=True)
class TextureProcessingPolicy:
    profile_key: str
    preserve_alpha: bool = True
    prefer_direct_dds: bool = True


def available_texture_profile_keys() -> tuple[str, ...]:
    return tuple(get_texture_processing_profile_keys())


def complete_swap_allows_inherited_layer_color_bindings(options: object = None) -> bool:
    raw_profile_name = getattr(options, "complete_swap_material_profile", options)
    return bool(complete_swap_material_allows_inherited_layer_color_bindings(str(raw_profile_name or "")))


def complete_swap_authority_contract(options: object = None) -> str:
    raw_profile_name = getattr(options, "complete_swap_material_profile", options)
    contract = complete_swap_material_authority_contract(str(raw_profile_name or ""))
    try:
        edge_strength = float(getattr(options, "edge_relief_strength", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        edge_strength = 0.0
    edge_source = str(getattr(options, "edge_relief_source", "hybrid") or "hybrid").strip().lower()
    if contract.startswith("true_source_authority") and edge_strength > 0.0 and edge_source in {"preserve_target", "hybrid"}:
        if "relief_support" not in contract:
            return f"{contract}_relief_support"
    return contract


def complete_swap_requires_true_source_authority(options: object = None) -> bool:
    raw_profile_name = getattr(options, "complete_swap_material_profile", options)
    return bool(complete_swap_material_requires_true_source_authority(str(raw_profile_name or "")))


MaterialAuthorityReportChecker = Callable[[Mapping[str, object]], Mapping[str, object]]


def check_final_preview_material_authority(
    final_preview: object,
    *,
    report_checker: MaterialAuthorityReportChecker | None = None,
) -> Mapping[str, object]:
    report_obj = getattr(final_preview, "material_authority_report", None)
    if report_obj is None:
        return {
            "status": "failed",
            "errors": ["Material authority report was not generated."],
            "warnings": [],
            "blocking_risk_flags": ["missing_material_authority_report"],
            "review_risk_flags": [],
        }
    try:
        report = report_obj.to_dict() if hasattr(report_obj, "to_dict") else dict(report_obj)
    except Exception as exc:
        return {
            "status": "failed",
            "errors": [f"Material authority report could not be serialized: {exc}"],
            "warnings": [],
            "blocking_risk_flags": ["invalid_material_authority_report"],
            "review_risk_flags": [],
        }
    if report_checker is None:
        precomputed = getattr(final_preview, "material_authority_check", None)
        if isinstance(precomputed, Mapping):
            return precomputed
        return {
            "status": "failed",
            "errors": ["Material authority report checker was not provided."],
            "warnings": [],
            "blocking_risk_flags": ["material_authority_checker_unavailable"],
            "review_risk_flags": [],
        }
    try:
        result = report_checker(report)
    except Exception as exc:
        return {
            "status": "failed",
            "errors": [f"Material authority report check crashed: {exc}"],
            "warnings": [],
            "blocking_risk_flags": ["material_authority_check_error"],
            "review_risk_flags": [],
        }
    return result if isinstance(result, Mapping) else {}


def material_authority_check_blockers(check_result: Mapping[str, object]) -> tuple[str, ...]:
    if str(check_result.get("status", "") or "") != "failed":
        return ()
    lines = [str(line) for line in tuple(check_result.get("errors", ()) or ()) if str(line or "").strip()]
    if not lines:
        flags = [str(flag) for flag in tuple(check_result.get("blocking_risk_flags", ()) or ()) if str(flag or "").strip()]
        if flags:
            lines.append("Blocking material authority risk flag(s): " + ", ".join(flags))
    return tuple(lines or ("Material authority report check failed.",))


def material_authority_check_review_lines(check_result: Mapping[str, object], *, limit: int = 8) -> tuple[str, ...]:
    if str(check_result.get("status", "") or "") not in {"needs_review", "failed"}:
        return ()
    warnings = [str(line) for line in tuple(check_result.get("warnings", ()) or ()) if str(line or "").strip()]
    flags = [str(flag) for flag in tuple(check_result.get("review_risk_flags", ()) or ()) if str(flag or "").strip()]
    if flags:
        warnings.insert(0, "Review material authority risk flag(s): " + ", ".join(flags[:limit]))
    return tuple(dict.fromkeys(warnings[:limit]))


__all__ = [
    "MaterialAuthorityReportChecker",
    "TextureProcessingPolicy",
    "available_texture_profile_keys",
    "check_final_preview_material_authority",
    "complete_swap_allows_inherited_layer_color_bindings",
    "complete_swap_authority_contract",
    "complete_swap_requires_true_source_authority",
    "material_authority_check_blockers",
    "material_authority_check_review_lines",
]
