"""Learned PAC XML profile helpers.

The runtime material generator treats PAC XML as the authority.  These helpers
parse the parts that are safe to reason about without trying to rebuild Crimson
shader definitions from scratch.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Mapping as MappingABC
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence


PAC_XML_CORPUS_ROOT_ENV = "CDMW_PAC_XML_CORPUS_ROOT"
PAC_XML_SETTINGS_DIR_ENV = "CDMW_SETTINGS_DIR"
PAC_XML_PROFILE_INDEX_V1_CACHE_NAME = "pac_xml_profile_index_v1.json"
PAC_XML_PROFILE_INDEX_V2_CACHE_NAME = "pac_xml_profile_index_v2.sqlite"
PAC_XML_PROFILE_INDEX_CACHE_NAME = PAC_XML_PROFILE_INDEX_V2_CACHE_NAME
PAC_XML_PROFILE_INDEX_SCHEMA = "cdmw_pac_xml_profile_index_v1_paths"
PAC_XML_PROFILE_INDEX_SQLITE_SCHEMA = "cdmw_pac_xml_profile_index_v2_sqlite_compact"


def default_pac_xml_corpus_root() -> Path:
    raw = str(os.environ.get(PAC_XML_CORPUS_ROOT_ENV, "") or "").strip()
    return Path(raw).expanduser() if raw else Path()


@dataclass(frozen=True, slots=True)
class PacXmlTextureRef:
    wrapper_name: str
    parameter_name: str
    texture_path: str
    role: str
    stock_runtime: bool


@dataclass(frozen=True, slots=True)
class PacXmlAuthorityParameter:
    wrapper_name: str
    parameter_name: str
    parameter_type: str
    item_id: str = ""
    index: str = ""
    value: str = ""
    texture_path: str = ""
    role: str = ""
    category: str = ""
    reason: str = ""
    stock_runtime: bool = False

    def to_dict(self) -> dict[str, object]:
        numeric_value = _authority_parameter_numeric_value(self.value)
        color_rgba = _authority_parameter_color_rgba(self.value)
        return {
            "wrapper_name": self.wrapper_name,
            "parameter_name": self.parameter_name,
            "parameter_type": self.parameter_type,
            "item_id": self.item_id,
            "index": self.index,
            "value": self.value,
            "numeric_value": numeric_value,
            "color_rgba": color_rgba,
            "color_order": "rgba" if color_rgba else "",
            "texture_path": self.texture_path,
            "role": self.role,
            "category": self.category,
            "reason": self.reason,
            "stock_runtime": bool(self.stock_runtime),
        }


@dataclass(frozen=True, slots=True)
class PacXmlNeutralizationAction:
    wrapper_name: str
    parameter_name: str
    parameter_type: str
    item_id: str = ""
    index: str = ""
    texture_path: str = ""
    inherited_reason: str = ""
    action: str = ""
    action_status: str = ""
    required: bool = False
    preserve_runtime_abi: bool = True
    replacement_target: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "wrapper_name": self.wrapper_name,
            "parameter_name": self.parameter_name,
            "parameter_type": self.parameter_type,
            "item_id": self.item_id,
            "index": self.index,
            "texture_path": self.texture_path,
            "inherited_reason": self.inherited_reason,
            "action": self.action,
            "action_status": self.action_status,
            "required": bool(self.required),
            "preserve_runtime_abi": bool(self.preserve_runtime_abi),
            "replacement_target": self.replacement_target,
        }


@dataclass(frozen=True, slots=True)
class PacXmlAuthorityWrapper:
    order: int
    wrapper_name: str
    item_id: str = ""
    shader_name: str = ""
    parameter_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "order": int(self.order),
            "wrapper_name": self.wrapper_name,
            "item_id": self.item_id,
            "shader_name": self.shader_name,
            "parameter_count": int(self.parameter_count),
        }


@dataclass(frozen=True, slots=True)
class PacXmlSubmeshBinding:
    order: int
    wrapper_name: str
    item_id: str = ""
    id_base: str = ""
    shader_name: str = ""
    parameter_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "order": int(self.order),
            "wrapper_name": self.wrapper_name,
            "item_id": self.item_id,
            "id_base": self.id_base,
            "shader_name": self.shader_name,
            "parameter_count": int(self.parameter_count),
        }


@dataclass(frozen=True, slots=True)
class PacXmlMaterialAuthorityReport:
    path: str
    authority_contract: str
    profile_family: str = "unknown"
    profile_slot: str = ""
    shader_families: tuple[str, ...] = ()
    wrapper_count: int = 0
    wrapper_order: tuple[PacXmlAuthorityWrapper, ...] = ()
    submesh_bindings: tuple[PacXmlSubmeshBinding, ...] = ()
    parameter_count: int = 0
    runtime_abi_parameters: tuple[PacXmlAuthorityParameter, ...] = ()
    source_authority_parameters: tuple[PacXmlAuthorityParameter, ...] = ()
    inherited_influence_parameters: tuple[PacXmlAuthorityParameter, ...] = ()
    unknown_material_response_parameters: tuple[PacXmlAuthorityParameter, ...] = ()
    neutralization_actions: tuple[PacXmlNeutralizationAction, ...] = ()
    warnings: tuple[str, ...] = ()
    neutralization_policy: str = ""

    @property
    def status(self) -> str:
        return "needs_review" if self.warnings else "ok"

    def summary(self) -> str:
        slot = f"/{self.profile_slot}" if self.profile_slot else ""
        shaders = ", ".join(self.shader_families) if self.shader_families else "unknown"
        return (
            f"PAC XML material authority: contract={self.authority_contract or 'unspecified'}; "
            f"profile={self.profile_family}{slot}; shaders={shaders}; wrappers={self.wrapper_count}; "
            f"params={self.parameter_count}; inherited={len(self.inherited_influence_parameters)}; "
            f"unknown={len(self.unknown_material_response_parameters)}; status={self.status}."
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "authority_contract": self.authority_contract,
            "profile_family": self.profile_family,
            "profile_slot": self.profile_slot,
            "shader_families": list(self.shader_families),
            "wrapper_count": int(self.wrapper_count),
            "wrapper_order": [wrapper.to_dict() for wrapper in self.wrapper_order],
            "submesh_bindings": [binding.to_dict() for binding in self.submesh_bindings],
            "parameter_count": int(self.parameter_count),
            "scalar_ranges": _authority_scalar_ranges(
                self.runtime_abi_parameters,
                self.source_authority_parameters,
                self.inherited_influence_parameters,
                self.unknown_material_response_parameters,
            ),
            "color_parameters": _authority_color_parameter_rows(
                self.runtime_abi_parameters,
                self.source_authority_parameters,
                self.inherited_influence_parameters,
                self.unknown_material_response_parameters,
            ),
            "alpha_controls": _authority_alpha_control_rows(
                self.runtime_abi_parameters,
                self.source_authority_parameters,
                self.inherited_influence_parameters,
                self.unknown_material_response_parameters,
            ),
            "runtime_abi_parameters": [parameter.to_dict() for parameter in self.runtime_abi_parameters],
            "source_authority_parameters": [parameter.to_dict() for parameter in self.source_authority_parameters],
            "inherited_influence_parameters": [parameter.to_dict() for parameter in self.inherited_influence_parameters],
            "unknown_material_response_parameters": [
                parameter.to_dict() for parameter in self.unknown_material_response_parameters
            ],
            "neutralization_actions": [action.to_dict() for action in self.neutralization_actions],
            "warnings": list(self.warnings),
            "neutralization_policy": self.neutralization_policy,
            "status": self.status,
            "summary": self.summary(),
        }


def _authority_parameter_numeric_value(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text.startswith("#") or len(text.split()) != 1:
        return None
    try:
        return float(text)
    except (TypeError, ValueError, OverflowError):
        return None


def _authority_parameter_color_rgba(value: object) -> tuple[int, int, int, int]:
    text = str(value or "").strip()
    if not text:
        return ()
    if text.startswith("#"):
        hex_value = re.sub(r"[^0-9a-fA-F]+", "", text)
        if len(hex_value) == 6:
            hex_value += "ff"
        if len(hex_value) == 8:
            try:
                return tuple(int(hex_value[index : index + 2], 16) for index in (0, 2, 4, 6))  # type: ignore[return-value]
            except ValueError:
                return ()
    parts = text.split()
    if len(parts) == 4:
        try:
            values = [float(part) for part in parts]
        except (TypeError, ValueError, OverflowError):
            return ()
        if all(0.0 <= value <= 1.0 for value in values):
            return tuple(max(0, min(255, int(round(value * 255.0)))) for value in values)  # type: ignore[return-value]
        if all(0.0 <= value <= 255.0 for value in values):
            return tuple(max(0, min(255, int(round(value)))) for value in values)  # type: ignore[return-value]
    return ()


def _authority_scalar_ranges(*groups: Sequence[PacXmlAuthorityParameter]) -> list[dict[str, object]]:
    by_name: dict[str, dict[str, object]] = {}
    for parameter in _authority_parameter_groups(*groups):
        numeric_value = _authority_parameter_numeric_value(parameter.value)
        if numeric_value is None:
            continue
        key = parameter.parameter_name or parameter.parameter_type or "<unknown>"
        row = by_name.setdefault(
            key,
            {
                "parameter_name": key,
                "parameter_type": parameter.parameter_type,
                "count": 0,
                "min": numeric_value,
                "max": numeric_value,
                "categories": set(),
            },
        )
        row["count"] = int(row["count"]) + 1
        row["min"] = min(float(row["min"]), numeric_value)
        row["max"] = max(float(row["max"]), numeric_value)
        categories = row.get("categories")
        if isinstance(categories, set) and parameter.category:
            categories.add(parameter.category)
    output: list[dict[str, object]] = []
    for row in by_name.values():
        categories = row.get("categories")
        output.append(
            {
                "parameter_name": row["parameter_name"],
                "parameter_type": row["parameter_type"],
                "count": row["count"],
                "min": row["min"],
                "max": row["max"],
                "categories": tuple(sorted(categories)) if isinstance(categories, set) else (),
            }
        )
    return sorted(output, key=lambda item: str(item["parameter_name"]).lower())


def _authority_color_parameter_rows(*groups: Sequence[PacXmlAuthorityParameter]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for parameter in _authority_parameter_groups(*groups):
        color_rgba = _authority_parameter_color_rgba(parameter.value)
        if not color_rgba:
            continue
        rows.append(
            {
                "wrapper_name": parameter.wrapper_name,
                "parameter_name": parameter.parameter_name,
                "parameter_type": parameter.parameter_type,
                "item_id": parameter.item_id,
                "index": parameter.index,
                "value": parameter.value,
                "color_rgba": color_rgba,
                "color_order": "rgba",
                "category": parameter.category,
                "reason": parameter.reason,
            }
        )
    return sorted(rows, key=lambda item: (str(item["wrapper_name"]).lower(), str(item["parameter_name"]).lower()))


def _authority_alpha_control_rows(*groups: Sequence[PacXmlAuthorityParameter]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for parameter in _authority_parameter_groups(*groups):
        key = _compact_parameter_name(parameter.parameter_name)
        mode = _authority_alpha_control_mode(key)
        if not mode:
            continue
        rows.append(
            {
                "wrapper_name": parameter.wrapper_name,
                "parameter_name": parameter.parameter_name,
                "parameter_type": parameter.parameter_type,
                "item_id": parameter.item_id,
                "index": parameter.index,
                "value": parameter.value,
                "numeric_value": _authority_parameter_numeric_value(parameter.value),
                "mode": mode,
                "category": parameter.category,
                "reason": parameter.reason,
            }
        )
    return sorted(rows, key=lambda item: (str(item["wrapper_name"]).lower(), str(item["parameter_name"]).lower()))


def _authority_alpha_control_mode(key: str) -> str:
    if not key or "colorblending" in key:
        return ""
    if "alphatest" in key:
        return "alpha_test"
    if "alphablend" in key or (("alpha" in key or "opacity" in key or "transparent" in key) and "blend" in key):
        return "alpha_blend"
    if "cutout" in key or "alphacutoff" in key or "alphacutout" in key:
        return "alpha_cutout"
    if "opacity" in key or "transparent" in key:
        return "opacity"
    if "alpha" in key:
        return "alpha"
    if "doublesided" in key or "twosided" in key:
        return "two_sided"
    if "cullmode" in key:
        return "cull_mode"
    return ""


def _authority_parameter_groups(*groups: Sequence[PacXmlAuthorityParameter]) -> tuple[PacXmlAuthorityParameter, ...]:
    rows: list[PacXmlAuthorityParameter] = []
    for group in groups:
        rows.extend(tuple(group or ()))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class PacXmlWrapperProfile:
    wrapper_name: str
    shader_name: str
    shader_family: str
    role: str
    render_setting_flag: str = ""
    parameter_names: tuple[str, ...] = ()
    parameter_types: tuple[str, ...] = ()
    texture_refs: tuple[PacXmlTextureRef, ...] = ()


@dataclass(frozen=True, slots=True)
class PacXmlProfile:
    family: str
    slot: str = ""
    profiles: tuple[str, ...] = ()
    confidence: float = 0.0
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PacXmlProfileReport:
    path: str
    profile: PacXmlProfile
    paired_model_path: str = ""
    wrappers: tuple[PacXmlWrapperProfile, ...] = ()
    pbd_materials: tuple[str, ...] = ()
    texture_ref_count: int = 0
    stock_texture_ref_count: int = 0

    @property
    def shader_families(self) -> tuple[str, ...]:
        return tuple(sorted({wrapper.shader_family for wrapper in self.wrappers if wrapper.shader_family}))

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(sorted({wrapper.role for wrapper in self.wrappers if wrapper.role}))

    def summary(self) -> str:
        profile_bits = ", ".join(self.profile.profiles) if self.profile.profiles else "none"
        shader_bits = ", ".join(self.shader_families) if self.shader_families else "unknown"
        role_bits = ", ".join(self.roles) if self.roles else "unknown"
        slot = f"/{self.profile.slot}" if self.profile.slot else ""
        return (
            f"PAC XML profile: family={self.profile.family}{slot}; shaders={shader_bits}; "
            f"roles={role_bits}; profiles={profile_bits}; wrappers={len(self.wrappers)}; "
            f"texture_refs={self.texture_ref_count} stock={self.stock_texture_ref_count}."
        )


@dataclass(frozen=True, slots=True)
class PacXmlProfileMatchReport:
    chosen_profile: PacXmlProfileReport
    similarity_score: float
    preserved_params: int
    patched_params: int
    generated_dds: int
    missing_refs: tuple[str, ...] = ()
    unsafe_refs: tuple[str, ...] = ()
    fallback_reason: str = ""

    def summary(self) -> str:
        profile = self.chosen_profile.profile
        slot = f"/{profile.slot}" if profile.slot else ""
        fallback = f"; fallback={self.fallback_reason}" if self.fallback_reason else ""
        return (
            f"PAC XML match: chosen={profile.family}{slot}; similarity={self.similarity_score:.2f}; "
            f"preserved_params={self.preserved_params}; patched_params={self.patched_params}; "
            f"generated_dds={self.generated_dds}; missing_refs={len(self.missing_refs)}; "
            f"unsafe_refs={len(self.unsafe_refs)}{fallback}."
        )


@dataclass(frozen=True, slots=True)
class PacXmlTemplateMatch:
    template_path: str = ""
    template_model_path: str = ""
    template_wrapper_name: str = ""
    template_parameter_name: str = ""
    template_shader_name: str = ""
    template_shader_family: str = ""
    score: float = 0.0
    supports_slot: bool = False
    fallback_reason: str = ""

    def summary(self, *, target_name: str = "", slot_kind: str = "") -> str:
        target = f" target={target_name}" if target_name else ""
        slot = f" slot={slot_kind}" if slot_kind else ""
        parameter = f" param={self.template_parameter_name}" if self.template_parameter_name else ""
        model = f" model={self.template_model_path}" if self.template_model_path else ""
        shader = f" shader={self.template_shader_family}" if self.template_shader_family else ""
        fallback = f" fallback={self.fallback_reason}" if self.fallback_reason else ""
        return (
            f"PAC XML corpus template:{target}{slot} template={self.template_path or '<none>'} "
            f"wrapper={self.template_wrapper_name or '<none>'}{parameter}{model}{shader} score={self.score:.2f}"
            f"{fallback}."
        )


@dataclass(slots=True)
class PacXmlCorpusIndex:
    root: Path
    cache_path: Path = field(default_factory=Path)
    sqlite_backed: bool = False
    source_file_count: int = 0
    newest_mtime_ns: int = 0
    xml_count: int = 0
    paired_model_count: int = 0
    wrapper_count: int = 0
    parameter_count: int = 0
    texture_ref_count: int = 0
    families: Counter[str] = field(default_factory=Counter)
    shader_families: Counter[str] = field(default_factory=Counter)
    roles: Counter[str] = field(default_factory=Counter)
    parameter_types: Counter[str] = field(default_factory=Counter)
    profiles: list[PacXmlProfileReport] = field(default_factory=list)


_STOCK_RUNTIME_TEXTURE_PREFIXES = (
    "character/texture/cd_texturelayer_",
    "character/texture/cd_common_default",
    "character/texture/v_common_default",
    "character/texture/cd_temp_",
    "character/texture/cd_unique_edge_detail_",
    "texture/nonetexture",
)
_STOCK_RUNTIME_TEXTURE_TOKENS = (
    "/cd_texturelayer_",
    "/cd_common_default",
    "/v_common_default",
    "/cd_temp_",
    "/cd_unique_edge_detail_",
    "/nonetexture",
)


def normalize_pac_xml_path(value: str | Path | PurePosixPath) -> str:
    text = str(value or "").replace("\\", "/").strip()
    return re.sub(r"/+", "/", text)


def _normalized_key(value: str | Path | PurePosixPath) -> str:
    return normalize_pac_xml_path(value).lower()


def is_stock_runtime_texture_path(value: str | Path | PurePosixPath) -> bool:
    key = _normalized_key(value)
    if not key:
        return False
    basename = PurePosixPath(key).name
    basename_stock = basename.startswith(
        (
            "cd_texturelayer_",
            "cd_common_default",
            "v_common_default",
            "cd_temp_",
            "cd_unique_edge_detail_",
            "nonetexture",
        )
    )
    return (
        key.startswith(_STOCK_RUNTIME_TEXTURE_PREFIXES)
        or any(token in key for token in _STOCK_RUNTIME_TEXTURE_TOKENS)
        or basename_stock
    )


def _pac_xml_settings_root(settings_dir: str | Path | None = None) -> Path:
    if settings_dir is not None and str(settings_dir or "").strip():
        return Path(settings_dir).expanduser()
    elif str(os.environ.get(PAC_XML_SETTINGS_DIR_ENV, "") or "").strip():
        return Path(str(os.environ.get(PAC_XML_SETTINGS_DIR_ENV, "") or "")).expanduser()
    elif os.environ.get("APPDATA"):
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "CDMW"
    else:
        return Path.home() / ".cdmw"


def default_pac_xml_profile_cache_path(settings_dir: str | Path | None = None) -> Path:
    return _pac_xml_settings_root(settings_dir) / PAC_XML_PROFILE_INDEX_V2_CACHE_NAME


def legacy_pac_xml_profile_cache_path(settings_dir: str | Path | None = None) -> Path:
    return _pac_xml_settings_root(settings_dir) / PAC_XML_PROFILE_INDEX_V1_CACHE_NAME


def _sqlite_cache_path_for(cache_path: str | Path | None = None) -> Path:
    if cache_path is None or not str(cache_path or "").strip():
        return default_pac_xml_profile_cache_path()
    path = Path(cache_path).expanduser()
    if path.name == PAC_XML_PROFILE_INDEX_V1_CACHE_NAME or path.suffix.lower() == ".json":
        return path.with_name(PAC_XML_PROFILE_INDEX_V2_CACHE_NAME)
    return path


def clear_pac_xml_profile_index_cache(settings_dir: str | Path | None = None) -> tuple[Path, ...]:
    removed: list[Path] = []
    for path in (
        legacy_pac_xml_profile_cache_path(settings_dir),
        default_pac_xml_profile_cache_path(settings_dir),
    ):
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
            try:
                if candidate.exists():
                    candidate.unlink()
                    removed.append(candidate)
            except OSError:
                pass
    return tuple(removed)


def classify_pac_xml_shader_family(shader_name: str) -> str:
    shader = str(shader_name or "").strip()
    compact = re.sub(r"[^a-z0-9]+", "", shader.lower())
    if not compact:
        return "Unknown"
    if "cloth" in compact or "torncloth" in compact:
        return "Cloth"
    if "hair" in compact:
        return "Hair"
    if "fur" in compact:
        return "Fur"
    if "eyecover" in compact:
        return "EyeCover"
    if "eye" in compact:
        return "Eye"
    if "emissive" in compact:
        return "Emissive"
    if "poster" in compact:
        return "Poster"
    if "chain" in compact:
        return "Chain"
    if "staticstandard" in compact:
        return "StaticStandard"
    if "standardver2" in compact:
        return "Standard_Ver2"
    if "standard" in compact:
        return "Standard"
    if "skinwrinkle" in compact:
        return "SkinWrinkle"
    if "skin" in compact and "skinnedmesh" not in compact.replace("skinnedmesh", "", 1):
        return "Skin"
    return shader or "Unknown"


def classify_pac_xml_wrapper_role(wrapper_name: str, path: str = "") -> str:
    text = f"{wrapper_name} {path}".lower()
    compact = re.sub(r"[^a-z0-9]+", "_", text)
    token_set = set(filter(None, compact.split("_")))
    if {"blade", "edge"} & token_set:
        return "blade"
    if {"axe", "head", "spear", "pike", "muzzle", "barrel"} & token_set:
        if "head" in token_set and "hel" not in token_set and "helmet" not in token_set:
            return "head"
        return "blade"
    if {"handle", "grip", "stick", "stock"} & token_set:
        return "handle"
    if {"guard", "crossguard", "hilt"} & token_set:
        return "guard"
    if {"shield", "face"} & token_set:
        return "shield_face"
    if {"cloak", "cloth", "flag", "cape"} & token_set:
        return "cloak"
    if {"hair", "beard", "eyebrow"} & token_set:
        return "hair"
    if {"eye", "pupil", "iris"} & token_set:
        return "eye"
    if {"skin", "head"} & token_set:
        return "skin"
    if {"ub", "upperbody", "body", "vest", "jacket"} & token_set:
        return "upperbody"
    if {"lb", "lowerbody", "leg"} & token_set:
        return "lowerbody"
    if {"hel", "helmet", "mask"} & token_set:
        return "helmet"
    if {"hand", "glove"} & token_set:
        return "hand"
    if {"foot", "boot", "sho"} & token_set:
        return "foot"
    if {"acc", "accessory", "ornament"} & token_set:
        return "acc"
    return "body"


def classify_pac_xml_profile(path: str | Path, xml_text: str | None = None) -> PacXmlProfile:
    key = _normalized_key(path)
    evidence: list[str] = []
    profiles: list[str] = []
    family = "unknown"
    slot = ""
    confidence = 0.2
    xml = str(xml_text or "")
    xml_lower = xml.lower()

    def add_profile(name: str, reason: str = "") -> None:
        if name and name not in profiles:
            profiles.append(name)
        if reason:
            evidence.append(reason)

    if "/weapon/" in key or any(
        token in key
        for token in (
            "/1_onehandweapon/",
            "/2_twohandweapon/",
            "/3_shield/",
            "/4_bow/",
            "/10_thrownweapon/",
            "/12_pike/",
            "/13_fist/",
            "/0_tools/",
        )
    ):
        family = "weapon"
        confidence = 0.95
        evidence.append("weapon path")
        if "shield" in key or "/3_shield/" in key:
            slot = "shield"
        elif "bow" in key or "crossbow" in key:
            slot = "bow"
        elif "pike" in key or "spear" in key or "/12_pike/" in key:
            slot = "pike"
        elif "musket" in key or "matchlock" in key or "barrel" in key:
            slot = "musket"
        elif "axe" in key:
            slot = "axe"
        elif "sword" in key:
            slot = "sword"
        elif "fishingrod" in key or "/0_tools/" in key:
            slot = "tool"
    elif "/head/hair/" in key or "/hair/" in key or "_hair_" in key or "_hair_acc_" in key:
        family = "hair"
        confidence = 0.95
        evidence.append("hair path")
    elif "/head/head/" in key or "/head/head_sub/" in key or "_head_" in key or "_head_sub_" in key:
        family = "head"
        confidence = 0.9
        evidence.append("head path")
    elif "/armor/" in key or any(
        token in key
        for token in (
            "/9_upperbody/",
            "/10_lowerbody/",
            "/11_hand/",
            "/12_foot/",
            "/13_hel/",
            "/14_sho/",
            "/15_vest/",
            "/16_jacket/",
            "/17_belt/",
            "/18_acc/",
            "/19_cloak/",
            "/20_mask/",
        )
    ):
        family = "armor"
        confidence = 0.95
        evidence.append("armor path")
        slot = _armor_slot_from_path(key)
    elif any(token in key for token in ("/monster/", "/mon/", "/npcmonster/", "/boss/", "/creature/")):
        family = "monster"
        confidence = 0.9
        evidence.append("monster path")
        if any(token in key for token in ("machine", "mechanic", "mecha", "golem", "construct", "vehicle")):
            slot = "mechanical"
        else:
            slot = "organic"
    elif any(token in key for token in ("/riding/", "/mount/", "/vehicle/", "/wagon/", "/horse/", "/camel/")):
        family = "riding"
        confidence = 0.85
        evidence.append("riding/mount path")
        if any(token in key for token in ("wagon", "vehicle", "boat", "ship", "cart", "carriage", "sled")):
            slot = "vehicle"
        else:
            slot = "animal"
    elif re.search(r"/(?:t|cd_[mr])\d{3,}[_/]", key) or any(
        token in key for token in ("dropitem", "gimmick", "wagon", "flag", "lantern", "pot", "chair", "door", "tool", "static")
    ):
        family = "prop"
        confidence = 0.75
        evidence.append("prop/static path")
        if any(token in key for token in ("tool", "fishingrod", "pickaxe", "axe", "hammer")):
            slot = "tool"
        elif any(token in key for token in ("poster", "flag", "sign")):
            slot = "static"
        else:
            slot = "prop"

    if xml:
        if re.search(r'_materialName="[^"]*(?:Cloth|TornCloth)[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("cloth", "cloth shader")
        if re.search(r'_materialName="[^"]*Hair[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("hair_physics", "hair shader")
            if family == "unknown":
                family = "hair"
                confidence = max(confidence, 0.8)
        if re.search(r'_materialName="[^"]*Fur[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("fur", "fur shader")
            if family == "monster" and not slot:
                slot = "organic"
        if re.search(r'_materialName="[^"]*(?:Eye|EyeCover)[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("eye", "eye shader")
        if re.search(r'_materialName="[^"]*Skin[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("skin", "skin shader")
            if family == "unknown":
                family = "head"
                confidence = max(confidence, 0.75)
        if re.search(r'_pbdSimulationMaterialName="[^"]*(?:Cloth|Cloak|Fabric|Flag|Spline|Hair)[^"]*"', xml, flags=re.IGNORECASE):
            add_profile("cloth" if "hair" not in xml_lower else "hair_physics", "pbd material")
        if 'weaponspline' in xml_lower:
            add_profile("spline", "WeaponSpline")
            if family == "unknown":
                family = "weapon"
                confidence = max(confidence, 0.75)

    return PacXmlProfile(
        family=family,
        slot=slot,
        profiles=tuple(profiles),
        confidence=confidence,
        evidence=tuple(evidence),
    )


def _armor_slot_from_path(key: str) -> str:
    mapping = (
        ("13_hel", "helmet"),
        ("20_mask", "face"),
        ("19_cloak", "cloak"),
        ("9_upperbody", "body"),
        ("15_vest", "body"),
        ("16_jacket", "body"),
        ("10_lowerbody", "legs"),
        ("11_hand", "hands"),
        ("12_foot", "feet"),
        ("14_sho", "feet"),
        ("17_belt", "accessory"),
        ("18_acc", "accessory"),
    )
    for token, slot in mapping:
        if f"/{token}/" in key:
            return slot
    return ""


def infer_pac_xml_texture_role(parameter_name: str, texture_path: str = "") -> str:
    name = re.sub(r"[^a-z0-9]+", "", str(parameter_name or "").lower())
    path = _normalized_key(texture_path)
    if "flow" in name:
        return "flow"
    if "wrinklemask" in name:
        return "wrinkle_mask"
    if "wrinklecolor" in name:
        return "wrinkle_color"
    if "hairdirection" in name or "ssdm" in name:
        return "flow"
    if "normal" in name or path.endswith("_n.dds"):
        return "normal"
    if path.endswith("_f.dds"):
        return "flow"
    if "pupil" in name:
        return "pupil"
    if "iris" in name:
        return "iris"
    if "alpha" in name or "opacity" in name or path.endswith("_alpha.dds"):
        return "opacity"
    if "height" in name or "displacement" in name or path.endswith("_disp.dds"):
        return "height"
    if "detailmask" in name or path.endswith("_mg.dds"):
        return "detail_mask"
    if "colorblendingmask" in name or "material" in name or path.endswith(("_ma.dds", "_m.dds", "_sp.dds")):
        return "material_mask"
    if "emissive" in name or path.endswith("_emi.dds"):
        return "emissive"
    if (name == "masktexture" or name.endswith("masktexture")) and not path:
        return "material_mask"
    if name == "masktexture" or name.endswith("masktexture"):
        return "mask"
    if any(token in name for token in ("overlaycolor", "basecolor", "diffuse", "albedo", "rgbtexture")):
        return "base"
    return "unknown"


def parse_pac_xml_profile(sidecar_text: str, sidecar_path: str | Path = "") -> PacXmlProfileReport:
    text = str(sidecar_text or "")
    path = normalize_pac_xml_path(sidecar_path)
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    wrappers: list[PacXmlWrapperProfile] = []
    texture_ref_count = 0
    stock_texture_ref_count = 0
    for match in wrapper_pattern.finditer(text):
        attrs = match.group("attrs") or ""
        body = match.group("body") or ""
        wrapper_name = _xml_attr(attrs, "_subMeshName")
        shader = _first_match(body, r'<Material\b[^>]*\b_materialName="([^"]*)"')
        params: list[str] = []
        param_types: list[str] = []
        for param_match in re.finditer(r"<MaterialParameter(?P<kind>[A-Za-z0-9_:.-]*)\b(?P<attrs>[^>]*)", body, flags=re.IGNORECASE):
            param_name = _xml_attr(param_match.group("attrs") or "", "_name") or _xml_attr(param_match.group("attrs") or "", "Name")
            if param_name:
                params.append(param_name)
                param_types.append(param_match.group("kind") or "")
        render_flag = _first_match(body, r'<MaterialParameterBitFlag32\b[^>]*(?:_name|Name)="_renderSettingFlag"[^>]*(?:_value|Value)="([^"]*)"')
        refs: list[PacXmlTextureRef] = []
        def add_texture_ref(param_name: str, texture_path: str) -> None:
            role = infer_pac_xml_texture_role(param_name, texture_path)
            stock = is_stock_runtime_texture_path(texture_path)
            refs.append(PacXmlTextureRef(wrapper_name, param_name, normalize_pac_xml_path(texture_path), role, stock))
            nonlocal_texture_counts[0] += 1
            if stock:
                nonlocal_texture_counts[1] += 1

        nonlocal_texture_counts = [0, 0]
        for tex_match in re.finditer(
            r"<MaterialParameterTexture\b(?P<attrs>[^>]*)>(?P<body>.*?)</MaterialParameterTexture>",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            param_name = _xml_attr(tex_match.group("attrs") or "", "_name") or _xml_attr(tex_match.group("attrs") or "", "Name")
            texture_path = _first_match(tex_match.group("body") or "", r'\b(?:_path|path|Path|_value|Value|value)="([^"]*)"')
            add_texture_ref(param_name, texture_path)
        for tex_match in re.finditer(
            r"<MaterialParameterTexture\b(?P<attrs>[^>]*)/>",
            body,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            attrs = tex_match.group("attrs") or ""
            param_name = _xml_attr(attrs, "_name") or _xml_attr(attrs, "Name")
            texture_path = _xml_attr(attrs, "_path") or _xml_attr(attrs, "path") or _xml_attr(attrs, "Path")
            if not texture_path:
                texture_path = _xml_attr(attrs, "_value") or _xml_attr(attrs, "Value") or _xml_attr(attrs, "value")
            add_texture_ref(param_name, texture_path)
        texture_ref_count += nonlocal_texture_counts[0]
        stock_texture_ref_count += nonlocal_texture_counts[1]
        wrappers.append(
            PacXmlWrapperProfile(
                wrapper_name=wrapper_name,
                shader_name=shader,
                shader_family=classify_pac_xml_shader_family(shader),
                role=classify_pac_xml_wrapper_role(wrapper_name, path),
                render_setting_flag=render_flag,
                parameter_names=tuple(params),
                parameter_types=tuple(param_types),
                texture_refs=tuple(refs),
            )
        )
    pbd_materials = tuple(
        dict.fromkeys(
            value.strip()
            for value in re.findall(r'_pbdSimulationMaterialName="([^"]*)"', text, flags=re.IGNORECASE)
            if value.strip()
        )
    )
    return PacXmlProfileReport(
        path=path,
        profile=classify_pac_xml_profile(path, text),
        wrappers=tuple(wrappers),
        pbd_materials=pbd_materials,
        texture_ref_count=texture_ref_count,
        stock_texture_ref_count=stock_texture_ref_count,
    )


def build_pac_xml_material_authority_report(
    sidecar_text: str,
    sidecar_path: str | Path = "",
    *,
    authority_contract: str = "true_source_authority",
) -> PacXmlMaterialAuthorityReport:
    """Classify target PAC/PAMI material parameters for source-authority replacement review."""

    text = str(sidecar_text or "")
    path = normalize_pac_xml_path(sidecar_path)
    contract = _normalize_authority_contract(authority_contract)
    profile_report = parse_pac_xml_profile(text, path)
    wrapper_order = _parse_material_authority_wrappers(text)
    submesh_bindings = _parse_material_authority_submesh_bindings(text)
    parameters = _parse_material_authority_parameters(text)
    runtime_abi: list[PacXmlAuthorityParameter] = []
    source_authority: list[PacXmlAuthorityParameter] = []
    inherited: list[PacXmlAuthorityParameter] = []
    unknown: list[PacXmlAuthorityParameter] = []
    for parameter in parameters:
        category, reason = _classify_material_authority_parameter(parameter)
        categorized = replace(parameter, category=category, reason=reason)
        if category == "runtime_abi":
            runtime_abi.append(categorized)
        elif category == "inherited_influence":
            inherited.append(categorized)
        elif category == "unknown_material_response":
            unknown.append(categorized)
        else:
            source_authority.append(categorized)

    warnings: list[str] = []
    if inherited:
        if contract == "runtime_xml_preserve":
            prefix = "Runtime XML preserve warning"
            action = "keeps target-side influence"
        else:
            prefix = "True source authority warning"
            action = "must neutralize or replace target-side influence"
        for parameter in inherited[:12]:
            location = _authority_parameter_location(parameter)
            detail = f" ({parameter.texture_path})" if parameter.texture_path else ""
            warnings.append(f"{prefix}: {location} {action}: {parameter.reason}{detail}.")
        if len(inherited) > 12:
            warnings.append(f"{prefix}: {len(inherited) - 12:,} more inherited target-side influence parameter(s).")
    if unknown:
        for parameter in unknown[:12]:
            warnings.append(
                "Material authority review: unknown material-response parameter "
                f"{_authority_parameter_location(parameter)} ({parameter.parameter_type})."
            )
        if len(unknown) > 12:
            warnings.append(f"Material authority review: {len(unknown) - 12:,} more unknown response parameter(s).")

    neutralization_actions = _material_neutralization_actions(inherited, contract)
    policy = (
        "Preserve target PAC XML runtime ABI: wrapper order, shader family, render flags, IDs, and protected cloth/PBD hooks. "
        "Runtime XML preserve keeps target tint/dye/detail/grime/shared texture-layer response and reports it as review risk."
        if contract == "runtime_xml_preserve"
        else "Preserve target PAC XML runtime ABI: wrapper order, shader family, render flags, IDs, and protected cloth/PBD hooks. "
        "For active source-owned wrappers, neutralize or replace target tint/dye/detail/grime/shared texture-layer "
        "parameters so source DDS/PBR is the visible material authority."
    )
    return PacXmlMaterialAuthorityReport(
        path=path,
        authority_contract=contract,
        profile_family=profile_report.profile.family,
        profile_slot=profile_report.profile.slot,
        shader_families=profile_report.shader_families,
        wrapper_count=len(profile_report.wrappers),
        wrapper_order=wrapper_order,
        submesh_bindings=submesh_bindings,
        parameter_count=len(parameters),
        runtime_abi_parameters=tuple(runtime_abi),
        source_authority_parameters=tuple(source_authority),
        inherited_influence_parameters=tuple(inherited),
        unknown_material_response_parameters=tuple(unknown),
        neutralization_actions=neutralization_actions,
        warnings=tuple(dict.fromkeys(warnings)),
        neutralization_policy=policy,
    )


def _normalize_authority_contract(value: str) -> str:
    compact = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    aliases = {
        "runtime_xml": "runtime_xml_preserve",
        "runtimexml": "runtime_xml_preserve",
        "runtime_xml_authority": "runtime_xml_preserve",
        "preserve": "runtime_xml_preserve",
        "source": "true_source_authority",
        "true_source": "true_source_authority",
        "source_authority": "true_source_authority",
        "strict_source": "true_source_authority",
        "detail_mask_authority": "true_source_authority_detail_mask",
        "true_source_detail_mask": "true_source_authority_detail_mask",
    }
    compact = aliases.get(compact, compact)
    if compact in {"runtime_xml_preserve", "true_source_authority", "true_source_authority_detail_mask"}:
        return compact
    return compact or "true_source_authority"


def _material_neutralization_actions(
    inherited: Sequence[PacXmlAuthorityParameter],
    contract: str,
) -> tuple[PacXmlNeutralizationAction, ...]:
    rows: list[PacXmlNeutralizationAction] = []
    for parameter in tuple(inherited or ()):
        if contract == "runtime_xml_preserve":
            action = "preserve_and_report_target_influence"
            action_status = "reported_only"
            required = False
            replacement_target = "runtime XML preserved target response"
        elif contract == "true_source_authority_detail_mask" and parameter.role == "detail_mask":
            action = "replace_with_source_owned_detail_mask_or_neutral_default"
            action_status = "required"
            required = True
            replacement_target = "source DDS detail mask or neutral detail mask"
        elif parameter.texture_path:
            action = "replace_with_source_owned_texture_or_neutral_default"
            action_status = "required"
            required = True
            replacement_target = "source DDS texture or neutral runtime-safe texture"
        else:
            action = "neutralize_scalar_or_color_to_source_neutral_default"
            action_status = "required"
            required = True
            replacement_target = "neutral scalar/color value preserving ItemID and Index"
        rows.append(
            PacXmlNeutralizationAction(
                wrapper_name=parameter.wrapper_name,
                parameter_name=parameter.parameter_name,
                parameter_type=parameter.parameter_type,
                item_id=parameter.item_id,
                index=parameter.index,
                texture_path=parameter.texture_path,
                inherited_reason=parameter.reason,
                action=action,
                action_status=action_status,
                required=required,
                preserve_runtime_abi=True,
                replacement_target=replacement_target,
            )
        )
    return tuple(rows)


def _parse_material_authority_wrappers(sidecar_text: str) -> tuple[PacXmlAuthorityWrapper, ...]:
    text = str(sidecar_text or "")
    root = _safe_xml_root(text)
    if root is not None:
        rows: list[PacXmlAuthorityWrapper] = []
        _collect_xml_material_authority_wrappers(root, rows)
        return tuple(rows)
    return tuple(_parse_material_authority_wrappers_regex(text))


def _collect_xml_material_authority_wrappers(element: ET.Element, rows: list[PacXmlAuthorityWrapper]) -> None:
    tag = _xml_local_name(element.tag)
    if tag.endswith("MaterialWrapper"):
        rows.append(
            PacXmlAuthorityWrapper(
                order=len(rows),
                wrapper_name=_xml_element_attr(element, "_subMeshName", "SubMeshName", "Name", "name"),
                item_id=_xml_element_attr(element, "ItemID", "_itemID", "itemID", "itemId", "id"),
                shader_name=_xml_wrapper_shader_name(element),
                parameter_count=sum(1 for child in element.iter() if _xml_local_name(child.tag).startswith("MaterialParameter")),
            )
        )
    for child in list(element):
        _collect_xml_material_authority_wrappers(child, rows)


def _xml_wrapper_shader_name(element: ET.Element) -> str:
    for child in element.iter():
        if child is element:
            continue
        if _xml_local_name(child.tag) != "Material":
            continue
        shader_name = _xml_element_attr(child, "_materialName", "MaterialName", "Name", "name")
        if shader_name:
            return shader_name
    return ""


def _parse_material_authority_wrappers_regex(sidecar_text: str) -> list[PacXmlAuthorityWrapper]:
    text = str(sidecar_text or "")
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[PacXmlAuthorityWrapper] = []
    for wrapper_match in wrapper_pattern.finditer(text):
        attrs = wrapper_match.group("attrs") or ""
        body = wrapper_match.group("body") or ""
        rows.append(
            PacXmlAuthorityWrapper(
                order=len(rows),
                wrapper_name=_xml_attr(attrs, "_subMeshName")
                or _xml_attr(attrs, "SubMeshName")
                or _xml_attr(attrs, "Name")
                or _xml_attr(attrs, "name"),
                item_id=_xml_attr(attrs, "ItemID")
                or _xml_attr(attrs, "_itemID")
                or _xml_attr(attrs, "itemID")
                or _xml_attr(attrs, "itemId")
                or _xml_attr(attrs, "id"),
                shader_name=_first_match(
                    body,
                    r"<Material\b[^>]*(?:_materialName|MaterialName|Name|name)=\"([^\"]*)\"",
                ),
                parameter_count=len(
                    re.findall(
                        r"<MaterialParameter[A-Za-z0-9_:.-]*\b",
                        body,
                        flags=re.IGNORECASE,
                    )
                ),
            )
        )
    return rows


def _parse_material_authority_submesh_bindings(sidecar_text: str) -> tuple[PacXmlSubmeshBinding, ...]:
    text = str(sidecar_text or "")
    root = _safe_xml_root(text)
    if root is not None:
        rows: list[PacXmlSubmeshBinding] = []
        _collect_xml_material_authority_submesh_bindings(root, rows)
        return tuple(rows)
    return tuple(_parse_material_authority_submesh_bindings_regex(text))


def _collect_xml_material_authority_submesh_bindings(
    element: ET.Element,
    rows: list[PacXmlSubmeshBinding],
) -> None:
    tag = _xml_local_name(element.tag)
    is_submesh_vector = tag.lower() == "vector" and _compact_parameter_name(
        _xml_element_attr(element, "Name", "_name", "name", "StringItemID")
    ) == "submeshresources"
    if is_submesh_vector:
        id_base = _xml_element_attr(element, "IdBase", "_idBase", "idBase", "idbase")
        for child in list(element):
            child_tag = _xml_local_name(child.tag)
            if not child_tag.lower().endswith("materialwrapper"):
                continue
            rows.append(
                PacXmlSubmeshBinding(
                    order=len(rows),
                    wrapper_name=_xml_element_attr(child, "_subMeshName", "SubMeshName", "Name", "name"),
                    item_id=_xml_element_attr(child, "ItemID", "_itemID", "itemID", "itemId", "id"),
                    id_base=id_base,
                    shader_name=_xml_wrapper_shader_name(child),
                    parameter_count=sum(
                        1 for descendant in child.iter() if _xml_local_name(descendant.tag).startswith("MaterialParameter")
                    ),
                )
            )
    for child in list(element):
        _collect_xml_material_authority_submesh_bindings(child, rows)


def _parse_material_authority_submesh_bindings_regex(sidecar_text: str) -> list[PacXmlSubmeshBinding]:
    text = str(sidecar_text or "")
    vector_pattern = re.compile(
        r"<(?P<tag>Vector)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[PacXmlSubmeshBinding] = []
    for vector_match in vector_pattern.finditer(text):
        attrs = vector_match.group("attrs") or ""
        name = _xml_attr(attrs, "Name") or _xml_attr(attrs, "_name") or _xml_attr(attrs, "name") or _xml_attr(attrs, "StringItemID")
        if _compact_parameter_name(name) != "submeshresources":
            continue
        id_base = _xml_attr(attrs, "IdBase") or _xml_attr(attrs, "_idBase") or _xml_attr(attrs, "idBase") or _xml_attr(attrs, "idbase")
        body = vector_match.group("body") or ""
        for wrapper_match in wrapper_pattern.finditer(body):
            wrapper_attrs = wrapper_match.group("attrs") or ""
            wrapper_body = wrapper_match.group("body") or ""
            rows.append(
                PacXmlSubmeshBinding(
                    order=len(rows),
                    wrapper_name=_xml_attr(wrapper_attrs, "_subMeshName")
                    or _xml_attr(wrapper_attrs, "SubMeshName")
                    or _xml_attr(wrapper_attrs, "Name")
                    or _xml_attr(wrapper_attrs, "name"),
                    item_id=_xml_attr(wrapper_attrs, "ItemID")
                    or _xml_attr(wrapper_attrs, "_itemID")
                    or _xml_attr(wrapper_attrs, "itemID")
                    or _xml_attr(wrapper_attrs, "itemId")
                    or _xml_attr(wrapper_attrs, "id"),
                    id_base=id_base,
                    shader_name=_first_match(
                        wrapper_body,
                        r"<Material\b[^>]*(?:_materialName|MaterialName|Name|name)=\"([^\"]*)\"",
                    ),
                    parameter_count=len(
                        re.findall(
                            r"<MaterialParameter[A-Za-z0-9_:.-]*\b",
                            wrapper_body,
                            flags=re.IGNORECASE,
                        )
                    ),
                )
            )
    return rows


def _parse_material_authority_parameters(sidecar_text: str) -> tuple[PacXmlAuthorityParameter, ...]:
    text = str(sidecar_text or "")
    root = _safe_xml_root(text)
    if root is not None:
        rows: list[PacXmlAuthorityParameter] = []
        _collect_xml_material_authority_parameters(root, "", rows)
        return tuple(rows)
    return tuple(_parse_material_authority_parameters_regex(text))


def _safe_xml_root(text: str) -> ET.Element | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    for candidate in (stripped, f"<Root>{stripped}</Root>"):
        try:
            return ET.fromstring(candidate)
        except ET.ParseError:
            continue
    return None


def _xml_local_name(tag: object) -> str:
    text = str(tag or "")
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _xml_element_attr(element: ET.Element, *names: str) -> str:
    lowered = {str(key).lower(): str(value) for key, value in element.attrib.items()}
    for name in names:
        value = lowered.get(str(name).lower())
        if value not in (None, ""):
            return value
    return ""


def _collect_xml_material_authority_parameters(
    element: ET.Element,
    wrapper_name: str,
    rows: list[PacXmlAuthorityParameter],
) -> None:
    tag = _xml_local_name(element.tag)
    current_wrapper = wrapper_name
    if tag.endswith("MaterialWrapper"):
        current_wrapper = _xml_element_attr(element, "_subMeshName", "SubMeshName", "Name", "name") or current_wrapper
    if tag.startswith("MaterialParameter"):
        kind = tag[len("MaterialParameter") :] or "Unknown"
        parameter_name = _xml_element_attr(element, "StringItemID", "_name", "Name", "name")
        value = _xml_element_attr(element, "_value", "Value", "value")
        texture_path = ""
        if kind.lower() == "texture":
            texture_path = _xml_parameter_texture_path(element)
        role = infer_pac_xml_texture_role(parameter_name, texture_path) if kind.lower() == "texture" else ""
        rows.append(
            PacXmlAuthorityParameter(
                wrapper_name=current_wrapper,
                parameter_name=parameter_name,
                parameter_type=kind,
                item_id=_xml_element_attr(element, "ItemID", "_itemID", "itemID", "itemId", "id"),
                index=_xml_element_attr(element, "Index", "_index", "index"),
                value=value,
                texture_path=normalize_pac_xml_path(texture_path),
                role=role,
                stock_runtime=is_stock_runtime_texture_path(texture_path) if texture_path else False,
            )
        )
    for child in list(element):
        _collect_xml_material_authority_parameters(child, current_wrapper, rows)


def _xml_parameter_texture_path(element: ET.Element) -> str:
    direct = _xml_element_attr(element, "_path", "path", "Path", "_value", "Value", "value")
    if direct:
        return direct
    for child in element.iter():
        if child is element:
            continue
        if _xml_local_name(child.tag) not in {"ResourceReferencePath_ITexture", "TextureRef"}:
            continue
        value = _xml_element_attr(child, "_path", "path", "Path", "_value", "Value", "value")
        if value:
            return value
    return ""


def _parse_material_authority_parameters_regex(sidecar_text: str) -> list[PacXmlAuthorityParameter]:
    text = str(sidecar_text or "")
    wrapper_pattern = re.compile(
        r"<(?P<tag>[A-Za-z0-9_:.-]*MaterialWrapper)\b(?P<attrs>[^>]*)>(?P<body>.*?)</(?P=tag)>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[PacXmlAuthorityParameter] = []
    matched = False
    for wrapper_match in wrapper_pattern.finditer(text):
        matched = True
        wrapper_name = _xml_attr(wrapper_match.group("attrs") or "", "_subMeshName")
        rows.extend(_parse_material_authority_parameter_body_regex(wrapper_match.group("body") or "", wrapper_name))
    if not matched:
        rows.extend(_parse_material_authority_parameter_body_regex(text, ""))
    return rows


def _parse_material_authority_parameter_body_regex(body: str, wrapper_name: str) -> list[PacXmlAuthorityParameter]:
    parameter_pattern = re.compile(
        r"<(?P<tag>MaterialParameter(?P<kind>[A-Za-z0-9_:.-]*))\b(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</(?P=tag)>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    rows: list[PacXmlAuthorityParameter] = []
    for parameter_match in parameter_pattern.finditer(str(body or "")):
        kind = str(parameter_match.group("kind") or "Unknown")
        attrs = parameter_match.group("attrs") or ""
        parameter_name = (
            _xml_attr(attrs, "StringItemID")
            or _xml_attr(attrs, "_name")
            or _xml_attr(attrs, "Name")
            or _xml_attr(attrs, "name")
        )
        value = _xml_attr(attrs, "_value") or _xml_attr(attrs, "Value") or _xml_attr(attrs, "value")
        texture_path = ""
        if kind.lower() == "texture":
            texture_path = (
                _xml_attr(attrs, "_path")
                or _xml_attr(attrs, "path")
                or _xml_attr(attrs, "Path")
                or _xml_attr(attrs, "_value")
                or _xml_attr(attrs, "Value")
                or _xml_attr(attrs, "value")
                or _first_match(parameter_match.group("body") or "", r'\b(?:_path|path|Path|_value|Value|value)="([^"]*)"')
            )
        role = infer_pac_xml_texture_role(parameter_name, texture_path) if kind.lower() == "texture" else ""
        rows.append(
            PacXmlAuthorityParameter(
                wrapper_name=wrapper_name,
                parameter_name=parameter_name,
                parameter_type=kind,
                item_id=_xml_attr(attrs, "ItemID")
                or _xml_attr(attrs, "_itemID")
                or _xml_attr(attrs, "itemID")
                or _xml_attr(attrs, "itemId")
                or _xml_attr(attrs, "id"),
                index=_xml_attr(attrs, "Index") or _xml_attr(attrs, "_index") or _xml_attr(attrs, "index"),
                value=value,
                texture_path=normalize_pac_xml_path(texture_path),
                role=role,
                stock_runtime=is_stock_runtime_texture_path(texture_path) if texture_path else False,
            )
        )
    return rows


def _classify_material_authority_parameter(parameter: PacXmlAuthorityParameter) -> tuple[str, str]:
    kind = str(parameter.parameter_type or "").strip().lower()
    key = _compact_parameter_name(parameter.parameter_name)
    path_key = _normalized_key(parameter.texture_path)
    if _is_runtime_abi_parameter(key, kind):
        return "runtime_abi", "runtime_abi"
    inherited_reason = _inherited_material_influence_reason(parameter, key, path_key)
    if inherited_reason:
        return "inherited_influence", inherited_reason
    if kind == "texture":
        if parameter.role in {"base", "normal", "material_mask", "detail_mask", "height", "emissive", "opacity", "pupil", "iris"}:
            return "source_authority", parameter.role
        return "unknown_material_response", "unknown_texture_parameter"
    if _is_known_material_response_parameter(key, kind):
        return "source_authority", "known_material_response"
    if kind in {"float", "float2", "float3", "float4", "half", "half2", "half3", "half4", "byte4", "color"}:
        return "unknown_material_response", "unknown_scalar_or_color_response"
    return "runtime_abi", "non_material_response"


def _compact_parameter_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _is_runtime_abi_parameter(key: str, kind: str) -> bool:
    if not key:
        return True
    if key in {
        "cableuvscalex",
        "frequencyu",
        "speedu",
        "speedv",
    }:
        return True
    if key in {
        "rendersettingflag",
        "materialinfo",
        "placementid",
        "clothcategory",
        "clothmaskbit",
        "alphatest",
        "alphablend",
        "doublesided",
        "twosided",
        "cullmode",
        "sortkey",
    }:
        return True
    if any(
        token in key
        for token in (
            "pbd",
            "cloth",
            "torn",
            "hair",
            "fur",
            "skin",
            "wrinkle",
            "eye",
            "jiggle",
            "flow",
            "wind",
            "socket",
            "bone",
            "ssdm",
            "cable",
        )
    ):
        return True
    return kind in {"bitflag32", "uint", "int", "bool"} and not any(
        token in key for token in ("colorblending", "dye", "grime", "detail", "tint", "material")
    )


def _inherited_material_influence_reason(parameter: PacXmlAuthorityParameter, key: str, path_key: str) -> str:
    if parameter.stock_runtime or is_stock_runtime_texture_path(path_key):
        if "texturelayer" in path_key:
            return "shared_texturelayer"
        return "stock_runtime_texture"
    for token, reason in (
        ("texturelayer", "shared_texturelayer"),
        ("grime", "grime_layer"),
        ("dyeing", "dye_color"),
        ("dye", "dye_color"),
        ("tint", "tint_color"),
        ("detaildiffuse", "detail_layer"),
        ("detailmask", "detail_layer"),
        ("detailnormal", "detail_layer"),
        ("detailheight", "detail_layer"),
        ("layerbasecolor", "layer_color"),
        ("colorblending", "color_blending_mask"),
        ("baseheighttint", "height_tint"),
        ("damage", "damage_layer"),
    ):
        if token in key or token in path_key:
            return reason
    for token, reason in (
        ("ghost", "target_ghost_shader"),
        ("growth", "target_growth_shader"),
        ("lava", "target_lava_shader"),
        ("parallax", "target_parallax_shader"),
        ("noise", "target_procedural_noise"),
        ("uvtiling", "target_uv_transform"),
        ("uvspeed", "target_uv_transform"),
        ("fresnelmask", "target_fresnel_mask"),
        ("vertexoffset", "target_vertex_offset"),
        ("terrainblend", "target_terrain_blend"),
        ("posterglow", "target_poster_shader"),
        ("transientaging", "target_skin_aging"),
    ):
        if token in key or token in path_key:
            return reason
    if parameter.role == "mask" and path_key:
        return "target_mask_effect"
    if key in {"heighttexture", "materialtexture"}:
        return "target_support_response"
    if key == "brightness":
        return "target_brightness"
    return ""


def _is_known_material_response_parameter(key: str, kind: str) -> bool:
    if kind not in {"float", "float2", "float3", "float4", "half", "half2", "half3", "half4", "byte4", "color"}:
        return False
    return any(
        token in key
        for token in (
            "roughness",
            "metallic",
            "metalness",
            "specular",
            "gloss",
            "smoothness",
            "shine",
            "sheen",
            "emissive",
            "opacity",
            "alpha",
            "cutout",
            "normal",
            "ao",
            "occlusion",
            "displacement",
            "height",
            "brightness",
            "color",
            "tint",
            "dye",
            "grime",
            "detail",
            "scratch",
            "pupil",
            "iris",
            "velvet",
            "thickness",
            "extinction",
            "subsurface",
            "translucent",
        )
    )


def _authority_parameter_location(parameter: PacXmlAuthorityParameter) -> str:
    wrapper = str(parameter.wrapper_name or "").strip() or "<flat>"
    name = str(parameter.parameter_name or "").strip() or "<unnamed>"
    return f"{wrapper} {name}"


def build_pac_xml_profile_match_report(
    original_sidecar_text: str,
    patched_sidecar_text: str,
    sidecar_path: str | Path = "",
    *,
    changed_wrappers: int = 0,
    generated_dds: int = 0,
) -> PacXmlProfileMatchReport:
    original = parse_pac_xml_profile(original_sidecar_text, sidecar_path)
    patched = parse_pac_xml_profile(patched_sidecar_text, sidecar_path)
    similarity = _profile_similarity_score(original, patched)
    preserved_params = _count_preserved_parameters(original, patched)
    patched_params = _count_patched_texture_parameters(original, patched)
    unsafe_refs = validate_pac_xml_sidecar_transition(original_sidecar_text, patched_sidecar_text)
    missing_refs = tuple(
        f"{wrapper.wrapper_name or '<unnamed>'} {ref.parameter_name}"
        for wrapper in patched.wrappers
        for ref in wrapper.texture_refs
        if not str(ref.texture_path or "").strip()
    )
    fallback_reason = ""
    if not original.wrappers:
        fallback_reason = "no parsed donor PAC XML wrapper"
    elif changed_wrappers <= 0:
        fallback_reason = "no compatible texture slot patched"
    elif similarity < 0.50:
        fallback_reason = "low template similarity"
    return PacXmlProfileMatchReport(
        chosen_profile=original,
        similarity_score=similarity,
        preserved_params=preserved_params,
        patched_params=patched_params,
        generated_dds=int(generated_dds),
        missing_refs=missing_refs,
        unsafe_refs=unsafe_refs,
        fallback_reason=fallback_reason,
    )


def _profile_similarity_score(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> float:
    if not original.wrappers or not patched.wrappers:
        return 0.0
    total = max(len(original.wrappers), len(patched.wrappers))
    paired = list(zip(original.wrappers, patched.wrappers))
    order_score = sum(1 for left, right in paired if left.wrapper_name == right.wrapper_name) / total
    shader_score = sum(1 for left, right in paired if left.shader_name == right.shader_name) / total
    param_scores: list[float] = []
    for left, right in paired:
        left_params = set(left.parameter_names)
        right_params = set(right.parameter_names)
        if not left_params and not right_params:
            param_scores.append(1.0)
            continue
        union = left_params | right_params
        param_scores.append((len(left_params & right_params) / len(union)) if union else 0.0)
    param_score = sum(param_scores) / len(param_scores) if param_scores else 0.0
    return round(max(0.0, min(1.0, (order_score + shader_score + param_score) / 3.0)), 3)


def _count_preserved_parameters(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> int:
    count = 0
    for left, right in zip(original.wrappers, patched.wrappers):
        if left.wrapper_name != right.wrapper_name:
            continue
        count += len(set(left.parameter_names) & set(right.parameter_names))
    return count


def _count_patched_texture_parameters(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> int:
    original_paths: dict[tuple[int, str, str], str] = {}
    for wrapper_index, wrapper in enumerate(original.wrappers):
        for ref in wrapper.texture_refs:
            original_paths[(wrapper_index, wrapper.wrapper_name, ref.parameter_name)] = ref.texture_path
    changed = 0
    for wrapper_index, wrapper in enumerate(patched.wrappers):
        for ref in wrapper.texture_refs:
            old_path = original_paths.get((wrapper_index, wrapper.wrapper_name, ref.parameter_name))
            if old_path is not None and normalize_pac_xml_path(old_path).lower() != normalize_pac_xml_path(ref.texture_path).lower():
                changed += 1
    return changed


def validate_pac_xml_texture_contract(sidecar_text: str) -> tuple[str, ...]:
    report = parse_pac_xml_profile(sidecar_text)
    warnings: list[str] = []
    for wrapper in report.wrappers:
        for ref in wrapper.texture_refs:
            if not ref.texture_path or ref.stock_runtime:
                continue
            expected = expected_texture_suffixes_for_parameter(ref.parameter_name)
            if expected and not ref.texture_path.lower().endswith(expected):
                warnings.append(
                    f"{wrapper.wrapper_name or '<unnamed>'} {ref.parameter_name}: texture {ref.texture_path} does not match expected suffix {expected}."
                )
    return tuple(warnings)


def validate_pac_xml_sidecar_transition(
    original_sidecar_text: str,
    patched_sidecar_text: str,
    *,
    allow_stock_mask_override: bool = False,
) -> tuple[str, ...]:
    original = parse_pac_xml_profile(original_sidecar_text)
    patched = parse_pac_xml_profile(patched_sidecar_text)
    warnings: list[str] = []
    warnings.extend(validate_pac_xml_texture_contract(patched_sidecar_text))
    warnings.extend(_protected_param_removal_warnings(original, patched))
    if not allow_stock_mask_override:
        warnings.extend(_stock_runtime_support_replacement_warnings(original, patched))
    return tuple(dict.fromkeys(warnings))


def expected_texture_suffixes_for_parameter(parameter_name: str) -> tuple[str, ...]:
    role = infer_pac_xml_texture_role(parameter_name)
    return {
        "normal": ("_n.dds",),
        "height": ("_disp.dds",),
        "detail_mask": ("_mg.dds",),
        "material_mask": ("_ma.dds", "_m.dds", "_sp.dds"),
        "emissive": ("_emi.dds", ".dds"),
    }.get(role, ())


def build_pac_xml_corpus_index(root: str | Path, *, limit: int | None = None) -> PacXmlCorpusIndex:
    if not str(root or "").strip() or Path(root).expanduser() == Path():
        return PacXmlCorpusIndex(root=Path())
    base = Path(root).expanduser()
    index = PacXmlCorpusIndex(root=base)
    if not base.exists():
        return index
    for xml_path in base.rglob("*.pac_xml"):
        if limit is not None and index.xml_count >= limit:
            break
        try:
            text = xml_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        index.source_file_count += 1
        try:
            index.newest_mtime_ns = max(index.newest_mtime_ns, xml_path.stat().st_mtime_ns)
        except OSError:
            pass
        rel = normalize_pac_xml_path(xml_path.relative_to(base))
        report = parse_pac_xml_profile(text, rel)
        index.xml_count += 1
        index.wrapper_count += len(report.wrappers)
        index.texture_ref_count += report.texture_ref_count
        index.families.update([report.profile.family])
        index.shader_families.update(report.shader_families)
        index.roles.update(report.roles)
        index.parameter_count += sum(len(wrapper.parameter_names) for wrapper in report.wrappers)
        for wrapper in report.wrappers:
            index.parameter_types.update(wrapper.parameter_types)
        model_rel = rel.replace("/modelproperty/", "/model/")
        if model_rel.endswith(".pac_xml"):
            model_rel = model_rel[:-4]
        if (base / model_rel).exists():
            index.paired_model_count += 1
            report = replace(report, paired_model_path=normalize_pac_xml_path(model_rel))
        index.profiles.append(report)
    return index


def load_or_build_pac_xml_corpus_index(
    root: str | Path | None = None,
    *,
    cache_path: str | Path | None = None,
    limit: int | None = None,
    force: bool = False,
) -> PacXmlCorpusIndex:
    if root is None or not str(root or "").strip():
        raw_root = str(os.environ.get(PAC_XML_CORPUS_ROOT_ENV, "") or "").strip()
        if not raw_root:
            return PacXmlCorpusIndex(root=Path())
        base = Path(raw_root).expanduser()
    else:
        base = Path(root).expanduser()
    if base == Path():
        return PacXmlCorpusIndex(root=Path())
    cache = _sqlite_cache_path_for(cache_path)
    count, newest = pac_xml_corpus_signature(base, limit=limit)
    if count <= 0:
        return PacXmlCorpusIndex(root=base, cache_path=cache, sqlite_backed=False)
    if not force and cache.is_file():
        cached = _load_pac_xml_corpus_index_sqlite(cache, base, count=count, newest_mtime_ns=newest)
        if cached is not None:
            return cached
    try:
        return build_pac_xml_corpus_sqlite_cache(base, cache, limit=limit, source_file_count=count, newest_mtime_ns=newest)
    except Exception:
        # Correctness fallback: keep the old in-memory behavior if SQLite is unavailable.
        try:
            index = build_pac_xml_corpus_index(base, limit=limit)
            index.source_file_count = count or index.source_file_count
            index.newest_mtime_ns = newest or index.newest_mtime_ns
            return index
        except Exception:
            return PacXmlCorpusIndex(
                root=base,
                cache_path=cache,
                sqlite_backed=False,
                source_file_count=count,
                newest_mtime_ns=newest,
            )


def pac_xml_corpus_signature(root: str | Path, *, limit: int | None = None) -> tuple[int, int]:
    base = Path(root).expanduser()
    if not base.exists():
        return 0, 0
    count = 0
    newest = 0
    for xml_path in base.rglob("*.pac_xml"):
        if limit is not None and count >= limit:
            break
        count += 1
        try:
            newest = max(newest, xml_path.stat().st_mtime_ns)
        except OSError:
            pass
    return count, newest


def build_pac_xml_corpus_sqlite_cache(
    root: str | Path,
    cache_path: str | Path | None = None,
    *,
    limit: int | None = None,
    source_file_count: int | None = None,
    newest_mtime_ns: int | None = None,
) -> PacXmlCorpusIndex:
    base = Path(root).expanduser()
    cache = _sqlite_cache_path_for(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache.with_name(f"{cache.name}.{os.getpid()}.tmp")
    try:
        temp_path.unlink()
    except OSError:
        pass

    index = PacXmlCorpusIndex(root=base, cache_path=cache, sqlite_backed=True)
    if source_file_count is not None:
        index.source_file_count = int(source_file_count)
    if newest_mtime_ns is not None:
        index.newest_mtime_ns = int(newest_mtime_ns)
    if not base.exists():
        return index

    conn = sqlite3.connect(str(temp_path))
    try:
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        _create_pac_xml_sqlite_schema(conn)
        for xml_path in base.rglob("*.pac_xml"):
            if limit is not None and index.xml_count >= limit:
                break
            try:
                text = xml_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            index.source_file_count += 0 if source_file_count is not None else 1
            try:
                index.newest_mtime_ns = max(index.newest_mtime_ns, xml_path.stat().st_mtime_ns)
            except OSError:
                pass
            rel = normalize_pac_xml_path(xml_path.relative_to(base))
            report = parse_pac_xml_profile(text, rel)
            model_rel = rel.replace("/modelproperty/", "/model/")
            if model_rel.endswith(".pac_xml"):
                model_rel = model_rel[:-4]
            if (base / model_rel).exists():
                index.paired_model_count += 1
                report = replace(report, paired_model_path=normalize_pac_xml_path(model_rel))
            _insert_pac_xml_sqlite_report(conn, index, report, profile_order=index.xml_count)
            index.xml_count += 1
            index.wrapper_count += len(report.wrappers)
            index.texture_ref_count += report.texture_ref_count
            index.families.update([report.profile.family])
            index.shader_families.update(report.shader_families)
            index.roles.update(report.roles)
            index.parameter_count += sum(len(wrapper.parameter_names) for wrapper in report.wrappers)
            for wrapper in report.wrappers:
                index.parameter_types.update(wrapper.parameter_types)

        if source_file_count is None:
            index.source_file_count = index.xml_count
        if newest_mtime_ns is None and not index.newest_mtime_ns:
            index.newest_mtime_ns = 0
        _insert_pac_xml_sqlite_metadata(conn, index)
        _insert_pac_xml_sqlite_counters(conn, index)
        conn.commit()
    except Exception:
        try:
            conn.close()
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if index.xml_count:
        temp_path.replace(cache)
    else:
        try:
            temp_path.unlink()
        except OSError:
            pass
    return index


def _create_pac_xml_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE counters (
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            count INTEGER NOT NULL,
            PRIMARY KEY (kind, name)
        );
        CREATE TABLE profiles (
            id INTEGER PRIMARY KEY,
            profile_order INTEGER NOT NULL,
            path TEXT NOT NULL,
            paired_model_path TEXT NOT NULL,
            family TEXT NOT NULL,
            slot TEXT NOT NULL,
            profile_names TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence TEXT NOT NULL,
            pbd TEXT NOT NULL,
            texture_ref_count INTEGER NOT NULL,
            stock_texture_ref_count INTEGER NOT NULL
        );
        CREATE TABLE wrappers (
            id INTEGER PRIMARY KEY,
            profile_id INTEGER NOT NULL,
            wrapper_index INTEGER NOT NULL,
            wrapper_name TEXT NOT NULL,
            shader_name TEXT NOT NULL,
            shader_family TEXT NOT NULL,
            role TEXT NOT NULL,
            render_setting_flag TEXT NOT NULL,
            parameter_names TEXT NOT NULL,
            parameter_types TEXT NOT NULL,
            texture_refs_blob BLOB NOT NULL
        );
        CREATE INDEX idx_profiles_order ON profiles(profile_order);
        CREATE INDEX idx_wrappers_profile_order ON wrappers(profile_id, wrapper_index);
        """
    )


