from __future__ import annotations

import re
import shutil
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.archive_media_preview import (
    build_loose_archive_preview_assets,
    ensure_archive_preview_source,
)
from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.core.mod_package import normalize_mod_package_payload_path
from cdmw.core.replace_assistant_package import publish_replace_assistant_packages
from cdmw.core.texture_pipeline.planning import (
    _build_loose_sidecar_index,
    _collect_loose_sidecar_texts,
)
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.core.texture_pipeline.inspection import parse_dds, read_png_dimensions
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.texture_native import encode_dds_with_directxtex
from cdmw.core.realesrgan_ncnn import (
    build_realesrgan_ncnn_command,
    parse_realesrgan_ncnn_extra_args,
    resolve_ncnn_model_dir,
)
from cdmw.core.upscale_postprocess import (
    apply_post_upscale_color_correction,
    build_source_match_plan_for_path,
)
from cdmw.core.upscale_profiles import build_ncnn_retry_tile_candidates
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    MatchedOriginalTexture,
    ModPackageInfo,
    ReplaceAssistantBuildOptions,
    ReplaceAssistantBuildSummary,
    ReplaceAssistantItem,
    ReplaceAssistantReviewItem,
    RunCancelled,
)


@dataclass(slots=True)
class ReplaceAssistantArchiveIndex:
    entries_by_relative_path: Dict[str, ArchiveEntry]
    entries_by_package_relative_path: Dict[str, ArchiveEntry]
    entries_by_basename: Dict[str, List[ArchiveEntry]]
    local_by_package_relative_path: Dict[str, Path]
    local_by_relative_path: Dict[str, List[Path]]
    local_by_basename: Dict[str, List[Path]]
    package_roots: Tuple[str, ...]
    original_dds_root: Optional[Path]


