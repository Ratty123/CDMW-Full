"""Resolve the frozen equipment catalogue against the current read-only archives."""

from __future__ import annotations

import copy
import hashlib
import json
import mmap
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.prefab_binary import PrefabBinaryError, decode_prefab_binary
from tools.mesh_harness.equipment_archive_worker import (
    AuditArchiveWorkerClient,
    archive_entry_from_worker,
)
from tools.mesh_harness.equipment_material_audit import (
    EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT,
    FrozenEquipmentCatalogue,
    normalize_archive_path,
    normalized_archive_key,
)


EQUIPMENT_AUDIT_RESOLUTION_SCHEMA = "cdmw_equipment_material_audit_resolution_v1"
EQUIPMENT_AUDIT_MODEL_EXTENSIONS = frozenset({".pac", ".pam", ".pamlod", ".pat"})
_PREFAB_PART_TOKEN = (
    r"body|head|hair|chain|cloth|acc|belt|sho|shoulder|ub|lb|hel|hand|foot|"
    r"blade|guard|handle|core|tail|wing|horn|fur"
)


def _resolve_catalogue_icons(catalogue, progress, worker):
    icon_paths = tuple(str(row["identity"]) for row in catalogue.icons)
    if progress is not None:
        progress(0, len(icon_paths), "Resolving exact inventory-icon paths")
    icon_entries = worker.resolve_values("exact_paths", icon_paths, chunk_size=96)
    icons_by_path = _rows_by_path(icon_entries)
    missing_icon_basenames = tuple(
        dict.fromkeys(
            PurePosixPath(path).name
            for path in icon_paths
            if path.casefold() not in icons_by_path
        )
    )
    fallback_icon_entries = worker.resolve_values(
        "basenames",
        missing_icon_basenames,
        chunk_size=64,
    )
    icons_by_basename = _rows_by_basename(fallback_icon_entries)
    icon_resolutions: list[dict[str, object]] = []
    for icon in catalogue.icons:
        path = str(icon["identity"])
        candidates = icons_by_path.get(path.casefold(), ())
        resolution_kind = "exact_path"
        if not candidates:
            candidates = icons_by_basename.get(PurePosixPath(path).name.casefold(), ())
            resolution_kind = "basename_fallback" if candidates else "unresolved"
        active = _active_entries_by_path(
            tuple(
                row
                for row in candidates
                if str(row.get("extension", "") or "").casefold() == ".dds"
            )
        )
        icon_resolutions.append(
            {
                "identity": path,
                "declared_name": str(icon.get("declared_name", "") or ""),
                "owners": list(icon.get("owners", ()) or ()),
                "status": resolution_kind if active else "unresolved",
                "entries": [dict(row) for row in active],
            }
        )
    return icon_resolutions