def _insert_pac_xml_sqlite_report(
    conn: sqlite3.Connection,
    index: PacXmlCorpusIndex,
    report: PacXmlProfileReport,
    *,
    profile_order: int,
) -> None:
    cursor = conn.execute(
        """
        INSERT INTO profiles (
            profile_order, path, paired_model_path, family, slot, profile_names,
            confidence, evidence, pbd, texture_ref_count, stock_texture_ref_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(profile_order),
            report.path,
            report.paired_model_path,
            report.profile.family,
            report.profile.slot,
            _pack_tuple(report.profile.profiles),
            float(report.profile.confidence),
            _pack_tuple(report.profile.evidence),
            _pack_tuple(report.pbd_materials),
            int(report.texture_ref_count),
            int(report.stock_texture_ref_count),
        ),
    )
    profile_id = int(cursor.lastrowid)
    for wrapper_index, wrapper in enumerate(report.wrappers):
        wrapper_cursor = conn.execute(
            """
            INSERT INTO wrappers (
                profile_id, wrapper_index, wrapper_name, shader_name, shader_family,
                role, render_setting_flag, parameter_names, parameter_types, texture_refs_blob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                int(wrapper_index),
                wrapper.wrapper_name,
                wrapper.shader_name,
                wrapper.shader_family,
                wrapper.role,
                wrapper.render_setting_flag,
                _pack_tuple(wrapper.parameter_names),
                _pack_tuple(wrapper.parameter_types),
                _pack_texture_refs(wrapper.texture_refs),
            ),
        )
        _ = wrapper_cursor.lastrowid


