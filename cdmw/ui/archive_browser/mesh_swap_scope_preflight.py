"""Worker-side preflight for the in-game mesh-swap scope dialog."""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional

from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.services.preview_workflow_service import try_decode_text_like_archive_data
from cdmw.domain.archives.relationships import (
    ARCHIVE_REL_INCLUDE_RECOMMENDED,
    ARCHIVE_REL_INCLUDE_REQUIRED,
    SWAP_SCOPE_BODY_HEAD,
    ArchiveRelationEdge,
)
from cdmw.services.archive_workflow_service import build_character_swap_plan
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry


@dataclass(frozen=True, slots=True)
class ArchiveMeshSwapScopePreflightRequest:
    request_id: int
    target_entry: ArchiveEntry
    source_entry: ArchiveEntry
    archive_entries: Sequence[ArchiveEntry]


@dataclass(frozen=True, slots=True)
class ArchiveMeshSwapScopePreflightResult:
    request_id: int
    allow_character_scope: bool
    item_family_scope: bool
    same_weapon_folder: bool
    character_relationship_plan: object | None
    source_related_entries: tuple[ArchiveEntry, ...]
    relationship_edges: tuple[tuple[object, ArchiveRelationEdge], ...]
    unresolved_relationship_edges: tuple[ArchiveRelationEdge, ...]
    source_sidecar_paths: frozenset[str]
    source_appearance_paths: frozenset[str]
    source_pbd_names: tuple[str, ...]
    source_wrapper_count: int
    target_wrapper_count: int
    source_has_pbd_contract: bool
    source_has_larger_material_contract: bool
    preserve_source_contract_default: bool


def _weapon_folder_segment(entry: ArchiveEntry) -> str:
    parts = list(PurePosixPath(str(entry.path or "").replace("\\", "/")).parts)
    lowered = [part.lower() for part in parts]
    try:
        weapon_index = lowered.index("weapon")
        return parts[weapon_index + 1].lower()
    except (ValueError, IndexError):
        return ""


def _material_contract_stats(
    entries: Sequence[ArchiveEntry],
    *,
    stop_event: Optional[threading.Event],
) -> tuple[int, int, tuple[str, ...]]:
    wrapper_count = 0
    pbd_names: list[str] = []
    pbd_hits = 0
    for sidecar_entry in entries:
        raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
        try:
            sidecar_data, _decompressed, _note = read_archive_entry_data(
                sidecar_entry,
                stop_event=stop_event,
            )
            sidecar_text = try_decode_text_like_archive_data(sidecar_data) or sidecar_data.decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
            continue
        wrapper_count += len(re.findall(r"<\s*SkinnedMeshMaterialWrapper\b", sidecar_text, flags=re.IGNORECASE))
        pbd_names.extend(
            value.strip()
            for value in re.findall(
                r'_pbdSimulationMaterialName\s*=\s*"([^"]+)"',
                sidecar_text,
                flags=re.IGNORECASE,
            )
            if value.strip()
        )
        pbd_hits += len(
            re.findall(
                r"_pbdSimulationMaterialName|<\s*OverridedPbdMaterialProperty\b|\bpbd\b",
                sidecar_text,
                flags=re.IGNORECASE,
            )
        )
    return wrapper_count, pbd_hits, tuple(dict.fromkeys(pbd_names))