def _resolve_logical_model_rows(
    candidate_models_by_logical, decoded_prefabs, initial_by_basename, logical_rows, model_by_basename,
    model_by_path, progress, relevant_prefab_keys_by_logical, relevant_prefabs, source_stems_by_logical,
):
    resolutions: list[dict[str, object]] = []
    for index, logical in enumerate(logical_rows, 1):
        logical_name = str(logical["identity"])
        if progress is not None and (index == 1 or index % 100 == 0 or index == len(logical_rows)):
            progress(index, len(logical_rows), f"Conserving logical model: {logical_name}")
        direct_candidates = _matching_model_rows(
            initial_by_basename,
            candidate_models_by_logical[logical_name],
        )
        direct_entries = _active_entries_by_path(direct_candidates)
        exact_direct_entries = tuple(
            row
            for row in direct_entries
            if PurePosixPath(normalize_archive_path(row.get("path"))).name.casefold()
            == logical_name.casefold()
        )
        prefab_rows = tuple(
            relevant_prefabs[key]
            for key in relevant_prefab_keys_by_logical.get(logical_name, ())
        )
        prefab_edges: list[dict[str, object]] = []
        prefab_component_entries: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
        for prefab in prefab_rows:
            prefab_identity = _entry_identity(prefab)
            for raw_edge in decoded_prefabs.get(prefab_identity, ()):
                edge = dict(raw_edge)
                path = normalize_archive_path(edge.get("path"))
                if not path:
                    continue
                candidates = model_by_path.get(path.casefold(), ())
                if not candidates:
                    candidates = model_by_basename.get(PurePosixPath(path).name.casefold(), ())
                resolved = _active_entries_by_path(
                    tuple(
                        row
                        for row in candidates
                        if str(row.get("extension", "") or "").casefold()
                        in EQUIPMENT_AUDIT_MODEL_EXTENSIONS
                    )
                )
                edge["source_prefab_path"] = str(prefab.get("path", "") or "")
                edge["resolution_status"] = "resolved" if resolved else "unresolved"
                edge["resolved_entry_count"] = len(resolved)
                prefab_edges.append(edge)
                prefab_component_entries.extend((entry, edge) for entry in resolved)

        component_sources: dict[tuple[object, ...], dict[str, object]] = {}
        for entry in direct_entries:
            entry_basename = PurePosixPath(normalize_archive_path(entry.get("path"))).name
            component_sources[_entry_identity(entry)] = {
                "entry": entry,
                "roles": [
                    "logical_pac"
                    if entry_basename.casefold() == logical_name.casefold()
                    else "archive_variant_alias"
                ],
                "source_prefabs": [],
                "model_property_indices": [],
            }
        for entry, edge in prefab_component_entries:
            identity = _entry_identity(entry)
            component = component_sources.setdefault(
                identity,
                {
                    "entry": entry,
                    "roles": [],
                    "source_prefabs": [],
                    "model_property_indices": [],
                },
            )
            role = str(edge.get("role", "prefab_model_resource") or "prefab_model_resource")
            if role not in component["roles"]:
                component["roles"].append(role)
            source_prefab = str(edge.get("source_prefab_path", "") or "")
            if source_prefab and source_prefab not in component["source_prefabs"]:
                component["source_prefabs"].append(source_prefab)
            property_index = edge.get("model_property_index")
            if isinstance(property_index, int) and property_index not in component["model_property_indices"]:
                component["model_property_indices"].append(property_index)

        components = sorted(
            component_sources.values(),
            key=lambda row: _entry_sort_key(row["entry"]),
        )
        primary_identity = _select_primary_component_identity(
            logical_name,
            direct_entries,
            tuple(row["entry"] for row in components),
        )
        serialized_components: list[dict[str, object]] = []
        for component in components:
            entry = component["entry"]
            serialized_components.append(
                {
                    "entry": dict(entry),
                    "roles": sorted(component["roles"]),
                    "source_prefabs": sorted(component["source_prefabs"], key=str.casefold),
                    "model_property_indices": sorted(component["model_property_indices"]),
                    "is_primary": _entry_identity(entry) == primary_identity,
                }
            )
        if not serialized_components:
            status = "unresolved"
        elif direct_entries and any(component["source_prefabs"] for component in serialized_components):
            status = (
                "direct_with_prefab_components"
                if exact_direct_entries
                else "archive_variant_alias_with_prefab_components"
            )
        elif direct_entries:
            status = "direct" if exact_direct_entries else "archive_variant_alias"
        else:
            status = "prefab_binary_reference"
        resolutions.append(
            {
                "identity": logical_name,
                "declared_name": str(logical.get("declared_name", "") or ""),
                "owners": list(logical.get("owners", ()) or ()),
                "source_model_stems": list(source_stems_by_logical.get(logical_name, ())),
                "model_candidate_basenames": list(candidate_models_by_logical[logical_name]),
                "status": status,
                "direct_candidates": [dict(row) for row in direct_candidates],
                "prefab_candidates": [dict(row) for row in prefab_rows],
                "prefab_edges": prefab_edges,
                "physical_components": serialized_components,
            }
        )
    return resolutions