def _insert_pac_xml_sqlite_metadata(conn: sqlite3.Connection, index: PacXmlCorpusIndex) -> None:
    metadata = {
        "schema": PAC_XML_PROFILE_INDEX_SQLITE_SCHEMA,
        "root": normalize_pac_xml_path(index.root),
        "source_file_count": str(int(index.source_file_count or index.xml_count)),
        "newest_mtime_ns": str(int(index.newest_mtime_ns)),
        "xml_count": str(int(index.xml_count)),
        "paired_model_count": str(int(index.paired_model_count)),
        "wrapper_count": str(int(index.wrapper_count)),
        "parameter_count": str(int(index.parameter_count)),
        "texture_ref_count": str(int(index.texture_ref_count)),
    }
    conn.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items())


def _insert_pac_xml_sqlite_counters(conn: sqlite3.Connection, index: PacXmlCorpusIndex) -> None:
    rows: list[tuple[str, str, int]] = []
    for kind, counter in (
        ("family", index.families),
        ("shader_family", index.shader_families),
        ("role", index.roles),
        ("parameter_type", index.parameter_types),
    ):
        rows.extend((kind, str(name), int(count)) for name, count in counter.items())
    conn.executemany("INSERT INTO counters(kind, name, count) VALUES (?, ?, ?)", rows)


