from __future__ import annotations

import re
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import (
    _ARCHIVE_METADATA_XML_EXTENSIONS,
    _ARCHIVE_XML_LIKE_EXTENSIONS,
    _TEXT_DDS_REFERENCE_RE,
    _is_material_sidecar_extension,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_preview_support import resolve_archive_pathc_path
from cdmw.core.common import raise_if_cancelled
from cdmw.core.upscale_profiles import (
    normalize_texture_reference_for_sidecar_lookup,
    parse_material_sidecar_profile,
    parse_texture_sidecar_bindings,
)
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    MODEL_PREVIEW_VISIBLE_TEXTURE_MODES,
    ModelPreviewRenderSettings,
    PreviewMaterialParameterInput,
    RelationConfidence,
    RelationKind,
    RunCancelled,
)


def extract_binary_strings(*args, **kwargs):
    from cdmw.core.archive_binary_preview import extract_binary_strings as owner

    return owner(*args, **kwargs)


def _archive_path_is_probable_item_icon(*args, **kwargs):
    from cdmw.core.archive_references import _archive_path_is_probable_item_icon as owner

    return owner(*args, **kwargs)


def _is_placeholder_model_texture(*args, **kwargs):
    from cdmw.core.archive_model_textures import _is_placeholder_model_texture as owner

    return owner(*args, **kwargs)


_ARCHIVE_TEXTURE_FAMILY_SUFFIXES: Tuple[str, ...] = (
    "",
    "_ct",
    "_color",
    "_col",
    "_albedo",
    "_basecolor",
    "_base_color",
    "_diffuse",
    "_n",
    "_normal",
    "_normalmap",
    "_sp",
    "_spec",
    "_specular",
    "_m",
    "_mask",
    "_ma",
    "_mg",
    "_orm",
    "_mra",
    "_rma",
    "_arm",
    "_ao",
    "_o",
    "_height",
    "_hgt",
    "_disp",
    "_displacement",
    "_dmap",
    "_d",
    "_bump",
    "_parallax",
    "_pom",
    "_ssdm",
    "_em",
    "_emi",
    "_emissive",
    "_glow",
    "_material",
    "_mat",
)
_ARCHIVE_MODEL_FAMILY_VARIANT_SUFFIXES: Tuple[str, ...] = (
    "_l",
    "_r",
    "_u",
    "_s",
    "_t",
    "_in",
    "_c",
    "_d",
    "_index01",
    "_index02",
    "_index03",
    "_index01_l",
    "_index01_r",
    "_index02_l",
    "_index02_r",
    "_index03_l",
    "_index03_r",
    "_sub01",
    "_sub02",
    "_sub03",
)
_ARCHIVE_ITEM_ICON_STEM_PREFIXES: Tuple[str, ...] = (
    "itemicon_prefab_",
    "itemicon_",
    "icon_prefab_",
    "icon_",
)
_ARCHIVE_ATTACHMENT_SIDE_SUFFIXES: Tuple[str, ...] = ("_l", "_r")
_ARCHIVE_ATTACHMENT_SIDE_METADATA_EXTENSIONS: Tuple[str, ...] = (
    ".prefab",
    ".prefabdata.xml",
    ".prefabdata_xml",
    ".pappt",
    ".pamhc",
    ".sockets.xml",
)
_ARCHIVE_NUMBERED_MODEL_FAMILY_VARIANT_RE = re.compile(r"_(?:index|sub)\d{2}$", re.IGNORECASE)
_ARCHIVE_PREFAB_HELM_DESCRIPTOR_RE = re.compile(
    r"^(?P<prefix>cd_)phm_(?P<variant>\d{2})_hel_(?P<rest>.+)$",
    re.IGNORECASE,
)
_ARCHIVE_PLATE_HELM_MODEL_RE = re.compile(
    r"^(?P<prefix>cd_)ptm_(?P<variant>\d{2})_hel_(?P<rest>.+)$",
    re.IGNORECASE,
)
_ARCHIVE_CHARACTER_EQUIPMENT_COMPONENT_RE = re.compile(
    r"^(?P<root>cd_[a-z]\d{4}_\d{2}_.+?)_"
    r"(?P<part>ub|lb|hel|sho|hand|foot|belt|vest|mask|cloak|cape|hair|head|face|acc|body|arm|leg)"
    r"(?:_[a-z0-9]+)*_\d{4}(?:_\d+)?$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _ArchiveModelSidecarTextureBinding:
    texture_path: str
    parameter_name: str = ""
    submesh_name: str = ""
    sidecar_path: str = ""
    sidecar_kind: str = ""
    linked_mesh_path: str = ""
    part_name: str = ""
    material_name: str = ""
    shader_family: str = ""
    texture_role: str = ""
    visualization_state: str = ""
    resolved_texture_exists: bool = False
    represent_color: Tuple[float, float, float] = ()
    tint_color: Tuple[float, float, float] = ()
    brightness: float = 1.0
    uv_scale: float = 1.0
    tile_type: str = ""
    srgb_mode: str = ""
    parameter_declared_by: str = ""
    material_output_quality: str = ""
    layer_role: str = ""
    layer_channel: str = ""
    blend_flags: Tuple[str, ...] = ()
    material_parameters: Tuple[PreviewMaterialParameterInput, ...] = ()


@dataclass(slots=True)
class _StructuredBinaryPreviewBundle:
    preview_text: str
    detail_lines: Tuple[str, ...] = ()
    related_references: Tuple[ArchiveModelTextureReference, ...] = ()
    metadata_label: str = ""


@dataclass(slots=True)
class _BinarySidecarStringRecord:
    offset: int
    text: str


_MODEL_SIDECAR_PARSE_CACHE_LIMIT = 512
_MODEL_SIDECAR_PARSE_CACHE: OrderedDict[
    Tuple[object, ...],
    Tuple[Tuple["_ArchiveModelSidecarTextureBinding", ...], Tuple[str, ...], Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]],
] = OrderedDict()
_MODEL_SIDECAR_REFERENCE_CACHE_LIMIT = 256
_MODEL_SIDECAR_REFERENCE_CACHE: OrderedDict[
    Tuple[object, ...],
    Tuple[Tuple["_ArchiveModelSidecarTextureBinding", ...], Tuple[str, ...], Dict[str, Tuple[str, ...]], Dict[str, Tuple[str, ...]]],
] = OrderedDict()
_MODEL_SIDECAR_PARSE_CACHE_LOCK = threading.Lock()

def _normalize_model_texture_reference(value: str) -> str:
    raw_text = str(value or "").replace("\\", "/").strip().lower()
    if not raw_text or raw_text == ".":
        return ""
    normalized = PurePosixPath(raw_text).as_posix().strip().lower()
    if normalized == ".":
        return ""
    return normalized


_ARCHIVE_TEXTURE_FAMILY_STOP_TOKENS = {
    "actor",
    "animation",
    "armor",
    "base",
    "bin",
    "character",
    "color",
    "common",
    "dds",
    "diff",
    "diffuse",
    "disp",
    "game",
    "height",
    "hkx",
    "material",
    "mesh",
    "meshphysics",
    "model",
    "modelproperty",
    "normal",
    "object",
    "overlay",
    "pac",
    "pamlod",
    "paz",
    "pc",
    "phm",
    "phw",
    "ptm",
    "rough",
    "sp",
    "texture",
    "textures",
    "wrinkle",
    "xml",
}


