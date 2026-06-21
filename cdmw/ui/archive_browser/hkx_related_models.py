"""Related model ranking helpers for HKX previews."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import List, Tuple

from cdmw.modding.static_mesh_replacer import _semantic_tokens
from cdmw.ui.archive_browser.hkx_editor_dialog_helpers import filter_terms


_RELATED_MODEL_STOP_TOKENS = {
    "bin",
    "bin_",
    "havok",
    "havokphysics",
    "meshphysics",
    "physics",
    "model",
    "character",
    "object",
    "leveldata",
    "animation",
    "animations",
    "pc",
    "npc",
    "mon",
    "hkx",
    "pac",
    "pam",
    "pamlod",
}

_RELATED_MODEL_FAST_STOP_TOKENS = {
    "bin",
    "havok",
    "havokphysics",
    "meshphysics",
    "physics",
    "character",
    "model",
    "pc",
    "hkx",
}


def _related_model_tokens(path_text: str, stop_tokens: set[str], *, min_length: int = 2) -> set[str]:
    return {
        token
        for token in _semantic_tokens(path_text)
        if token not in stop_tokens and len(token) >= min_length and not token.isdigit()
    }


def score_hkx_related_model_entry(source_entry: object, candidate: object, filter_text: str = "") -> Tuple[int, str]:
    source_path_text = str(getattr(source_entry, "path", "") or "").replace("\\", "/").strip().casefold()
    candidate_path_text = str(getattr(candidate, "path", "") or "").replace("\\", "/").strip().casefold()
    source_name = PurePosixPath(source_path_text).name
    source_stem = PurePosixPath(source_path_text).stem
    candidate_name = PurePosixPath(candidate_path_text).name
    candidate_stem = PurePosixPath(candidate_path_text).stem
    source_parts = tuple(part for part in PurePosixPath(source_path_text).parts if part)
    candidate_parts = tuple(part for part in PurePosixPath(candidate_path_text).parts if part)
    source_tokens = _related_model_tokens(source_path_text.replace("/", " "), _RELATED_MODEL_STOP_TOKENS)
    candidate_tokens = _related_model_tokens(candidate_path_text.replace("/", " "), _RELATED_MODEL_STOP_TOKENS)
    source_stem_tokens = _related_model_tokens(source_stem, _RELATED_MODEL_STOP_TOKENS)
    candidate_stem_tokens = _related_model_tokens(candidate_stem, _RELATED_MODEL_STOP_TOKENS)
    score = 0
    reasons: List[str] = []
    raw_filter_terms = filter_terms(filter_text)
    if raw_filter_terms:
        filter_haystack = f"{candidate_path_text} {getattr(candidate, 'package_label', '')}".casefold()
        if not all(term in filter_haystack for term in raw_filter_terms):
            return -1, ""
        score += 100
        reasons.append("filter match")
    if getattr(candidate, "pamt_path", None) == getattr(source_entry, "pamt_path", None):
        score += 18
        reasons.append("same package")
    if source_name and source_name == candidate_name:
        score += 240
        reasons.append("same basename")
    if source_stem and source_stem == candidate_stem:
        score += 180
        reasons.append("same stem")
    elif source_stem and source_stem in candidate_path_text:
        score += 95
        reasons.append(f"path contains {source_stem}")
    shared_stem_tokens = sorted(source_stem_tokens & candidate_stem_tokens)
    if shared_stem_tokens:
        score += min(80, 26 * len(shared_stem_tokens))
        reasons.append("shared stem token " + ", ".join(shared_stem_tokens[:3]))
    shared_tokens = sorted(source_tokens & candidate_tokens)
    if shared_tokens:
        score += min(60, 10 * len(shared_tokens))
        reasons.append("shared path token " + ", ".join(shared_tokens[:4]))
    if source_parts and candidate_parts:
        if source_parts[0] == candidate_parts[0]:
            score += 10
            reasons.append(f"same archive role {source_parts[0]}")
        source_role_parts = {part for part in source_parts if re.fullmatch(r"\d+_[a-z0-9]+", part)}
        candidate_role_parts = {part for part in candidate_parts if re.fullmatch(r"\d+_[a-z0-9]+", part)}
        shared_role_parts = sorted(source_role_parts & candidate_role_parts)
        if shared_role_parts:
            score += 18 * len(shared_role_parts)
            reasons.append("same role " + ", ".join(shared_role_parts[:2]))
    if "/model/" in candidate_path_text or "/modeldata/" in candidate_path_text:
        score += 8
    candidate_extension = str(getattr(candidate, "extension", "") or "")
    if candidate_extension == ".pac":
        score += 8
    elif candidate_extension in {".pam", ".pamlod"}:
        score += 5
    if score <= 0 and not raw_filter_terms:
        return -1, ""
    if not reasons:
        reasons.append("model entry")
    return score, "; ".join(reasons[:4])


def hkx_related_model_candidate_rows(
    source_entry: object,
    candidate_pool: Sequence[object],
    filter_text: str = "",
    limit: int = 200,
) -> List[Tuple[int, str, object]]:
    candidates = tuple(candidate_pool or ())
    if not str(filter_text or "").strip() and len(candidates) > 900:
        source_path_text = str(getattr(source_entry, "path", "") or "").replace("\\", "/").strip().casefold()
        source_stem = PurePosixPath(source_path_text).stem
        fast_tokens = _related_model_tokens(
            source_path_text.replace("/", " "),
            _RELATED_MODEL_FAST_STOP_TOKENS,
            min_length=3,
        )
        narrowed_pool = tuple(
            candidate
            for candidate in candidates
            if (
                getattr(candidate, "pamt_path", None) == getattr(source_entry, "pamt_path", None)
                or (source_stem and source_stem in str(getattr(candidate, "path", "") or "").replace("\\", "/").casefold())
                or any(token in str(getattr(candidate, "path", "") or "").replace("\\", "/").casefold() for token in fast_tokens)
            )
        )
        if narrowed_pool:
            candidates = narrowed_pool
    rows: List[Tuple[int, str, object]] = []
    for candidate in candidates:
        score, reason = score_hkx_related_model_entry(source_entry, candidate, filter_text)
        if score >= 0:
            rows.append((score, reason, candidate))
    rows.sort(
        key=lambda row: (
            row[0],
            str(getattr(row[2], "extension", "") or "") == ".pac",
            -len(str(getattr(row[2], "path", "") or "")),
            str(getattr(row[2], "path", "") or "").casefold(),
        ),
        reverse=True,
    )
    return rows[: max(1, int(limit))]


__all__ = ["hkx_related_model_candidate_rows", "score_hkx_related_model_entry"]