def _load_pac_xml_corpus_index_sqlite(
    cache_path: str | Path,
    root: Path,
    *,
    count: int,
    newest_mtime_ns: int,
) -> PacXmlCorpusIndex | None:
    cache = Path(cache_path).expanduser()
    try:
        conn = sqlite3.connect(str(cache))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None
    try:
        metadata = {str(row["key"]): str(row["value"]) for row in conn.execute("SELECT key, value FROM metadata")}
        if (
            metadata.get("schema") != PAC_XML_PROFILE_INDEX_SQLITE_SCHEMA
            or normalize_pac_xml_path(metadata.get("root", "")).lower() != normalize_pac_xml_path(root).lower()
            or int(metadata.get("source_file_count") or 0) != int(count)
            or int(metadata.get("newest_mtime_ns") or 0) != int(newest_mtime_ns)
        ):
            return None
        index = PacXmlCorpusIndex(
            root=root,
            cache_path=cache,
            sqlite_backed=True,
            source_file_count=int(metadata.get("source_file_count") or 0),
            newest_mtime_ns=int(metadata.get("newest_mtime_ns") or 0),
            xml_count=int(metadata.get("xml_count") or 0),
            paired_model_count=int(metadata.get("paired_model_count") or 0),
            wrapper_count=int(metadata.get("wrapper_count") or 0),
            parameter_count=int(metadata.get("parameter_count") or 0),
            texture_ref_count=int(metadata.get("texture_ref_count") or 0),
        )
        for row in conn.execute("SELECT kind, name, count FROM counters"):
            kind = str(row["kind"])
            name = str(row["name"])
            value = int(row["count"] or 0)
            if kind == "family":
                index.families[name] = value
            elif kind == "shader_family":
                index.shader_families[name] = value
            elif kind == "role":
                index.roles[name] = value
            elif kind == "parameter_type":
                index.parameter_types[name] = value
        return index
    except Exception:
        return None
    finally:
        conn.close()