def _archive_reference_family_tokens(value: str) -> set[str]:
    normalized = _normalize_model_texture_reference(value)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", normalized):
        token = token.strip().lower()
        if len(token) < 3:
            continue
        if token in _ARCHIVE_TEXTURE_FAMILY_STOP_TOKENS:
            continue
        if token.isdigit() or re.fullmatch(r"[a-z]{1,3}\d+", token):
            continue
        tokens.add(token)
    return tokens


def _archive_texture_family_mismatch_summary(
    source_path: str,
    texture_paths: Sequence[str],
    *,
    sidecar_paths: Sequence[str] = (),
) -> str:
    source_tokens = _archive_reference_family_tokens(source_path)
    texture_tokens: set[str] = set()
    for texture_path in texture_paths:
        texture_tokens.update(_archive_reference_family_tokens(texture_path))
    if not source_tokens or not texture_tokens or source_tokens & texture_tokens:
        return ""
    source_display = ", ".join(sorted(source_tokens)[:4])
    texture_display = ", ".join(sorted(texture_tokens)[:5])
    sidecar_display = ", ".join(str(path or "").strip() for path in sidecar_paths[:2] if str(path or "").strip())
    sidecar_note = f" from {sidecar_display}" if sidecar_display else ""
    return (
        "Cross-family material notice: the exact companion sidecar"
        f"{sidecar_note} points at texture family tokens [{texture_display}], while the selected model path looks like "
        f"[{source_display}]. This can be legitimate material reuse, but it is not proof of item identity."
    )


def _archive_texture_family_mismatch_reason(source_entry: ArchiveEntry, texture_entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(texture_entry, ArchiveEntry):
        return ""
    notice = _archive_texture_family_mismatch_summary(source_entry.path, (texture_entry.path,))
    if not notice:
        return ""
    return "cross-family texture name; exact sidecar binding may be legitimate material reuse"


def _normalize_model_submesh_reference(value: str) -> str:
    raw_text = str(value or "").replace("\\", "/").strip().lower()
    if not raw_text:
        return ""
    basename = PurePosixPath(raw_text).name or raw_text
    normalized = re.sub(r"[^a-z0-9]+", "", basename)
    if normalized:
        return normalized
    return re.sub(r"[^a-z0-9]+", "", raw_text)


def _is_anonymous_model_submesh_reference_key(value: str) -> bool:
    normalized = _normalize_model_submesh_reference(value)
    if not normalized:
        return True
    generic_roots = (
        "default",
        "group",
        "mesh",
        "node",
        "object",
        "root",
        "scene",
        "sceneroot",
        "submesh",
        "unknown",
    )
    if normalized in generic_roots:
        return True
    return any(re.fullmatch(fr"{root}\d*", normalized) for root in generic_roots)


def extract_binary_dds_references(
    data: bytes,
    *,
    sample_limit: int = 262_144,
    max_strings: int = 96,
) -> List[str]:
    references: List[str] = []
    seen: set[str] = set()
    string_candidates = extract_binary_strings(
        data,
        sample_limit=sample_limit,
        max_strings=max(max_strings * 2, 48),
    )
    for text in string_candidates:
        for match in _TEXT_DDS_REFERENCE_RE.finditer(text):
            raw_text = str(match.group(0) or "").strip().strip("\x00")
            if not raw_text or not any(char.isalpha() for char in raw_text):
                continue
            normalized = _normalize_model_texture_reference(raw_text)
            if not normalized or not normalized.endswith(".dds") or normalized in seen:
                continue
            seen.add(normalized)
            references.append(raw_text.replace("\\", "/"))
            if len(references) >= max_strings:
                return references
    return references


def _humanize_model_texture_hint(semantic_hint: str) -> str:
    raw_text = str(semantic_hint or "").strip().lstrip("_")
    if not raw_text:
        return ""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_text)
    spaced = re.sub(r"[_\s]+", " ", spaced).strip()
    if not spaced:
        return ""
    return " ".join(part[:1].upper() + part[1:] for part in spaced.split())


def _model_texture_hint_priority(semantic_hint: str) -> Optional[Tuple[int, int]]:
    normalized = str(semantic_hint or "").strip().lower().replace("_", "")
    if not normalized:
        return None

    technical_tokens = (
        "normal",
        "height",
        "displacement",
        "materialtexture",
        "materialmask",
        "detailmask",
        "masktexture",
        "roughness",
        "metallic",
        "occlusion",
        "opacity",
        "screenspacedisplacement",
        "specular",
    )
    if any(token in normalized for token in technical_tokens):
        return (0, 0)

    channel_priority = 0
    for suffix, priority in (
        ("texturer", 3),
        ("maskr", 3),
        ("textureg", 2),
        ("maskg", 2),
        ("textureb", 1),
        ("maskb", 1),
        ("texturea", 0),
        ("maska", 0),
    ):
        if normalized.endswith(suffix):
            channel_priority = priority
            break

    if any(token in normalized for token in ("grimediffusetexture", "grimediffusemask", "grimecolortexture")):
        return (3, channel_priority)
    if any(token in normalized for token in ("detaildiffusetexture", "detaildiffusemask", "detailcolortexture")):
        return (5, 1 + channel_priority)
    if "diffusetexture" in normalized:
        return (6, 4 + channel_priority)
    if "diffusemask" in normalized:
        return (6, 1 + channel_priority)
    if "overlaycolor" in normalized:
        return (5, 2)
    if any(
        token in normalized
        for token in (
            "colortexture",
            "diffuse",
            "albedo",
            "basecolor",
            "emissive",
            "tintcolor",
        )
    ):
        return (6, 3)
    if "color" in normalized or "overlay" in normalized or "tint" in normalized:
        return (6, 2)
    return None


def _normalize_model_visible_texture_mode(visible_texture_mode: str) -> str:
    normalized_mode = str(visible_texture_mode or "").strip().lower()
    if normalized_mode not in MODEL_PREVIEW_VISIBLE_TEXTURE_MODES:
        return ModelPreviewRenderSettings().visible_texture_mode
    return normalized_mode


def _classify_model_sidecar_visible_binding(semantic_hint: str, texture_path: str) -> str:
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    texture_basename = PurePosixPath(str(texture_path or "").replace("\\", "/")).stem.lower()
    if _is_placeholder_model_texture(texture_path):
        return "technical"

    technical_tokens = (
        "normal",
        "height",
        "displacement",
        "material",
        "roughness",
        "metallic",
        "ambientocclusion",
        "occlusion",
        "opacity",
        "specular",
        "orm",
        "rma",
        "mra",
        "arm",
        "ao",
        "flow",
        "direction",
        "vector",
        "velocity",
        "position",
        "pivot",
        "ssdm",
    )
    technical_suffixes = (
        "_n",
        "_normal",
        "_normalmap",
        "_disp",
        "_displacement",
        "_height",
        "_hgt",
        "_dmap",
        "_parallax",
        "_pom",
        "_ssdm",
        "_mask",
        "_ma",
        "_mg",
        "_sp",
        "_orm",
        "_rma",
        "_mra",
        "_arm",
        "_ao",
        "_spec",
        "_specular",
        "_roughness",
        "_metallic",
        "_dr",
        "_flow",
        "_velocity",
        "_vector",
        "_pos",
        "_position",
        "_pivot",
        "_pivotpos",
    )
    if any(token in normalized_hint for token in technical_tokens):
        return "technical"
    if normalized_hint in {"colorblendingmasktexture", "detailmasktexture"}:
        return "technical"
    if "mask" in normalized_hint and not any(
        token in normalized_hint for token in ("diffuse", "albedo", "color", "colour", "overlay", "emissive")
    ):
        return "technical"
    if texture_basename.endswith(technical_suffixes):
        return "technical"

    layer_tokens = (
        "grime",
        "detail",
        "layer",
        "blend",
        "decal",
    )
    if any(token in normalized_hint for token in layer_tokens):
        return "layer_visible"

    primary_tokens = (
        "basecolor",
        "basecolour",
        "albedo",
        "diffuse",
        "colortexture",
        "overlaycolor",
        "base",
    )
    if any(token in normalized_hint for token in primary_tokens):
        return "primary_visible"

    generic_tokens = (
        "color",
        "colour",
        "overlay",
        "tint",
        "emissive",
    )
    if any(token in normalized_hint for token in generic_tokens):
        return "visible_generic"

    if not normalized_hint:
        return "visible_generic"
    return "visible_generic"