def _resolve_catalogue_model_candidates(catalogue, logical_names, logical_rows, progress, worker):
    source_stems_by_logical = _source_model_stems_by_logical(catalogue)
    candidate_models_by_logical: dict[str, tuple[str, ...]] = {
        name: (name,) for name in logical_names
    }
    candidate_prefabs_by_logical = {
        name: tuple(
            dict.fromkeys(
                basename
                for source_name in (name, *source_stems_by_logical.get(name, ()))
                for basename in prefab_candidate_basenames(source_name)
            )
        )
        for name in logical_names
    }
    candidate_basenames = tuple(
        dict.fromkeys(
            [
                *logical_names,
                *(
                    basename
                    for names in candidate_prefabs_by_logical.values()
                    for basename in names
                ),
            ]
        )
    )
    if progress is not None:
        progress(0, len(logical_rows), "Resolving logical PAC and prefab basenames")
    initial_entries = worker.resolve_values(
        "basenames",
        candidate_basenames,
        chunk_size=64,
    )
    initial_by_basename = _rows_by_basename(initial_entries)

    unresolved_after_exact = tuple(
        name
        for name in logical_names
        if not _matching_model_rows(
            initial_by_basename,
            candidate_models_by_logical[name],
        )
        and not _matching_prefab_rows(
            initial_by_basename,
            candidate_prefabs_by_logical[name],
        )
    )
    fallback_models_by_logical = {
        name: _fallback_model_basenames(name, source_stems_by_logical.get(name, ()))
        for name in unresolved_after_exact
    }
    fallback_model_basenames = tuple(
        dict.fromkeys(
            basename
            for names in fallback_models_by_logical.values()
            for basename in names
        )
    )
    fallback_model_entries = worker.resolve_values(
        "basenames",
        fallback_model_basenames,
        chunk_size=64,
    )
    initial_entries = _dedupe_entries((*initial_entries, *fallback_model_entries))
    initial_by_basename = _rows_by_basename(initial_entries)
    for name, basenames in fallback_models_by_logical.items():
        candidate_models_by_logical[name] = tuple(
            dict.fromkeys((*candidate_models_by_logical[name], *basenames))
        )

    unresolved_after_model_alias = tuple(
        name
        for name in unresolved_after_exact
        if not _matching_model_rows(
            initial_by_basename,
            candidate_models_by_logical[name],
        )
        and not _matching_prefab_rows(
            initial_by_basename,
            candidate_prefabs_by_logical[name],
        )
    )
    fallback_prefabs_by_logical = {
        name: _fallback_prefab_basenames(name, source_stems_by_logical.get(name, ()))
        for name in unresolved_after_model_alias
    }
    fallback_prefab_basenames = tuple(
        dict.fromkeys(
            basename
            for names in fallback_prefabs_by_logical.values()
            for basename in names
        )
    )
    fallback_prefab_entries = worker.resolve_values(
        "basenames",
        fallback_prefab_basenames,
        chunk_size=64,
    )
    initial_entries = _dedupe_entries((*initial_entries, *fallback_prefab_entries))
    initial_by_basename = _rows_by_basename(initial_entries)
    for name, basenames in fallback_prefabs_by_logical.items():
        candidate_prefabs_by_logical[name] = tuple(
            dict.fromkeys((*candidate_prefabs_by_logical[name], *basenames))
        )
    return candidate_models_by_logical, candidate_prefabs_by_logical, initial_entries, initial_by_basename, source_stems_by_logical