def pac_xml_corpus_index_to_dict(index: PacXmlCorpusIndex) -> dict[str, object]:
    reports = index.profiles
    if index.sqlite_backed and not reports:
        reports = list(_sqlite_profile_reports(index))
    return {
        "schema": PAC_XML_PROFILE_INDEX_SCHEMA,
        "root": normalize_pac_xml_path(index.root),
        "source_file_count": int(index.source_file_count or index.xml_count),
        "newest_mtime_ns": int(index.newest_mtime_ns),
        "xml_count": int(index.xml_count),
        "paired_model_count": int(index.paired_model_count),
        "wrapper_count": int(index.wrapper_count),
        "parameter_count": int(index.parameter_count),
        "texture_ref_count": int(index.texture_ref_count),
        "profiles": [_report_to_dict(report) for report in reports],
    }


def pac_xml_corpus_index_from_dict(payload: Mapping[str, object]) -> PacXmlCorpusIndex:
    root = Path(str(payload.get("root") or ""))
    index = PacXmlCorpusIndex(
        root=root,
        source_file_count=int(payload.get("source_file_count") or 0),
        newest_mtime_ns=int(payload.get("newest_mtime_ns") or 0),
        xml_count=int(payload.get("xml_count") or 0),
        paired_model_count=int(payload.get("paired_model_count") or 0),
        wrapper_count=int(payload.get("wrapper_count") or 0),
        parameter_count=int(payload.get("parameter_count") or 0),
        texture_ref_count=int(payload.get("texture_ref_count") or 0),
    )
    for raw_report in tuple(payload.get("profiles") or ()):
        if not isinstance(raw_report, MappingABC):
            continue
        report = _report_from_dict(raw_report)
        index.profiles.append(report)
        index.families.update([report.profile.family])
        index.shader_families.update(report.shader_families)
        index.roles.update(report.roles)
        for wrapper in report.wrappers:
            index.parameter_types.update(wrapper.parameter_types)
    if not index.xml_count:
        index.xml_count = len(index.profiles)
    return index


