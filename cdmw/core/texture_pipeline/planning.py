from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

try:
    from PIL import Image as PilImage
except Exception:  # pragma: no cover - optional preview helper
    PilImage = None  # type: ignore[assignment]

from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_preview_png
from cdmw.core.common import raise_if_cancelled
from cdmw.core.upscale_profiles import (
    TexturePreviewSample,
    TextureUpscaleDecision,
    classify_texture_type,
    derive_texture_group_key,
    normalize_texture_reference_for_sidecar_lookup,
    parse_texture_sidecar_bindings,
    suggest_texture_upscale_decision,
)
from cdmw.domain.textures.plan import _build_backend_capability_matrix, _build_texture_processing_plan_entry
from cdmw.domain.textures.rules import find_matching_texture_rule
from cdmw.models import BackendCapabilityMatrix, NormalizedConfig, TextureProcessingPlan

_LOOSE_SEMANTIC_SIDECAR_EXTENSIONS = {
    ".xml",
    ".pami",
    ".material",
    ".shader",
    ".json",
    ".lua",
    ".txt",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
}
_LOOSE_SIDECAR_TEXT_LIMIT = 196_608


def build_single_texture_processing_plan(
    normalized: NormalizedConfig,
    dds_path: Path,
    *,
    relative_path: Optional[Path] = None,
    decision: Optional[TextureUpscaleDecision] = None,
    backend_matrix: Optional[BackendCapabilityMatrix] = None,
) -> TextureProcessingPlan:
    resolved_relative = relative_path or dds_path.relative_to(normalized.original_dds_root)
    dds_info = parse_dds(dds_path)
    resolved_decision = decision or suggest_texture_upscale_decision(
        resolved_relative.as_posix(),
        preset=normalized.upscale_texture_preset,
        original_dds_format=dds_info.dds_format,
        has_alpha=dds_info.has_alpha,
        enable_automatic_rules=normalized.enable_automatic_texture_rules,
    )
    rule = find_matching_texture_rule(resolved_relative, normalized.texture_rules)
    resolved_backend_matrix = backend_matrix or _build_backend_capability_matrix(normalized)
    return _build_texture_processing_plan_entry(
        normalized,
        dds_path,
        resolved_relative,
        dds_info,
        resolved_decision,
        rule,
        resolved_backend_matrix,
    )


def _read_loose_sidecar_text(path: Path, *, stop_event: Optional[object] = None) -> str:
    try:
        raise_if_cancelled(stop_event)
        with path.open("rb") as handle:
            raw = handle.read(_LOOSE_SIDECAR_TEXT_LIMIT + 1)
        raise_if_cancelled(stop_event)
    except OSError:
        return ""
    if not raw:
        return ""
    if len(raw) > _LOOSE_SIDECAR_TEXT_LIMIT:
        raw = raw[:_LOOSE_SIDECAR_TEXT_LIMIT]
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return raw.decode(encoding, errors="ignore")
        except Exception:
            continue
    return ""


def _build_loose_sidecar_index(
    root: Path,
    *,
    stop_event: Optional[object] = None,
) -> Tuple[
    Dict[str, List[Path]],
    Dict[str, List[Path]],
    Dict[str, List[Path]],
    Dict[str, List[Path]],
    Dict[Path, str],
]:
    by_group: Dict[str, List[Path]] = defaultdict(list)
    by_folder: Dict[str, List[Path]] = defaultdict(list)
    by_texture_path: Dict[str, List[Path]] = defaultdict(list)
    by_texture_basename: Dict[str, List[Path]] = defaultdict(list)
    text_cache: Dict[Path, str] = {}
    if not root.exists() or not root.is_dir():
        return {}, {}, {}, {}, {}
    for path in root.rglob("*"):
        raise_if_cancelled(stop_event)
        if not path.is_file() or path.suffix.lower() not in _LOOSE_SEMANTIC_SIDECAR_EXTENSIONS:
            continue
        try:
            rel_text = path.relative_to(root).as_posix()
        except Exception:
            continue
        by_group[derive_texture_group_key(rel_text)].append(path)
        by_folder[str(path.relative_to(root).parent).replace("\\", "/")].append(path)
        text = _read_loose_sidecar_text(path, stop_event=stop_event)
        text_cache[path] = text
        if text and path.suffix.lower() in {".xml", ".pami"}:
            for binding in parse_texture_sidecar_bindings(text, sidecar_path=rel_text):
                normalized_texture = normalize_texture_reference_for_sidecar_lookup(binding.texture_path)
                if not normalized_texture:
                    continue
                by_texture_path[normalized_texture].append(path)
                texture_basename = PurePosixPath(normalized_texture).name
                if texture_basename:
                    by_texture_basename[texture_basename].append(path)
    return dict(by_group), dict(by_folder), dict(by_texture_path), dict(by_texture_basename), text_cache