def _allowed_model_sidecar_visible_classes(visible_texture_mode: str) -> Tuple[str, ...]:
    normalized_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    if normalized_mode == "mesh_base_first":
        return ("primary_visible",)
    if normalized_mode == "layer_aware_visible":
        return ("primary_visible", "visible_generic", "layer_visible")
    return ("primary_visible", "visible_generic", "layer_visible")


def _model_sidecar_visible_class_priority(binding_class: str) -> int:
    if binding_class == "primary_visible":
        return 3
    if binding_class == "layer_visible":
        return 2
    if binding_class == "visible_generic":
        return 1
    return 0


def _model_texture_slot_hint_priority(preview_slot: str, semantic_hint: str) -> Optional[Tuple[int, int]]:
    normalized_slot = str(preview_slot or "").strip().lower()
    normalized_hint = str(semantic_hint or "").strip().lower().replace("_", "")
    if not normalized_slot or not normalized_hint:
        return None

    if normalized_slot == "base":
        if "basecolor" in normalized_hint:
            return (9, 4)
        if any(token in normalized_hint for token in ("grimediffuse", "detaildiffuse", "detailalbedo", "detailcolor")):
            return (5, 1)
        if any(
            token in normalized_hint
            for token in (
                "overlaycolor",
                "colortexture",
                "diffuse",
                "albedo",
                "emissive",
            )
        ):
            return (8, 3)
        if "tintcolor" in normalized_hint:
            return (6, 1)
        if "color" in normalized_hint or "overlay" in normalized_hint or "tint" in normalized_hint:
            return (5, 0)
        return None

    if normalized_slot == "normal":
        if normalized_hint in {"normaltexture", "basenormaltexture"}:
            return (9, 4)
        if "detailnormal" in normalized_hint or "grimenormal" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("normal") or normalized_hint.endswith("normaltexture"):
            return (8, 3)
        if "normal" in normalized_hint:
            return (6, 0)
        return None

    if normalized_slot == "material":
        if normalized_hint in {"materialtexture", "basematerialtexture"}:
            return (9, 4)
        if "detailmaterial" in normalized_hint or "grimematerial" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("material") or normalized_hint.endswith("materialtexture"):
            return (8, 3)
        if any(token in normalized_hint for token in ("masktexture", "detailmask", "material", "roughness", "metallic", "occlusion")):
            return (6, 0)
        return None

    if normalized_slot == "height":
        if normalized_hint in {"heighttexture", "displacementtexture"}:
            return (9, 4)
        if "detailheight" in normalized_hint or "detaildisplacement" in normalized_hint:
            return (5, 1)
        if normalized_hint.startswith("height") or normalized_hint.endswith("heighttexture"):
            return (8, 3)
        if normalized_hint.startswith("displacement") or normalized_hint.endswith("displacementtexture"):
            return (8, 2)
        if any(token in normalized_hint for token in ("height", "displacement", "parallax", "pom", "ssdm", "bump")):
            return (6, 0)
        return None

    return None


def _score_model_sidecar_entry_candidate(source_entry: ArchiveEntry, candidate: ArchiveEntry) -> Tuple[int, int, int]:
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    source_path = _normalize_model_texture_reference(source_entry.path)
    source_root = PurePosixPath(source_path).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 10
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 6
    if "/texture/" in normalized_candidate:
        score_value += 8
    if candidate_root and source_root and candidate_root == source_root:
        score_value += 4
    source_extension = str(source_entry.extension or "").strip().lower()
    candidate_extension = str(candidate.extension or "").strip().lower()
    candidate_basename = PurePosixPath(candidate.path.replace("\\", "/")).name.lower()
    if source_extension in {".pam", ".pamlod"} and normalized_candidate.endswith(".pami"):
        extension_priority = 2
    elif _is_material_sidecar_extension(candidate_extension, candidate_basename):
        extension_priority = 2
    elif normalized_candidate.endswith(".xml") or candidate_extension in _ARCHIVE_METADATA_XML_EXTENSIONS:
        extension_priority = 1
    else:
        extension_priority = 0
    return score_value, extension_priority, -len(candidate.path)


