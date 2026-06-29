from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_MODEL_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
)
from cdmw.core.archive_format import (
    _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS,
    _ARCHIVE_XML_LIKE_EXTENSIONS,
    _is_material_sidecar_extension,
    archive_entry_role,
    normalize_archive_extension_filter,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_name_search import (
    _ARCHIVE_SEARCH_DEFAULT_FIELD,
    _archive_name_search_text_match,
    _archive_search_text_match,
    parse_archive_search_query,
)
from cdmw.core.common import raise_if_cancelled
from cdmw.core.upscale_profiles import derive_texture_group_key
from cdmw.models import ArchiveEntry


def _archive_core():
    from cdmw.core import archive as archive_core

    return archive_core


def _strip_archive_model_family_variant_suffix(stem: str) -> str:
    return _archive_core()._strip_archive_model_family_variant_suffix(stem)


def iter_archive_character_equipment_root_alias_stems(stem: str):
    return _archive_core().iter_archive_character_equipment_root_alias_stems(stem)


def iter_archive_equipment_model_alias_stems(stem: str):
    return _archive_core().iter_archive_equipment_model_alias_stems(stem)


def _normalize_model_texture_reference(value: str) -> str:
    return _archive_core()._normalize_model_texture_reference(value)


def build_archive_relationship_references(*args, **kwargs):
    return _archive_core().build_archive_relationship_references(*args, **kwargs)


def merge_archive_reference_rows(*args, **kwargs):
    return _archive_core().merge_archive_reference_rows(*args, **kwargs)


def build_archive_entry_related_references(*args, **kwargs):
    return _archive_core().build_archive_entry_related_references(*args, **kwargs)


def _find_archive_model_related_entries(*args, **kwargs):
    return _archive_core()._find_archive_model_related_entries(*args, **kwargs)


def read_archive_entry_data(*args, **kwargs):
    return _archive_core().read_archive_entry_data(*args, **kwargs)


_COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS: Tuple[str, ...] = (
    "*_n.dds",
    "*_nm.dds",
    "*_nrm.dds",
    "*_normal.dds",
    "*_normalmap.dds",
    "*_sp.dds",
    "*_spec.dds",
    "*_specular.dds",
    "*_m.dds",
    "*_mask.dds",
    "*_orm.dds",
    "*_rma.dds",
    "*_mra.dds",
    "*_arm.dds",
    "*_ao.dds",
    "*_metal.dds",
    "*_metallic.dds",
    "*_rough.dds",
    "*_roughness.dds",
    "*_gloss.dds",
    "*_smooth.dds",
    "*_height.dds",
    "*_hgt.dds",
    "*_disp.dds",
    "*_displacement.dds",
    "*_dmap.dds",
    "*_bump.dds",
    "*_parallax.dds",
    "*_pom.dds",
    "*_ssdm.dds",
    "*_vector.dds",
    "*_dr.dds",
    "*_op.dds",
    "*_wn.dds",
    "*_flow.dds",
    "*_velocity.dds",
    "*_pos.dds",
    "*_position.dds",
    "*_pivot.dds",
    "*_depth.dds",
    "*_pivotpos.dds",
    "*_ma.dds",
    "*_mg.dds",
    "*_o.dds",
    "*_emi.dds",
    "*_emc.dds",
    "*_subsurface.dds",
    "*_1bit.dds",
    "*_mask_amg.dds",
    "*_d.dds",
)
_STRUCTURED_BINARY_IDENTIFIER_RE = re.compile(r"^[_A-Za-z][A-Za-z0-9_:<>-]{2,127}$")
_STRUCTURED_BINARY_ASSET_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+")
_STRUCTURED_BINARY_ASSET_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".dds",
        ".xml",
        ".pac_xml",
        ".pam_xml",
        ".pamlod_xml",
        ".prefabdata_xml",
        ".pami",
        ".meshinfo",
        ".hkx",
        ".hkt",
        ".pam",
        ".pamlod",
        ".pac",
        ".pab",
        ".pabc",
        ".pabv",
        ".pabgb",
        ".pabgh",
        ".pamhc",
        ".pappt",
        ".paccd",
        ".papr",
        ".paa",
        ".paa_metabin",
        ".pae",
        ".paem",
        ".paseq",
        ".paseqc",
        ".paschedule",
        ".paschedulepath",
        ".pastage",
        ".prefab",
        ".levelinfo",
        ".palevel",
        ".roadsector",
        ".road",
        ".nav",
        ".seqmt",
        ".wem",
        ".bnk",
        ".mp4",
        ".bk2",
        ".json",
    }
)

def archive_entry_is_previewable(entry: ArchiveEntry) -> bool:
    extension = entry.extension
    return (
        extension in ARCHIVE_IMAGE_EXTENSIONS
        or extension in ARCHIVE_AUDIO_EXTENSIONS
        or extension in ARCHIVE_VIDEO_EXTENSIONS
        or extension in ARCHIVE_TEXT_EXTENSIONS
        or extension in ARCHIVE_MODEL_EXTENSIONS
        or extension in _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS
        or extension == ".pathc"
    )


def archive_entry_matches_advanced_filters(
    entry: ArchiveEntry,
    *,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    min_size_kb: int,
    previewable_only: bool,
) -> bool:
    package_filter = package_filter_text.strip().lower()
    if package_filter and package_filter not in entry.package_label.lower() and package_filter not in str(entry.pamt_path).lower():
        return False

    if min_size_kb > 0 and entry.orig_size < min_size_kb * 1024:
        return False

    if previewable_only and not archive_entry_is_previewable(entry):
        return False

    normalized_structure = normalize_archive_structure_filter_value(structure_filter)
    if normalized_structure:
        if normalized_structure not in archive_entry_structure_prefixes(entry):
            return False

    normalized_role = role_filter.strip().lower()
    if normalized_role and normalized_role != "all":
        entry_role = archive_entry_role(entry)
        if normalized_role == "texture":
            if entry_role not in {"image", "normal", "material", "impostor", "ui"}:
                return False
        elif entry_role != normalized_role:
            return False

    return True