_PACKAGE_ROOT_RE = re.compile(r"^\d{4}$")
_KNOWN_CONTENT_ROOTS = {
    "character",
    "effect",
    "leveldata",
    "object",
    "tree",
    "ui",
    "vehicle",
    "world",
}
def build_replace_assistant_archive_index(
    entries: Sequence[ArchiveEntry],
    *,
    original_dds_root: Optional[Path] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> ReplaceAssistantArchiveIndex:
    relative_index: Dict[str, ArchiveEntry] = {}
    package_relative_index: Dict[str, ArchiveEntry] = {}
    basename_index: Dict[str, List[ArchiveEntry]] = defaultdict(list)
    package_roots: List[str] = []
    local_by_package_relative_path: Dict[str, Path] = {}
    local_by_relative_path: Dict[str, List[Path]] = defaultdict(list)
    local_by_basename: Dict[str, List[Path]] = defaultdict(list)

    total_entries = len(entries)
    if on_progress is not None and total_entries:
        on_progress(0, total_entries, f"Indexing archive entries 0 / {total_entries}...")
    for index, entry in enumerate(entries, start=1):
        rel_key = PurePosixPath(entry.path.replace("\\", "/")).as_posix().lower()
        relative_index[rel_key] = entry
        package_root = entry.pamt_path.parent.name.strip() or "package"
        package_key = f"{package_root}/{rel_key}"
        package_relative_index[package_key] = entry
        basename_index[entry.basename.lower()].append(entry)
        if package_root not in package_roots:
            package_roots.append(package_root)
        if on_progress is not None and total_entries and (index == total_entries or index % 5000 == 0):
            on_progress(index, total_entries, f"Indexing archive entries {index} / {total_entries}...")

    for candidates in basename_index.values():
        candidates.sort(key=lambda item: (item.path.lower(), item.package_label.lower()))

    resolved_original_root: Optional[Path] = None
    if original_dds_root is not None:
        candidate_root = original_dds_root.expanduser()
        if candidate_root.exists() and candidate_root.is_dir():
            resolved_original_root = candidate_root.resolve()
            if on_progress is not None:
                on_progress(total_entries, total_entries, "Scanning Original DDS root for local matches...")
            for dds_path in resolved_original_root.rglob("*.dds"):
                if not dds_path.is_file():
                    continue
                resolved_dds = dds_path.resolve()
                relative = resolved_dds.relative_to(resolved_original_root)
                relative_text = PurePosixPath(relative.as_posix()).as_posix().lower()
                local_by_package_relative_path[relative_text] = resolved_dds
                relative_without_package = _strip_package_prefix(relative_text)
                local_by_relative_path[relative_without_package].append(resolved_dds)
                local_by_basename[resolved_dds.name.lower()].append(resolved_dds)

    for candidates in local_by_basename.values():
        candidates.sort(key=lambda path: str(path).lower())
    for candidates in local_by_relative_path.values():
        candidates.sort(key=lambda path: str(path).lower())

    package_roots.sort(key=str.lower)
    return ReplaceAssistantArchiveIndex(
        entries_by_relative_path=relative_index,
        entries_by_package_relative_path=package_relative_index,
        entries_by_basename=basename_index,
        local_by_package_relative_path=local_by_package_relative_path,
        local_by_relative_path=local_by_relative_path,
        local_by_basename=local_by_basename,
        package_roots=tuple(package_roots),
        original_dds_root=resolved_original_root,
    )


def _normalize_source_path_text(path: Path) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix().strip().strip("/")


def _strip_package_prefix(path_text: str) -> str:
    normalized = PurePosixPath(path_text.replace("\\", "/")).as_posix().strip("/")
    parts = [part for part in PurePosixPath(normalized).parts if part]
    if parts and _PACKAGE_ROOT_RE.fullmatch(parts[0]):
        parts = parts[1:]
    return PurePosixPath(*parts).as_posix().lower()


def _infer_loose_relative_path(path_value: Path, original_dds_root: Optional[Path]) -> Optional[Path]:
    resolved = path_value.expanduser().resolve()
    if original_dds_root is not None:
        try:
            relative = resolved.relative_to(original_dds_root)
            if relative.parts and _PACKAGE_ROOT_RE.fullmatch(relative.parts[0]):
                return relative
        except Exception:
            pass
    for index, part in enumerate(resolved.parts):
        if _PACKAGE_ROOT_RE.fullmatch(part):
            tail = resolved.parts[index:]
            if len(tail) >= 2:
                return Path(*tail)
    return None


def _package_root_from_loose_relative(loose_relative: Optional[Path]) -> str:
    if loose_relative is None or not loose_relative.parts:
        return ""
    first = loose_relative.parts[0]
    return first if _PACKAGE_ROOT_RE.fullmatch(first) else ""


def _candidate_relative_keys(
    source_path: Path,
    package_roots: Sequence[str],
    original_dds_root: Optional[Path] = None,
) -> List[str]:
    candidates: List[str] = []
    normalized = _normalize_source_path_text(source_path)
    if normalized:
        candidates.append(normalized.lower())
    if original_dds_root is not None:
        try:
            relative = source_path.expanduser().resolve().relative_to(original_dds_root.expanduser().resolve())
            rel_text = PurePosixPath(relative.as_posix()).as_posix().lower()
            if rel_text:
                candidates.append(rel_text)
        except Exception:
            pass

    parts = [part for part in source_path.parts if part not in {"", ".", ".."}]
    lowered_parts = [part.lower() for part in parts]
    for index, part in enumerate(lowered_parts):
        if part in {package.lower() for package in package_roots}:
            rel = PurePosixPath(*parts[index + 1 :]).as_posix().lower()
            if rel:
                candidates.append(rel)
            if rel:
                candidates.append(f"{part}/{rel}")
    for index, part in enumerate(lowered_parts):
        if part not in _KNOWN_CONTENT_ROOTS:
            continue
        rel = PurePosixPath(*parts[index:]).as_posix().lower()
        if rel:
            candidates.append(rel)
    basename_candidate = (
        source_path.name.lower()
        if source_path.suffix.lower() == ".dds"
        else source_path.with_suffix(".dds").name.lower()
    )
    if basename_candidate:
        candidates.append(basename_candidate)

    normalized_candidates: List[str] = []
    for candidate in candidates:
        normalized_candidate = str(candidate or "").strip().lower()
        if not normalized_candidate:
            continue
        normalized_candidates.append(normalized_candidate)
        if source_path.suffix.lower() != ".dds":
            try:
                candidate_path = PurePosixPath(normalized_candidate)
                if candidate_path.suffix:
                    normalized_candidates.append(candidate_path.with_suffix(".dds").as_posix().lower())
            except Exception:
                pass
    return [candidate for candidate in dict.fromkeys(normalized_candidates) if candidate]


def match_replace_assistant_original(
    source_path: Path,
    archive_index: ReplaceAssistantArchiveIndex,
) -> MatchedOriginalTexture:
    resolved_source = source_path.expanduser().resolve()
    package_root = ""
    archive_relative_path = ""
    original_dds_path: Optional[Path] = None
    archive_entry: Optional[ArchiveEntry] = None
    match_reason = ""

    for candidate in _candidate_relative_keys(resolved_source, archive_index.package_roots, archive_index.original_dds_root):
        local_match = archive_index.local_by_package_relative_path.get(candidate)
        if local_match is not None and local_match != resolved_source:
            loose_relative = _infer_loose_relative_path(local_match, archive_index.original_dds_root)
            package_root = _package_root_from_loose_relative(loose_relative)
            archive_relative_path = _strip_package_prefix(candidate)
            original_dds_path = local_match
            match_reason = f"matched package-prefixed local path: {candidate}"
            break
        if candidate in archive_index.entries_by_package_relative_path:
            archive_entry = archive_index.entries_by_package_relative_path[candidate]
            package_root = archive_entry.pamt_path.parent.name.strip() or "package"
            archive_relative_path = PurePosixPath(archive_entry.path).as_posix()
            match_reason = f"matched package-prefixed relative path: {candidate}"
            break
        local_relative_matches = [
            path
            for path in archive_index.local_by_relative_path.get(_strip_package_prefix(candidate), [])
            if path != resolved_source
        ]
        if len(local_relative_matches) == 1:
            original_dds_path = local_relative_matches[0]
            loose_relative = _infer_loose_relative_path(original_dds_path, archive_index.original_dds_root)
            package_root = _package_root_from_loose_relative(loose_relative)
            archive_relative_path = _strip_package_prefix(candidate)
            match_reason = f"matched local relative path: {archive_relative_path}"
            break
        if candidate in archive_index.entries_by_relative_path:
            archive_entry = archive_index.entries_by_relative_path[candidate]
            package_root = archive_entry.pamt_path.parent.name.strip() or "package"
            archive_relative_path = PurePosixPath(archive_entry.path).as_posix()
            match_reason = f"matched relative path: {candidate}"
            break

    basename_candidates = [resolved_source.name.lower()]
    if resolved_source.suffix.lower() != ".dds":
        basename_candidates.append(resolved_source.with_suffix(".dds").name.lower())
    basename_candidates = list(dict.fromkeys(basename_candidates))

    if archive_entry is None and original_dds_path is None:
        for basename in basename_candidates:
            local_basename_matches = [
                path for path in archive_index.local_by_basename.get(basename, []) if path != resolved_source
            ]
            if len(local_basename_matches) == 1:
                original_dds_path = local_basename_matches[0]
                loose_relative = _infer_loose_relative_path(original_dds_path, archive_index.original_dds_root)
                package_root = _package_root_from_loose_relative(loose_relative)
                archive_relative_path = _strip_package_prefix(loose_relative.as_posix()) if loose_relative is not None else basename
                match_reason = "unique local basename fallback"
                break
            if len(local_basename_matches) > 1:
                match_reason = f"ambiguous local basename fallback ({len(local_basename_matches)} matches)"
                break

    if archive_entry is None and original_dds_path is None:
        for basename in basename_candidates:
            basename_matches = archive_index.entries_by_basename.get(basename, [])
            if len(basename_matches) == 1:
                archive_entry = basename_matches[0]
                package_root = archive_entry.pamt_path.parent.name.strip() or "package"
                archive_relative_path = PurePosixPath(archive_entry.path).as_posix()
                match_reason = "unique basename fallback"
                break
            if len(basename_matches) > 1:
                package_root = basename_matches[0].pamt_path.parent.name.strip() or "package"
                archive_relative_path = PurePosixPath(basename_matches[0].path).as_posix()
                match_reason = f"ambiguous basename fallback ({len(basename_matches)} matches)"
                break
        else:
            match_reason = "unmatched"

    if archive_entry is not None:
        if archive_index.original_dds_root is not None:
            local_key = f"{package_root}/{archive_relative_path}".lower()
            candidate = archive_index.local_by_package_relative_path.get(local_key)
            if candidate is not None and candidate != resolved_source and candidate.exists():
                original_dds_path = candidate

    if archive_entry is None and original_dds_path is None:
        package_root = ""
        archive_relative_path = ""
        match_reason = (
            f"{match_reason}; Choose Archive Original."
            if match_reason.startswith("ambiguous")
            else "Choose Archive Original."
        )

    return MatchedOriginalTexture(
        package_root=package_root,
        archive_relative_path=archive_relative_path,
        loose_relative_path=Path(package_root) / Path(PurePosixPath(archive_relative_path))
        if package_root
        else Path(PurePosixPath(archive_relative_path)),
        original_dds_path=original_dds_path,
        archive_entry=archive_entry,
        match_reason=match_reason,
    )


def collect_replace_assistant_imports(paths: Sequence[Path | str]) -> List[Path]:
    discovered: List[Path] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = Path(raw).expanduser()
        if not candidate.exists():
            continue
        if candidate.is_dir():
            files = sorted(
                path
                for path in candidate.rglob("*")
                if path.is_file() and path.suffix.lower() in {".png", ".dds"}
            )
        else:
            files = [candidate] if candidate.suffix.lower() in {".png", ".dds"} else []
        for file_path in files:
            resolved = file_path.resolve()
            lowered = str(resolved).lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            discovered.append(resolved)
    return discovered


def build_replace_assistant_items(
    imported_paths: Sequence[Path | str],
    *,
    archive_entries: Sequence[ArchiveEntry] = (),
    original_dds_root: Optional[Path] = None,
    archive_index: Optional[ReplaceAssistantArchiveIndex] = None,
    on_stage: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    perform_matching: bool = True,
) -> List[ReplaceAssistantItem]:
    if on_stage is not None:
        on_stage("Scanning selected files...")
    discovered_paths = collect_replace_assistant_imports(imported_paths)
    if not perform_matching:
        items: List[ReplaceAssistantItem] = []
        total = len(discovered_paths)
        if on_stage is not None:
            on_stage("Queuing imported files...")
        if on_progress is not None and total:
            on_progress(0, total, f"Queued 0 / {total} imported file(s)...")
        for index, source_path in enumerate(discovered_paths, start=1):
            items.append(
                ReplaceAssistantItem(
                    source_path=source_path,
                    source_kind=source_path.suffix.lower().lstrip("."),
                    status="pending",
                    status_detail="ready to auto-match",
                )
            )
            if on_progress is not None and total:
                on_progress(index, total, f"Queued {index} / {total} imported file(s)...")
        return items
    active_index = archive_index or build_replace_assistant_archive_index(
        archive_entries,
        original_dds_root=original_dds_root,
    )
    if on_stage is not None:
        on_stage("Matching imported files to original DDS entries...")
    items: List[ReplaceAssistantItem] = []
    total = len(discovered_paths)
    if on_progress is not None and total:
        on_progress(0, total, f"Matching 0 / {total} imported file(s)...")
    for index, source_path in enumerate(discovered_paths, start=1):
        matched = match_replace_assistant_original(source_path, active_index)
        items.append(
            ReplaceAssistantItem(
                source_path=source_path,
                source_kind=source_path.suffix.lower().lstrip("."),
                detected_relative_path=matched.archive_relative_path,
                detected_package_root=matched.package_root,
                matched_original=matched if matched.archive_entry is not None or matched.original_dds_path is not None else None,
                warning=matched.match_reason if matched.match_reason.startswith("ambiguous") else "",
                status="matched" if matched.archive_entry is not None or matched.original_dds_path is not None else "unresolved",
                status_detail=matched.match_reason or "unmatched",
            )
        )
        if on_progress is not None and total:
            on_progress(index, total, f"Matching {index} / {total} imported file(s)...")
    return items


def match_replace_assistant_item_to_local_original(
    item: ReplaceAssistantItem,
    original_dds_path: Path,
    *,
    original_dds_root: Optional[Path] = None,
) -> None:
    resolved = original_dds_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file() or resolved.suffix.lower() != ".dds":
        raise ValueError("Choose a valid original DDS file.")
    loose_relative_path = _infer_loose_relative_path(resolved, original_dds_root)
    if loose_relative_path is None:
        raise ValueError(
            "Could not infer a package-prefixed loose DDS path from the selected original. "
            "Choose a file inside Original DDS root or with a path like 0009/character/texture/..."
        )
    package_root = _package_root_from_loose_relative(loose_relative_path)
    archive_relative_path = _strip_package_prefix(loose_relative_path.as_posix())
    item.detected_package_root = package_root
    item.detected_relative_path = archive_relative_path
    item.matched_original = MatchedOriginalTexture(
        package_root=package_root,
        archive_relative_path=archive_relative_path,
        loose_relative_path=loose_relative_path,
        original_dds_path=resolved,
        archive_entry=None,
        match_reason="manual local original",
    )
    item.warning = ""
    item.status = "matched"
    item.status_detail = "manual local original"


def match_replace_assistant_item_to_archive_entry(
    item: ReplaceAssistantItem,
    entry: ArchiveEntry,
) -> None:
    package_root = entry.pamt_path.parent.name.strip() or "package"
    archive_relative_path = PurePosixPath(entry.path.replace("\\", "/")).as_posix()
    item.detected_package_root = package_root
    item.detected_relative_path = archive_relative_path
    item.matched_original = MatchedOriginalTexture(
        package_root=package_root,
        archive_relative_path=archive_relative_path,
        loose_relative_path=Path(package_root) / Path(PurePosixPath(archive_relative_path)),
        original_dds_path=None,
        archive_entry=entry,
        match_reason="manual archive original",
    )
    item.warning = ""
    item.status = "matched"
    item.status_detail = "manual archive original"


def build_replace_assistant_preview_assets(
    source_path: Path,
) -> Tuple[str, str, str]:
    resolved_source = source_path.expanduser().resolve()
    suffix = resolved_source.suffix.lower()
    if suffix == ".dds":
        return build_loose_archive_preview_assets(resolved_source)
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tga"}:
        return str(resolved_source), f"Edited image | {resolved_source.name}", f"Edited image preview from: {resolved_source}"
    return "", f"Edited file | {resolved_source.name}", f"Edited file preview from: {resolved_source}\nThis file type cannot be previewed as an image."


def _normalize_edited_dds_to_png(
    source_path: Path,
    scratch_root: Path,
    *,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    output_dir = scratch_root / "dds_source_png"
    output_dir.mkdir(parents=True, exist_ok=True)
    if on_log:
        on_log(f"Normalizing edited DDS to PNG with DirectXTex/native path: {source_path}")
    preview_path = ensure_dds_display_preview_png(
        source_path,
        dds_info=parse_dds(source_path),
        max_dimension=0,
        stop_event=stop_event,
    )
    candidate = output_dir / f"{source_path.stem}.png"
    if Path(preview_path).expanduser().resolve() != candidate.expanduser().resolve():
        shutil.copy2(preview_path, candidate)
    if not candidate.exists():
        raise ValueError(f"DDS preview backend did not create a normalized PNG for {source_path}")
    return candidate


def _prepare_processing_png(
    source_path: Path,
    *,
    source_kind: str,
    scratch_root: Path,
    target_stem: str,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    target_png = scratch_root / "normalized" / f"{target_stem}.png"
    target_png.parent.mkdir(parents=True, exist_ok=True)
    if source_kind == "dds":
        normalized_png = _normalize_edited_dds_to_png(
            source_path,
            scratch_root,
            stop_event=stop_event,
            on_log=on_log,
        )
        shutil.copy2(normalized_png, target_png)
    else:
        shutil.copy2(source_path, target_png)
    return target_png


def _apply_optional_ncnn(
    processed_png: Path,
    *,
    options: ReplaceAssistantBuildOptions,
    target_stem: str,
    scratch_root: Path,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    if options.build_mode != "upscale_then_rebuild":
        return processed_png
    if options.ncnn_exe_path is None:
        raise ValueError("NCNN upscaling was requested, but the executable path is missing.")
    resolved_model_dir = resolve_ncnn_model_dir(options.ncnn_exe_path, options.ncnn_model_dir)
    if resolved_model_dir is None:
        raise ValueError("NCNN upscaling was requested, but the model folder could not be resolved.")
    if not options.ncnn_model_name.strip():
        raise ValueError("NCNN upscaling was requested, but no model name is selected.")

    output_png = scratch_root / "upscaled" / f"{target_stem}.png"
    output_png.parent.mkdir(parents=True, exist_ok=True)
    extra_args = parse_realesrgan_ncnn_extra_args(options.ncnn_extra_args)
    retry_plan = build_ncnn_retry_tile_candidates(options.ncnn_tile_size, include_full_frame_fallback=False)
    attempt_tiles = (retry_plan.requested_tile_size, *retry_plan.candidate_tile_sizes)
    if not options.retry_smaller_tile_on_failure:
        attempt_tiles = (retry_plan.requested_tile_size,)
    last_error: Optional[Exception] = None
    for attempt_index, tile_size in enumerate(attempt_tiles, start=1):
        try:
            cmd = build_realesrgan_ncnn_command(
                options.ncnn_exe_path,
                input_path=processed_png,
                output_path=output_png,
                model_dir=resolved_model_dir,
                model_name=options.ncnn_model_name,
                scale=options.ncnn_scale,
                tile_size=tile_size,
                extra_args=extra_args,
            )
            if on_log:
                on_log(
                    f"Running Real-ESRGAN NCNN on edited texture: {processed_png.name}"
                    + (f" (attempt {attempt_index}/{len(attempt_tiles)}, tile {tile_size})" if len(attempt_tiles) > 1 else "")
                )
            run_process_with_cancellation(cmd, stop_event=stop_event)
            if not output_png.exists():
                raise ValueError(f"Real-ESRGAN NCNN did not create output PNG: {output_png}")
            break
        except Exception as exc:
            last_error = exc
            if attempt_index >= len(attempt_tiles):
                raise
            if on_log:
                on_log(f"NCNN attempt failed for {processed_png.name}: {exc}. Retrying with tile {attempt_tiles[attempt_index]}.")
    if not output_png.exists():
        if last_error is not None:
            raise last_error
        raise ValueError(f"Real-ESRGAN NCNN did not create output PNG: {output_png}")

    if options.upscale_post_correction_mode and options.upscale_post_correction_mode.lower() != "none":
        return output_png
    return output_png


def build_replace_assistant_package(
    items: Sequence[ReplaceAssistantItem],
    options: ReplaceAssistantBuildOptions,
    *,
    archive_entries: Sequence[ArchiveEntry] = (),
    original_dds_root: Optional[Path] = None,
    stop_event: Optional[threading.Event] = None,
    on_log: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_current_file: Optional[Callable[[str], None]] = None,
) -> ReplaceAssistantBuildSummary:
    raise_if_cancelled(stop_event, "Texture Replacer build cancelled by user.")
    archive_index = build_replace_assistant_archive_index(archive_entries, original_dds_root=original_dds_root)
    resolved_original_dds_root: Optional[Path] = None
    sidecars_by_group: Dict[str, List[Path]] = {}
    sidecars_by_folder: Dict[str, List[Path]] = {}
    sidecars_by_texture_path: Dict[str, List[Path]] = {}
    sidecars_by_texture_basename: Dict[str, List[Path]] = {}
    sidecar_text_cache: Dict[Path, str] = {}
    if original_dds_root is not None:
        candidate_root = original_dds_root.expanduser()
        if candidate_root.exists() and candidate_root.is_dir():
            resolved_original_dds_root = candidate_root.resolve()
            (
                sidecars_by_group,
                sidecars_by_folder,
                sidecars_by_texture_path,
                sidecars_by_texture_basename,
                sidecar_text_cache,
            ) = _build_loose_sidecar_index(resolved_original_dds_root)
    stage_root = Path(tempfile.mkdtemp(prefix="cdmw_replace_stage_"))
    scratch_root = Path(tempfile.mkdtemp(prefix="cdmw_replace_work_"))
    total_items = len(items)
    built_items = 0
    skipped_items = 0
    unresolved_items = 0
    failed_items = 0
    cancelled = False
    review_items: List[ReplaceAssistantReviewItem] = []
    try:
        raise_if_cancelled(stop_event, "Texture Replacer build cancelled by user.")
        stage_root.mkdir(parents=True, exist_ok=True)
        if on_log:
            on_log(f"Building replace package stage in {stage_root}")

        for index, item in enumerate(items, start=1):
            raise_if_cancelled(stop_event, "Texture Replacer build cancelled by user.")
            source_path = item.source_path.expanduser().resolve()
            current_file_label = source_path.name
            if on_current_file:
                on_current_file(current_file_label)
            if on_progress:
                on_progress(index - 1, total_items, f"{index - 1} / {total_items} items")

            matched = item.matched_original or match_replace_assistant_original(source_path, archive_index)
            if matched.archive_entry is None and not matched.original_dds_path:
                unresolved_items += 1
                if on_log:
                    on_log(f"[{index}/{total_items}] UNRESOLVED {source_path} -> {matched.match_reason}")
                continue

            target_original = matched.original_dds_path
            if target_original is None and matched.archive_entry is not None:
                target_original, _note = ensure_archive_preview_source(matched.archive_entry)
            if target_original is None or not target_original.exists():
                failed_items += 1
                if on_log:
                    on_log(f"[{index}/{total_items}] FAIL {source_path} -> original DDS could not be resolved")
                continue

            try:
                dds_info = parse_dds(target_original)
            except Exception as exc:
                failed_items += 1
                if on_log:
                    on_log(f"[{index}/{total_items}] FAIL {source_path} -> could not read original DDS: {exc}")
                continue

            original_rel_path = matched.archive_relative_path or target_original.name
            original_rel = PurePosixPath(original_rel_path.replace("\\", "/"))
            target_stem = original_rel.stem
            package_label = matched.package_root or (matched.archive_entry.pamt_path.parent.name if matched.archive_entry else "package")

            try:
                input_suffix = source_path.suffix.lower()
                source_kind = "dds" if input_suffix == ".dds" else "png"
                normalized_png = _prepare_processing_png(
                    source_path,
                    source_kind=source_kind,
                    scratch_root=scratch_root / f"item_{index}",
                    target_stem=target_stem,
                    stop_event=stop_event,
                    on_log=on_log,
                )
                processing_source_png = normalized_png
                processed_png = normalized_png
                if options.build_mode == "upscale_then_rebuild":
                    processed_png = _apply_optional_ncnn(
                        processing_source_png,
                        options=options,
                        target_stem=target_stem,
                        scratch_root=scratch_root / f"item_{index}",
                        stop_event=stop_event,
                        on_log=on_log,
                    )
                    if options.upscale_post_correction_mode and options.upscale_post_correction_mode.lower() != "none":
                        sidecar_texts: Sequence[str] = ()
                        if resolved_original_dds_root is not None:
                            try:
                                sidecar_texts = tuple(
                                    _collect_loose_sidecar_texts(
                                        resolved_original_dds_root,
                                        Path(package_label) / Path(original_rel),
                                        sidecars_by_group=sidecars_by_group,
                                        sidecars_by_folder=sidecars_by_folder,
                                        sidecars_by_texture_path=sidecars_by_texture_path,
                                        sidecars_by_texture_basename=sidecars_by_texture_basename,
                                        text_cache=sidecar_text_cache,
                                    )
                                )
                            except Exception:
                                sidecar_texts = ()
                        decision, correction_plan = build_source_match_plan_for_path(
                            relative_path=original_rel.as_posix(),
                            source_png_path=processing_source_png,
                            mode=options.upscale_post_correction_mode,
                            preset=options.upscale_texture_preset,
                            enable_automatic_rules=options.enable_automatic_texture_rules,
                            sidecar_texts=sidecar_texts,
                            original_dds_path=target_original,
                            direct_backend_supported=True,
                        )
                        if on_log:
                            on_log(
                                f"[{index}/{total_items}] POST {source_path.name} -> {decision.texture_type}/{decision.semantic_subtype} using {correction_plan.correction_eligibility}"
                            )
                        apply_post_upscale_color_correction(
                            processing_source_png,
                            processed_png,
                            options.upscale_post_correction_mode,
                            correction_plan=correction_plan,
                        )

                output_dir = stage_root / package_label / original_rel.parent
                output_dir.mkdir(parents=True, exist_ok=True)
                output_width, output_height = read_png_dimensions(processed_png)
                if options.size_mode == "match_original":
                    resize_width = dds_info.width
                    resize_height = dds_info.height
                    output_width = dds_info.width
                    output_height = dds_info.height
                    resize_to_dimensions = True
                else:
                    resize_width = None
                    resize_height = None
                    resize_to_dimensions = False
                mip_count = max_mips_for_size(output_width, output_height)
                if on_log:
                    mode = "UPSCALE+REBUILD" if options.build_mode == "upscale_then_rebuild" else "REBUILD"
                    on_log(
                        f"[{index}/{total_items}] {mode} {original_rel.as_posix()} -> format={dds_info.dds_format} "
                        f"mips={mip_count} output={output_width}x{output_height}"
                    )
                built_output_path = output_dir / f"{target_stem}.dds"
                native_report = encode_dds_with_directxtex(
                    processed_png,
                    built_output_path,
                    dds_format=dds_info.dds_format,
                    width=resize_width or 0,
                    height=resize_height or 0,
                    mip_count=mip_count,
                    stop_event=stop_event,
                )
                if native_report and built_output_path.exists() and built_output_path.stat().st_size > 0:
                    built_items += 1
                    if on_log:
                        on_log(f"[{index}/{total_items}] BUILT {original_rel.as_posix()} with DirectXTex native DDS encode")
                else:
                    raise RuntimeError("Native DDS encode failed.")
                if built_output_path.exists():
                    review_items.append(
                        ReplaceAssistantReviewItem(
                            source_path=source_path,
                            relative_path=Path(package_label) / Path(original_rel.as_posix()),
                            output_dds_path=built_output_path,
                            original_dds_path=target_original,
                            build_mode=options.build_mode,
                            size_mode=options.size_mode,
                        )
                    )
            except RunCancelled:
                cancelled = True
                raise
            except Exception as exc:
                failed_items += 1
                if on_log:
                    on_log(f"[{index}/{total_items}] FAIL {source_path} -> {exc}")
                continue

            if on_progress:
                on_progress(index, total_items, f"{index} / {total_items} items")

        raise_if_cancelled(stop_event, "Texture Replacer build cancelled by user.")

        if failed_items == 0 and unresolved_items == 0:
            published_packages = publish_replace_assistant_packages(
                stage_root,
                output_parent=options.package_output_root,
                package_info=options.package_info,
                export_options=options.export_options,
                create_no_encrypt_file=options.create_no_encrypt_file,
                overwrite=options.overwrite_existing_package_files,
                file_count=built_items,
                on_log=on_log,
            )
            final_package_root, final_payload_root = published_packages[0]
            return ReplaceAssistantBuildSummary(
                total_items=total_items,
                built_items=built_items,
                skipped_items=skipped_items,
                unresolved_items=unresolved_items,
                failed_items=failed_items,
                cancelled=cancelled,
                output_root=final_package_root,
                review_items=tuple(
                    ReplaceAssistantReviewItem(
                        source_path=item.source_path,
                        relative_path=item.relative_path,
                        output_dds_path=final_payload_root / Path(
                            normalize_mod_package_payload_path(item.output_dds_path.relative_to(stage_root)).as_posix()
                        ),
                        original_dds_path=item.original_dds_path,
                        build_mode=item.build_mode,
                        size_mode=item.size_mode,
                    )
                    for item in review_items
                    if item.output_dds_path.exists()
                ),
            )

        if on_log:
            on_log(
                "Replace package not written because "
                f"{unresolved_items} item(s) were unresolved and {failed_items} item(s) failed."
            )
        return ReplaceAssistantBuildSummary(
            total_items=total_items,
            built_items=built_items,
            skipped_items=skipped_items,
            unresolved_items=unresolved_items,
            failed_items=failed_items,
            cancelled=cancelled,
            output_root=None,
            review_items=(),
        )
    except RunCancelled:
        cancelled = True
        if on_log:
            on_log("Texture Replacer build cancelled by user.")
        return ReplaceAssistantBuildSummary(
            total_items=total_items,
            built_items=built_items,
            skipped_items=skipped_items,
            unresolved_items=unresolved_items,
            failed_items=failed_items,
            cancelled=True,
            output_root=None,
            review_items=(),
        )
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
        shutil.rmtree(scratch_root, ignore_errors=True)
