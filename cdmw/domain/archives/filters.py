"""Pure archive filter state and category rules."""

from __future__ import annotations

import re
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_VIDEO_EXTENSIONS,
)
from cdmw.models import ArchiveEntry, ArchiveEntryIdentity, RunCancelled


COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS: tuple[str, ...] = (
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


@dataclass(frozen=True, slots=True)
class ArchiveFilterState:
    query: str = ""
    asset_family: str = ""
    case_sensitive: bool = False

    @property
    def normalized_query(self) -> str:
        value = self.query.strip()
        return value if self.case_sensitive else value.lower()


def archive_browser_entry_category(entry: object) -> str:
    ext = str(getattr(entry, "extension", "") or "").lower()
    path = str(getattr(entry, "path", "") or "").replace("\\", "/").lower()
    if ext in ARCHIVE_IMAGE_EXTENSIONS:
        return "Texture"
    if ext in {".pami", ".pac_xml", ".pam_xml", ".pamlod_xml"}:
        return "Material Sidecar"
    if ext in {".pab"}:
        return "Skeleton/Rig"
    if ext in {".hkx", ".hkt"} and any(token in path for token in ("meshphysics", "havokphysics", "ragdoll", "physics")):
        return "Physics"
    if ext in {".hkx", ".hkt", ".paa", ".paa_metabin", ".motionblending", ".pae", ".paem"}:
        return "Animation"
    if ext in ARCHIVE_AUDIO_EXTENSIONS:
        return "Audio"
    if ext in ARCHIVE_VIDEO_EXTENSIONS:
        return "Video"
    if ext in {".pac", ".pam", ".pamlod", ".obj", ".fbx", ".dae", ".gltf", ".glb", ".mesh", ".mdl", ".model", ".pat", ".patx"}:
        return "Mesh"
    if ext in ARCHIVE_TEXT_EXTENSIONS or ext in {".meshinfo", ".motionblending", ".paa_metabin", ".prefab", ".pappt", ".pamhc", ".seqmt"}:
        return "Text/Metadata"
    return "Other"


def build_archive_category_entry_index(
    entries: Sequence[object],
    *,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    total_entries = len(entries)
    progress_total = max(total_entries, 1)
    update_every = 50_000 if total_entries >= 500_000 else 10_000 if total_entries >= 100_000 else 2_000
    if on_progress:
        on_progress(0 if total_entries > 0 else 1, progress_total, f"Indexing archive categories... 0 / {total_entries:,} entries")
    for entry_index, entry in enumerate(entries):
        current = entry_index + 1
        if stop_event is not None and (current == 1 or current % 2048 == 0) and stop_event.is_set():
            raise RunCancelled("Archive category indexing cancelled.")
        grouped.setdefault(archive_browser_entry_category(entry), []).append(entry_index)
        if on_progress and (current == 1 or current % update_every == 0 or current == total_entries):
            on_progress(current, progress_total, f"Indexing archive categories... {current:,} / {total_entries:,} entries")
    return grouped


def archive_filter_text_explicitly_requests_item_name(filter_text: object) -> bool:
    return bool(re.search(r"(^|\s)name\s*:", str(filter_text or "").strip(), flags=re.IGNORECASE))


def archive_filter_text_needs_item_name_search(filter_text: object) -> bool:
    text = str(filter_text or "").strip()
    if not text:
        return False
    if archive_filter_text_explicitly_requests_item_name(text):
        return True
    return not any(char in text for char in "/\\_*.?[]")


def normalize_archive_browser_sort_column(value: object) -> int:
    try:
        column = int(value)
    except (TypeError, ValueError):
        return -1
    return column if 0 <= column <= 7 else -1


def normalize_archive_browser_sort_order(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return "desc" if normalized in {"desc", "descending", "1"} else "asc"


def archive_browser_sort_is_active(sort_column: object) -> bool:
    return normalize_archive_browser_sort_column(sort_column) >= 0


def normalize_archive_structure_filter_value(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return ""
    return "/".join(part.lower() for part in raw.split("/") if part not in {"", ".", ".."})


def archive_entry_identity_key(entry: ArchiveEntry) -> ArchiveEntryIdentity:
    return entry.identity


def archive_entry_is_mod_package(entry: ArchiveEntry) -> bool:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_key = str(getattr(package_parent, "name", "") or "").strip().casefold()
    if not package_key:
        return False
    if package_key.startswith(("dmm", "mod")):
        return True
    return not bool(re.fullmatch(r"\d+", package_key))


def archive_entry_load_priority(entry: ArchiveEntry) -> tuple[int, int, int, int, str]:
    package_parent = getattr(getattr(entry, "pamt_path", None), "parent", Path())
    package_key = str(getattr(package_parent, "name", "") or "").strip().casefold()
    package_number_match = re.fullmatch(r"0*(\d+)", package_key)
    if package_key.startswith("dmm"):
        tier = 3
    elif not package_number_match:
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
    return max(candidates, key=archive_entry_load_priority) if candidates else None


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
        group_entries = grouped[normalized_path]
        if len(group_entries) <= 1:
            ordered.extend(group_entries)
            continue
        active = active_archive_entry_for_virtual_path(group_entries) or group_entries[0]
        active_key = archive_entry_identity_key(active)
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


__all__ = [
    "ArchiveFilterState",
    "COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS",
    "active_archive_entry_for_virtual_path",
    "archive_browser_sort_is_active",
    "archive_browser_entry_category",
    "archive_entry_identity_key",
    "archive_entry_is_mod_package",
    "archive_entry_load_priority",
    "archive_filter_text_explicitly_requests_item_name",
    "archive_filter_text_needs_item_name_search",
    "build_archive_category_entry_index",
    "normalize_archive_browser_sort_column",
    "normalize_archive_browser_sort_order",
    "normalize_archive_structure_filter_value",
    "order_archive_entries_by_active_overrides",
]