def hydrate_pac_xml_corpus_index(index: PacXmlCorpusIndex) -> PacXmlCorpusIndex:
    if index.sqlite_backed and not index.profiles and index.cache_path:
        index.profiles.extend(_sqlite_profile_reports(index))
    return index


def select_best_pac_xml_template(
    target_report: PacXmlProfileReport | None,
    target_wrapper: PacXmlWrapperProfile | None,
    slot_kind: str,
    corpus_index: PacXmlCorpusIndex | None,
    *,
    allow_shader_mismatch: bool = False,
    preferred_shader_families: Sequence[str] = (),
) -> PacXmlTemplateMatch:
    slot = str(slot_kind or "").strip().lower()
    if corpus_index is None or (not corpus_index.profiles and not corpus_index.sqlite_backed):
        return PacXmlTemplateMatch(fallback_reason="no corpus index")
    if target_report is None:
        return PacXmlTemplateMatch(fallback_reason="no target PAC XML report")
    target_profile = target_report.profile
    target_role = target_wrapper.role if target_wrapper is not None else ""
    target_shader = target_wrapper.shader_family if target_wrapper is not None else ""
    target_params = set(target_wrapper.parameter_names) if target_wrapper is not None else set()
    preferred_shaders = {str(value or "").strip() for value in tuple(preferred_shader_families or ()) if str(value or "").strip()}
    best_score = 0.0
    best_report: PacXmlProfileReport | None = None
    best_wrapper: PacXmlWrapperProfile | None = None
    best_parameter = ""
    best_supported_score = 0.0
    best_supported_report: PacXmlProfileReport | None = None
    best_supported_wrapper: PacXmlWrapperProfile | None = None
    best_supported_parameter = ""
    saw_candidate = False
    for candidate_report, candidate_wrapper in _iter_pac_xml_template_candidates(corpus_index, slot):
        saw_candidate = True
        parameter = pac_xml_parameter_for_slot(candidate_wrapper, slot)
        supports_slot = bool(parameter)
        score = 0.0
        if candidate_report.profile.family == target_profile.family:
            score += 0.28
        if candidate_report.profile.slot and candidate_report.profile.slot == target_profile.slot:
            score += 0.14
        elif not target_profile.slot or not candidate_report.profile.slot:
            score += 0.04
        if target_role and candidate_wrapper.role == target_role:
            score += 0.18
        if target_shader and candidate_wrapper.shader_family == target_shader:
            score += 0.14
        elif preferred_shaders and candidate_wrapper.shader_family in preferred_shaders:
            score += 0.12
        elif allow_shader_mismatch and target_shader and candidate_wrapper.shader_family != target_shader:
            score -= 0.04
        if target_wrapper is not None and candidate_wrapper.render_setting_flag == target_wrapper.render_setting_flag:
            score += 0.05
        if supports_slot:
            score += 0.17
        if target_params:
            overlap = len(target_params & set(candidate_wrapper.parameter_names))
            union = len(target_params | set(candidate_wrapper.parameter_names))
            param_overlap_ratio = (overlap / union) if union else 0.0
            if union:
                score += 0.04 * param_overlap_ratio
        else:
            param_overlap_ratio = 0.0
        if (
            supports_slot
            and target_shader
            and candidate_wrapper.shader_family != target_shader
            and not allow_shader_mismatch
            and param_overlap_ratio < 0.35
        ):
            continue
        if candidate_report.pbd_materials and target_report.pbd_materials:
            score += 0.02
        if score > best_score:
            best_score = score
            best_report = candidate_report
            best_wrapper = candidate_wrapper
            best_parameter = parameter
        if supports_slot and score > best_supported_score:
            best_supported_score = score
            best_supported_report = candidate_report
            best_supported_wrapper = candidate_wrapper
            best_supported_parameter = parameter
    if not saw_candidate:
        return PacXmlTemplateMatch(fallback_reason="no corpus index")
    if best_supported_report is not None and best_supported_wrapper is not None:
        best_score = best_supported_score
        best_report = best_supported_report
        best_wrapper = best_supported_wrapper
        best_parameter = best_supported_parameter
    if best_report is None or best_wrapper is None:
        return PacXmlTemplateMatch(fallback_reason="no candidate template")
    supports = bool(best_parameter)
    fallback = "" if supports and best_score >= 0.45 else "template lacks compatible slot" if not supports else "low template score"
    return PacXmlTemplateMatch(
        template_path=best_report.path,
        template_model_path=best_report.paired_model_path,
        template_wrapper_name=best_wrapper.wrapper_name,
        template_parameter_name=best_parameter,
        template_shader_name=best_wrapper.shader_name,
        template_shader_family=best_wrapper.shader_family,
        score=round(min(1.0, best_score), 3),
        supports_slot=bool(supports and best_score >= 0.45),
        fallback_reason=fallback,
    )