def _score_model_related_entry_candidate(source_entry: ArchiveEntry, candidate: ArchiveEntry) -> Tuple[int, int, int]:
    normalized_candidate = _normalize_model_texture_reference(candidate.path)
    source_path = _normalize_model_texture_reference(source_entry.path)
    source_root = PurePosixPath(source_path).parts[:1]
    candidate_root = PurePosixPath(normalized_candidate).parts[:1]
    score_value = 0
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 10
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 6
    if candidate_root and source_root and candidate_root == source_root:
        score_value += 4
    source_extension = str(source_entry.extension or "").strip().lower()
    candidate_extension = str(candidate.extension or "").strip().lower()
    extension_priority = 0
    if source_extension == ".pam":
        if candidate_extension == ".pamlod":
            extension_priority = 6
        elif candidate_extension in {".pami", ".pam_xml"}:
            extension_priority = 5
        elif candidate_extension in {".xml", ".pamlod_xml"}:
            extension_priority = 4
        elif candidate_extension == ".meshinfo":
            extension_priority = 3
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 2
    elif source_extension == ".pamlod":
        if candidate_extension == ".pam":
            extension_priority = 6
        elif candidate_extension in {".pami", ".pamlod_xml", ".pam_xml"}:
            extension_priority = 5
        elif candidate_extension == ".xml":
            extension_priority = 4
        elif candidate_extension == ".meshinfo":
            extension_priority = 3
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 2
    elif source_extension == ".pac":
        if candidate_extension == ".pab":
            extension_priority = 7
        elif candidate_extension == ".pac_xml":
            extension_priority = 6
        elif candidate_extension in {".xml", ".prefabdata_xml"}:
            extension_priority = 5
        elif candidate_extension == ".meshinfo":
            extension_priority = 4
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 3
        elif candidate_extension in {".prefab", ".pappt", ".pamhc"}:
            extension_priority = 3
    elif source_extension == ".prefab":
        if candidate_extension == ".pac":
            extension_priority = 7
        elif candidate_extension == ".pac_xml":
            extension_priority = 6
        elif candidate_extension in {".pab", ".meshinfo"}:
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 3
        elif candidate_extension == ".dds":
            extension_priority = 2
    elif source_extension in {".pappt", ".pamhc"}:
        if candidate_extension in {".pac", ".pam", ".pamlod"}:
            extension_priority = 7
        elif candidate_extension in {".prefab", ".prefabdata_xml", ".app_xml"}:
            extension_priority = 6
        elif candidate_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".pami"}:
            extension_priority = 5
        elif candidate_extension in {".meshinfo", ".hkx", ".hkt"}:
            extension_priority = 4
        elif candidate_extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
            extension_priority = 3
    elif source_extension == ".meshinfo":
        if candidate_extension in {".pam", ".pamlod", ".pac"}:
            extension_priority = 7
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 6
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 5
        elif candidate_extension == ".pami":
            extension_priority = 4
    elif source_extension == ".pab":
        if candidate_extension == ".pac":
            extension_priority = 7
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 6
        elif candidate_extension == ".meshinfo":
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif source_extension in {".paa", ".paa_metabin", ".motionblending", ".pae", ".paem", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"}:
        if candidate_extension in {".hkx", ".hkt", ".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"}:
            extension_priority = 6
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 5
    elif source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
        source_stem_lower = PurePosixPath(source_entry.path.replace("\\", "/")).stem.lower()
        if source_stem_lower.endswith(".pac"):
            if candidate_extension == ".pac":
                extension_priority = 7
            elif candidate_extension == ".pab":
                extension_priority = 6
            elif candidate_extension == ".meshinfo":
                extension_priority = 5
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 4
        elif source_stem_lower.endswith(".pam"):
            if candidate_extension == ".pam":
                extension_priority = 7
            elif candidate_extension == ".pamlod":
                extension_priority = 6
            elif candidate_extension == ".pami":
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 3
        elif source_stem_lower.endswith(".pamlod"):
            if candidate_extension == ".pamlod":
                extension_priority = 7
            elif candidate_extension == ".pam":
                extension_priority = 6
            elif candidate_extension == ".pami":
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 3
        elif source_stem_lower.endswith(".pab"):
            if candidate_extension == ".pab":
                extension_priority = 7
            elif candidate_extension == ".pac":
                extension_priority = 6
            elif candidate_extension in {".hkx", ".hkt"}:
                extension_priority = 5
            elif candidate_extension == ".meshinfo":
                extension_priority = 4
        elif candidate_extension in {".pam", ".pamlod", ".pac", ".pab", ".pami", ".meshinfo", ".hkx", ".hkt"}:
            extension_priority = 3
    elif source_extension == ".pami":
        if candidate_extension in {".pam", ".pamlod"}:
            extension_priority = 7
        elif candidate_extension == ".meshinfo":
            extension_priority = 6
        elif candidate_extension in {".hkx", ".hkt"}:
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif source_extension in {".hkx", ".hkt"}:
        if candidate_extension in {".pam", ".pamlod", ".pac"}:
            extension_priority = 7
        elif candidate_extension == ".pab":
            extension_priority = 6
        elif candidate_extension == ".meshinfo":
            extension_priority = 5
        elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            extension_priority = 4
    elif candidate_extension in _ARCHIVE_XML_LIKE_EXTENSIONS | {".meshinfo", ".hkx", ".hkt"}:
        extension_priority = 2
    return score_value, extension_priority, -len(candidate.path)


def _extend_archive_related_target_basenames(
    add_target: Callable[[str], None],
    *,
    stem: str,
    source_extension: str,
) -> None:
    if not stem:
        return
    add_target(f"{stem}.xml")
    add_target(f"{stem}.hkx")
    add_target(f"{stem}.hkt")
    add_target(f"{stem}.meshinfo")
    add_target(f"{stem}.app_xml")
    add_target(f"{stem}.app.xml")
    add_target(f"{stem}.prefab")
    add_target(f"{stem}.prefabdata.xml")
    add_target(f"{stem}.prefabdata_xml")
    add_target(f"{stem}.pappt")
    add_target(f"{stem}.pamhc")
    add_target(f"{stem}.sockets.xml")
    add_target(f"{stem}.paa")
    add_target(f"{stem}.paa_metabin")
    add_target(f"{stem}.pae")
    add_target(f"{stem}.paem")
    add_target(f"{stem}.motionblending")
    add_target(f"{stem}.paseq")
    add_target(f"{stem}.paseqc")
    add_target(f"{stem}.paschedule")
    add_target(f"{stem}.paschedulepath")
    add_target(f"{stem}.pastage")
    add_target(f"{stem}.seqmt")
    if source_extension in {".pam", ".pamlod"}:
        add_target(f"{stem}.pami")
        add_target(f"{stem}.pam_xml")
        add_target(f"{stem}.pamlod_xml")
    if source_extension == ".pam":
        add_target(f"{stem}.pamlod")
        if stem.endswith("_breakable"):
            add_target(f"{stem[:-10]}.pamlod")
    elif source_extension == ".pamlod":
        add_target(f"{stem}.pam")
    elif source_extension == ".pac":
        add_target(f"{stem}.pab")
        add_target(f"{stem}.pac_xml")
        add_target(f"{stem}.pac.xml")
        add_target(f"{stem}.pappt")
        add_target(f"{stem}.pamhc")
    elif source_extension == ".meshinfo":
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pami")
    elif source_extension == ".pab":
        add_target(f"{stem}.pac")
    elif source_extension == ".pami":
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
    elif source_extension in {".pappt", ".pamhc"}:
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pab")
        add_target(f"{stem}.hkx")
        add_target(f"{stem}.hkt")
        add_target(f"{stem}.meshinfo")
        add_target(f"{stem}.pac_xml")
        add_target(f"{stem}.pam_xml")
        add_target(f"{stem}.pamlod_xml")
        add_target(f"{stem}.pami")
        add_target(f"{stem}.prefab")
        add_target(f"{stem}.prefabdata.xml")
        add_target(f"{stem}.prefabdata_xml")
    elif source_extension in {".pac_xml", ".pam_xml", ".pamlod_xml", ".prefabdata_xml"}:
        if source_extension == ".pac_xml":
            add_target(f"{stem}.pac")
            add_target(f"{stem}.pab")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.app_xml")
            add_target(f"{stem}.app.xml")
            add_target(f"{stem}.prefabdata.xml")
            add_target(f"{stem}.prefabdata_xml")
        elif source_extension == ".pam_xml":
            add_target(f"{stem}.pam")
            add_target(f"{stem}.pamlod")
            add_target(f"{stem}.pami")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
        elif source_extension == ".pamlod_xml":
            add_target(f"{stem}.pamlod")
            add_target(f"{stem}.pam")
            add_target(f"{stem}.pami")
            add_target(f"{stem}.meshinfo")
            add_target(f"{stem}.hkx")
            add_target(f"{stem}.hkt")
    elif source_extension == ".seqmt":
        for related_extension in (
            ".dds",
            ".paa",
            ".paa_metabin",
            ".pae",
            ".paem",
            ".motionblending",
            ".hkx",
            ".hkt",
            ".paseq",
            ".paseqc",
            ".paschedule",
            ".paschedulepath",
            ".pastage",
            ".seqmt",
        ):
            add_target(f"{stem}{related_extension}")
    elif source_extension in {".paa", ".paa_metabin", ".motionblending", ".pae", ".paem", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
        for related_extension in (".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".hkx", ".hkt", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage", ".seqmt"):
            add_target(f"{stem}{related_extension}")
    elif source_extension in {".hkx", ".hkt"}:
        add_target(f"{stem}.pam")
        add_target(f"{stem}.pamlod")
        add_target(f"{stem}.pac")
        add_target(f"{stem}.pab")
        add_target(f"{stem}.pami")


def _collect_same_stem_related_target_basenames(source_entry: ArchiveEntry) -> set[str]:
    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip().lower()
    stem = PurePosixPath(normalized_path).stem.strip()
    source_extension = str(source_entry.extension or "").strip().lower()
    targets: set[str] = set()

    def add_target(raw_value: str) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            targets.add(candidate)

    if basename:
        add_target(f"{basename}.xml")
        add_target(f"{basename}.hkx")
        add_target(f"{basename}.hkt")
        add_target(f"{basename}.meshinfo")
    if stem:
        _extend_archive_related_target_basenames(
            add_target,
            stem=stem,
            source_extension=source_extension,
        )
        if source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = stem.strip().lower()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(nested_basename)
                _extend_archive_related_target_basenames(
                    add_target,
                    stem=nested_stem,
                    source_extension=nested_extension,
                )
    return targets


def _strip_archive_model_family_variant_suffix(stem: str) -> str:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ""
    while True:
        before = normalized
        for suffix in sorted(_ARCHIVE_MODEL_FAMILY_VARIANT_SUFFIXES, key=len, reverse=True):
            if normalized.endswith(suffix) and len(normalized) > len(suffix):
                normalized = normalized[: -len(suffix)]
                break
        if normalized != before:
            continue
        stripped = _ARCHIVE_NUMBERED_MODEL_FAMILY_VARIANT_RE.sub("", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        stripped = re.sub(r"(?<=\d)[a-z]$", "", normalized).strip()
        if stripped and stripped != normalized:
            normalized = stripped
            continue
        return normalized or before


def _iter_archive_prefab_equipment_family_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    add(normalized)
    add(_strip_archive_model_family_variant_suffix(normalized))
    for candidate in tuple(candidates):
        if "_set_" in candidate:
            add(candidate.replace("_set_", "_", 1))

    for candidate in tuple(candidates):
        match = _ARCHIVE_PREFAB_HELM_DESCRIPTOR_RE.match(candidate)
        if not match:
            continue
        rest = match.group("rest")
        for model_variant in ("00", "01"):
            add(f"{match.group('prefix')}ptm_{model_variant}_hel_{rest}")
    return tuple(candidates)


def _iter_archive_attachment_side_family_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    add(normalized)
    base_stem = _strip_archive_model_family_variant_suffix(normalized)
    add(base_stem)
    for side_suffix in _ARCHIVE_ATTACHMENT_SIDE_SUFFIXES:
        if base_stem and not base_stem.endswith(side_suffix):
            add(f"{base_stem}{side_suffix}")
    return tuple(candidates)


def iter_archive_equipment_model_alias_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    source_stems = [normalized, _strip_archive_model_family_variant_suffix(normalized)]
    for source_stem in source_stems:
        match = _ARCHIVE_PLATE_HELM_MODEL_RE.match(source_stem)
        if not match:
            continue
        rest = match.group("rest")
        descriptor_stem = f"{match.group('prefix')}phm_00_hel_{rest}"
        add(descriptor_stem)
        add(f"{descriptor_stem}_c")
        if rest.isdigit():
            set_descriptor_stem = f"{match.group('prefix')}phm_00_hel_set_{rest}"
            add(set_descriptor_stem)
            add(f"{set_descriptor_stem}_c")
    return tuple(candidates)


def iter_archive_character_equipment_root_alias_stems(stem: str) -> Tuple[str, ...]:
    normalized = str(stem or "").strip().lower()
    if not normalized:
        return ()
    candidates: List[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = str(value or "").strip().lower()
        if candidate and candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    for source_stem in (normalized, _strip_archive_model_family_variant_suffix(normalized)):
        match = _ARCHIVE_CHARACTER_EQUIPMENT_COMPONENT_RE.match(source_stem)
        if match:
            add(match.group("root"))
    return tuple(candidates)


def _collect_family_heuristic_target_basenames(source_entry: ArchiveEntry) -> set[str]:
    normalized_path = source_entry.path.replace("\\", "/").strip().lower()
    source_extension = str(source_entry.extension or "").strip().lower()
    if source_extension not in {
        ".pac",
        ".pam",
        ".pamlod",
        ".pab",
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".seqmt",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".app_xml",
        ".prefabdata_xml",
        ".prefab",
        ".pappt",
        ".pamhc",
    }:
        return set()
    targets: set[str] = set()
    for pab_basename in iter_pab_candidate_basenames(normalized_path):
        normalized_pab = str(pab_basename or "").strip().lower()
        if not normalized_pab:
            continue
        targets.add(normalized_pab)
        family_stem = PurePosixPath(normalized_pab).stem
        if not family_stem:
            continue
        for extension in (".pac", ".pab", ".hkx", ".hkt", ".meshinfo", ".seqmt", ".app_xml", ".app.xml", ".prefabdata.xml", ".pac_xml", ".prefabdata_xml", ".pappt", ".pamhc"):
            targets.add(f"{family_stem}{extension}")
    if source_extension in {".prefab", ".pappt", ".pamhc"}:
        source_stem = PurePosixPath(normalized_path).stem.strip().lower()
        for family_stem in _iter_archive_prefab_equipment_family_stems(source_stem):
            for extension in (
                ".pac",
                ".pab",
                ".hkx",
                ".hkt",
                ".meshinfo",
                ".seqmt",
                ".prefabdata.xml",
                ".pac_xml",
                ".prefabdata_xml",
                ".pappt",
                ".pamhc",
                ".sockets.xml",
            ):
                targets.add(f"{family_stem}{extension}")
            for texture_suffix in _ARCHIVE_TEXTURE_FAMILY_SUFFIXES:
                targets.add(f"{family_stem}{texture_suffix}.dds")
    elif source_extension in {
        ".pac",
        ".pam",
        ".pamlod",
        ".pab",
        ".hkx",
        ".hkt",
        ".meshinfo",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".app_xml",
        ".prefabdata_xml",
    }:
        source_stem = PurePosixPath(normalized_path).stem.strip().lower()
        for family_stem in _iter_archive_attachment_side_family_stems(source_stem):
            for extension in _ARCHIVE_ATTACHMENT_SIDE_METADATA_EXTENSIONS:
                targets.add(f"{family_stem}{extension}")
    return targets


def _relation_group_for_kind(relation_kind: str) -> str:
    normalized_kind = str(relation_kind or "").strip().lower()
    if normalized_kind == "item_icon":
        return "Item Icons"
    if normalized_kind == RelationKind.TEXTURE.value:
        return "Textures"
    if normalized_kind == RelationKind.MATERIAL_SIDECAR.value:
        return "Material Sidecars"
    if normalized_kind in {RelationKind.MESH.value, RelationKind.LOD.value}:
        return "Mesh / Model"
    if normalized_kind == RelationKind.SKELETON.value:
        return "Skeleton / Rig"
    if normalized_kind == "physics":
        return "Physics / Collision"
    if normalized_kind == RelationKind.ANIMATION.value:
        return "Animation / Motion"
    return "Metadata / Other"


def _relation_kind_for_entry(candidate_entry: Optional[ArchiveEntry], reference_name: str = "") -> str:
    reference_path = str(getattr(candidate_entry, "path", "") or reference_name).replace("\\", "/")
    reference_path_lower = reference_path.lower()
    reference_basename = PurePosixPath(reference_path).name.lower()
    extension = str(getattr(candidate_entry, "extension", "") or PurePosixPath(reference_path).suffix).strip().lower()
    if _archive_path_is_probable_item_icon(reference_path):
        return "item_icon"
    if extension in {".dds", ".seqmt"}:
        return RelationKind.TEXTURE.value
    if _is_material_sidecar_extension(extension, reference_basename):
        return RelationKind.MATERIAL_SIDECAR.value
    if extension == ".xml":
        return RelationKind.METADATA.value
    if extension in {".app_xml", ".prefabdata_xml", ".pappt", ".pamhc"}:
        return RelationKind.METADATA.value
    if extension in {".pab", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
        return RelationKind.SKELETON.value
    if extension in {".pac", ".pam"}:
        return RelationKind.MESH.value
    if extension == ".pamlod":
        return RelationKind.LOD.value
    if extension in {".hkx", ".hkt"}:
        if any(token in reference_path_lower for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
            return "physics"
        return RelationKind.ANIMATION.value
    if extension in {".motionblending", ".papr", ".paa", ".paa_metabin", ".pae", ".paem", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
        return RelationKind.ANIMATION.value
    return RelationKind.METADATA.value


def _build_archive_relation_metadata(
    source_entry: ArchiveEntry,
    *,
    reference_name: str = "",
    resolved_entry: Optional[ArchiveEntry] = None,
    authoritative: bool = False,
    authoritative_reason: str = "",
) -> Tuple[str, str, str, str]:
    relation_kind = _relation_kind_for_entry(resolved_entry, reference_name=reference_name)
    normalized_reference = _normalize_model_texture_reference(reference_name)
    normalized_source = _normalize_model_texture_reference(source_entry.path)
    normalized_resolved = _normalize_model_texture_reference(str(getattr(resolved_entry, "path", "") or ""))
    normalized_basename = PurePosixPath(
        str(getattr(resolved_entry, "path", "") or reference_name).replace("\\", "/")
    ).name.strip().lower()
    same_stem_targets = _collect_same_stem_related_target_basenames(source_entry)
    family_targets = _collect_family_heuristic_target_basenames(source_entry)
    if authoritative:
        confidence = RelationConfidence.AUTHORITATIVE.value
        reason = authoritative_reason or "Explicit path or sidecar binding"
    elif normalized_reference and normalized_resolved and normalized_reference == normalized_resolved:
        confidence = RelationConfidence.EXACT_PATH.value
        reason = "Exact archive path"
    elif (
        normalized_reference
        and normalized_resolved
        and normalized_reference.lstrip("/") == normalized_resolved.lstrip("/")
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Path-normalized reference"
    elif (
        normalized_source
        and normalized_resolved
        and normalized_source.replace("/modelproperty/", "/model/") == normalized_resolved
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Linked mesh via modelproperty -> model"
    elif (
        normalized_source
        and normalized_resolved
        and normalized_source.replace("/model/", "/modelproperty/") == normalized_resolved
    ):
        confidence = RelationConfidence.PATH_NORMALIZED.value
        reason = "Linked material sidecar via model -> modelproperty"
    elif (
        isinstance(resolved_entry, ArchiveEntry)
        and source_entry.pamt_path != resolved_entry.pamt_path
        and source_entry.pamt_path.parent != resolved_entry.pamt_path.parent
    ):
        confidence = RelationConfidence.CROSS_PACKAGE.value
        reason = "Cross-package reference"
    elif normalized_basename and normalized_basename in family_targets and normalized_basename not in same_stem_targets:
        confidence = RelationConfidence.DERIVED_FAMILY_HEURISTIC.value
        reason = "Family-token heuristic"
    else:
        confidence = RelationConfidence.DERIVED_SAME_STEM.value
        reason = "Same-stem heuristic"
    return relation_kind, _relation_group_for_kind(relation_kind), confidence, reason


def _find_archive_model_related_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()

    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip()
    source_stem = PurePosixPath(normalized_path).stem.strip()
    if not basename:
        return ()

    source_extension = str(source_entry.extension or "").strip().lower()
    target_basenames: set[str] = set()
    must_keep_basenames: set[str] = set()

    def add_target(raw_value: str, *, must_keep: bool = False) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            target_basenames.add(candidate)
            if must_keep:
                must_keep_basenames.add(candidate)

    add_target(f"{basename}.xml", must_keep=True)
    if source_stem:
        _extend_archive_related_target_basenames(
            add_target,
            stem=source_stem,
            source_extension=source_extension,
        )
        if source_extension == ".pac":
            add_target(f"{source_stem}.pab", must_keep=True)
            add_target(f"{source_stem}.prefabdata.xml", must_keep=True)
            add_target(f"{source_stem}.pac_xml", must_keep=True)
            add_target(f"{source_stem}.prefabdata_xml", must_keep=True)
        elif source_extension == ".pam":
            add_target(f"{source_stem}.pami", must_keep=True)
            add_target(f"{source_stem}.pam_xml", must_keep=True)
            add_target(f"{source_stem}.pamlod", must_keep=True)
        elif source_extension == ".pamlod":
            add_target(f"{source_stem}.pami", must_keep=True)
            add_target(f"{source_stem}.pamlod_xml", must_keep=True)
            add_target(f"{source_stem}.pam_xml", must_keep=True)
            add_target(f"{source_stem}.pam", must_keep=True)
        if source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = source_stem.strip()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(nested_basename, must_keep=True)
                _extend_archive_related_target_basenames(
                    add_target,
                    stem=nested_stem,
                    source_extension=nested_extension,
                )
    for family_target in _collect_family_heuristic_target_basenames(source_entry):
        add_target(family_target)
    add_target(f"{basename}.hkx", must_keep=True)
    add_target(f"{basename}.hkt", must_keep=True)
    add_target(f"{basename}.meshinfo", must_keep=True)

    candidates: List[ArchiveEntry] = []
    must_keep_candidates: List[ArchiveEntry] = []
    for target_basename in target_basenames:
        for candidate in archive_entries_by_basename.get(target_basename, ()):
            if candidate.path == source_entry.path:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
            if target_basename in must_keep_basenames and candidate not in must_keep_candidates:
                must_keep_candidates.append(candidate)
    if not candidates:
        return ()
    candidates.sort(key=lambda candidate: _score_model_related_entry_candidate(source_entry, candidate), reverse=True)
    ordered: List[ArchiveEntry] = []
    for candidate in must_keep_candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    for candidate in candidates:
        if candidate not in ordered:
            ordered.append(candidate)
    return tuple(ordered[:64])


def _find_archive_model_sidecar_entries(
    source_entry: ArchiveEntry,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]],
) -> Tuple[ArchiveEntry, ...]:
    if archive_entries_by_basename is None:
        return ()

    normalized_path = source_entry.path.replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name.strip()
    source_stem = PurePosixPath(normalized_path).stem.strip()
    source_extension = str(source_entry.extension or "").strip().lower()
    target_basenames: set[str] = set()

    def add_target(raw_value: str) -> None:
        candidate = str(raw_value or "").strip().lower()
        if candidate:
            target_basenames.add(candidate)

    if basename:
        add_target(f"{basename}.xml")
    if source_stem:
        add_target(f"{source_stem}.xml")
        if source_extension == ".pac":
            add_target(f"{source_stem}.pac_xml")
        elif source_extension == ".pam":
            add_target(f"{source_stem}.pam_xml")
        elif source_extension == ".pamlod":
            add_target(f"{source_stem}.pamlod_xml")
        if source_extension in {".pam", ".pamlod"}:
            add_target(f"{source_stem}.pami")
        elif source_extension in _ARCHIVE_XML_LIKE_EXTENSIONS:
            nested_basename = source_stem.strip()
            nested_extension = PurePosixPath(nested_basename).suffix.strip().lower()
            nested_stem = PurePosixPath(nested_basename).stem.strip()
            if nested_extension:
                add_target(f"{nested_basename}.xml")
                add_target(f"{nested_stem}.xml")
                if nested_extension == ".pac":
                    add_target(f"{nested_stem}.pac_xml")
                elif nested_extension == ".pam":
                    add_target(f"{nested_stem}.pam_xml")
                elif nested_extension == ".pamlod":
                    add_target(f"{nested_stem}.pamlod_xml")
                if nested_extension in {".pam", ".pamlod"}:
                    add_target(f"{nested_stem}.pami")

    candidates: List[ArchiveEntry] = []
    for target_basename in target_basenames:
        for candidate in archive_entries_by_basename.get(target_basename, ()):
            if candidate.path == source_entry.path:
                continue
            candidate_basename = PurePosixPath(candidate.path.replace("\\", "/")).name.lower()
            if not _is_material_sidecar_extension(candidate.extension, candidate_basename):
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    if not candidates:
        candidates = [
            candidate
            for candidate in _find_archive_model_related_entries(source_entry, archive_entries_by_basename)
            if _is_material_sidecar_extension(
                str(candidate.extension or "").strip().lower(),
                PurePosixPath(candidate.path.replace("\\", "/")).name.lower(),
            )
        ]
    if not candidates:
        return ()
    if len(candidates) > 1:
        source_parts = [part for part in PurePosixPath(_normalize_model_texture_reference(source_entry.path)).parts if part]

        def shared_prefix_depth(candidate: ArchiveEntry) -> int:
            candidate_parts = [part for part in PurePosixPath(_normalize_model_texture_reference(candidate.path)).parts if part]
            depth = 0
            for source_part, candidate_part in zip(source_parts, candidate_parts):
                if source_part != candidate_part:
                    break
                depth += 1
            return depth

        best_depth = max(shared_prefix_depth(candidate) for candidate in candidates)
        if best_depth > 0:
            candidates = [candidate for candidate in candidates if shared_prefix_depth(candidate) == best_depth]
    candidates.sort(key=lambda candidate: _score_model_sidecar_entry_candidate(source_entry, candidate), reverse=True)
    return tuple(candidates[:8])


def _parse_archive_model_sidecar_texture_bindings(
    sidecar_text: str,
    *,
    sidecar_path: str,
) -> Tuple[_ArchiveModelSidecarTextureBinding, ...]:
    parsed_bindings = parse_texture_sidecar_bindings(sidecar_text, sidecar_path=sidecar_path)
    material_profile = parse_material_sidecar_profile(sidecar_text, sidecar_path=sidecar_path)
    slot_parameters_by_key: Dict[Tuple[str, str, str, str], Tuple[PreviewMaterialParameterInput, ...]] = {}

    def _sidecar_parameter_input(kind: str, parameter: object) -> PreviewMaterialParameterInput:
        return PreviewMaterialParameterInput(
            parameter_kind=str(kind or "").strip().lower(),
            parameter_name=str(getattr(parameter, "parameter_name", "") or "").strip(),
            tag_name=str(getattr(parameter, "tag_name", "") or "").strip(),
            string_item_id=str(getattr(parameter, "string_item_id", "") or "").strip(),
            item_id=str(getattr(parameter, "item_id", "") or "").strip(),
            index=int(getattr(parameter, "index", -1) or -1),
            value=str(getattr(parameter, "value", "") or "").strip(),
            texture_path=str(getattr(parameter, "texture_path", "") or "").strip(),
            color_value=tuple(getattr(parameter, "color_value", ()) or ()),
            numeric_value=getattr(parameter, "numeric_value", None),
        )

    def _binding_slot_key(
        *,
        part_name: object,
        material_name: object,
        submesh_name: object = "",
        shader_family: object = "",
    ) -> Tuple[str, str, str, str]:
        return (
            str(part_name or "").strip().lower(),
            str(material_name or "").strip().lower(),
            str(submesh_name or "").strip().lower(),
            str(shader_family or "").strip().lower(),
        )

    for slot in tuple(getattr(material_profile, "materials", ()) or ()):
        parameters: List[PreviewMaterialParameterInput] = []
        for kind, values in (
            ("texture", getattr(slot, "texture_parameters", ()) or ()),
            ("color", getattr(slot, "color_parameters", ()) or ()),
            ("float", getattr(slot, "float_parameters", ()) or ()),
            ("flag", getattr(slot, "flag_parameters", ()) or ()),
            ("byte4", getattr(slot, "byte4_parameters", ()) or ()),
        ):
            parameters.extend(_sidecar_parameter_input(kind, parameter) for parameter in tuple(values or ()))
        if not parameters:
            continue
        keys = {
            _binding_slot_key(
                part_name=getattr(slot, "part_name", ""),
                material_name=getattr(slot, "material_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(slot, "part_name", ""),
                material_name=getattr(slot, "part_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(slot, "material_name", ""),
                material_name=getattr(slot, "material_name", ""),
                shader_family=getattr(slot, "shader_family", ""),
            ),
        }
        for key in keys:
            if key[0] or key[1] or key[3]:
                slot_parameters_by_key[key] = tuple(parameters)

    def _parameters_for_binding(binding: object) -> Tuple[PreviewMaterialParameterInput, ...]:
        keys = (
            _binding_slot_key(
                part_name=getattr(binding, "part_name", ""),
                material_name=getattr(binding, "material_name", ""),
                submesh_name=getattr(binding, "submesh_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "part_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "submesh_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
            _binding_slot_key(
                part_name=getattr(binding, "material_name", ""),
                material_name=getattr(binding, "material_name", ""),
                shader_family=getattr(binding, "shader_family", ""),
            ),
        )
        for key in keys:
            parameters = slot_parameters_by_key.get(key, ())
            if parameters:
                return parameters
        return ()

    archive_bindings: List[_ArchiveModelSidecarTextureBinding] = []
    try:
        from cdmw.modding.asset_replacement import classify_texture_binding
    except Exception:
        classify_texture_binding = None  # type: ignore[assignment]
    for binding in parsed_bindings:
        texture_role = binding.texture_role
        visualization_state = binding.visualization_state
        if classify_texture_binding is not None:
            try:
                classification = classify_texture_binding(binding.parameter_name, binding.texture_path)
                texture_role = classification.slot_label or classification.slot_kind
                visualization_state = classification.visual_state
            except Exception:
                pass
        archive_bindings.append(
            _ArchiveModelSidecarTextureBinding(
                texture_path=binding.texture_path,
                parameter_name=binding.parameter_name,
                submesh_name=binding.submesh_name,
                sidecar_path=binding.sidecar_path,
                sidecar_kind=binding.sidecar_kind,
                linked_mesh_path=binding.linked_mesh_path,
                part_name=binding.part_name,
                material_name=binding.material_name,
                shader_family=binding.shader_family,
                texture_role=texture_role,
                visualization_state=visualization_state,
                resolved_texture_exists=binding.resolved_texture_exists,
                represent_color=tuple(binding.represent_color or ()),
                tint_color=tuple(binding.tint_color or ()),
                brightness=float(binding.brightness or 1.0),
                uv_scale=float(binding.uv_scale or 1.0),
                tile_type=binding.tile_type,
                srgb_mode=str(getattr(binding, "srgb_mode", "") or ""),
                parameter_declared_by=str(getattr(binding, "parameter_declared_by", "") or ""),
                material_output_quality=str(getattr(binding, "material_output_quality", "") or ""),
                layer_role=str(getattr(binding, "layer_role", "") or ""),
                layer_channel=str(getattr(binding, "layer_channel", "") or ""),
                blend_flags=tuple(str(value) for value in tuple(getattr(binding, "blend_flags", ()) or ()) if str(value)),
                material_parameters=_parameters_for_binding(binding),
            )
        )
    return tuple(archive_bindings)


def _archive_entry_identity_signature(entry: ArchiveEntry) -> Tuple[object, ...]:
    try:
        paz_stat = Path(getattr(entry, "paz_file", "")).stat()
        paz_stamp = (
            int(paz_stat.st_size),
            int(getattr(paz_stat, "st_mtime_ns", int(paz_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        paz_stamp = (0, 0)
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/"),
        str(getattr(entry, "pamt_path", "") or ""),
        str(getattr(entry, "paz_file", "") or ""),
        paz_stamp,
        int(getattr(entry, "offset", 0)),
        int(getattr(entry, "comp_size", 0)),
        int(getattr(entry, "orig_size", 0)),
        int(getattr(entry, "flags", 0)),
        int(getattr(entry, "paz_index", 0)),
    )


def _archive_entry_pathc_identity_signature(entry: ArchiveEntry) -> Tuple[object, ...]:
    if str(getattr(entry, "extension", "") or "").lower() != ".dds" or int(getattr(entry, "compression_type", 0) or 0) != 1:
        return ()
    try:
        pathc_path = resolve_archive_pathc_path(entry)
        pathc_stat = pathc_path.stat()
        return (
            str(pathc_path),
            int(pathc_stat.st_size),
            int(getattr(pathc_stat, "st_mtime_ns", int(pathc_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        return ("missing_pathc",)


def _texconv_identity_signature(texconv_path: Optional[Path]) -> Tuple[object, ...]:
    if texconv_path is None:
        return ("native_directxtex",)
    try:
        resolved_path = texconv_path.expanduser().resolve()
    except OSError:
        resolved_path = texconv_path.expanduser()
    try:
        texconv_stat = resolved_path.stat()
        return (
            str(resolved_path),
            int(texconv_stat.st_size),
            int(getattr(texconv_stat, "st_mtime_ns", int(texconv_stat.st_mtime * 1_000_000_000))),
        )
    except OSError:
        return (str(resolved_path), 0, 0)


def _extract_model_sidecar_entry_bindings_cached(
    sidecar_entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Tuple[_ArchiveModelSidecarTextureBinding, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    cache_key = _archive_entry_identity_signature(sidecar_entry)
    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        cached = _MODEL_SIDECAR_PARSE_CACHE.get(cache_key)
        if cached is not None:
            _MODEL_SIDECAR_PARSE_CACHE.move_to_end(cache_key)
            return cached

    sidecar_data, _decompressed, _note = read_archive_entry_data(sidecar_entry, stop_event=stop_event)
    text = try_decode_text_like_archive_data(sidecar_data)
    if text is None:
        parsed_result = ((), (), {}, {})
    else:
        parsed_bindings = _parse_archive_model_sidecar_texture_bindings(text, sidecar_path=sidecar_entry.path)
        sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
        sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)
        for binding in parsed_bindings:
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            if not normalized_texture_path:
                continue
            if text not in sidecar_texts_by_normalized_path[normalized_texture_path]:
                sidecar_texts_by_normalized_path[normalized_texture_path].append(text)
            texture_basename = PurePosixPath(normalized_texture_path).name
            if texture_basename and text not in sidecar_texts_by_basename[texture_basename]:
                sidecar_texts_by_basename[texture_basename].append(text)
        parsed_result = (
            tuple(parsed_bindings),
            (sidecar_entry.path,) if parsed_bindings else (),
            {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
            {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
        )

    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        _MODEL_SIDECAR_PARSE_CACHE[cache_key] = parsed_result
        _MODEL_SIDECAR_PARSE_CACHE.move_to_end(cache_key)
        while len(_MODEL_SIDECAR_PARSE_CACHE) > _MODEL_SIDECAR_PARSE_CACHE_LIMIT:
            _MODEL_SIDECAR_PARSE_CACHE.popitem(last=False)
    return parsed_result


def _extract_archive_model_sidecar_texture_references(
    source_entry: ArchiveEntry,
    *,
    archive_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[
    Tuple[_ArchiveModelSidecarTextureBinding, ...],
    Tuple[str, ...],
    Dict[str, Tuple[str, ...]],
    Dict[str, Tuple[str, ...]],
]:
    raise_if_cancelled(stop_event)
    sidecar_entries = _find_archive_model_sidecar_entries(source_entry, archive_entries_by_basename)
    cache_key: Tuple[object, ...] = (
        _archive_entry_identity_signature(source_entry),
        tuple(_archive_entry_identity_signature(sidecar_entry) for sidecar_entry in sidecar_entries),
    )
    with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
        cached = _MODEL_SIDECAR_REFERENCE_CACHE.get(cache_key)
        if cached is not None:
            _MODEL_SIDECAR_REFERENCE_CACHE.move_to_end(cache_key)
            return cached

    bindings: List[_ArchiveModelSidecarTextureBinding] = []
    sidecar_paths: List[str] = []
    seen_binding_keys: set[Tuple[str, str, str]] = set()
    sidecar_texts_by_normalized_path: Dict[str, List[str]] = defaultdict(list)
    sidecar_texts_by_basename: Dict[str, List[str]] = defaultdict(list)
    had_sidecar_error = False

    def append_unique_texts(target: Dict[str, List[str]], key: str, values: Sequence[str]) -> None:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            return
        bucket = target[normalized_key]
        for value in values:
            text = str(value or "")
            if not text.strip() or text in bucket:
                continue
            bucket.append(text)

    for sidecar_entry in sidecar_entries:
        raise_if_cancelled(stop_event)
        try:
            parsed_bindings, parsed_paths, parsed_texts_by_path, parsed_texts_by_basename = (
                _extract_model_sidecar_entry_bindings_cached(sidecar_entry, stop_event=stop_event)
            )
        except RunCancelled:
            raise
        except Exception:
            had_sidecar_error = True
            continue
        if not parsed_bindings:
            continue
        for parsed_path in parsed_paths:
            if parsed_path not in sidecar_paths:
                sidecar_paths.append(parsed_path)
        for key, values in parsed_texts_by_path.items():
            append_unique_texts(sidecar_texts_by_normalized_path, key, values)
        for key, values in parsed_texts_by_basename.items():
            append_unique_texts(sidecar_texts_by_basename, key, values)
        for binding in parsed_bindings:
            normalized_texture_path = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
            key = (
                normalized_texture_path,
                str(binding.submesh_name or "").strip().lower(),
                str(binding.parameter_name or "").strip().lower(),
            )
            if key in seen_binding_keys:
                continue
            seen_binding_keys.add(key)
            bindings.append(binding)
    result = (
        tuple(bindings),
        tuple(sidecar_paths),
        {key: tuple(values) for key, values in sidecar_texts_by_normalized_path.items()},
        {key: tuple(values) for key, values in sidecar_texts_by_basename.items()},
    )
    raise_if_cancelled(stop_event)
    if not had_sidecar_error:
        with _MODEL_SIDECAR_PARSE_CACHE_LOCK:
            _MODEL_SIDECAR_REFERENCE_CACHE[cache_key] = result
            _MODEL_SIDECAR_REFERENCE_CACHE.move_to_end(cache_key)
            while len(_MODEL_SIDECAR_REFERENCE_CACHE) > _MODEL_SIDECAR_REFERENCE_CACHE_LIMIT:
                _MODEL_SIDECAR_REFERENCE_CACHE.popitem(last=False)
    return result
