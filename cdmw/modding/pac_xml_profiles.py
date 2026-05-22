"""Learned PAC XML profile helpers.

The runtime material generator treats PAC XML as the authority.  These helpers
parse the parts that are safe to reason about without trying to rebuild Crimson
shader definitions from scratch.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping as MappingABC
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence


DEFAULT_PAC_XML_CORPUS_ROOT = Path(r"C:\Users\Ratrider\Desktop\CTF\archive_extract")
PAC_XML_PROFILE_INDEX_CACHE_NAME = "pac_xml_profile_index_v1.json"
PAC_XML_PROFILE_INDEX_SCHEMA = "cdmw_pac_xml_profile_index_v1_paths"


@dataclass(frozen=True, slots=True)
class PacXmlTextureRef:
    wrapper_name: str
    parameter_name: str
    texture_path: str
    role: str
    stock_runtime: bool


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
    template_wrapper_name: str = ""
    template_parameter_name: str = ""
    score: float = 0.0
    supports_slot: bool = False
    fallback_reason: str = ""

    def summary(self, *, target_name: str = "", slot_kind: str = "") -> str:
        target = f" target={target_name}" if target_name else ""
        slot = f" slot={slot_kind}" if slot_kind else ""
        parameter = f" param={self.template_parameter_name}" if self.template_parameter_name else ""
        fallback = f" fallback={self.fallback_reason}" if self.fallback_reason else ""
        return (
            f"PAC XML corpus template:{target}{slot} template={self.template_path or '<none>'} "
            f"wrapper={self.template_wrapper_name or '<none>'}{parameter} score={self.score:.2f}"
            f"{fallback}."
        )


@dataclass(slots=True)
class PacXmlCorpusIndex:
    root: Path
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


def default_pac_xml_profile_cache_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        root = Path(appdata) / "CDMW"
    else:
        root = Path.home() / ".cdmw"
    return root / PAC_XML_PROFILE_INDEX_CACHE_NAME


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
    if "normal" in name or path.endswith("_n.dds"):
        return "normal"
    if "height" in name or "displacement" in name or path.endswith("_disp.dds"):
        return "height"
    if "detailmask" in name or path.endswith("_mg.dds"):
        return "detail_mask"
    if "colorblendingmask" in name or "material" in name or path.endswith(("_ma.dds", "_m.dds", "_sp.dds")):
        return "material_mask"
    if "emissive" in name or path.endswith("_emi.dds"):
        return "emissive"
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
        index.profiles.append(report)
    return index


def load_or_build_pac_xml_corpus_index(
    root: str | Path = DEFAULT_PAC_XML_CORPUS_ROOT,
    *,
    cache_path: str | Path | None = None,
    limit: int | None = None,
    force: bool = False,
) -> PacXmlCorpusIndex:
    base = Path(root).expanduser()
    cache = Path(cache_path).expanduser() if cache_path is not None else default_pac_xml_profile_cache_path()
    count, newest = pac_xml_corpus_signature(base, limit=limit)
    if not force and count > 0 and cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            if (
                isinstance(payload, MappingABC)
                and payload.get("schema") == PAC_XML_PROFILE_INDEX_SCHEMA
                and normalize_pac_xml_path(payload.get("root", "")).lower() == normalize_pac_xml_path(base).lower()
                and int(payload.get("source_file_count") or 0) == count
                and int(payload.get("newest_mtime_ns") or 0) == newest
            ):
                return pac_xml_corpus_index_from_dict(payload)
        except Exception:
            pass
    index = build_pac_xml_corpus_index(base, limit=limit)
    index.source_file_count = count or index.source_file_count
    index.newest_mtime_ns = newest or index.newest_mtime_ns
    if index.xml_count:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(pac_xml_corpus_index_to_dict(index), separators=(",", ":"), sort_keys=True), encoding="utf-8")
        except Exception:
            pass
    return index


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


def pac_xml_corpus_index_to_dict(index: PacXmlCorpusIndex) -> dict[str, object]:
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
        "profiles": [_report_to_dict(report) for report in index.profiles],
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


def select_best_pac_xml_template(
    target_report: PacXmlProfileReport | None,
    target_wrapper: PacXmlWrapperProfile | None,
    slot_kind: str,
    corpus_index: PacXmlCorpusIndex | None,
) -> PacXmlTemplateMatch:
    slot = str(slot_kind or "").strip().lower()
    if corpus_index is None or not corpus_index.profiles:
        return PacXmlTemplateMatch(fallback_reason="no corpus index")
    if target_report is None:
        return PacXmlTemplateMatch(fallback_reason="no target PAC XML report")
    target_profile = target_report.profile
    target_role = target_wrapper.role if target_wrapper is not None else ""
    target_shader = target_wrapper.shader_family if target_wrapper is not None else ""
    target_params = set(target_wrapper.parameter_names) if target_wrapper is not None else set()
    best_score = 0.0
    best_report: PacXmlProfileReport | None = None
    best_wrapper: PacXmlWrapperProfile | None = None
    best_parameter = ""
    for candidate_report in corpus_index.profiles:
        for candidate_wrapper in candidate_report.wrappers:
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
    if best_report is None or best_wrapper is None:
        return PacXmlTemplateMatch(fallback_reason="no candidate template")
    supports = bool(best_parameter)
    fallback = "" if supports and best_score >= 0.45 else "template lacks compatible slot" if not supports else "low template score"
    return PacXmlTemplateMatch(
        template_path=best_report.path,
        template_wrapper_name=best_wrapper.wrapper_name,
        template_parameter_name=best_parameter,
        score=round(min(1.0, best_score), 3),
        supports_slot=bool(supports and best_score >= 0.45),
        fallback_reason=fallback,
    )


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
    for ref in wrapper.texture_refs:
        if ref.role == slot:
            return ref.parameter_name
    return ""


def _report_to_dict(report: PacXmlProfileReport) -> dict[str, object]:
    return {
        "path": report.path,
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


def _protected_param_removal_warnings(original: PacXmlProfileReport, patched: PacXmlProfileReport) -> tuple[str, ...]:
    warnings: list[str] = []
    protected_tokens = (
        "pbd",
        "cloth",
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