def _collect_loose_sidecar_texts(
    root: Path,
    relative_path: Path,
    *,
    sidecars_by_group: Dict[str, List[Path]],
    sidecars_by_folder: Dict[str, List[Path]],
    sidecars_by_texture_path: Dict[str, List[Path]],
    sidecars_by_texture_basename: Dict[str, List[Path]],
    text_cache: Dict[Path, str],
    limit: int = 6,
    stop_event: Optional[object] = None,
) -> List[str]:
    raise_if_cancelled(stop_event)
    rel_text = relative_path.as_posix()
    group_key = derive_texture_group_key(rel_text)
    folder_key = str(relative_path.parent).replace("\\", "/")
    normalized_target = normalize_texture_reference_for_sidecar_lookup(rel_text)
    target_basename = PurePosixPath(normalized_target).name
    candidates: List[Tuple[Path, bool]] = []
    seen: set[Path] = set()

    def add_candidate(path: Path, *, exact_match: bool) -> None:
        if path not in seen:
            seen.add(path)
            candidates.append((path, exact_match))

    for path in sidecars_by_texture_path.get(normalized_target, []):
        add_candidate(path, exact_match=True)
    for path in sidecars_by_texture_basename.get(target_basename, []):
        add_candidate(path, exact_match=True)
    for path in sidecars_by_group.get(group_key, []):
        add_candidate(path, exact_match=False)
    for path in sidecars_by_folder.get(folder_key, []):
        add_candidate(path, exact_match=False)

    snippets: List[str] = []
    target_name = relative_path.name.lower()
    target_stem = relative_path.stem.lower()
    for path, exact_match in candidates[:limit]:
        raise_if_cancelled(stop_event)
        text = text_cache.get(path)
        if text is None:
            text = _read_loose_sidecar_text(path, stop_event=stop_event)
            text_cache[path] = text
        lowered = text.lower()
        if lowered and (
            exact_match
            or target_name in lowered
            or target_stem in lowered
            or derive_texture_group_key(path.relative_to(root).as_posix()).lower() == group_key.lower()
        ):
            snippets.append(text)
    return snippets


def _collect_texture_preview_sample(image_path: Path) -> Optional[TexturePreviewSample]:
    if PilImage is None:
        return None
    try:
        image_module = cast(Any, PilImage)
        with image_module.open(image_path) as image_handle:
            image = cast(Any, image_handle)
            working = image.convert("RGBA")
            resampling = getattr(getattr(image_module, "Resampling", image_module), "BICUBIC", getattr(image_module, "BICUBIC", 3))
            if max(working.size) > 64:
                working.thumbnail((64, 64), resampling)
            pixels = cast(List[Tuple[int, int, int, int]], list(working.getdata()))
    except Exception:
        return None

    if not pixels:
        return None

    sample_count = len(pixels)
    sum_r = sum_g = sum_b = sum_a = 0.0
    sum_luma = 0.0
    sum_chroma = 0.0
    min_luma = 255.0
    max_luma = 0.0
    opaque_count = 0
    transparent_count = 0

    for r, g, b, a in pixels:
        luma = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
        chroma = float(max(r, g, b) - min(r, g, b))
        sum_r += r
        sum_g += g
        sum_b += b
        sum_a += a
        sum_luma += luma
        sum_chroma += chroma
        min_luma = min(min_luma, luma)
        max_luma = max(max_luma, luma)
        if a >= 250:
            opaque_count += 1
        if a <= 5:
            transparent_count += 1

    return TexturePreviewSample(
        mean_r=sum_r / sample_count,
        mean_g=sum_g / sample_count,
        mean_b=sum_b / sample_count,
        mean_a=sum_a / sample_count,
        luma_mean=sum_luma / sample_count,
        luma_range=max_luma - min_luma,
        mean_chroma=sum_chroma / sample_count,
        opaque_fraction=opaque_count / sample_count,
        transparent_fraction=transparent_count / sample_count,
    )


def _preview_sample_for_unknown_dds(dds_path: Path, texture_type: str) -> Optional[TexturePreviewSample]:
    if texture_type != "unknown":
        return None
    try:
        preview_path = ensure_dds_preview_png(dds_path)
    except Exception:
        return None
    return _collect_texture_preview_sample(preview_path)


def build_texture_processing_plan(
    normalized: NormalizedConfig,
    dds_files: Sequence[Path],
    *,
    backend_matrix: Optional[BackendCapabilityMatrix] = None,
) -> List[TextureProcessingPlan]:
    resolved_backend_matrix = backend_matrix or _build_backend_capability_matrix(normalized)
    (
        sidecars_by_group,
        sidecars_by_folder,
        sidecars_by_texture_path,
        sidecars_by_texture_basename,
        sidecar_text_cache,
    ) = _build_loose_sidecar_index(normalized.original_dds_root)
    family_members_by_group: Dict[str, List[str]] = defaultdict(list)
    for dds_path in dds_files:
        rel_text = dds_path.relative_to(normalized.original_dds_root).as_posix()
        family_members_by_group[derive_texture_group_key(rel_text)].append(rel_text)
    plan: List[TextureProcessingPlan] = []
    for dds_path in dds_files:
        rel_path = dds_path.relative_to(normalized.original_dds_root)
        rel_display = rel_path.as_posix()
        family_members = tuple(family_members_by_group.get(derive_texture_group_key(rel_display), ()))
        coarse_texture_type = classify_texture_type(rel_display)
        dds_info = parse_dds(dds_path)
        sidecar_texts = _collect_loose_sidecar_texts(
            normalized.original_dds_root,
            rel_path,
            sidecars_by_group=sidecars_by_group,
            sidecars_by_folder=sidecars_by_folder,
            sidecars_by_texture_path=sidecars_by_texture_path,
            sidecars_by_texture_basename=sidecars_by_texture_basename,
            text_cache=sidecar_text_cache,
        )
        preview_sample = _preview_sample_for_unknown_dds(dds_path, coarse_texture_type)
        decision = suggest_texture_upscale_decision(
            rel_display,
            preset=normalized.upscale_texture_preset,
            original_dds_format=dds_info.dds_format,
            has_alpha=dds_info.has_alpha,
            sidecar_texts=sidecar_texts,
            enable_automatic_rules=normalized.enable_automatic_texture_rules,
            family_members=family_members,
            preview_sample=preview_sample,
        )
        rule = find_matching_texture_rule(rel_path, normalized.texture_rules)
        plan.append(
            _build_texture_processing_plan_entry(
                normalized,
                dds_path,
                rel_path,
                dds_info,
                decision,
                rule,
                resolved_backend_matrix,
            )
        )
    return plan