def resolve_live_equipment_catalogue(
    catalogue: FrozenEquipmentCatalogue,
    worker: AuditArchiveWorkerClient,
    *,
    progress: Callable[[int, int, str], None] | None = None,
    prefab_reader: Callable[[Mapping[str, object]], Sequence[Mapping[str, object]]] | None = None,
) -> Mapping[str, object]:
    """Resolve every logical PAC and icon without changing the frozen selection."""

    session = worker.session
    if session is None:
        raise RuntimeError("Equipment archive resolution requires an open worker session.")
    logical_rows = tuple(catalogue.logical_models)
    if len(logical_rows) != EQUIPMENT_AUDIT_LOGICAL_PAC_COUNT:
        raise ValueError("Equipment archive resolution received an incomplete frozen catalogue.")
    read_prefab = prefab_reader or _read_prefab_model_edges

    logical_names = tuple(str(row["identity"]) for row in logical_rows)
    (
        candidate_models_by_logical, candidate_prefabs_by_logical, initial_entries, initial_by_basename,
        source_stems_by_logical,
    ) = _resolve_catalogue_model_candidates(
        catalogue, logical_names, logical_rows, progress, worker,
    )

    relevant_prefabs: dict[tuple[object, ...], Mapping[str, object]] = {}
    relevant_prefab_keys_by_logical: dict[str, tuple[tuple[object, ...], ...]] = {}
    for logical_name in logical_names:
        keys: list[tuple[object, ...]] = []
        for basename in candidate_prefabs_by_logical[logical_name]:
            for row in initial_by_basename.get(basename.casefold(), ()):
                if str(row.get("extension", "") or "").casefold() != ".prefab":
                    continue
                key = _entry_identity(row)
                relevant_prefabs[key] = row
                keys.append(key)
        relevant_prefab_keys_by_logical[logical_name] = tuple(dict.fromkeys(keys))

    decoded_prefabs: dict[tuple[object, ...], tuple[Mapping[str, object], ...]] = {}
    model_reference_paths: list[str] = []
    prefab_errors: list[dict[str, object]] = []
    total_prefabs = len(relevant_prefabs)
    for index, (identity, prefab) in enumerate(
        sorted(relevant_prefabs.items(), key=lambda item: _entry_sort_key(item[1])),
        1,
    ):
        if progress is not None and (index == 1 or index % 25 == 0 or index == total_prefabs):
            progress(index, total_prefabs, f"Decoding prefab relationships: {prefab.get('path', '')}")
        try:
            edges = tuple(dict(edge) for edge in read_prefab(prefab))
        except Exception as exc:
            edges = ()
            prefab_errors.append(
                {
                    "path": str(prefab.get("path", "") or ""),
                    "entry_identity": list(identity),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        decoded_prefabs[identity] = edges
        model_reference_paths.extend(
            normalize_archive_path(edge.get("path"))
            for edge in edges
            if _model_extension(edge.get("path")) in EQUIPMENT_AUDIT_MODEL_EXTENSIONS
        )

    model_reference_paths = list(dict.fromkeys(path for path in model_reference_paths if path))
    if progress is not None:
        progress(0, len(model_reference_paths), "Resolving physical prefab model paths")
    referenced_model_entries = worker.resolve_values(
        "exact_paths",
        model_reference_paths,
        chunk_size=96,
    )
    referenced_by_path = _rows_by_path(referenced_model_entries)
    unresolved_reference_basenames = tuple(
        dict.fromkeys(
            PurePosixPath(path).name
            for path in model_reference_paths
            if normalized_archive_key(path) not in referenced_by_path
        )
    )
    fallback_model_entries = worker.resolve_values(
        "basenames",
        unresolved_reference_basenames,
        chunk_size=64,
    )

    all_model_entries = _dedupe_entries((*initial_entries, *referenced_model_entries, *fallback_model_entries))
    model_by_path = _rows_by_path(all_model_entries)
    model_by_basename = _rows_by_basename(all_model_entries)
    resolutions = _resolve_logical_model_rows(
        candidate_models_by_logical, decoded_prefabs, initial_by_basename, logical_rows, model_by_basename,
        model_by_path, progress, relevant_prefab_keys_by_logical, relevant_prefabs, source_stems_by_logical,
    )

    icon_resolutions = _resolve_catalogue_icons(catalogue, progress, worker)

    _propagate_same_record_aliases(resolutions)
    _classify_catalogue_source_only_rows(catalogue, resolutions)

    status_counts: dict[str, int] = defaultdict(int)
    physical_identities: set[tuple[object, ...]] = set()
    component_edge_count = 0
    for resolution in resolutions:
        status_counts[str(resolution["status"])] += 1
        components = tuple(resolution["physical_components"])
        component_edge_count += len(components)
        for component in components:
            entry = component.get("entry") if isinstance(component, Mapping) else None
            if isinstance(entry, Mapping):
                physical_identities.add(_entry_identity(entry))
    unresolved_icons = sum(row["status"] == "unresolved" for row in icon_resolutions)
    payload: dict[str, object] = {
        "schema": EQUIPMENT_AUDIT_RESOLUTION_SCHEMA,
        "frozen_catalogue": {
            "schema": catalogue.payload.get("schema"),
            "item_catalog_sha256": catalogue.source_sha256,
            "selection_sha256": catalogue.payload["selection"]["selection_sha256"],
        },
        "live_archive": {
            "package_root": str(session.package_root),
            "fingerprint": session.fingerprint,
            "entry_count": session.entry_count,
            "index_version": session.index_version,
            "cache_hit": session.cache_hit,
        },
        "counts": {
            "logical_models": len(resolutions),
            "logical_model_statuses": dict(sorted(status_counts.items())),
            "unresolved_logical_models": status_counts.get("unresolved", 0),
            "physical_component_edges": component_edge_count,
            "unique_physical_entries": len(physical_identities),
            "prefabs_decoded": len(decoded_prefabs),
            "prefab_decode_errors": len(prefab_errors),
            "icons": len(icon_resolutions),
            "unresolved_icons": unresolved_icons,
        },
        "prefab_decode_errors": prefab_errors,
        "logical_models": resolutions,
        "icons": icon_resolutions,
    }
    payload["resolution_sha256"] = _canonical_sha256(payload)
    return payload


def prefab_candidate_basenames(logical_pac: str) -> tuple[str, ...]:
    """Mirror Preview Core's bounded same-stem prefab candidate contract."""

    stem = PurePosixPath(normalize_archive_path(logical_pac)).stem
    stems: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        key = candidate.casefold()
        if candidate and key not in seen:
            seen.add(key)
            stems.append(candidate)

    add(stem)
    if not stem.casefold().endswith("_v"):
        add(f"{stem}_v")
    match = re.match(r"^(.+)_sub[0-9]+$", stem, re.IGNORECASE)
    if match:
        add(match.group(1))
    match = re.match(
        rf"^(.+)_({_PREFAB_PART_TOKEN})_([0-9].*)$",
        stem,
        re.IGNORECASE,
    )
    if match:
        add(f"{match.group(1)}_{match.group(3)}")
    match = re.match(
        rf"^(.+_[0-9].*)_({_PREFAB_PART_TOKEN})$",
        stem,
        re.IGNORECASE,
    )
    if match:
        add(match.group(1))
    match = re.match(
        r"^(.+)_(ub|lb|sho|hel|hand|foot|cloak)_(acc|belt|hair|cloth)_([0-9].*)$",
        stem,
        re.IGNORECASE,
    )
    if match:
        add(f"{match.group(1)}_{match.group(2)}_{match.group(4)}")
        add(f"{match.group(1)}_{match.group(4)}")

    result: list[str] = []
    result_seen: set[str] = set()
    for candidate in stems:
        for basename in (
            f"{candidate}_s.prefab",
            f"{candidate}_l.prefab",
            f"{candidate}_r.prefab",
            f"{candidate}.prefab",
        ):
            key = basename.casefold()
            if key not in result_seen:
                result_seen.add(key)
                result.append(basename)
    return tuple(result)


def _source_model_stems_by_logical(
    catalogue: FrozenEquipmentCatalogue,
) -> Mapping[str, tuple[str, ...]]:
    """Recover the exact pre-normalization model stems that produced each PAC edge."""

    result: dict[str, list[str]] = defaultdict(list)
    for record in catalogue.records:
        raw_pac_files = record.get("pac_files", ())
        raw_model_stems = record.get("model_stems", ())
        if (
            not isinstance(raw_pac_files, Sequence)
            or isinstance(raw_pac_files, (str, bytes, bytearray))
            or not isinstance(raw_model_stems, Sequence)
            or isinstance(raw_model_stems, (str, bytes, bytearray))
        ):
            continue
        pac_identities = {
            PurePosixPath(normalize_archive_path(value)).name.casefold()
            for value in raw_pac_files
            if normalize_archive_path(value)
        }
        for raw_stem in raw_model_stems:
            stem = PurePosixPath(normalize_archive_path(raw_stem)).stem
            if not stem:
                continue
            identity = f"{_strip_catalogue_model_variant_suffix(stem)}.pac".casefold()
            if identity not in pac_identities:
                continue
            stems = result[identity]
            if stem.casefold() not in {value.casefold() for value in stems}:
                stems.append(stem)
    return {
        identity: tuple(stems)
        for identity, stems in result.items()
    }


def _strip_catalogue_model_variant_suffix(stem: str) -> str:
    """Mirror the frozen catalogue's v3 model-stem normalization."""

    normalized = stem.strip().casefold()
    suffixes = (
        "_index01_l",
        "_index01_r",
        "_index02_l",
        "_index02_r",
        "_index03_l",
        "_index03_r",
        "_index01",
        "_index02",
        "_index03",
        "_sub01",
        "_sub02",
        "_sub03",
        "_in",
        "_l",
        "_r",
        "_u",
        "_s",
        "_t",
        "_c",
        "_d",
    )
    while normalized:
        prior = normalized
        for suffix in suffixes:
            if len(normalized) > len(suffix) and normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        if normalized == prior:
            break
    if (
        len(normalized) >= 2
        and normalized[-2].isascii()
        and normalized[-2].isdigit()
        and normalized[-1].isascii()
        and normalized[-1].isalpha()
    ):
        normalized = normalized[:-1]
    return normalized


def _fallback_model_basenames(
    logical_name: str,
    source_stems: Sequence[str],
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for source in (PurePosixPath(normalize_archive_path(logical_name)).stem, *source_stems):
        stem = PurePosixPath(normalize_archive_path(source)).stem
        candidates = [stem]
        short_variant = re.match(r"^(.+)_([a-z]{1,2})$", stem, re.IGNORECASE)
        if short_variant:
            candidates.append(short_variant.group(1))
        for candidate in tuple(candidates):
            if candidate.casefold().startswith("cd_phm_m0001_"):
                candidates.append(
                    "cd_m0001_" + candidate[len("cd_phm_m0001_") :]
                )
        for candidate in candidates[1:]:
            basename = f"{candidate}.pac"
            key = basename.casefold()
            if key not in seen and key != logical_name.casefold():
                seen.add(key)
                result.append(basename)
    return tuple(result)


def _fallback_prefab_basenames(
    logical_name: str,
    source_stems: Sequence[str],
) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    model_aliases = _fallback_model_basenames(logical_name, source_stems)
    stems = [
        PurePosixPath(normalize_archive_path(value)).stem
        for value in (*source_stems, *model_aliases)
    ]
    for stem in stems:
        for suffix in ("_c", "_d", "_dd", "_f", "_t", "_u", "_y"):
            basename = f"{stem}{suffix}.prefab"
            key = basename.casefold()
            if key not in seen:
                seen.add(key)
                result.append(basename)
    return tuple(result)


def _matching_model_rows(
    rows_by_basename: Mapping[str, tuple[Mapping[str, object], ...]],
    basenames: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    return _dedupe_entries(
        tuple(
            row
            for basename in basenames
            for row in rows_by_basename.get(basename.casefold(), ())
            if str(row.get("extension", "") or "").casefold()
            in EQUIPMENT_AUDIT_MODEL_EXTENSIONS
        )
    )


def _matching_prefab_rows(
    rows_by_basename: Mapping[str, tuple[Mapping[str, object], ...]],
    basenames: Sequence[str],
) -> tuple[Mapping[str, object], ...]:
    return _dedupe_entries(
        tuple(
            row
            for basename in basenames
            for row in rows_by_basename.get(basename.casefold(), ())
            if str(row.get("extension", "") or "").casefold() == ".prefab"
        )
    )


def _propagate_same_record_aliases(resolutions: list[dict[str, object]]) -> None:
    """Resolve only aliases whose same-record siblings converge on one component set."""

    by_record: dict[str, list[dict[str, object]]] = defaultdict(list)
    for resolution in resolutions:
        for owner in tuple(resolution.get("owners", ()) or ()):
            if not isinstance(owner, Mapping):
                continue
            record_id = str(owner.get("record_id", "") or "")
            if record_id:
                by_record[record_id].append(resolution)

    changed = True
    while changed:
        changed = False
        for target in resolutions:
            if target.get("status") != "unresolved":
                continue
            candidate_sets: dict[
                tuple[tuple[object, ...], ...],
                list[tuple[dict[str, object], str]],
            ] = defaultdict(list)
            for owner in tuple(target.get("owners", ()) or ()):
                if not isinstance(owner, Mapping):
                    continue
                record_id = str(owner.get("record_id", "") or "")
                for source in by_record.get(record_id, ()):
                    if source is target or source.get("status") == "unresolved":
                        continue
                    components = tuple(source.get("physical_components", ()) or ())
                    signature = tuple(
                        sorted(
                            _entry_identity(component["entry"])
                            for component in components
                            if isinstance(component, Mapping)
                            and isinstance(component.get("entry"), Mapping)
                        )
                    )
                    if signature:
                        candidate_sets[signature].append((source, record_id))
            if len(candidate_sets) != 1:
                continue
            sources = next(iter(candidate_sets.values()))
            source = sources[0][0]
            propagated_components = copy.deepcopy(
                list(source.get("physical_components", ()) or ())
            )
            for component in propagated_components:
                if not isinstance(component, dict):
                    continue
                roles = list(component.get("roles", ()) or ())
                if "same_record_catalogue_alias" not in roles:
                    roles.append("same_record_catalogue_alias")
                component["roles"] = sorted(str(role) for role in roles)
            target["physical_components"] = propagated_components
            target["status"] = "same_record_catalogue_alias"
            target["alias_sources"] = [
                {
                    "identity": str(candidate.get("identity", "") or ""),
                    "shared_record_id": record_id,
                    "status": str(candidate.get("status", "") or ""),
                }
                for candidate, record_id in sorted(
                    sources,
                    key=lambda row: (
                        str(row[0].get("identity", "") or "").casefold(),
                        row[1],
                    ),
                )
            ]
            changed = True


def _classify_catalogue_source_only_rows(
    catalogue: FrozenEquipmentCatalogue,
    resolutions: list[dict[str, object]],
) -> None:
    """Prove icon-derived logical names that never named a frozen physical asset."""

    frozen_index_path = catalogue.source_path.parent / "archive.ali"
    if not frozen_index_path.is_file():
        return
    records_by_id = {
        str(record.get("record_id", "") or ""): record
        for record in catalogue.records
    }
    with frozen_index_path.open("rb") as stream:
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as frozen_index:
            for resolution in resolutions:
                if resolution.get("status") != "unresolved":
                    continue
                identity = str(resolution.get("identity", "") or "").casefold()
                owner_records = [
                    records_by_id.get(str(owner.get("record_id", "") or ""))
                    for owner in tuple(resolution.get("owners", ()) or ())
                    if isinstance(owner, Mapping)
                ]
                owner_records = [record for record in owner_records if record is not None]
                if not owner_records or any(record.get("prefab_hashes") for record in owner_records):
                    continue
                owner_pac_sets = [
                    {
                        PurePosixPath(normalize_archive_path(value)).name.casefold()
                        for value in tuple(record.get("pac_files", ()) or ())
                    }
                    for record in owner_records
                ]
                if any(pac_names != {identity} for pac_names in owner_pac_sets):
                    continue
                source_stems = tuple(resolution.get("source_model_stems", ()) or ())
                candidate_tokens = tuple(
                    dict.fromkeys(
                        (
                            identity,
                            *prefab_candidate_basenames(identity),
                            *_fallback_model_basenames(identity, source_stems),
                            *_fallback_prefab_basenames(identity, source_stems),
                        )
                    )
                )
                present_tokens = [
                    token
                    for token in candidate_tokens
                    if frozen_index.find(token.casefold().encode("ascii", "strict")) >= 0
                ]
                if present_tokens:
                    continue
                resolution["status"] = "catalogue_source_only"
                resolution["source_only_finding"] = {
                    "finding": "catalogue_name_has_no_renderable_archive_binding",
                    "frozen_archive_fingerprint": catalogue.payload.get("source", {}).get(
                        "archive_fingerprint", ""
                    ),
                    "frozen_index_path": str(frozen_index_path),
                    "candidate_path_tokens_checked": list(candidate_tokens),
                    "candidate_path_tokens_present": [],
                    "owner_prefab_hashes_empty": True,
                    "owner_has_no_sibling_pac": True,
                    "associated_icons": sorted(
                        {
                            normalize_archive_path(icon)
                            for record in owner_records
                            for icon in tuple(record.get("icon_paths", ()) or ())
                        },
                        key=str.casefold,
                    ),
                }


def _read_prefab_model_edges(prefab: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    entry = archive_entry_from_worker(prefab)
    try:
        document = decode_prefab_binary(read_archive_entry_data(entry)[0])
    except (OSError, RuntimeError, ValueError, PrefabBinaryError) as exc:
        raise ValueError(f"Could not decode {entry.path}: {exc}") from exc
    edges: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for item in document.objects:
        property_index: int | None = None
        property_raw = ""
        for number in item.numbers:
            if number.name.casefold() != "_modelpropertyindex":
                continue
            property_raw = bytes(number.raw).hex()
            property_index = int.from_bytes(number.raw, "little", signed=False)
            break
        for field, value in item.values:
            path = normalize_archive_path(value.text)
            extension = _model_extension(path)
            if extension not in EQUIPMENT_AUDIT_MODEL_EXTENSIONS:
                continue
            role = (
                "prefab_skinned_model_resource"
                if "skinned" in field.casefold()
                else "prefab_model_resource"
            )
            key = (path.casefold(), field.casefold(), property_index, item.index)
            if key in seen:
                continue
            seen.add(key)
            edge: dict[str, object] = {
                "path": path,
                "role": role,
                "confidence": "prefab_binary_reference",
                "source_field": field,
                "object_index": int(item.index),
                "component_type": str(item.component_type or ""),
            }
            if property_index is not None:
                edge["model_property_index"] = property_index
                edge["model_property_index_raw_le"] = property_raw
            edges.append(edge)
    return tuple(edges)


def _model_extension(path: object) -> str:
    return PurePosixPath(normalize_archive_path(path)).suffix.casefold()


def _rows_by_basename(
    rows: Sequence[Mapping[str, object]],
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        path = normalize_archive_path(row.get("path"))
        if path:
            grouped[PurePosixPath(path).name.casefold()].append(row)
    return {
        key: tuple(sorted(values, key=_entry_sort_key))
        for key, values in grouped.items()
    }


def _rows_by_path(
    rows: Sequence[Mapping[str, object]],
) -> Mapping[str, tuple[Mapping[str, object], ...]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        key = normalized_archive_key(row.get("path"))
        if key:
            grouped[key].append(row)
    return {
        key: tuple(sorted(values, key=_entry_sort_key))
        for key, values in grouped.items()
    }


def _active_entries_by_path(
    rows: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    grouped = _rows_by_path(rows)
    selected: list[Mapping[str, object]] = []
    for candidates in grouped.values():
        active = tuple(row for row in candidates if bool(row.get("is_active_override", False)))
        if active:
            selected.extend(active)
            continue
        unshadowed = tuple(
            row
            for row in candidates
            if not str(row.get("override_state", "") or "").casefold().startswith("shadowed")
        )
        selected.extend(unshadowed or candidates[:1])
    return tuple(sorted(selected, key=_entry_sort_key))


def _select_primary_component_identity(
    logical_name: str,
    direct_entries: Sequence[Mapping[str, object]],
    components: Sequence[Mapping[str, object]],
) -> tuple[object, ...] | None:
    candidates = tuple(direct_entries) or tuple(components)
    if not candidates:
        return None
    logical_stem = _prefab_component_match_stem(PurePosixPath(logical_name).stem)
    ordered = sorted(
        candidates,
        key=lambda row: (
            _prefab_component_match_stem(
                PurePosixPath(normalize_archive_path(row.get("path"))).stem
            )
            != logical_stem,
            _entry_sort_key(row),
        ),
    )
    return _entry_identity(ordered[0])


def _prefab_component_match_stem(stem: str) -> str:
    value = stem.casefold()
    for suffix in ("_op_s", "_op_v", "_v", "_s"):
        if len(value) > len(suffix) and value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _dedupe_entries(
    rows: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    result: list[Mapping[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for row in rows:
        identity = _entry_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(row)
    return tuple(result)


def _entry_identity(row: Mapping[str, object]) -> tuple[object, ...]:
    identity = row.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    return (
        normalized_archive_key(
            identity.get("normalized_path") or row.get("path")
        ),
        str(identity.get("source_pamt") or row.get("source_pamt") or "")
        .replace("\\", "/")
        .casefold(),
        int(identity.get("paz_index") or row.get("paz_index") or 0),
        int(identity.get("archive_offset") or row.get("offset") or 0),
    )


def _entry_sort_key(row: Mapping[str, object]) -> tuple[object, ...]:
    path = normalized_archive_key(row.get("path"))
    return (
        0 if bool(row.get("is_active_override", False)) else 1,
        0 if path.startswith("character/model/") else 1,
        path,
        str(row.get("source_pamt", "") or "").casefold(),
        int(row.get("offset", 0) or 0),
    )


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EQUIPMENT_AUDIT_MODEL_EXTENSIONS",
    "EQUIPMENT_AUDIT_RESOLUTION_SCHEMA",
    "prefab_candidate_basenames",
    "resolve_live_equipment_catalogue",
]