def _iter_pac_xml_template_candidates(
    corpus_index: PacXmlCorpusIndex,
    slot_kind: str,
) -> Iterable[tuple[PacXmlProfileReport, PacXmlWrapperProfile]]:
    if corpus_index.sqlite_backed and not corpus_index.profiles and corpus_index.cache_path:
        yield from _sqlite_template_candidates(corpus_index, slot_kind)
        return
    for candidate_report in corpus_index.profiles:
        for candidate_wrapper in candidate_report.wrappers:
            yield candidate_report, candidate_wrapper


def _sqlite_template_candidates(
    corpus_index: PacXmlCorpusIndex,
    slot_kind: str,
) -> Iterable[tuple[PacXmlProfileReport, PacXmlWrapperProfile]]:
    cache = Path(corpus_index.cache_path)
    if not cache.is_file():
        return
    try:
        conn = sqlite3.connect(str(cache))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return
    try:
        query = """
            SELECT
                p.path AS path,
                p.paired_model_path AS paired_model_path,
                p.family AS family,
                p.slot AS slot,
                p.profile_names AS profile_names,
                p.confidence AS confidence,
                p.evidence AS evidence,
                p.pbd AS pbd,
                p.texture_ref_count AS texture_ref_count,
                p.stock_texture_ref_count AS stock_texture_ref_count,
                w.id AS wrapper_id,
                w.wrapper_name AS wrapper_name,
                w.shader_name AS shader_name,
                w.shader_family AS shader_family,
                w.role AS role,
                w.render_setting_flag AS render_setting_flag,
                w.parameter_names AS parameter_names,
                w.parameter_types AS parameter_types,
                w.texture_refs_blob AS texture_refs_blob
            FROM wrappers w
            JOIN profiles p ON p.id = w.profile_id
            ORDER BY p.profile_order ASC, w.wrapper_index ASC
        """
        for row in conn.execute(query):
            wrapper_name = str(row["wrapper_name"] or "")
            wrapper = PacXmlWrapperProfile(
                wrapper_name=wrapper_name,
                shader_name=str(row["shader_name"] or ""),
                shader_family=str(row["shader_family"] or "Unknown"),
                role=str(row["role"] or "body"),
                render_setting_flag=str(row["render_setting_flag"] or ""),
                parameter_names=_unpack_tuple(row["parameter_names"]),
                parameter_types=_unpack_tuple(row["parameter_types"]),
            )
            if not pac_xml_parameter_for_slot(wrapper, slot_kind) and str(slot_kind or "").strip().lower() not in {"base", "normal", "emissive"}:
                wrapper = replace(
                    wrapper,
                    texture_refs=_unpack_texture_refs(row["texture_refs_blob"], wrapper_name),
                )
            profile = PacXmlProfile(
                family=str(row["family"] or "unknown"),
                slot=str(row["slot"] or ""),
                profiles=_unpack_tuple(row["profile_names"]),
                confidence=float(row["confidence"] or 0.0),
                evidence=_unpack_tuple(row["evidence"]),
            )
            report = PacXmlProfileReport(
                path=str(row["path"] or ""),
                profile=profile,
                paired_model_path=str(row["paired_model_path"] or ""),
                wrappers=(wrapper,),
                pbd_materials=_unpack_tuple(row["pbd"]),
                texture_ref_count=int(row["texture_ref_count"] or 0),
                stock_texture_ref_count=int(row["stock_texture_ref_count"] or 0),
            )
            yield report, wrapper
    except Exception:
        return
    finally:
        conn.close()