def prepare_archive_mesh_swap_scope(
    owner: object,
    request: ArchiveMeshSwapScopePreflightRequest,
    *,
    stop_event: Optional[threading.Event] = None,
) -> ArchiveMeshSwapScopePreflightResult:
    raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
    target_entry = request.target_entry
    source_entry = request.source_entry
    allow_character_scope = bool(owner._archive_entries_allow_character_swap_scope(target_entry, source_entry))
    item_family_scope = bool(
        not allow_character_scope
        and (
            owner._archive_entry_is_equipment_model_for_swap(target_entry)
            or owner._archive_entry_is_equipment_model_for_swap(source_entry)
        )
    )
    target_weapon_folder = _weapon_folder_segment(target_entry)
    source_weapon_folder = _weapon_folder_segment(source_entry)
    same_weapon_folder = bool(
        target_weapon_folder and source_weapon_folder and target_weapon_folder == source_weapon_folder
    )
    character_relationship_plan = None
    if allow_character_scope:
        try:
            character_relationship_plan = build_character_swap_plan(
                target_entry,
                source_entry,
                request.archive_entries,
                swap_scope=SWAP_SCOPE_BODY_HEAD,
            )
        except Exception:
            raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
    raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")

    source_related_entries_by_key: dict[object, ArchiveEntry] = {}
    relationship_edges_by_key: dict[object, ArchiveRelationEdge] = {}
    unresolved_relationship_edges: list[ArchiveRelationEdge] = []

    def add_related_entry(entry: ArchiveEntry) -> None:
        key = owner._archive_entry_identity_key(entry)
        if key and key not in source_related_entries_by_key:
            source_related_entries_by_key[key] = entry

    def add_relationship_edge(edge: ArchiveRelationEdge) -> None:
        if edge.unresolved:
            unresolved_relationship_edges.append(edge)
            return
        entry = edge.related_entry
        if not isinstance(entry, ArchiveEntry):
            return
        key = owner._archive_entry_identity_key(entry)
        if not key:
            return
        add_related_entry(entry)
        current = relationship_edges_by_key.get(key)
        current_rank = 0
        if current is not None:
            current_rank = (
                3
                if current.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED
                else 2
                if current.include_policy == ARCHIVE_REL_INCLUDE_RECOMMENDED
                else 1
            )
        rank = (
            3
            if edge.include_policy == ARCHIVE_REL_INCLUDE_REQUIRED
            else 2
            if edge.include_policy == ARCHIVE_REL_INCLUDE_RECOMMENDED
            else 1
        )
        if current is None or rank > current_rank:
            relationship_edges_by_key[key] = edge

    for related_entry in owner._archive_model_related_entries_for_swap(source_entry):
        raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
        add_related_entry(related_entry)
    if allow_character_scope:
        for edge in tuple(getattr(character_relationship_plan, "edges", ()) or ()):
            add_relationship_edge(edge)
        for related_entry in owner._archive_character_app_graph_entries_for_swap(
            source_entry,
            stop_event=stop_event,
        ):
            raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
            add_related_entry(related_entry)
        for texture_entry in owner._archive_character_app_graph_texture_entries_for_swap(
            source_entry,
            stop_event=stop_event,
        ):
            raise_if_cancelled(stop_event, "In-game mesh swap scope preparation cancelled.")
            add_related_entry(texture_entry)
    for texture_entry in owner._archive_model_source_texture_entries_for_swap(
        source_entry,
        stop_event=stop_event,
    ):
        add_related_entry(texture_entry)

    source_related_entries = list(source_related_entries_by_key.values())
    source_sidecar_entries = tuple(owner._archive_model_sidecar_entries_for_swap(source_entry))
    target_sidecar_entries = tuple(owner._archive_model_sidecar_entries_for_swap(target_entry))
    source_sidecar_paths = {entry.path for entry in source_sidecar_entries}
    source_appearance_paths = (
        {
            entry.path
            for entry in owner._archive_character_appearance_entries_for_swap(
                source_entry,
                stop_event=stop_event,
            )
        }
        if allow_character_scope
        else set()
    )
    for related_entry in source_related_entries:
        if owner._archive_entry_is_material_sidecar(related_entry):
            source_sidecar_paths.add(related_entry.path)
        if owner._archive_entry_is_appearance_descriptor(related_entry):
            source_appearance_paths.add(related_entry.path)

    if item_family_scope:
        source_stem = PurePosixPath(source_entry.path.replace("\\", "/")).stem.lower()

        def is_item_family_related(entry: ArchiveEntry) -> bool:
            normalized_path = entry.path.replace("\\", "/").strip().lower()
            basename = PurePosixPath(normalized_path).name.lower()
            if entry.extension == ".dds":
                return True
            if owner._archive_entry_is_material_sidecar(entry) and entry.path in source_sidecar_paths:
                return True
            return bool(source_stem and source_stem in basename)

        source_related_entries = [entry for entry in source_related_entries if is_item_family_related(entry)]
    source_related_entries.sort(
        key=lambda entry: (
            owner._archive_entry_swap_companion_group(entry),
            entry.path.replace("\\", "/").casefold(),
        )
    )

    source_wrapper_count, source_pbd_hits, source_pbd_names = _material_contract_stats(
        source_sidecar_entries,
        stop_event=stop_event,
    )
    target_wrapper_count, _target_pbd_hits, _target_pbd_names = _material_contract_stats(
        target_sidecar_entries,
        stop_event=stop_event,
    )
    source_has_pbd_contract = source_pbd_hits > 0
    source_has_larger_material_contract = bool(
        source_wrapper_count > 0
        and target_wrapper_count > 0
        and source_wrapper_count > target_wrapper_count
    )
    preserve_source_contract_default = bool(
        item_family_scope and (source_has_pbd_contract or source_has_larger_material_contract)
    )
    return ArchiveMeshSwapScopePreflightResult(
        request_id=request.request_id,
        allow_character_scope=allow_character_scope,
        item_family_scope=item_family_scope,
        same_weapon_folder=same_weapon_folder,
        character_relationship_plan=character_relationship_plan,
        source_related_entries=tuple(source_related_entries),
        relationship_edges=tuple(relationship_edges_by_key.items()),
        unresolved_relationship_edges=tuple(unresolved_relationship_edges),
        source_sidecar_paths=frozenset(source_sidecar_paths),
        source_appearance_paths=frozenset(source_appearance_paths),
        source_pbd_names=source_pbd_names,
        source_wrapper_count=source_wrapper_count,
        target_wrapper_count=target_wrapper_count,
        source_has_pbd_contract=source_has_pbd_contract,
        source_has_larger_material_contract=source_has_larger_material_contract,
        preserve_source_contract_default=preserve_source_contract_default,
    )


__all__ = [
    "ArchiveMeshSwapScopePreflightRequest",
    "ArchiveMeshSwapScopePreflightResult",
    "prepare_archive_mesh_swap_scope",
]
