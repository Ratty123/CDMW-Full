from __future__ import annotations

import threading
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.models import (
    ArchiveEntry,
    DdsInfo,
)
from cdmw.core.common import RunCancelled, raise_if_cancelled
from cdmw.core.archive_model_references import (
    _archive_entry_identity_signature,
    _archive_entry_pathc_identity_signature,
    _model_texture_hint_priority,
    _normalize_model_texture_reference,
    _texconv_identity_signature,
)
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.upscale_profiles import (
    derive_texture_group_key,
    normalize_texture_reference_for_sidecar_lookup,
)

from cdmw.core import archive_model_texture_config as _config
from cdmw.core.archive_model_texture_pbd import ensure_archive_preview_source
from cdmw.core.archive_model_texture_semantics import (
    _has_explicit_model_texture_reference,
    _is_placeholder_model_texture,
    _iter_model_texture_reference_candidates,
    _iter_model_texture_slot_family_reference_candidates,
    _model_texture_candidate_slot_priority,
    _resolve_model_texture_semantics,
)

_MODEL_TEXTURE_PREVIEW_PATH_CACHE = _config.MODEL_TEXTURE_PREVIEW_PATH_CACHE
_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT = _config.MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT
_MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK = _config.MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK

def _score_model_texture_archive_candidate(
    source_entry: ArchiveEntry,
    candidate: ArchiveEntry,
    reference_candidates: Sequence[str],
) -> Tuple[int, int]:
    score_value = 0
    normalized_candidate_path = _normalize_model_texture_reference(candidate.path)
    candidate_basename = PurePosixPath(normalized_candidate_path).name
    for reference_index, normalized_reference in enumerate(reference_candidates):
        reference_basename = PurePosixPath(normalized_reference).name
        if normalized_candidate_path == normalized_reference:
            score_value += max(8, 24 - reference_index)
            break
        if candidate_basename and candidate_basename == reference_basename:
            score_value += max(4, 16 - reference_index)
            break
    if candidate.pamt_path == source_entry.pamt_path:
        score_value += 8
    if candidate.pamt_path.parent == source_entry.pamt_path.parent:
        score_value += 4
    if candidate.paz_file == source_entry.paz_file:
        score_value += 2
    if "/texture/" in normalized_candidate_path:
        score_value += 1
    return score_value, -len(candidate.path)