def _split_archive_filter_patterns(text: str) -> Tuple[str, ...]:
    if not text:
        return ()
    raw_parts = re.split(r"[;\r\n,]+", text)
    parts = [part.strip().lower() for part in raw_parts if part and part.strip()]
    return tuple(parts)


def _archive_entry_item_alias_text(entry: ArchiveEntry, item_search_aliases: Optional[Mapping[str, str]]) -> str:
    if not item_search_aliases:
        return ""
    if not _archive_entry_supports_item_alias_search(entry):
        return ""
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return ""
    keys = [stem]
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem not in keys:
        keys.append(grouped_stem)
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem not in keys:
        keys.append(family_stem)
    for alias_stem in iter_archive_character_equipment_root_alias_stems(stem):
        if alias_stem not in keys:
            keys.append(alias_stem)
    for alias_stem in iter_archive_equipment_model_alias_stems(stem):
        if alias_stem not in keys:
            keys.append(alias_stem)
    aliases: List[str] = []
    seen: set[str] = set()
    for key in keys:
        alias = str(item_search_aliases.get(key, "") or "").strip().lower()
        if alias and alias not in seen:
            aliases.append(alias)
            seen.add(alias)
    return " ".join(aliases)


def archive_entry_model_base_key_matches(entry: ArchiveEntry) -> Tuple[Tuple[str, str], ...]:
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.strip().lower()
    if not stem:
        return ()
    matches: List[Tuple[str, str]] = []
    seen: set[str] = set()

    def add(key: str, relation: str) -> None:
        normalized_key = str(key or "").strip().lower()
        if normalized_key and normalized_key not in seen:
            matches.append((normalized_key, relation))
            seen.add(normalized_key)

    add(stem, "exact")
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem:
        add(grouped_stem, "related")
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem:
        add(family_stem, "related")
    for alias_stem in iter_archive_character_equipment_root_alias_stems(stem):
        add(alias_stem, "related")
    for alias_stem in iter_archive_equipment_model_alias_stems(stem):
        add(alias_stem, "related")
    return tuple(matches)


def archive_entry_item_name_match(
    entry: ArchiveEntry,
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
) -> Tuple[str, str, str]:
    first_related_name = ""
    first_related_reason = ""
    display_names = item_display_names or {}
    exact_display_names = item_exact_display_names or {}
    related_display_names = item_related_display_names or {}
    for key, relation in archive_entry_model_base_key_matches(entry):
        exact_display_name = str(exact_display_names.get(key, "") or "").strip()
        if relation == "exact" and exact_display_name:
            return (
                exact_display_name,
                "Exact localization",
                "Exact item name: ItemInfo._itemName localization resolved through ItemInfo._prefabDataList model/prefab evidence.",
            )

        related_display_name = str(related_display_names.get(key, "") or "").strip()
        if not related_display_name and relation == "related":
            related_display_name = exact_display_name
        if not related_display_name:
            related_display_name = str(display_names.get(key, "") or "").strip()
        if related_display_name and not first_related_name:
            first_related_name = related_display_name
            first_related_reason = (
                "Possible related item name. This is a navigation hint from a model family, variant, texture group, "
                "equipment alias, icon reference, or related asset expansion; it is not proof that this file is that item."
            )
    if first_related_name:
        return "", f"Name hint: {first_related_name}", first_related_reason
    return "", "", ""


