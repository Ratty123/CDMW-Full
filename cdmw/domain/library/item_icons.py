"""Immutable item-icon records, specifications, and selection policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence


ITEM_ICON_SOURCE_EXTENSIONS = {
    ".bmp",
    ".dds",
    ".jpeg",
    ".jpg",
    ".png",
    ".tga",
    ".tif",
    ".tiff",
    ".webp",
}
ITEM_ICON_BACKGROUND_MODES = {"auto_transparent", "keep_source", "target_underlay"}
ITEM_ICON_DEFAULT_BACKGROUND_MODE = "auto_transparent"


@dataclass(frozen=True, slots=True)
class ItemIconSourceCandidate:
    path: Path
    score: int
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ItemIconOverrideSpec:
    source_path: Path
    target_entry: object
    target_path: str
    source_mode: str
    fit_mode: str = "fit_pad"
    background_mode: str = ITEM_ICON_DEFAULT_BACKGROUND_MODE


@dataclass(frozen=True, slots=True)
class ItemIconBuildResult:
    payload_data: bytes
    target_path: str
    source_path: Path
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    target_format: str
    target_mip_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ItemIconLooseModPatchResult:
    source_root: Path
    output_root: Path
    icon_path: Path
    manifest_path: Optional[Path] = None
    zip_path: Optional[Path] = None
    copied_file_count: int = 0
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ItemIconLibraryRecord:
    path: Path
    root_path: Path
    relative_path: str
    file_size: int
    mtime_ns: int
    width: int = 0
    height: int = 0
    tags: tuple[str, ...] = ()
    notes: str = ""
    favorite: bool = False
    source_kind: str = "folder"
    warning: str = ""


@dataclass(frozen=True, slots=True)
class ItemIconTemplateInfo:
    width: int
    height: int
    target_format: str
    mip_count: int
    suffix: str


@dataclass(frozen=True, slots=True)
class ItemIconPreparedImageResult:
    source_width: int
    source_height: int
    output_path: Path
    background_mode: str
    warnings: tuple[str, ...] = ()


def normalize_item_icon_background_mode(value: object) -> str:
    mode = str(value or "").strip().casefold()
    return mode if mode in ITEM_ICON_BACKGROUND_MODES else ITEM_ICON_DEFAULT_BACKGROUND_MODE


def _icon_match_stem(value: object) -> str:
    stem = PurePosixPath(str(value or "").replace("\\", "/")).stem.casefold().strip()
    for prefix in ("itemicon_prefab_", "itemicon_", "icon_prefab_", "icon_"):
        if stem.startswith(prefix):
            return stem[len(prefix) :].strip("_")
    return stem


def _tokens(value: object) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()) if len(token) >= 2}


def score_item_icon_source_candidate(
    path: Path,
    *,
    target_path: str,
    related_stems: Sequence[str] = (),
    display_name: str = "",
) -> ItemIconSourceCandidate:
    candidate_stem = _icon_match_stem(path.name)
    target_stem = _icon_match_stem(target_path)
    related = tuple(dict.fromkeys(_icon_match_stem(stem) for stem in related_stems if _icon_match_stem(stem)))
    reasons: list[str] = []
    score = 0
    if candidate_stem and target_stem and candidate_stem == target_stem:
        score += 240
        reasons.append("exact target icon stem")
    elif candidate_stem and target_stem and (candidate_stem in target_stem or target_stem in candidate_stem):
        score += 150
        reasons.append("target icon stem contains match")
    for related_stem in related:
        if candidate_stem == related_stem:
            score += 210
            reasons.append("exact related model stem")
            break
        if candidate_stem and related_stem and (candidate_stem in related_stem or related_stem in candidate_stem):
            score += 120
            reasons.append("related model stem contains match")
            break
    target_tokens = _tokens(target_stem) | set().union(*(_tokens(stem) for stem in related)) | _tokens(display_name)
    candidate_tokens = _tokens(candidate_stem)
    overlap = candidate_tokens & target_tokens
    if overlap:
        score += min(90, len(overlap) * 18)
        reasons.append("token overlap: " + ", ".join(sorted(overlap)[:5]))
    if any(token in candidate_tokens for token in {"icon", "itemicon", "inventory", "ui"}):
        score += 20
        reasons.append("icon filename hint")
    return ItemIconSourceCandidate(path=path, score=score, reason="; ".join(reasons) or "weak filename match")


def select_item_icon_source_candidate(
    candidates: Sequence[ItemIconSourceCandidate],
) -> tuple[Optional[ItemIconSourceCandidate], tuple[ItemIconSourceCandidate, ...], str]:
    ranked = tuple(sorted(candidates, key=lambda candidate: (-candidate.score, candidate.path.as_posix().casefold())))
    if not ranked:
        return None, (), "No supported icon source image matched the selected target icon."
    if len(ranked) == 1:
        return ranked[0], ranked, ranked[0].reason
    if ranked[0].score == ranked[1].score:
        return None, ranked, "Icon source folder match is ambiguous; choose an explicit image file."
    return ranked[0], ranked, ranked[0].reason


__all__ = [
    "ITEM_ICON_BACKGROUND_MODES",
    "ITEM_ICON_DEFAULT_BACKGROUND_MODE",
    "ITEM_ICON_SOURCE_EXTENSIONS",
    "ItemIconBuildResult",
    "ItemIconLibraryRecord",
    "ItemIconLooseModPatchResult",
    "ItemIconOverrideSpec",
    "ItemIconPreparedImageResult",
    "ItemIconSourceCandidate",
    "ItemIconTemplateInfo",
    "normalize_item_icon_background_mode",
    "score_item_icon_source_candidate",
    "select_item_icon_source_candidate",
]