def _collect_model_texture_archive_entry_candidates(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    expand_family_candidates: bool = True,
    preferred_slot: str = "",
) -> List[Tuple[ArchiveEntry, Tuple[int, int]]]:
    reference_candidates = _iter_model_texture_reference_candidates(texture_name, material_name)
    if not reference_candidates:
        return []

    expanded_reference_candidates: List[str] = list(reference_candidates)
    if expand_family_candidates:
        seen_expanded = set(expanded_reference_candidates)
        for normalized_reference in reference_candidates:
            group_key = derive_texture_group_key(normalized_reference)
            for family_reference in _iter_model_texture_slot_family_reference_candidates(group_key, preferred_slot):
                if family_reference in seen_expanded:
                    continue
                seen_expanded.add(family_reference)
                expanded_reference_candidates.append(family_reference)

    candidates: List[ArchiveEntry] = []
    for normalized_reference in expanded_reference_candidates:
        if texture_entries_by_normalized_path is not None:
            for candidate in texture_entries_by_normalized_path.get(normalized_reference, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

        basename = PurePosixPath(normalized_reference).name
        if texture_entries_by_basename is not None and basename:
            for candidate in texture_entries_by_basename.get(basename, []):
                if candidate.extension == ".dds" and candidate not in candidates:
                    candidates.append(candidate)

    if not candidates:
        return []

    scored_candidates = [
        (candidate, _score_model_texture_archive_candidate(source_entry, candidate, reference_candidates))
        for candidate in candidates
    ]
    scored_candidates.sort(key=lambda item: item[1], reverse=True)
    return scored_candidates

def _model_texture_semantic_priority(texture_type: str, semantic_subtype: str) -> Tuple[int, int]:
    normalized_type = str(texture_type or "").strip().lower()
    normalized_subtype = str(semantic_subtype or "").strip().lower()
    if normalized_type == "color":
        subtype_priority = {
            "albedo": 4,
            "albedo_variant": 3,
            "diffuse": 2,
        }.get(normalized_subtype, 1)
        return 6, subtype_priority
    if normalized_type == "ui":
        return 5, 0
    if normalized_type == "emissive":
        return 4, 0
    if normalized_type == "impostor":
        return 3, 0
    if normalized_type == "unknown":
        return 2, 0
    if normalized_type == "mask" and normalized_subtype in {"detail_support", "grayscale_data"}:
        return 1, 0
    return 0, 0

def _resolve_model_texture_archive_entry(
    source_entry: ArchiveEntry,
    texture_name: str,
    material_name: str,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]],
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]],
    *,
    semantic_hint: str = "",
    expand_family_candidates: Optional[bool] = None,
    allow_technical_match: bool = False,
    preferred_slot: str = "",
    sidecar_texts_by_normalized_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    sidecar_texts_by_basename: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> Tuple[Optional[ArchiveEntry], str]:
    normalized_preferred_slot = str(preferred_slot or "").strip().lower()
    if _has_explicit_model_texture_reference(texture_name) and _is_placeholder_model_texture(texture_name):
        return None, "missing"
    if _has_explicit_model_texture_reference(material_name) and _is_placeholder_model_texture(material_name):
        return None, "missing"
    if expand_family_candidates is None:
        if normalized_preferred_slot in {"normal", "material", "height"}:
            expand_family_candidates = True
        else:
            expand_family_candidates = not _has_explicit_model_texture_reference(texture_name, material_name)
    scored_candidates = _collect_model_texture_archive_entry_candidates(
        source_entry,
        texture_name,
        material_name,
        texture_entries_by_normalized_path,
        texture_entries_by_basename,
        expand_family_candidates=expand_family_candidates,
        preferred_slot=normalized_preferred_slot,
    )
    if not scored_candidates:
        return None, "missing"

    family_members_by_group: Dict[str, Tuple[str, ...]] = defaultdict(tuple)
    grouped_family_members: Dict[str, List[str]] = defaultdict(list)
    for candidate, _direct_score in scored_candidates:
        grouped_family_members[derive_texture_group_key(candidate.path)].append(candidate.path)
    for group_key, members in grouped_family_members.items():
        family_members_by_group[group_key] = tuple(members)

    best_candidate: Optional[ArchiveEntry] = None
    best_candidate_key: Optional[Tuple[int, int, int, Tuple[int, int]]] = None
    best_candidate_priority = (0, 0)
    hint_priority = _model_texture_hint_priority(semantic_hint)
    slot_filtered_out = False
    for candidate, direct_score in scored_candidates:
        group_key = derive_texture_group_key(candidate.path)
        candidate_normalized_path = normalize_texture_reference_for_sidecar_lookup(candidate.path)
        sidecar_texts = tuple(sidecar_texts_by_normalized_path.get(candidate_normalized_path, ())) if (
            sidecar_texts_by_normalized_path is not None and candidate_normalized_path
        ) else ()
        if not sidecar_texts and sidecar_texts_by_basename is not None:
            sidecar_texts = tuple(
                sidecar_texts_by_basename.get(PurePosixPath(candidate.path.replace("\\", "/")).name.lower(), ())
            )
        texture_type, semantic_subtype, confidence = _resolve_model_texture_semantics(
            candidate.path,
            family_members=family_members_by_group.get(group_key, (candidate.path,)),
            sidecar_texts=sidecar_texts,
        )
        if normalized_preferred_slot in {"normal", "material", "height"}:
            semantic_priority = _model_texture_candidate_slot_priority(
                normalized_preferred_slot,
                candidate.path,
                sidecar_texts=sidecar_texts,
            )
            if semantic_priority is None:
                slot_filtered_out = True
                continue
        else:
            semantic_priority = _model_texture_semantic_priority(
                texture_type,
                semantic_subtype,
            )
            if hint_priority is not None and hint_priority > semantic_priority:
                semantic_priority = hint_priority
        sort_key = (
            semantic_priority[0],
            semantic_priority[1],
            confidence,
            direct_score,
        )
        if best_candidate_key is None or sort_key > best_candidate_key:
            best_candidate = candidate
            best_candidate_key = sort_key
            best_candidate_priority = semantic_priority

    if best_candidate is None:
        if normalized_preferred_slot in {"normal", "material", "height"} and slot_filtered_out:
            return None, "technical_only"
        return None, "missing"
    if allow_technical_match and best_candidate_priority[0] <= 0:
        return best_candidate, "resolved"
    if best_candidate_priority[0] <= 0:
        return None, "technical_only"
    return best_candidate, "resolved"

def _ensure_archive_model_texture_preview_path(
    resolved_texconv_path: Optional[Path],
    texture_entry: ArchiveEntry,
    *,
    max_dimension: Optional[int] = None,
    slot_kind: str = "base",
    stop_event: Optional[threading.Event] = None,
) -> str:
    resolved_max_dimension = (
        int(max_dimension)
        if max_dimension is not None
        else int(_config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION)
    )
    cache_key: Tuple[object, ...] = (
        _archive_entry_identity_signature(texture_entry),
        _archive_entry_pathc_identity_signature(texture_entry),
        _texconv_identity_signature(resolved_texconv_path),
        resolved_max_dimension,
        str(slot_kind or "base").strip().lower(),
    )
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
        if cached_preview_path:
            cached_path = Path(cached_preview_path)
            try:
                if cached_path.is_file() and cached_path.stat().st_size > 0:
                    _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                    return cached_preview_path
            except OSError:
                pass
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)

    texture_source_path, _texture_note = ensure_archive_preview_source(
        texture_entry,
        stop_event=stop_event,
    )
    dds_info: Optional[DdsInfo] = None
    try:
        dds_info = parse_dds(texture_source_path)
    except Exception:
        dds_info = None
    preview_path = ensure_dds_display_preview_png(
        resolved_texconv_path,
        texture_source_path.resolve(),
        dds_info=dds_info,
        max_dimension=resolved_max_dimension,
        slot_kind=slot_kind,
        stop_event=stop_event,
    )
    preview_path_text = str(preview_path)
    with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
        while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
    return preview_path_text