def _sqlite_profile_reports(index: PacXmlCorpusIndex) -> tuple[PacXmlProfileReport, ...]:
    cache = Path(index.cache_path)
    if not cache.is_file():
        return ()
    try:
        conn = sqlite3.connect(str(cache))
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return ()
    try:
        reports: list[PacXmlProfileReport] = []
        for profile_row in conn.execute(
            """
            SELECT *
            FROM profiles
            ORDER BY profile_order ASC
            """
        ):
            wrappers: list[PacXmlWrapperProfile] = []
            for wrapper_row in conn.execute(
                """
                SELECT *
                FROM wrappers
                WHERE profile_id = ?
                ORDER BY wrapper_index ASC
                """,
                (int(profile_row["id"]),),
            ):
                wrapper_name = str(wrapper_row["wrapper_name"] or "")
                wrappers.append(
                    PacXmlWrapperProfile(
                        wrapper_name=wrapper_name,
                        shader_name=str(wrapper_row["shader_name"] or ""),
                        shader_family=str(wrapper_row["shader_family"] or "Unknown"),
                        role=str(wrapper_row["role"] or "body"),
                        render_setting_flag=str(wrapper_row["render_setting_flag"] or ""),
                        parameter_names=_unpack_tuple(wrapper_row["parameter_names"]),
                        parameter_types=_unpack_tuple(wrapper_row["parameter_types"]),
                        texture_refs=_unpack_texture_refs(wrapper_row["texture_refs_blob"], wrapper_name),
                    )
                )
            reports.append(
                PacXmlProfileReport(
                    path=str(profile_row["path"] or ""),
                    profile=PacXmlProfile(
                        family=str(profile_row["family"] or "unknown"),
                        slot=str(profile_row["slot"] or ""),
                        profiles=_unpack_tuple(profile_row["profile_names"]),
                        confidence=float(profile_row["confidence"] or 0.0),
                        evidence=_unpack_tuple(profile_row["evidence"]),
                    ),
                    paired_model_path=str(profile_row["paired_model_path"] or ""),
                    wrappers=tuple(wrappers),
                    pbd_materials=_unpack_tuple(profile_row["pbd"]),
                    texture_ref_count=int(profile_row["texture_ref_count"] or 0),
                    stock_texture_ref_count=int(profile_row["stock_texture_ref_count"] or 0),
                )
            )
        return tuple(reports)
    except Exception:
        return ()
    finally:
        conn.close()


def pac_xml_parameter_for_slot(wrapper: PacXmlWrapperProfile, slot_kind: str) -> str:
    slot = str(slot_kind or "").strip().lower()
    candidates = {
        "base": ("_overlayColorTexture", "_baseColorTexture", "_diffuseTexture", "_albedoTexture"),
        "normal": ("_normalTexture",),
        "emissive": ("_emissiveIntensityTexture", "_emissiveTexture", "_emissiveProgressTexture"),
        "height": ("_heightTexture",),
        "detail_mask": ("_detailMaskTexture",),
        "material_mask": ("_colorBlendingMaskTexture",),
    }.get(slot, ())
    parameter_map = {param.lower(): param for param in wrapper.parameter_names}
    for candidate in candidates:
        value = parameter_map.get(candidate.lower())
        if value:
            return value
    if slot in {"base", "normal", "emissive"}:
        return ""
    for ref in wrapper.texture_refs:
        if ref.role == slot:
            return ref.parameter_name
    return ""


def _report_to_dict(report: PacXmlProfileReport) -> dict[str, object]:
    return {
        "path": report.path,
        "paired_model_path": report.paired_model_path,
        "profile": {
            "family": report.profile.family,
            "slot": report.profile.slot,
            "profiles": list(report.profile.profiles),
            "confidence": report.profile.confidence,
            "evidence": list(report.profile.evidence),
        },
        "pbd": _pack_tuple(report.pbd_materials),
        "texture_ref_count": report.texture_ref_count,
        "stock_texture_ref_count": report.stock_texture_ref_count,
        "w": [
            {
                "n": wrapper.wrapper_name,
                "m": wrapper.shader_name,
                "sf": wrapper.shader_family,
                "r": wrapper.role,
                "flag": wrapper.render_setting_flag,
                "pn": _pack_tuple(wrapper.parameter_names),
                "pt": _pack_tuple(wrapper.parameter_types),
                "tr": [
                    {
                        "p": ref.parameter_name,
                        "t": ref.texture_path,
                        "r": ref.role,
                        "s": 1 if ref.stock_runtime else 0,
                    }
                    for ref in wrapper.texture_refs
                ],
            }
            for wrapper in report.wrappers
        ],
    }


def _report_from_dict(payload: Mapping[str, object]) -> PacXmlProfileReport:
    raw_profile = payload.get("profile") if isinstance(payload.get("profile"), MappingABC) else {}
    profile = PacXmlProfile(
        family=str(raw_profile.get("family") or "unknown"),
        slot=str(raw_profile.get("slot") or ""),
        profiles=tuple(str(value) for value in tuple(raw_profile.get("profiles") or ()) if str(value or "")),
        confidence=float(raw_profile.get("confidence") or 0.0),
        evidence=tuple(str(value) for value in tuple(raw_profile.get("evidence") or ()) if str(value or "")),
    )
    wrappers: list[PacXmlWrapperProfile] = []
    raw_wrappers = payload.get("w") or payload.get("wrappers") or ()
    for raw_wrapper in tuple(raw_wrappers):
        if not isinstance(raw_wrapper, MappingABC):
            continue
        refs: list[PacXmlTextureRef] = []
        raw_refs = raw_wrapper.get("tr") or raw_wrapper.get("texture_refs") or ()
        wrapper_name = str(raw_wrapper.get("n") or raw_wrapper.get("wrapper_name") or "")
        for raw_ref in tuple(raw_refs):
            if not isinstance(raw_ref, MappingABC):
                continue
            refs.append(
                PacXmlTextureRef(
                    wrapper_name=str(raw_ref.get("wrapper_name") or wrapper_name),
                    parameter_name=str(raw_ref.get("p") or raw_ref.get("parameter_name") or ""),
                    texture_path=str(raw_ref.get("t") or raw_ref.get("texture_path") or ""),
                    role=str(raw_ref.get("r") or raw_ref.get("role") or "unknown"),
                    stock_runtime=bool(raw_ref.get("s") or raw_ref.get("stock_runtime")),
                )
            )
        wrappers.append(
            PacXmlWrapperProfile(
                wrapper_name=wrapper_name,
                shader_name=str(raw_wrapper.get("m") or raw_wrapper.get("shader_name") or ""),
                shader_family=str(raw_wrapper.get("sf") or raw_wrapper.get("shader_family") or "Unknown"),
                role=str(raw_wrapper.get("r") or raw_wrapper.get("role") or "body"),
                render_setting_flag=str(raw_wrapper.get("flag") or raw_wrapper.get("render_setting_flag") or ""),
                parameter_names=_unpack_tuple(raw_wrapper.get("pn") or raw_wrapper.get("parameter_names")),
                parameter_types=_unpack_tuple(raw_wrapper.get("pt") or raw_wrapper.get("parameter_types")),
                texture_refs=tuple(refs),
            )
        )
    return PacXmlProfileReport(
        path=str(payload.get("path") or ""),
        profile=profile,
        paired_model_path=str(payload.get("paired_model_path") or payload.get("paired_model") or ""),
        wrappers=tuple(wrappers),
        pbd_materials=_unpack_tuple(payload.get("pbd") or payload.get("pbd_materials")),
        texture_ref_count=int(payload.get("texture_ref_count") or 0),
        stock_texture_ref_count=int(payload.get("stock_texture_ref_count") or 0),
    )


def _pack_tuple(values: Sequence[str]) -> str:
    return "\x1f".join(str(value) for value in tuple(values or ()) if str(value or ""))


def _unpack_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part for part in value.split("\x1f") if part)
    return tuple(str(item) for item in tuple(value or ()) if str(item or ""))


def _pack_texture_refs(refs: Sequence[PacXmlTextureRef]) -> bytes:
    rows: list[str] = []
    for ref in tuple(refs or ()):
        rows.append(
            "\x1e".join(
                (
                    str(ref.parameter_name or ""),
                    str(ref.texture_path or ""),
                    str(ref.role or "unknown"),
                    "1" if ref.stock_runtime else "0",
                )
            )
        )
    if not rows:
        return b""
    return zlib.compress("\x1f".join(rows).encode("utf-8"), level=6)


def _unpack_texture_refs(value: object, wrapper_name: str) -> tuple[PacXmlTextureRef, ...]:
    if value is None:
        return ()
    if isinstance(value, memoryview):
        raw = value.tobytes()
    elif isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        return ()
    if not raw:
        return ()
    try:
        text = zlib.decompress(raw).decode("utf-8", errors="ignore")
    except Exception:
        try:
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return ()
    refs: list[PacXmlTextureRef] = []
    for row in text.split("\x1f"):
        if not row:
            continue
        parts = row.split("\x1e")
        while len(parts) < 4:
            parts.append("")
        refs.append(
            PacXmlTextureRef(
                wrapper_name=wrapper_name,
                parameter_name=parts[0],
                texture_path=parts[1],
                role=parts[2] or "unknown",
                stock_runtime=(parts[3] == "1"),
            )
        )
    return tuple(refs)


def _protected_param_removal_warnings(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> tuple[str, ...]:
    warnings: list[str] = []
    protected_tokens = (
        "pbd",
        "cloth",
        "torn",
        "hair",
        "fur",
        "skin",
        "wrinkle",
        "eye",
        "pupil",
        "iris",
        "flow",
        "alphatest",
        "thickness",
    )
    patched_by_name: dict[str, list[PacXmlWrapperProfile]] = {}
    for wrapper in patched.wrappers:
        patched_by_name.setdefault(_wrapper_match_key(wrapper.wrapper_name), []).append(wrapper)
    for wrapper_index, left in enumerate(original.wrappers):
        right = None
        candidates = patched_by_name.get(_wrapper_match_key(left.wrapper_name), [])
        if candidates:
            right = candidates.pop(0)
        elif wrapper_index < len(patched.wrappers):
            indexed = patched.wrappers[wrapper_index]
            if _wrapper_match_key(indexed.wrapper_name) == _wrapper_match_key(left.wrapper_name):
                right = indexed
        if right is None:
            if _wrapper_has_protected_features(left, protected_tokens):
                warnings.append(f"{left.wrapper_name or '<unnamed>'}: protected PAC XML wrapper removed.")
            continue
        left_params = set(left.parameter_names)
        right_params = set(right.parameter_names)
        for removed in sorted(left_params - right_params):
            compact = re.sub(r"[^a-z0-9]+", "", removed.lower())
            if any(token in compact for token in protected_tokens):
                warnings.append(f"{left.wrapper_name or '<unnamed>'}: protected PAC XML param removed: {removed}.")
        if left.shader_family in {"Cloth", "Hair", "Fur", "Skin", "SkinWrinkle", "Eye", "EyeCover"} and left.shader_name != right.shader_name:
            warnings.append(
                f"{left.wrapper_name or '<unnamed>'}: protected shader changed from {left.shader_name or '<none>'} to {right.shader_name or '<none>'}."
            )
    if original.pbd_materials and not patched.pbd_materials:
        warnings.append("Protected PBD simulation material refs removed from PAC XML.")
    return tuple(warnings)


def _wrapper_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _wrapper_has_protected_features(wrapper: PacXmlWrapperProfile, protected_tokens: Sequence[str]) -> bool:
    if wrapper.shader_family in {"Cloth", "Hair", "Fur", "Skin", "SkinWrinkle", "Eye", "EyeCover"}:
        return True
    for param in wrapper.parameter_names:
        compact = re.sub(r"[^a-z0-9]+", "", param.lower())
        if any(token in compact for token in protected_tokens):
            return True
    return False


def _stock_runtime_support_replacement_warnings(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> tuple[str, ...]:
    warnings: list[str] = []
    original_refs: dict[tuple[int, str, str], PacXmlTextureRef] = {}
    for wrapper_index, wrapper in enumerate(original.wrappers):
        for ref in wrapper.texture_refs:
            original_refs[(wrapper_index, wrapper.wrapper_name, ref.parameter_name)] = ref
    for wrapper_index, wrapper in enumerate(patched.wrappers):
        for ref in wrapper.texture_refs:
            old = original_refs.get((wrapper_index, wrapper.wrapper_name, ref.parameter_name))
            if old is None or not old.stock_runtime:
                continue
            if old.role not in {"material_mask", "detail_mask", "height"}:
                continue
            if ref.stock_runtime or normalize_pac_xml_path(old.texture_path).lower() == normalize_pac_xml_path(ref.texture_path).lower():
                continue
            warnings.append(
                f"{wrapper.wrapper_name or '<unnamed>'} {ref.parameter_name}: stock runtime {old.texture_path} replaced by mod-owned {ref.texture_path} without explicit opt-in."
            )
    return tuple(warnings)


def _xml_attr(attrs: str, name: str) -> str:
    match = re.search(rf'\b{re.escape(name)}="([^"]*)"', str(attrs or ""), flags=re.IGNORECASE)
    return str(match.group(1) if match else "")


def _first_match(text: str, pattern: str) -> str:
    match = re.search(pattern, str(text or ""), flags=re.IGNORECASE | re.DOTALL)
    return str(match.group(1) if match else "")