def archive_entry_role_label(entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(entry, ArchiveEntry):
        return "Unknown"
    ext = str(entry.extension or "").lower()
    path = str(entry.path or "").replace("\\", "/").lower()
    basename = PurePosixPath(path).name
    if ext in ARCHIVE_IMAGE_EXTENSIONS:
        return "Texture"
    if _is_material_sidecar_extension(ext, basename) or ext in {".pac_xml", ".pam_xml", ".pamlod_xml"}:
        return "Material"
    if ext in {".hkx", ".hkt"}:
        if "meshphysics" in path or "havokphysics" in path or "ragdoll" in path or "physics" in path:
            return "Physics"
        return "HKX"
    if ext == ".paa_metabin":
        return "Animation Metadata"
    if ext in {".paa", ".motionblending", ".pae", ".paem", ".papr", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
        return "Animation"
    if ext == ".pab":
        return "Skeleton / Rig"
    if ext in {".prefab", ".prefabdata_xml", ".prefabdata.xml", ".pappt"}:
        return "Prefab"
    if ext == ".pamhc":
        return "Model Property Metadata"
    if ext == ".paccd":
        return "Character Customization"
    if ext == ".seqmt":
        return "Sequence Texture Metadata"
    if ext in ARCHIVE_AUDIO_EXTENSIONS:
        return "Audio"
    if ext in ARCHIVE_VIDEO_EXTENSIONS:
        return "Video"
    if ext in ARCHIVE_TEXT_EXTENSIONS or ext in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".paccd", ".seqmt"}:
        if "/ui" in path or path.startswith("ui/"):
            return "UI"
        return "Metadata"
    if ext in {".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model", ".pat", ".patx"}:
        return "Mesh"
    if "/ui" in path or path.startswith("ui/"):
        return "UI"
    return "Unknown"


def archive_entry_role_display_text(entry: Optional[ArchiveEntry]) -> str:
    if not isinstance(entry, ArchiveEntry):
        return "Unknown"
    role = archive_entry_role_label(entry)
    extension = str(entry.extension or "").lower()
    return f"{role} {extension}".strip()


def archive_entry_override_state(
    entry: Optional[ArchiveEntry],
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[str, str]:
    if not isinstance(entry, ArchiveEntry):
        return "", ""
    normalized_path = str(entry.path or "").replace("\\", "/").strip().lower()
    same_path_entries: List[ArchiveEntry] = []
    if archive_entries_by_normalized_path:
        same_path_entries = [
            candidate
            for candidate in archive_entries_by_normalized_path.get(normalized_path, ())
            if isinstance(candidate, ArchiveEntry)
        ]
    if not same_path_entries:
        same_path_entries = [entry]
    is_mod_package = archive_entry_is_mod_package(entry)
    if len(same_path_entries) <= 1:
        if is_mod_package:
            return (
                "Mod-added",
                "This file comes from a mod/DMM-style package and no vanilla duplicate with the same virtual path was found.",
            )
        return "", ""
    active_entry = active_archive_entry_for_virtual_path(same_path_entries) or entry
    active_key = archive_entry_identity_key(active_entry)
    current_key = archive_entry_identity_key(entry)
    active_label = str(getattr(active_entry, "package_label", "") or "").strip() or str(active_entry.pamt_path)
    duplicate_labels = [
        str(getattr(candidate, "package_label", "") or "").strip() or str(candidate.pamt_path)
        for candidate in sorted(same_path_entries, key=archive_entry_load_priority, reverse=True)
    ]
    duplicate_text = "\n".join(f"- {label}" for label in duplicate_labels[:12])
    if current_key == active_key:
        state = "Active mod" if archive_entry_is_mod_package(entry) else "Active original"
        return (
            state,
            "This duplicate is the active winner for this virtual path based on package/load priority.\n"
            f"Active package: {active_label}\n"
            f"Duplicate candidates:\n{duplicate_text}",
        )
    state = "Shadowed mod" if is_mod_package else "Shadowed original"
    return (
        state,
        "This duplicate is shadowed by a higher-priority archive entry with the same virtual path.\n"
        f"Active package: {active_label}\n"
        f"Duplicate candidates:\n{duplicate_text}",
    )


def normalize_archive_browser_sort_column(value: object) -> int:
    try:
        column = int(value)
    except (TypeError, ValueError):
        return -1
    return column if 0 <= column <= 8 else -1


def normalize_archive_browser_sort_order(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"desc", "descending", "1"}:
        return "desc"
    return "asc"


def archive_browser_sort_is_active(sort_column: object) -> bool:
    return normalize_archive_browser_sort_column(sort_column) >= 0


_ARCHIVE_BROWSER_NATURAL_SORT_RE = re.compile(r"\d+|\D+")


def _archive_browser_natural_sort_key(value: object) -> Tuple[Tuple[int, object, str], ...]:
    text = str(value or "").replace("\\", "/").strip().casefold()
    parts: List[Tuple[int, object, str]] = []
    for token in _ARCHIVE_BROWSER_NATURAL_SORT_RE.findall(text):
        if token.isdigit():
            try:
                parts.append((0, int(token), token))
            except ValueError:
                parts.append((1, token, token))
        else:
            parts.append((1, token, token))
    return tuple(parts)


def archive_browser_entry_sort_key(
    entry: ArchiveEntry,
    sort_column: object,
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> Tuple[object, ...]:
    column = normalize_archive_browser_sort_column(sort_column)
    normalized_path = str(entry.path or "").replace("\\", "/").strip()
    basename = PurePosixPath(normalized_path).name or entry.basename
    parent_path = normalized_path.rpartition("/")[0]
    exact_name, name_evidence, _name_tooltip = archive_entry_item_name_match(
        entry,
        item_display_names=item_display_names,
        item_exact_display_names=item_exact_display_names,
        item_related_display_names=item_related_display_names,
    )
    override_state, _override_tooltip = archive_entry_override_state(entry, archive_entries_by_normalized_path)
    if column == 0:
        primary: object = _archive_browser_natural_sort_key(basename)
    elif column == 1:
        primary = _archive_browser_natural_sort_key(exact_name)
    elif column == 2:
        primary = _archive_browser_natural_sort_key(name_evidence)
    elif column == 3:
        primary = _archive_browser_natural_sort_key(archive_entry_role_display_text(entry))
    elif column == 4:
        primary = (int(entry.orig_size), int(entry.comp_size))
    elif column == 5:
        primary = (
            _archive_browser_natural_sort_key(entry.compression_label),
            int(entry.compression_type),
            int(entry.flags),
        )
    elif column == 6:
        primary = _archive_browser_natural_sort_key(entry.package_label)
    elif column == 7:
        primary = _archive_browser_natural_sort_key(override_state)
    elif column == 8:
        primary = _archive_browser_natural_sort_key(normalized_path or parent_path)
    else:
        primary = ()
    return (
        primary,
        _archive_browser_natural_sort_key(normalized_path),
        _archive_browser_natural_sort_key(entry.package_label),
        int(getattr(entry, "paz_index", 0) or 0),
        int(getattr(entry, "offset", 0) or 0),
        int(getattr(entry, "orig_size", 0) or 0),
        int(getattr(entry, "comp_size", 0) or 0),
    )


def sort_archive_entries_for_browser(
    entries: Sequence[ArchiveEntry],
    sort_column: object,
    sort_order: object = "asc",
    *,
    item_display_names: Optional[Mapping[str, str]] = None,
    item_exact_display_names: Optional[Mapping[str, str]] = None,
    item_related_display_names: Optional[Mapping[str, str]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> List[ArchiveEntry]:
    column = normalize_archive_browser_sort_column(sort_column)
    if column < 0:
        return list(entries)
    descending = normalize_archive_browser_sort_order(sort_order) == "desc"
    return sorted(
        entries,
        key=lambda entry: archive_browser_entry_sort_key(
            entry,
            column,
            item_display_names=item_display_names,
            item_exact_display_names=item_exact_display_names,
            item_related_display_names=item_related_display_names,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
        ),
        reverse=descending,
    )


def _archive_entry_supports_item_alias_search(entry: ArchiveEntry) -> bool:
    extension = str(entry.extension or "").strip().lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension in ARCHIVE_IMAGE_EXTENSIONS:
        return True
    if extension in {".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".pamhc", ".meshinfo", ".seqmt", ".pab", ".hkx", ".hkt"}:
        return True
    return extension in _ARCHIVE_XML_LIKE_EXTENSIONS or _is_material_sidecar_extension(extension, basename)


def _archive_entry_has_item_alias_key(entry: ArchiveEntry, alias_keys: set[str]) -> bool:
    if not alias_keys:
        return False
    if not _archive_entry_supports_item_alias_search(entry):
        return False
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return False
    if stem in alias_keys:
        return True
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem in alias_keys:
        return True
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem in alias_keys:
        return True
    if any(alias_stem in alias_keys for alias_stem in iter_archive_character_equipment_root_alias_stems(stem)):
        return True
    return any(alias_stem in alias_keys for alias_stem in iter_archive_equipment_model_alias_stems(stem))


def _archive_entry_item_alias_relevance_rank(entry: ArchiveEntry, alias_keys: set[str]) -> Optional[int]:
    if not alias_keys or not _archive_entry_supports_item_alias_search(entry):
        return None
    stem = PurePosixPath(entry.basename.replace("\\", "/")).stem.lower()
    if not stem:
        return None
    extension = str(entry.extension or "").strip().lower()
    exact_model_extensions = {".pac", ".pam", ".pamlod", ".prefab"}
    if stem in alias_keys:
        return 1 if extension in exact_model_extensions else 2
    grouped_stem = derive_texture_group_key(entry.basename).strip().lower()
    if grouped_stem and grouped_stem in alias_keys:
        return 2
    family_stem = _strip_archive_model_family_variant_suffix(stem)
    if family_stem and family_stem in alias_keys:
        return 2
    if any(alias_stem in alias_keys for alias_stem in iter_archive_character_equipment_root_alias_stems(stem)):
        return 2
    if any(alias_stem in alias_keys for alias_stem in iter_archive_equipment_model_alias_stems(stem)):
        return 2
    return None


def _archive_item_alias_match_keys_for_patterns(
    item_search_aliases: Optional[Mapping[str, str]],
    patterns: Sequence[str],
) -> set[str]:
    if not item_search_aliases or not patterns:
        return set()
    result: set[str] = set()
    for key, alias in item_search_aliases.items():
        normalized_key = str(key or "").strip().lower()
        alias_lower = str(alias or "").strip().lower()
        if not normalized_key or not alias_lower:
            continue
        if any(_archive_entry_matches_text_pattern("", "", pattern, alias_lower) for pattern in patterns):
            result.add(normalized_key)
    return result


def _archive_entry_matches_text_pattern(path_lower: str, basename_lower: str, pattern: str, alias_lower: str = "") -> bool:
    if not pattern:
        return False
    if any(char in pattern for char in "*?[]"):
        return (
            fnmatch.fnmatch(path_lower, pattern)
            or fnmatch.fnmatch(basename_lower, pattern)
            or bool(alias_lower and fnmatch.fnmatch(alias_lower, pattern))
        )
    return (
        pattern in path_lower
        or pattern in basename_lower
        or bool(alias_lower and (pattern in alias_lower or _archive_alias_token_prefix_match(alias_lower, pattern)))
    )


def _archive_alias_token_prefix_match(alias_lower: str, query_lower: str) -> bool:
    query_tokens = tuple(re.findall(r"[a-z0-9]+", str(query_lower or "").lower()))
    if not query_tokens:
        return False
    alias_tokens = tuple(re.findall(r"[a-z0-9]+", str(alias_lower or "").lower()))
    if not alias_tokens:
        return False
    return all(any(alias_token.startswith(query_token) for alias_token in alias_tokens) for query_token in query_tokens)


def _archive_entry_matches_size_term(entry: ArchiveEntry, term: ArchiveSearchTerm) -> bool:
    value = int(getattr(entry, "orig_size", 0) or 0)
    target = int(term.size_bytes or 0)
    operator = term.size_operator or "="
    if operator == ">":
        return value > target
    if operator == ">=":
        return value >= target
    if operator == "<":
        return value < target
    if operator == "<=":
        return value <= target
    return value == target


def _archive_entry_content_text(entry: ArchiveEntry, *, stop_event: Optional[threading.Event] = None) -> str:
    if stop_event is not None:
        raise_if_cancelled(stop_event)
    try:
        data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    except Exception:
        return ""
    decoded = try_decode_text_like_archive_data(data)
    if decoded is not None:
        return decoded
    return bytes(data[:262_144]).decode("latin-1", errors="ignore")


def _archive_search_term_matches_entry(
    entry: ArchiveEntry,
    term: ArchiveSearchTerm,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bool, bool]:
    field = str(term.field or _ARCHIVE_SEARCH_DEFAULT_FIELD).lower()
    path_text = str(entry.path or "")
    basename_text = str(entry.basename or PurePosixPath(path_text.replace("\\", "/")).name)
    alias_text = _archive_entry_item_alias_text(entry, item_search_aliases)
    alias_matched = False

    if field == "size":
        return _archive_entry_matches_size_term(entry, term), False
    if field == "ext":
        wanted = str(term.value or "").strip().casefold()
        actual = str(entry.extension or "").strip().casefold()
        if wanted and not wanted.startswith("."):
            wanted = f".{wanted}"
        return actual == wanted, False
    if field == "role":
        return _archive_search_text_match(archive_entry_role(entry), term), False
    if field == "package":
        package_text = " ".join((str(entry.package_label or ""), str(entry.pamt_path or "")))
        return _archive_search_text_match(package_text, term), False
    if field == "path":
        return _archive_name_search_text_match(path_text, term), False
    if field == "name":
        if _archive_name_search_text_match(basename_text, term):
            return True, False
        alias_matched = bool(alias_text and _archive_name_search_text_match(alias_text, term))
        return alias_matched, alias_matched
    if field == "content":
        content = _archive_entry_content_text(entry, stop_event=stop_event)
        return _archive_search_text_match(content, term), False

    if _archive_name_search_text_match(path_text, term) or _archive_name_search_text_match(basename_text, term):
        return True, False
    alias_matched = bool(alias_text and _archive_name_search_text_match(alias_text, term))
    return alias_matched, alias_matched


def _archive_search_query_matches_entry(
    entry: ArchiveEntry,
    query: ArchiveSearchQuery,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    stop_event: Optional[threading.Event] = None,
) -> Tuple[bool, bool]:
    if query.is_empty:
        return True, False
    for group in query.groups:
        group_matched = True
        group_alias_matched = False
        positive_count = 0
        for term in group:
            term_matched, alias_matched = _archive_search_term_matches_entry(
                entry,
                term,
                item_search_aliases=item_search_aliases,
                stop_event=stop_event,
            )
            if term.negated:
                if term_matched:
                    group_matched = False
                    break
                continue
            positive_count += 1
            if not term_matched:
                group_matched = False
                break
            group_alias_matched = group_alias_matched or alias_matched
        if group_matched and (positive_count > 0 or group):
            return True, group_alias_matched
    return False, False


def _archive_search_query_matches_alias(alias_text: str, query: ArchiveSearchQuery) -> bool:
    if query.is_empty:
        return False
    alias = str(alias_text or "")
    if not alias:
        return False
    for group in query.groups:
        ok = True
        positive_count = 0
        for term in group:
            if term.field not in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "name"}:
                if not term.negated:
                    ok = False
                    break
                continue
            matched = _archive_name_search_text_match(alias, term)
            if term.negated and matched:
                ok = False
                break
            if not term.negated:
                positive_count += 1
                if not matched:
                    ok = False
                    break
        if ok and positive_count > 0:
            return True
    return False


def _archive_item_alias_match_keys_for_query(
    item_search_aliases: Optional[Mapping[str, str]],
    query: ArchiveSearchQuery,
) -> set[str]:
    if not item_search_aliases or query.is_empty:
        return set()
    result: set[str] = set()
    for key, alias in item_search_aliases.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key and _archive_search_query_matches_alias(str(alias or ""), query):
            result.add(normalized_key)
    return result


def _archive_entry_search_relevance_rank(
    entry: ArchiveEntry,
    *,
    text: str,
    include_patterns: Sequence[str],
    wildcard_filter: bool,
    wildcard_pattern: str,
    item_search_aliases: Optional[Mapping[str, str]],
    simple_alias_match_keys: set[str],
) -> int:
    if not text:
        return 0
    path_lower = entry.path.lower()
    basename_lower = entry.basename.lower()
    if len(include_patterns) > 1:
        for pattern in include_patterns:
            if _archive_entry_matches_text_pattern(path_lower, basename_lower, pattern):
                return 0
    elif wildcard_filter:
        if fnmatch.fnmatch(path_lower, wildcard_pattern) or fnmatch.fnmatch(basename_lower, wildcard_pattern):
            return 0
    elif text in path_lower or text in basename_lower:
        return 0

    alias_rank = _archive_entry_item_alias_relevance_rank(entry, simple_alias_match_keys)
    if alias_rank is not None:
        return alias_rank

    alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
    if alias_lower:
        if len(include_patterns) > 1:
            if any(_archive_entry_matches_text_pattern("", "", pattern, alias_lower) for pattern in include_patterns):
                return 2
        elif wildcard_filter:
            if fnmatch.fnmatch(alias_lower, wildcard_pattern):
                return 2
        elif text in alias_lower:
            return 2
    return 3


def _archive_entry_search_query_relevance_rank(
    entry: ArchiveEntry,
    query: ArchiveSearchQuery,
    *,
    item_search_aliases: Optional[Mapping[str, str]],
    simple_alias_match_keys: set[str],
) -> int:
    if query.is_empty:
        return 0
    path_lower = entry.path.casefold()
    basename_lower = entry.basename.casefold()
    alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
    for group in query.groups:
        positive_terms = [term for term in group if not term.negated]
        if not positive_terms:
            continue
        if all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "path", "name"}
            and (
                _archive_search_text_match(path_lower, term)
                or _archive_search_text_match(basename_lower, term)
            )
            for term in positive_terms
        ):
            return 0
        if all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "path", "name"}
            and (
                _archive_name_search_text_match(path_lower, term)
                or _archive_name_search_text_match(basename_lower, term)
            )
            for term in positive_terms
        ):
            return 1
        alias_rank = _archive_entry_item_alias_relevance_rank(entry, simple_alias_match_keys)
        if alias_rank is not None:
            return alias_rank
        if alias_lower and all(
            term.field in {_ARCHIVE_SEARCH_DEFAULT_FIELD, "name"}
            and _archive_name_search_text_match(alias_lower, term)
            for term in positive_terms
        ):
            return 2
    return 3


def _archive_entry_is_item_alias_expansion_source(entry: ArchiveEntry) -> bool:
    extension = str(entry.extension or "").strip().lower()
    basename = PurePosixPath(entry.path.replace("\\", "/")).name.lower()
    if extension in {".pac", ".pam", ".pamlod", ".prefab", ".pappt", ".pamhc", ".meshinfo", ".seqmt", ".pab", ".hkx", ".hkt"}:
        return True
    if extension in _ARCHIVE_XML_LIKE_EXTENSIONS or _is_material_sidecar_extension(extension, basename):
        return True
    return False


def _archive_item_alias_related_expansion_needed(
    *,
    normalized_extension: str,
    alias_matched_entries: Sequence[ArchiveEntry],
    hidden_alias_expansion_sources: Sequence[ArchiveEntry],
) -> bool:
    if hidden_alias_expansion_sources:
        return True
    if not alias_matched_entries:
        return False
    if normalized_extension == ".pac":
        return False
    return True


def _read_archive_entry_text_or_binary_for_reference_expansion(
    entry: ArchiveEntry,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[str, bytes]:
    extension = str(entry.extension or "").strip().lower()
    if extension not in _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS and extension not in ARCHIVE_TEXT_EXTENSIONS:
        return "", b""
    try:
        raw_data, _decompressed, _note = read_archive_entry_data(entry, stop_event=stop_event)
    except Exception:
        return "", b""
    text = try_decode_text_like_archive_data(raw_data)
    if text is not None:
        return text, b""
    return "", raw_data


def _expand_archive_filter_item_alias_related_entries(
    entries: Sequence[ArchiveEntry],
    filtered: List[ArchiveEntry],
    alias_matched_entries: Sequence[ArchiveEntry],
    *,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    candidate_filter: Optional[Callable[[ArchiveEntry], bool]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    expansion_sources: List[ArchiveEntry] = []
    seen_source_paths: set[str] = set()
    for entry in alias_matched_entries:
        normalized_path = _normalize_model_texture_reference(entry.path)
        if not normalized_path or normalized_path in seen_source_paths:
            continue
        if not _archive_entry_is_item_alias_expansion_source(entry):
            continue
        seen_source_paths.add(normalized_path)
        expansion_sources.append(entry)
        if len(expansion_sources) >= 32:
            break
    if not expansion_sources:
        return filtered

    basename_index = archive_entries_by_basename or build_archive_entry_basename_index(entries)
    normalized_path_index = archive_entries_by_normalized_path or build_archive_entry_path_index(entries)
    expanded_entries: List[ArchiveEntry] = list(filtered)
    seen_filtered_paths = {
        _normalize_model_texture_reference(entry.path)
        for entry in expanded_entries
        if _normalize_model_texture_reference(entry.path)
    }

    def add_entry(candidate: Optional[ArchiveEntry]) -> bool:
        if not isinstance(candidate, ArchiveEntry):
            return False
        if candidate_filter is not None and not candidate_filter(candidate):
            return False
        normalized_candidate = _normalize_model_texture_reference(candidate.path)
        if not normalized_candidate or normalized_candidate in seen_filtered_paths:
            return False
        seen_filtered_paths.add(normalized_candidate)
        expanded_entries.append(candidate)
        return True

    def add_related_for_source(source_entry: ArchiveEntry, *, include_sidecar_children: bool) -> None:
        raise_if_cancelled(stop_event)
        companion_entries = _find_archive_model_related_entries(source_entry, basename_index)
        text, binary_data = _read_archive_entry_text_or_binary_for_reference_expansion(
            source_entry,
            stop_event=stop_event,
        )
        references = build_archive_entry_related_references(
            source_entry,
            text=text,
            binary_data=binary_data,
            companion_entries=companion_entries,
            archive_entries_by_normalized_path=normalized_path_index,
            archive_entries_by_basename=basename_index,
        )
        graph_references = build_archive_relationship_references(
            source_entry,
            archive_entries_by_normalized_path=normalized_path_index,
            archive_entries_by_basename=basename_index,
        )
        references = merge_archive_reference_rows(references, graph_references)
        sidecar_children: List[ArchiveEntry] = []
        for reference in references:
            related_entry = getattr(reference, "resolved_entry", None)
            if add_entry(related_entry):
                extension = str(getattr(related_entry, "extension", "") or "").strip().lower()
                basename = PurePosixPath(str(getattr(related_entry, "path", "") or "").replace("\\", "/")).name.lower()
                if include_sidecar_children and _is_material_sidecar_extension(extension, basename):
                    sidecar_children.append(related_entry)
        if include_sidecar_children:
            for sidecar_entry in sidecar_children[:12]:
                add_related_for_source(sidecar_entry, include_sidecar_children=False)

    for source in expansion_sources:
        add_related_for_source(source, include_sidecar_children=True)

    return expanded_entries


def filter_archive_entries(
    entries: Sequence[ArchiveEntry],
    *,
    filter_text: str,
    exclude_filter_text: str,
    extension_filter: str,
    package_filter_text: str,
    structure_filter: str,
    role_filter: str,
    exclude_common_technical_suffixes: bool,
    min_size_kb: int,
    previewable_only: bool,
    item_search_aliases: Optional[Mapping[str, str]] = None,
    archive_entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    archive_name_search_index: Optional[ArchiveNameSearchIndex] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> List[ArchiveEntry]:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    text = filter_text.strip().lower()
    search_query = parse_archive_search_query(filter_text)
    include_patterns = _split_archive_filter_patterns(text)
    wildcard_pattern = include_patterns[0] if include_patterns else ""
    wildcard_filter = len(include_patterns) == 1 and any(char in include_patterns[0] for char in "*?[]")
    simple_alias_match_keys = _archive_item_alias_match_keys_for_query(item_search_aliases, search_query)
    exclude_patterns = list(_split_archive_filter_patterns(exclude_filter_text))
    if exclude_common_technical_suffixes:
        exclude_patterns.extend(_COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS)
    package_filter = package_filter_text.strip().lower()
    min_size_bytes = min_size_kb * 1024 if min_size_kb > 0 else 0
    normalized_structure = normalize_archive_structure_filter_value(structure_filter)
    normalized_role = role_filter.strip().lower()
    require_role = bool(normalized_role and normalized_role != "all")
    candidate_entries: Sequence[ArchiveEntry] = entries
    if archive_name_search_index is not None:
        indexed_entries = archive_name_search_index.entries_for_query(entries, search_query)
        if indexed_entries is not None:
            candidate_entries = indexed_entries
    total_entries = len(candidate_entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000

    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Applying archive filters... 0 / {total_entries:,} entries")

    def text_match_for_entry(entry: ArchiveEntry) -> Tuple[bool, bool]:
        if search_query.is_empty:
            return True, False
        query_matched, alias_matched = _archive_search_query_matches_entry(
            entry,
            search_query,
            item_search_aliases=item_search_aliases,
            stop_event=stop_event,
        )
        if query_matched:
            return True, alias_matched
        if simple_alias_match_keys:
            alias_matched = _archive_entry_has_item_alias_key(entry, simple_alias_match_keys)
            return alias_matched, alias_matched
        return False, False

    def entry_passes_post_text_filters(
        entry: ArchiveEntry,
        *,
        enforce_extension: bool,
        enforce_structure_role_size_preview: bool = True,
    ) -> bool:
        if (
            enforce_extension
            and normalized_extension
            and normalized_extension not in {"*", "all", ".*"}
            and entry.extension != normalized_extension
        ):
            return False

        path_lower = entry.path.lower()
        basename_lower = entry.basename.lower()
        if exclude_patterns:
            if any(
                _archive_entry_matches_text_pattern(path_lower, basename_lower, pattern)
                for pattern in exclude_patterns
            ):
                return False
            if item_search_aliases:
                alias_lower = _archive_entry_item_alias_text(entry, item_search_aliases)
                if alias_lower and any(
                    _archive_entry_matches_text_pattern("", "", pattern, alias_lower)
                    for pattern in exclude_patterns
                ):
                    return False

        if package_filter:
            package_label_lower = entry.package_label.lower()
            pamt_path_lower = str(entry.pamt_path).lower()
            if package_filter not in package_label_lower and package_filter not in pamt_path_lower:
                return False

        if not enforce_structure_role_size_preview:
            return True

        if min_size_bytes and entry.orig_size < min_size_bytes:
            return False

        if previewable_only and not archive_entry_is_previewable(entry):
            return False

        if normalized_structure and normalized_structure not in archive_entry_structure_prefixes(entry):
            return False

        if require_role:
            entry_role = archive_entry_role(entry)
            if normalized_role == "texture":
                if entry_role not in {"image", "normal", "material", "impostor", "ui"}:
                    return False
            elif entry_role != normalized_role:
                return False

        return True

    filtered: List[ArchiveEntry] = []
    alias_matched_entries: List[ArchiveEntry] = []
    hidden_alias_expansion_sources: List[ArchiveEntry] = []
    for index, entry in enumerate(candidate_entries, start=1):
        if stop_event is not None and (index == 1 or index % 2048 == 0):
            raise_if_cancelled(stop_event)
        text_matched, alias_matched = text_match_for_entry(entry)
        matched = text_matched and entry_passes_post_text_filters(entry, enforce_extension=True)

        if matched:
            filtered.append(entry)
            if alias_matched:
                alias_matched_entries.append(entry)
        elif (
            text
            and item_search_aliases
            and alias_matched
            and normalized_extension == ".dds"
            and _archive_entry_is_item_alias_expansion_source(entry)
            and entry_passes_post_text_filters(
                entry,
                enforce_extension=False,
                enforce_structure_role_size_preview=False,
            )
        ):
            hidden_alias_expansion_sources.append(entry)

        if on_progress and (index == 1 or index % update_every == 0 or index == total_entries):
            on_progress(index, progress_total, f"Applying archive filters... {index:,} / {total_entries:,} entries")

    if text and item_search_aliases and _archive_item_alias_related_expansion_needed(
        normalized_extension=normalized_extension,
        alias_matched_entries=alias_matched_entries,
        hidden_alias_expansion_sources=hidden_alias_expansion_sources,
    ):
        def related_candidate_matches_active_filters(candidate: ArchiveEntry) -> bool:
            return entry_passes_post_text_filters(candidate, enforce_extension=True)

        filtered = _expand_archive_filter_item_alias_related_entries(
            entries,
            filtered,
            (*alias_matched_entries, *hidden_alias_expansion_sources),
            archive_entries_by_basename=archive_entries_by_basename,
            archive_entries_by_normalized_path=archive_entries_by_normalized_path,
            candidate_filter=related_candidate_matches_active_filters,
            stop_event=stop_event,
        )

    if text and len(filtered) > 1:
        original_order = {
            _normalize_model_texture_reference(entry.path): index
            for index, entry in enumerate(filtered)
            if _normalize_model_texture_reference(entry.path)
        }
        filtered.sort(
            key=lambda entry: (
                _archive_entry_search_query_relevance_rank(
                    entry,
                    item_search_aliases=item_search_aliases,
                    query=search_query,
                    simple_alias_match_keys=simple_alias_match_keys,
                ),
                original_order.get(_normalize_model_texture_reference(entry.path), 0),
            )
        )

    return order_archive_entries_by_active_overrides(filtered)


def count_archive_entries_with_extension(
    entries: Sequence[ArchiveEntry],
    extension_filter: str,
) -> int:
    normalized_extension = normalize_archive_extension_filter(extension_filter)
    if not normalized_extension or normalized_extension in {"*", "all", ".*"}:
        return len(entries)
    return sum(1 for entry in entries if entry.extension == normalized_extension)


def normalize_archive_structure_filter_value(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    return "/".join(
        part.lower()
        for part in raw.split("/")
        if part not in {"", ".", ".."}
    )


def archive_entry_path_parts(entry: ArchiveEntry) -> Tuple[str, ...]:
    return tuple(
        part
        for part in entry.path.replace("\\", "/").split("/")
        if part not in {"", ".", ".."}
    )


def archive_entry_folder_parts(entry: ArchiveEntry) -> Tuple[str, ...]:
    package_dir = entry.pamt_path.parent.name.strip().lower() or "package"
    parent_parts = tuple(part.lower() for part in archive_entry_path_parts(entry)[:-1])
    return (package_dir, *parent_parts)


def archive_entry_structure_prefixes(entry: ArchiveEntry) -> Tuple[str, ...]:
    parts = archive_entry_folder_parts(entry)
    return tuple("/".join(parts[: index + 1]) for index in range(len(parts)))


def archive_entry_identity_key(entry: ArchiveEntry) -> Tuple[str, str, int, int]:
    return (
        str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower(),
        str(getattr(entry, "pamt_path", "") or "").strip().lower(),
        int(getattr(entry, "offset", 0) or 0),
        int(getattr(entry, "paz_index", 0) or 0),
    )


def archive_entry_is_mod_package(entry: ArchiveEntry) -> bool:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_name = str(getattr(package_parent, "name", "") or "")
    package_key = package_name.strip().casefold()
    if not package_key:
        return False
    if package_key.startswith("dmm") or package_key.startswith("mod"):
        return True
    return not bool(re.fullmatch(r"\d+", package_key))


def archive_entry_load_priority(entry: ArchiveEntry) -> Tuple[int, int, int, int, str]:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_name = str(getattr(package_parent, "name", "") or "")
    package_key = package_name.strip().casefold()
    package_number_match = re.fullmatch(r"0*(\d+)", package_key)
    is_numeric_package = bool(package_number_match)
    is_dmm_package = package_key.startswith("dmm")
    if is_dmm_package:
        tier = 3
    elif not is_numeric_package:
        tier = 2
    else:
        tier = 1
    package_number = int(package_number_match.group(1)) if package_number_match else -1
    pamt_stem = str(getattr(getattr(entry, "pamt_path", None), "stem", "") or "").strip().casefold()
    pamt_number_match = re.fullmatch(r"0*(\d+)", pamt_stem)
    pamt_number = int(pamt_number_match.group(1)) if pamt_number_match else -1
    return (
        tier,
        package_number,
        pamt_number,
        int(getattr(entry, "paz_index", 0) or 0),
        str(getattr(entry, "pamt_path", "") or "").casefold(),
    )


def active_archive_entry_for_virtual_path(entries: Sequence[ArchiveEntry]) -> Optional[ArchiveEntry]:
    candidates = [entry for entry in entries if isinstance(entry, ArchiveEntry)]
    if not candidates:
        return None
    return max(candidates, key=archive_entry_load_priority)


def order_archive_entries_by_active_overrides(entries: Sequence[ArchiveEntry]) -> List[ArchiveEntry]:
    grouped: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    ordered_paths: List[str] = []
    for entry in entries:
        normalized_path = str(getattr(entry, "path", "") or "").replace("\\", "/").strip().lower()
        if not normalized_path:
            normalized_path = archive_entry_identity_key(entry)[0]
        if normalized_path not in grouped:
            ordered_paths.append(normalized_path)
        grouped[normalized_path].append(entry)
    ordered: List[ArchiveEntry] = []
    for normalized_path in ordered_paths:
        group_entries = grouped.get(normalized_path, [])
        if len(group_entries) <= 1:
            ordered.extend(group_entries)
            continue
        active_key = archive_entry_identity_key(active_archive_entry_for_virtual_path(group_entries) or group_entries[0])
        ordered.extend(
            sorted(
                group_entries,
                key=lambda entry: (
                    archive_entry_identity_key(entry) != active_key,
                    -archive_entry_load_priority(entry)[0],
                    -archive_entry_load_priority(entry)[1],
                    -archive_entry_load_priority(entry)[2],
                    str(getattr(entry, "package_label", "") or "").casefold(),
                ),
            )
        )
    return ordered


def build_archive_entry_path_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        normalized_path = archive_entry.path.replace("\\", "/").strip().lower()
        index.setdefault(normalized_path, []).append(archive_entry)
    return index


def build_archive_entry_basename_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        normalized_path = archive_entry.path.replace("\\", "/").strip()
        basename = normalized_path.rsplit("/", 1)[-1].strip().lower()
        if not basename:
            continue
        index.setdefault(basename, []).append(archive_entry)
    for basename, basename_entries in index.items():
        basename_entries.sort(
            key=lambda entry: (
                -str(entry.path or "").replace("\\", "/").strip().count("/"),
                -len(str(entry.path or "").replace("\\", "/").strip()),
                str(entry.path or "").replace("\\", "/").strip().lower(),
            )
        )
    return index


def build_archive_entry_extension_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    for archive_entry in entries:
        extension = normalize_archive_extension_filter(archive_entry.extension)
        if not extension:
            continue
        index.setdefault(extension, []).append(archive_entry)
    return index


def build_archive_entry_role_index(entries: Sequence[ArchiveEntry]) -> Dict[str, List[ArchiveEntry]]:
    index: Dict[str, List[ArchiveEntry]] = {}
    texture_roles = {"image", "normal", "material", "impostor", "ui"}
    for archive_entry in entries:
        role = archive_entry_role(archive_entry)
        if role:
            index.setdefault(role, []).append(archive_entry)
            if role in texture_roles:
                index.setdefault("texture", []).append(archive_entry)
    return index