def _prefetch_archive_model_texture_preview_paths(
    resolved_texconv_path: Optional[Path],
    requests: Sequence[Tuple[ArchiveEntry, str, int]],
    preview_cache: Dict[str, str],
    *,
    stop_event: Optional[threading.Event] = None,
) -> None:
    if not requests:
        return
    try:
        from cdmw.core.texture_native import directxtex_preview_result_key, ensure_directxtex_dds_preview_pngs
    except Exception:
        return

    normalized_requests: List[Tuple[ArchiveEntry, str, int, str, Tuple[object, ...]]] = []
    seen: set[Tuple[str, str, int]] = set()
    for texture_entry, slot_kind, max_dimension in requests:
        slot_key = str(slot_kind or "base").strip().lower() or "base"
        resolved_max_dimension = max(1, int(max_dimension or _config.MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION))
        normalized_path = _normalize_model_texture_reference(texture_entry.path)
        if not normalized_path:
            continue
        local_key = f"{normalized_path}|{slot_key}"
        dedupe_key = (normalized_path, slot_key, resolved_max_dimension)
        if dedupe_key in seen or preview_cache.get(local_key):
            continue
        seen.add(dedupe_key)
        cache_key: Tuple[object, ...] = (
            _archive_entry_identity_signature(texture_entry),
            _archive_entry_pathc_identity_signature(texture_entry),
            _texconv_identity_signature(resolved_texconv_path),
            resolved_max_dimension,
            slot_key,
        )
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            cached_preview_path = _MODEL_TEXTURE_PREVIEW_PATH_CACHE.get(cache_key)
            if cached_preview_path:
                cached_path = Path(cached_preview_path)
                try:
                    if cached_path.is_file() and cached_path.stat().st_size > 0:
                        _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
                        preview_cache[local_key] = cached_preview_path
                        continue
                except OSError:
                    pass
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.pop(cache_key, None)
        normalized_requests.append((texture_entry, slot_key, resolved_max_dimension, local_key, cache_key))

    if not normalized_requests:
        return

    jobs: List[Dict[str, object]] = []
    by_job_key: Dict[str, Tuple[str, Tuple[object, ...]]] = {}
    by_source: Dict[str, Tuple[str, Tuple[object, ...]]] = {}
    for texture_entry, slot_key, resolved_max_dimension, local_key, cache_key in normalized_requests:
        raise_if_cancelled(stop_event)
        try:
            texture_source_path, _texture_note = ensure_archive_preview_source(texture_entry, stop_event=stop_event)
            source_key = str(texture_source_path.expanduser().resolve())
        except RunCancelled:
            raise
        except OSError:
            continue
        except Exception:
            continue
        jobs.append(
            {
                "dds_path": source_key,
                "slot_kind": slot_key,
                "max_dimension": resolved_max_dimension,
                "normal_space": "green_up" if slot_key == "normal" else "auto",
                "srgb": "auto",
            }
        )
        job_key = directxtex_preview_result_key(
            Path(source_key),
            max_dimension=resolved_max_dimension,
            slot_kind=slot_key,
            srgb="auto",
            normal_space="green_up" if slot_key == "normal" else "auto",
        )
        by_job_key[job_key] = (local_key, cache_key)
        by_source.setdefault(source_key, (local_key, cache_key))

    if not jobs:
        return

    try:
        timeout_seconds = max(10.0, min(180.0, 4.0 + (len(jobs) * 4.0)))
        results = ensure_directxtex_dds_preview_pngs(
            jobs,
            timeout_seconds=timeout_seconds,
            include_job_keys=True,
            stop_event=stop_event,
        )
    except RunCancelled:
        raise
    except Exception:
        return
    for result_key, mapped in by_job_key.items():
        preview_path = results.get(result_key)
        if preview_path is None:
            source_key = result_key.split("|slot=", 1)[0]
            preview_path = results.get(source_key)
        if preview_path is None:
            continue
        local_key, cache_key = mapped
        preview_path_text = str(preview_path)
        preview_cache[local_key] = preview_path_text
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
            while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
    for source_key, preview_path in results.items():
        if "|slot=" in str(source_key):
            continue
        mapped = by_source.get(str(source_key))
        if mapped is None:
            try:
                mapped = by_source.get(str(Path(source_key).expanduser().resolve()))
            except OSError:
                mapped = None
        if mapped is None:
            continue
        local_key, cache_key = mapped
        if local_key in preview_cache:
            continue
        preview_path_text = str(preview_path)
        preview_cache[local_key] = preview_path_text
        with _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK:
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE[cache_key] = preview_path_text
            _MODEL_TEXTURE_PREVIEW_PATH_CACHE.move_to_end(cache_key)
            while len(_MODEL_TEXTURE_PREVIEW_PATH_CACHE) > _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT:
                _MODEL_TEXTURE_PREVIEW_PATH_CACHE.popitem(last=False)
