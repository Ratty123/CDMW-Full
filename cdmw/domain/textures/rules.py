"""Pure texture workflow rule parsing, matching, and coercion."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import (
    DDS_FORMAT_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_FULL_CHAIN,
    DDS_MIP_MODE_MATCH_ORIGINAL,
    DDS_MIP_MODE_SINGLE,
    DDS_SIZE_MODE_ORIGINAL,
    DDS_SIZE_MODE_PNG,
    SUPPORTED_DDS_FORMAT_CHOICES,
    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
    UPSCALE_POST_CORRECTION_NONE,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
)
from cdmw.domain.textures.plan import _profile_for_key, _semantic_override_components
from cdmw.models import TextureRule, TextureWorkflowProfile

_VALID_RULE_COLORSPACE_OVERRIDES = frozenset({"srgb", "linear", "match_source"})
_VALID_RULE_ALPHA_POLICIES = frozenset({"none", "straight", "cutout_coverage", "channel_data", "premultiplied"})
_VALID_RULE_INTERMEDIATE_OVERRIDES = frozenset(
    {"visible_color_png_path", "technical_preserve_path", "technical_high_precision_path"}
)
_VALID_RULE_MATCH_MODES = frozenset({"glob", "exact"})
_VALID_WORKFLOW_PROFILE_ACTIONS = frozenset(
    {"", "upscale_then_rebuild", "rebuild_from_png", "preserve_original", "skip"}
)


def _validate_choice(value: str, allowed: Sequence[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"Unsupported {label}: {value}")
    return value


def _rule_matches_path(pattern: str, relative_path: Path, *, match_mode: str = "glob") -> bool:
    rel_posix = relative_path.as_posix().lower()
    basename = relative_path.name.lower()
    normalized_pattern = pattern.replace("\\", "/").strip().lower()
    if not normalized_pattern:
        return False
    if match_mode == "exact":
        return rel_posix == normalized_pattern
    return fnmatch.fnmatch(rel_posix, normalized_pattern) or fnmatch.fnmatch(basename, normalized_pattern)


def find_matching_texture_rule(relative_path: Path, rules: Sequence[TextureRule]) -> Optional[TextureRule]:
    for rule in reversed(tuple(rules)):
        if not bool(getattr(rule, "enabled", True)):
            continue
        if _rule_matches_path(rule.pattern, relative_path, match_mode=str(getattr(rule, "match_mode", "glob") or "glob")):
            return rule
    return None


def parse_texture_rules(raw_text: str) -> Tuple[TextureRule, ...]:
    rules: List[TextureRule] = []
    for line_number, raw_line in enumerate(raw_text.replace("\r", "\n").split("\n"), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in line.split(";") if part.strip()]
        if not parts:
            continue

        pattern = parts[0]
        if "=" in pattern:
            raise ValueError(f"Texture rule line {line_number} is missing the leading file pattern.")

        rule = TextureRule(pattern=pattern, source_line=line)
        for part in parts[1:]:
            if "=" not in part:
                raise ValueError(f"Texture rule line {line_number} has an invalid token: {part}")
            key, value = [piece.strip() for piece in part.split("=", 1)]
            lowered_key = key.lower()
            lowered_value = value.lower()
            if lowered_key == "action":
                if lowered_value not in {"process", "skip"}:
                    raise ValueError(f"Texture rule line {line_number} has an invalid action: {value}")
                rule.action = lowered_value
            elif lowered_key == "format":
                if lowered_value in {"match_original", "original"}:
                    rule.format_value = DDS_FORMAT_MODE_MATCH_ORIGINAL
                elif value in SUPPORTED_DDS_FORMAT_CHOICES:
                    rule.format_value = value
                else:
                    raise ValueError(f"Texture rule line {line_number} has an unsupported format: {value}")
            elif lowered_key == "size":
                if lowered_value in {DDS_SIZE_MODE_PNG, DDS_SIZE_MODE_ORIGINAL}:
                    rule.size_value = lowered_value
                elif re.match(r"^\d+x\d+$", lowered_value):
                    rule.size_value = lowered_value
                else:
                    raise ValueError(f"Texture rule line {line_number} has an invalid size: {value}")
            elif lowered_key in {"mips", "mipmaps", "mip"}:
                if lowered_value in {DDS_MIP_MODE_MATCH_ORIGINAL, DDS_MIP_MODE_FULL_CHAIN, DDS_MIP_MODE_SINGLE}:
                    rule.mip_value = lowered_value
                elif lowered_value.isdigit() and int(lowered_value) >= 1:
                    rule.mip_value = lowered_value
                else:
                    raise ValueError(f"Texture rule line {line_number} has an invalid mip setting: {value}")
            elif lowered_key in {"semantic", "semantics"}:
                _semantic_override_components(value)
                rule.semantic_value = lowered_value
            elif lowered_key == "profile":
                _profile_for_key(lowered_value)
                rule.profile_value = lowered_value
            elif lowered_key == "colorspace":
                if lowered_value not in _VALID_RULE_COLORSPACE_OVERRIDES:
                    raise ValueError(f"Texture rule line {line_number} has an invalid colorspace override: {value}")
                rule.colorspace_value = lowered_value
            elif lowered_key in {"alpha", "alpha_policy"}:
                if lowered_value not in _VALID_RULE_ALPHA_POLICIES:
                    raise ValueError(f"Texture rule line {line_number} has an invalid alpha policy override: {value}")
                rule.alpha_policy_value = lowered_value
            elif lowered_key in {"intermediate", "path"}:
                if lowered_value not in _VALID_RULE_INTERMEDIATE_OVERRIDES:
                    raise ValueError(f"Texture rule line {line_number} has an invalid intermediate override: {value}")
                rule.intermediate_value = lowered_value
            else:
                raise ValueError(f"Texture rule line {line_number} has an unknown key: {key}")

        rules.append(rule)

    return tuple(rules)


def _normalize_rule_match_mode(value: object) -> str:
    normalized = str(value or "").strip().lower() or "glob"
    if normalized not in _VALID_RULE_MATCH_MODES:
        raise ValueError(f"Unsupported texture rule match mode: {value}")
    return normalized


def _normalize_workflow_action_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "inherit":
        normalized = ""
    if normalized not in _VALID_WORKFLOW_PROFILE_ACTIONS:
        raise ValueError(f"Unsupported workflow profile action mode: {value}")
    return normalized


def _coerce_optional_positive_int(value: object, field_name: str) -> Optional[int]:
    if value in (None, "", False):
        return None
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{field_name} must be 0 or greater.")
    return parsed


def coerce_texture_workflow_profiles(raw_value: object) -> Tuple[TextureWorkflowProfile, ...]:
    if raw_value in (None, "", ()):
        return ()
    items = raw_value
    if isinstance(items, TextureWorkflowProfile):
        items = (items,)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise ValueError("Workflow profiles must be a sequence.")

    profiles: List[TextureWorkflowProfile] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(items, start=1):
        if isinstance(item, TextureWorkflowProfile):
            profile = TextureWorkflowProfile(
                profile_id=str(item.profile_id or "").strip(),
                label=str(item.label or "").strip(),
                action_mode=_normalize_workflow_action_mode(item.action_mode),
                format_value=str(item.format_value or "").strip() or None,
                size_value=str(item.size_value or "").strip().lower() or None,
                mip_value=str(item.mip_value or "").strip().lower() or None,
                ncnn_model_name=str(item.ncnn_model_name or "").strip(),
                ncnn_scale=_coerce_optional_positive_int(item.ncnn_scale, "Workflow profile NCNN scale"),
                ncnn_tile_size=_coerce_optional_positive_int(item.ncnn_tile_size, "Workflow profile NCNN tile size"),
                ncnn_extra_args=str(item.ncnn_extra_args or "").strip(),
                post_correction_mode=str(item.post_correction_mode or "").strip().lower(),
            )
        elif isinstance(item, Mapping):
            profile = TextureWorkflowProfile(
                profile_id=str(item.get("profile_id", "") or "").strip(),
                label=str(item.get("label", "") or "").strip(),
                action_mode=_normalize_workflow_action_mode(item.get("action_mode", "")),
                format_value=str(item.get("format_value", "") or "").strip() or None,
                size_value=str(item.get("size_value", "") or "").strip().lower() or None,
                mip_value=str(item.get("mip_value", "") or "").strip().lower() or None,
                ncnn_model_name=str(item.get("ncnn_model_name", "") or "").strip(),
                ncnn_scale=_coerce_optional_positive_int(item.get("ncnn_scale"), "Workflow profile NCNN scale"),
                ncnn_tile_size=_coerce_optional_positive_int(item.get("ncnn_tile_size"), "Workflow profile NCNN tile size"),
                ncnn_extra_args=str(item.get("ncnn_extra_args", "") or "").strip(),
                post_correction_mode=str(item.get("post_correction_mode", "") or "").strip().lower(),
            )
        else:
            raise ValueError(f"Workflow profile {index} is invalid.")

        if not profile.profile_id:
            raise ValueError(f"Workflow profile {index} is missing profile_id.")
        if not profile.label:
            raise ValueError(f"Workflow profile {index} is missing label.")
        if profile.profile_id in seen_ids:
            raise ValueError(f"Workflow profile id '{profile.profile_id}' is duplicated.")
        if profile.format_value and profile.format_value not in {DDS_FORMAT_MODE_MATCH_ORIGINAL, *SUPPORTED_DDS_FORMAT_CHOICES}:
            raise ValueError(f"Workflow profile '{profile.label}' has an unsupported DDS format override: {profile.format_value}")
        if profile.size_value:
            if profile.size_value not in {DDS_SIZE_MODE_PNG, DDS_SIZE_MODE_ORIGINAL} and not re.match(r"^\d+x\d+$", profile.size_value):
                raise ValueError(f"Workflow profile '{profile.label}' has an invalid DDS size override: {profile.size_value}")
        if profile.mip_value:
            if profile.mip_value not in {DDS_MIP_MODE_MATCH_ORIGINAL, DDS_MIP_MODE_FULL_CHAIN, DDS_MIP_MODE_SINGLE} and not (profile.mip_value.isdigit() and int(profile.mip_value) >= 1):
                raise ValueError(f"Workflow profile '{profile.label}' has an invalid DDS mip override: {profile.mip_value}")
        if profile.ncnn_scale is not None and profile.ncnn_scale not in {2, 3, 4}:
            raise ValueError(f"Workflow profile '{profile.label}' has an invalid NCNN scale override: {profile.ncnn_scale}")
        if profile.post_correction_mode:
            _validate_choice(
                profile.post_correction_mode,
                (
                    UPSCALE_POST_CORRECTION_NONE,
                    UPSCALE_POST_CORRECTION_MATCH_MEAN_LUMA,
                    UPSCALE_POST_CORRECTION_MATCH_LEVELS,
                    UPSCALE_POST_CORRECTION_MATCH_HISTOGRAM,
                    UPSCALE_POST_CORRECTION_SOURCE_MATCH_BALANCED,
                    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXTENDED,
                    UPSCALE_POST_CORRECTION_SOURCE_MATCH_EXPERIMENTAL,
                ),
                "workflow profile post-upscale correction mode",
            )
        profiles.append(profile)
        seen_ids.add(profile.profile_id)
    return tuple(profiles)


def coerce_texture_workflow_rules(raw_value: object) -> Tuple[TextureRule, ...]:
    if raw_value in (None, "", ()):
        return ()
    items = raw_value
    if isinstance(items, TextureRule):
        items = (items,)
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise ValueError("Texture workflow rules must be a sequence.")

    rules: List[TextureRule] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, TextureRule):
            rule = TextureRule(
                pattern=str(item.pattern or "").strip(),
                action=str(item.action or "process").strip().lower() or "process",
                format_value=str(item.format_value or "").strip() or None,
                size_value=str(item.size_value or "").strip().lower() or None,
                mip_value=str(item.mip_value or "").strip().lower() or None,
                semantic_value=str(item.semantic_value or "").strip().lower() or None,
                profile_value=str(item.profile_value or "").strip().lower() or None,
                colorspace_value=str(item.colorspace_value or "").strip().lower() or None,
                alpha_policy_value=str(item.alpha_policy_value or "").strip().lower() or None,
                intermediate_value=str(item.intermediate_value or "").strip().lower() or None,
                enabled=bool(getattr(item, "enabled", True)),
                match_mode=_normalize_rule_match_mode(getattr(item, "match_mode", "glob")),
                workflow_profile_id=str(getattr(item, "workflow_profile_id", "") or "").strip(),
                source_line=str(item.source_line or "").strip(),
            )
        elif isinstance(item, Mapping):
            rule = TextureRule(
                pattern=str(item.get("pattern", "") or "").strip(),
                action=str(item.get("action", "process") or "process").strip().lower() or "process",
                format_value=str(item.get("format_value", "") or "").strip() or None,
                size_value=str(item.get("size_value", "") or "").strip().lower() or None,
                mip_value=str(item.get("mip_value", "") or "").strip().lower() or None,
                semantic_value=str(item.get("semantic_value", "") or "").strip().lower() or None,
                profile_value=str(item.get("profile_value", "") or "").strip().lower() or None,
                colorspace_value=str(item.get("colorspace_value", "") or "").strip().lower() or None,
                alpha_policy_value=str(item.get("alpha_policy_value", "") or "").strip().lower() or None,
                intermediate_value=str(item.get("intermediate_value", "") or "").strip().lower() or None,
                enabled=bool(item.get("enabled", True)),
                match_mode=_normalize_rule_match_mode(item.get("match_mode", "glob")),
                workflow_profile_id=str(item.get("workflow_profile_id", "") or "").strip(),
                source_line=str(item.get("source_line", "") or "").strip(),
            )
        else:
            raise ValueError(f"Texture workflow rule {index} is invalid.")

        if not rule.pattern:
            raise ValueError(f"Texture workflow rule {index} is missing a pattern.")
        if rule.action not in {"process", "skip"}:
            raise ValueError(f"Texture workflow rule '{rule.pattern}' has an invalid legacy action: {rule.action}")
        if rule.semantic_value:
            _semantic_override_components(rule.semantic_value)
        if rule.profile_value:
            _profile_for_key(rule.profile_value)
        if rule.colorspace_value and rule.colorspace_value not in _VALID_RULE_COLORSPACE_OVERRIDES:
            raise ValueError(f"Texture workflow rule '{rule.pattern}' has an invalid colorspace override: {rule.colorspace_value}")
        if rule.alpha_policy_value and rule.alpha_policy_value not in _VALID_RULE_ALPHA_POLICIES:
            raise ValueError(f"Texture workflow rule '{rule.pattern}' has an invalid alpha policy override: {rule.alpha_policy_value}")
        if rule.intermediate_value and rule.intermediate_value not in _VALID_RULE_INTERMEDIATE_OVERRIDES:
            raise ValueError(f"Texture workflow rule '{rule.pattern}' has an invalid intermediate override: {rule.intermediate_value}")
        rules.append(rule)
    return tuple(rules)


def _make_unique_workflow_profile_id(seed: str, existing_ids: set[str], *, fallback_prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(seed or "").strip().lower()).strip("_") or fallback_prefix
    candidate = normalized
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{normalized}_{suffix}"
        suffix += 1
    existing_ids.add(candidate)
    return candidate


def migrate_legacy_texture_rules_to_structured(raw_text: str) -> Tuple[Tuple[TextureWorkflowProfile, ...], Tuple[TextureRule, ...]]:
    legacy_rules = parse_texture_rules(raw_text)
    if not legacy_rules:
        return (), ()

    profiles: List[TextureWorkflowProfile] = []
    rules: List[TextureRule] = []
    existing_profile_ids: set[str] = set()

    for index, legacy_rule in enumerate(legacy_rules, start=1):
        workflow_profile_id = ""
        if (
            legacy_rule.action == "skip"
            or legacy_rule.format_value
            or legacy_rule.size_value
            or legacy_rule.mip_value
        ):
            label_seed = legacy_rule.pattern or f"Imported Rule {index}"
            workflow_profile_id = _make_unique_workflow_profile_id(
                f"imported_{label_seed}",
                existing_profile_ids,
                fallback_prefix=f"imported_rule_{index}",
            )
            profiles.append(
                TextureWorkflowProfile(
                    profile_id=workflow_profile_id,
                    label=f"Imported Rule {index}",
                    action_mode="skip" if legacy_rule.action == "skip" else "",
                    format_value=legacy_rule.format_value,
                    size_value=legacy_rule.size_value,
                    mip_value=legacy_rule.mip_value,
                )
            )
        rules.append(
            TextureRule(
                pattern=legacy_rule.pattern,
                semantic_value=legacy_rule.semantic_value,
                profile_value=legacy_rule.profile_value,
                colorspace_value=legacy_rule.colorspace_value,
                alpha_policy_value=legacy_rule.alpha_policy_value,
                intermediate_value=legacy_rule.intermediate_value,
                enabled=True,
                match_mode="glob",
                workflow_profile_id=workflow_profile_id,
                source_line=legacy_rule.source_line or legacy_rule.pattern,
            )
        )

    return tuple(profiles), tuple(rules)


__all__ = [
    "_VALID_RULE_ALPHA_POLICIES",
    "_VALID_RULE_COLORSPACE_OVERRIDES",
    "_VALID_RULE_INTERMEDIATE_OVERRIDES",
    "_VALID_RULE_MATCH_MODES",
    "_VALID_WORKFLOW_PROFILE_ACTIONS",
    "_coerce_optional_positive_int",
    "_make_unique_workflow_profile_id",
    "_normalize_rule_match_mode",
    "_normalize_workflow_action_mode",
    "_rule_matches_path",
    "coerce_texture_workflow_profiles",
    "coerce_texture_workflow_rules",
    "find_matching_texture_rule",
    "migrate_legacy_texture_rules_to_structured",
    "parse_texture_rules",
]
