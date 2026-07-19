from __future__ import annotations

from importlib import import_module
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import (
    ARCHIVE_AUDIO_EXTENSIONS,
    ARCHIVE_BINARY_HEX_PREVIEW_LIMIT,
    ARCHIVE_IMAGE_EXTENSIONS,
    ARCHIVE_MODEL_EXTENSIONS,
    ARCHIVE_TEXT_EXTENSIONS,
    ARCHIVE_TEXT_PREVIEW_LIMIT,
    ARCHIVE_VIDEO_EXTENSIONS,
)
from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ArchivePreviewResult,
    DdsInfo,
    ModelPreviewData,
)
from cdmw.core.common import RunCancelled
from cdmw.core.archive_model_references import _ArchiveModelSidecarTextureBinding
from cdmw.core.archive_model_textures import _FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE
from cdmw.core.archive_content_analysis import load_archive_content_analysis
from cdmw.core.archive_compat_exports import ARCHIVE_EXPORTS


def _archive_proxy(name: str):
    module_name, attribute_name = ARCHIVE_EXPORTS[name]

    def _proxy(*args, **kwargs):
        owner = getattr(import_module(module_name), attribute_name)
        return owner(*args, **kwargs)

    return _proxy

_archive_texture_family_mismatch_summary = _archive_proxy("_archive_texture_family_mismatch_summary")
_attach_hkx_physics_overlay_to_model_preview = _archive_proxy("_attach_hkx_physics_overlay_to_model_preview")
_attach_model_sidecar_texture_preview_paths = _archive_proxy("_attach_model_sidecar_texture_preview_paths")
_attach_model_support_texture_preview_paths = _archive_proxy("_attach_model_support_texture_preview_paths")
_attach_model_texture_preview_paths = _archive_proxy("_attach_model_texture_preview_paths")
_attach_pbd_cloth_preview_to_model_preview = _archive_proxy("_attach_pbd_cloth_preview_to_model_preview")
_build_hkx_preview_context_from_related_references = _archive_proxy("_build_hkx_preview_context_from_related_references")
_build_model_preview_texture_slot_detail_text = _archive_proxy("_build_model_preview_texture_slot_detail_text")
_build_mp4_media_preview_detail_text = _archive_proxy("_build_mp4_media_preview_detail_text")
_build_pac_model_preview_with_fallback = _archive_proxy("_build_pac_model_preview_with_fallback")
_build_pam_model_preview_with_fallback = _archive_proxy("_build_pam_model_preview_with_fallback")
_build_pamlod_model_preview_with_fallback = _archive_proxy("_build_pamlod_model_preview_with_fallback")
_build_wem_media_preview_detail_text = _archive_proxy("_build_wem_media_preview_detail_text")
_clone_hkx_context_model_preview = _archive_proxy("_clone_hkx_context_model_preview")
_collect_archive_texture_sidecar_texts_from_entries = _archive_proxy("_collect_archive_texture_sidecar_texts_from_entries")
_ensure_media_preview_source_path = _archive_proxy("_ensure_media_preview_source_path")
_extract_archive_model_sidecar_texture_references = _archive_proxy("_extract_archive_model_sidecar_texture_references")
_extract_binary_asset_references = _archive_proxy("_extract_binary_asset_references")
_find_archive_model_related_entries = _archive_proxy("_find_archive_model_related_entries")
_find_archive_texture_referencing_sidecar_entries = _archive_proxy("_find_archive_texture_referencing_sidecar_entries")
_get_hkx_context_model_preview_cache = _archive_proxy("_get_hkx_context_model_preview_cache")
_hkx_context_model_preview_cache_key = _archive_proxy("_hkx_context_model_preview_cache_key")
_normalize_archive_preview_quality_tier = _archive_proxy("_normalize_archive_preview_quality_tier")
_normalize_model_visible_texture_mode = _archive_proxy("_normalize_model_visible_texture_mode")
_remember_hkx_context_model_preview_cache = _archive_proxy("_remember_hkx_context_model_preview_cache")
build_archive_asset_family_graph = _archive_proxy("build_archive_asset_family_graph")
build_archive_binary_preview_payload = _archive_proxy("build_archive_binary_preview_payload")
build_archive_entry_detail_text = _archive_proxy("build_archive_entry_detail_text")
build_archive_entry_metadata_summary = _archive_proxy("build_archive_entry_metadata_summary")
build_archive_entry_related_references = _archive_proxy("build_archive_entry_related_references")
build_archive_model_texture_references = _archive_proxy("build_archive_model_texture_references")
build_archive_pathc_lookup_detail_for_entry = _archive_proxy("build_archive_pathc_lookup_detail_for_entry")
build_archive_pathc_preview = _archive_proxy("build_archive_pathc_preview")
build_archive_related_file_references = _archive_proxy("build_archive_related_file_references")
build_archive_relationship_references = _archive_proxy("build_archive_relationship_references")
build_binary_strings_preview = _archive_proxy("build_binary_strings_preview")
build_bnk_soundbank_preview = _archive_proxy("build_bnk_soundbank_preview")
build_dds_header_detail_text = _archive_proxy("build_dds_header_detail_text")
build_hkx_editable_geometry_document = _archive_proxy("build_hkx_editable_geometry_document")
build_hkx_model_preview_from_document = _archive_proxy("build_hkx_model_preview_from_document")
build_hkx_physics_overlay_from_document = _archive_proxy("build_hkx_physics_overlay_from_document")
build_hkx_preview = _archive_proxy("build_hkx_preview")
build_loose_archive_media_preview_assets = _archive_proxy("build_loose_archive_media_preview_assets")
build_loose_archive_preview_assets = _archive_proxy("build_loose_archive_preview_assets")
build_meshinfo_preview = _archive_proxy("build_meshinfo_preview")
build_pab_preview = _archive_proxy("build_pab_preview")
build_par_structured_preview = _archive_proxy("build_par_structured_preview")
build_pat_model_preview = _archive_proxy("build_pat_model_preview")
build_simplified_text_asset_summary = _archive_proxy("build_simplified_text_asset_summary")
build_structured_asset_preview = _archive_proxy("build_structured_asset_preview")
ensure_archive_preview_source = _archive_proxy("ensure_archive_preview_source")
ensure_dds_display_preview_png = _archive_proxy("ensure_dds_display_preview_png")
extract_binary_dds_references = _archive_proxy("extract_binary_dds_references")
format_binary_header_preview = _archive_proxy("format_binary_header_preview")
format_byte_size = _archive_proxy("format_byte_size")
iter_archive_loose_file_candidates = _archive_proxy("iter_archive_loose_file_candidates")
merge_archive_reference_rows = _archive_proxy("merge_archive_reference_rows")
parse_archive_note_flags = _archive_proxy("parse_archive_note_flags")
parse_dds = _archive_proxy("parse_dds")
read_archive_entry_data = _archive_proxy("read_archive_entry_data")
read_archive_entry_raw_data = _archive_proxy("read_archive_entry_raw_data")
resolve_hkx_preview_context_model_entry = _archive_proxy("resolve_hkx_preview_context_model_entry")
summarize_obj_text = _archive_proxy("summarize_obj_text")
try_decode_text_like_archive_data = _archive_proxy("try_decode_text_like_archive_data")

def build_archive_preview_result(
    entry: Optional[ArchiveEntry],
    loose_search_roots: Optional[Sequence[Path]] = None,
    *,
    companion_entry: Optional[ArchiveEntry] = None,
    texture_entries_by_normalized_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    texture_entries_by_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_path: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    sidecar_entries_by_texture_basename: Optional[Dict[str, Sequence[ArchiveEntry]]] = None,
    include_loose_preview_assets: bool = True,
    semantic_sidecar_texts: Sequence[str] = (),
    visible_texture_mode: str = "mesh_base_first",
    support_texture_slots: Sequence[str] = ("normal", "material", "height", "emissive"),
    quality_tier: str = "full",
    enable_hkx_visual_preview: bool = True,
    stop_event: Optional[threading.Event] = None,
) -> ArchivePreviewResult:
    normalized_quality_tier = _normalize_archive_preview_quality_tier(quality_tier)
    if entry is None:
        return ArchivePreviewResult(
            status="missing",
            title="Archive Preview",
            metadata_summary="Nothing selected.",
            detail_text="Select an archive file or folder to preview it here.",
            quality_tier=normalized_quality_tier,
            preferred_view="info",
        )

    metadata_summary = build_archive_entry_metadata_summary(entry)
    extension = entry.extension
    normalized_visible_texture_mode = _normalize_model_visible_texture_mode(visible_texture_mode)
    timings: Dict[str, float] = {}

    def add_timing(key: str, started_at: float) -> None:
        timings[key] = timings.get(key, 0.0) + max(0.0, float(time.perf_counter() - started_at))

    loose_file_path = ""
    loose_preview_image_path = ""
    loose_preview_media_path = ""
    loose_preview_media_kind = ""
    loose_preview_title = ""
    loose_preview_metadata_summary = ""
    loose_preview_detail_text = ""

    if loose_search_roots:
        loose_candidates = list(iter_archive_loose_file_candidates(entry, loose_search_roots))
        if loose_candidates:
            loose_candidate = loose_candidates[0]
            loose_file_path = str(loose_candidate)
            loose_preview_title = f"{entry.basename} (Loose file)"
            if include_loose_preview_assets:
                try:
                    if loose_candidate.suffix.lower() in ARCHIVE_AUDIO_EXTENSIONS.union(ARCHIVE_VIDEO_EXTENSIONS):
                        (
                            loose_preview_media_path,
                            loose_preview_media_kind,
                            loose_preview_metadata_summary,
                            loose_preview_detail_text,
                        ) = build_loose_archive_media_preview_assets(
                            loose_candidate,
                            stop_event=stop_event,
                        )
                    else:
                        (
                            loose_preview_image_path,
                            loose_preview_metadata_summary,
                            loose_preview_detail_text,
                        ) = build_loose_archive_preview_assets(
                            loose_candidate,
                            stop_event=stop_event,
                        )
                except RunCancelled:
                    raise
                except Exception as exc:
                    loose_preview_metadata_summary = f"Loose file | {loose_candidate.name}"
                    loose_preview_detail_text = (
                        f"Loose file candidate found at {loose_candidate}, but preview failed: {exc}"
                    )
                if len(loose_candidates) > 1:
                    loose_preview_detail_text += (
                        f"\n\nAdditional loose candidates found: {len(loose_candidates) - 1}"
                    )

    try:
        if extension in ARCHIVE_VIDEO_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            metadata_summary, media_detail = _build_mp4_media_preview_detail_text(source_path, loose=False)
            extra_detail_parts: List[str] = []
            if "ChaCha20" in parse_archive_note_flags(note):
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            extra_detail_parts.append(media_detail)
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(part for part in extra_detail_parts if part)),
                preview_media_path=str(source_path.resolve()),
                preview_media_kind="video",
                preferred_view="media",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_AUDIO_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            media_source, playback_note = _ensure_media_preview_source_path(
                source_path,
                extension,
                stop_event=stop_event,
            )
            try:
                with source_path.open("rb") as handle:
                    audio_sample = handle.read(131072)
            except OSError:
                audio_sample = b""
            metadata_summary, media_detail = _build_wem_media_preview_detail_text(
                source_path,
                audio_sample,
                loose=False,
                playback_source_path=media_source,
                playback_note=playback_note,
            )
            extra_detail_parts: List[str] = []
            if "ChaCha20" in parse_archive_note_flags(note):
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            extra_detail_parts.append(media_detail)
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(part for part in extra_detail_parts if part)),
                preview_media_path=str(media_source),
                preview_media_kind="audio",
                preferred_view="media",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".dds":
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            note_flags = parse_archive_note_flags(note)
            referencing_sidecar_entries = _find_archive_texture_referencing_sidecar_entries(
                entry,
                sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
            )
            combined_semantic_sidecar_texts: List[str] = [
                str(text or "").strip()
                for text in semantic_sidecar_texts
                if str(text or "").strip()
            ]
            for sidecar_text in _collect_archive_texture_sidecar_texts_from_entries(
                referencing_sidecar_entries,
                stop_event=stop_event,
            ):
                if sidecar_text not in combined_semantic_sidecar_texts:
                    combined_semantic_sidecar_texts.append(sidecar_text)
            related_references = build_archive_entry_related_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
                sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
                sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
                companion_entries=referencing_sidecar_entries,
            )
            warning_badge = ""
            warning_text = ""
            extra_detail_parts: List[str] = []
            dds_info: Optional[DdsInfo] = None
            try:
                dds_info = parse_dds(source_path)
                metadata_summary = (
                    f"{metadata_summary} | {dds_info.dds_format} | "
                    f"{dds_info.width}x{dds_info.height} | Mips {dds_info.mip_count}"
                )
                extra_detail_parts.append(
                    build_dds_header_detail_text(
                        source_path,
                        dds_info,
                        logical_path=entry.path,
                        sidecar_texts=tuple(combined_semantic_sidecar_texts),
                    )
                )
            except Exception as exc:
                extra_detail_parts.append(f"DDS metadata unavailable: {exc}")
            if "PartialDDS" in note_flags:
                extra_detail_parts.append(
                    "Type 1 DDS reconstructed successfully using meta/0.pathc partial-header metadata."
                )
            elif "SparseDDS" in note_flags:
                warning_badge = "Type 1 DDS: Unsupported Preview"
                warning_text = (
                    "This archive DDS is stored as truncated type 1 data. "
                    "The image shown here is a padded best-effort preview and may be corrupted, noisy, or incomplete."
                )
                extra_detail_parts.append(warning_text)
                if loose_file_path:
                    extra_detail_parts.append(f"Loose file candidate found: {loose_file_path}")
            if "ChaCha20" in note_flags:
                extra_detail_parts.append("Archive payload decrypted via deterministic ChaCha20 filename derivation.")
            pathc_lookup_detail = build_archive_pathc_lookup_detail_for_entry(entry)
            if pathc_lookup_detail:
                extra_detail_parts.append(pathc_lookup_detail)
            preview_png = ensure_dds_display_preview_png(
                source_path.resolve(),
                dds_info=dds_info,
                stop_event=stop_event,
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, "\n\n".join(extra_detail_parts)),
                preview_image_path=str(preview_png),
                preferred_view="image",
                warning_badge=warning_badge,
                warning_text=warning_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_IMAGE_EXTENSIONS:
            source_path, note = ensure_archive_preview_source(entry, stop_event=stop_event)
            related_references = build_archive_entry_related_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(
                    entry,
                    "Preview fallback: sparse DDS padding was applied."
                    if "SparseDDS" in parse_archive_note_flags(note)
                    else "",
                ),
                preview_image_path=str(source_path),
                preferred_view="image",
                model_texture_references=related_references,
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        entry_read_started_at = time.perf_counter()
        data, _decompressed, note = read_archive_entry_data(entry, stop_event=stop_event)
        add_timing("entry_read_s", entry_read_started_at)
        note_flags = parse_archive_note_flags(note)

        if extension == ".bnk":
            bnk_preview_text, bnk_detail_text = build_bnk_soundbank_preview(data)
            detail_extra = "\n\n".join(
                part
                for part in [
                    (
                        "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes."
                        if "PartialRaw" in note_flags
                        else ""
                    ),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    bnk_detail_text,
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | Wwise SoundBank",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=bnk_preview_text or build_binary_strings_preview(data),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".pathc":
            pathc_preview = build_archive_pathc_preview(data, entry.path)
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(pathc_preview.detail_lines),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {pathc_preview.metadata_label}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=pathc_preview.preview_text,
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".pab":
            skeleton_preview = build_pab_preview(data, entry.path)
            related_references = build_archive_related_file_references(
                entry,
                explicit_reference_names=_extract_binary_asset_references(data, sample_limit=262_144, max_references=48),
                companion_entries=(
                    _find_archive_model_related_entries(entry, texture_entries_by_basename)
                    if texture_entries_by_basename is not None
                    else ()
                ),
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(skeleton_preview.detail_lines),
                    ("Companion and related files are listed below." if related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | Skeleton",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=skeleton_preview.preview_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension == ".meshinfo":
            meshinfo_preview = build_meshinfo_preview(
                data,
                entry.path,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(meshinfo_preview.detail_lines),
                    ("Companion and related files are listed below." if meshinfo_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {meshinfo_preview.metadata_label or 'Mesh Metadata'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=meshinfo_preview.preview_text,
                model_texture_references=meshinfo_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, meshinfo_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".paa", ".paa_metabin", ".pae", ".paem", ".motionblending", ".papr", ".paseq", ".paseqc", ".paschedule", ".paschedulepath", ".pastage"}:
            structured_preview = build_par_structured_preview(
                data,
                entry.path,
                extension=extension,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(structured_preview.detail_lines),
                    ("Companion and related files are listed below." if structured_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {structured_preview.metadata_label or 'Structured Binary'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=structured_preview.preview_text,
                model_texture_references=structured_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, structured_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".prefab", ".pappt", ".pamhc", ".paccd", ".seqmt", ".levelinfo", ".palevel", ".roadsector", ".road", ".nav", ".pabc", ".pabv", ".pabgb", ".pabgh"}:
            structured_preview = build_structured_asset_preview(
                data,
                entry.path,
                extension=extension,
                source_entry=entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
                stop_event=stop_event,
            )
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(structured_preview.detail_lines),
                    ("Companion and related files are listed below." if structured_preview.related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=f"{metadata_summary} | {structured_preview.metadata_label or 'Structured Binary'}",
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=structured_preview.preview_text,
                model_texture_references=structured_preview.related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, structured_preview.related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in {".hkx", ".hkt"}:
            hkx_preview = build_hkx_preview(data, entry.path)
            related_references = build_archive_entry_related_references(
                entry,
                binary_data=data,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            graph_references = build_archive_relationship_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            related_references = merge_archive_reference_rows(related_references, graph_references)
            if not enable_hkx_visual_preview:
                detail_extra = "\n\n".join(
                    part
                    for part in [
                        ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                        ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                        "\n".join(hkx_preview.detail_lines),
                        "HKX visual body/physics preview skipped for archive browsing. Use the HKX editor for explicit collision/body preview.",
                        ("Companion and related files are listed below." if related_references else ""),
                    ]
                    if part
                )
                return ArchivePreviewResult(
                    status="ok",
                    title=entry.basename,
                    metadata_summary=f"{metadata_summary} | Havok",
                    detail_text=build_archive_entry_detail_text(entry, detail_extra),
                    preview_text=hkx_preview.preview_text,
                    model_texture_references=related_references,
                    asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                    preferred_view="text",
                    loose_file_path=loose_file_path,
                    loose_preview_image_path=loose_preview_image_path,
                    loose_preview_media_path=loose_preview_media_path,
                    loose_preview_media_kind=loose_preview_media_kind,
                    loose_preview_title=loose_preview_title,
                    loose_preview_metadata_summary=loose_preview_metadata_summary,
                    loose_preview_detail_text=loose_preview_detail_text,
                )
            descriptor_hints, skeleton_bone_positions, hkx_visual_notes = _build_hkx_preview_context_from_related_references(
                related_references,
                stop_event=stop_event,
            )
            hkx_model_preview: Optional[ModelPreviewData] = None
            hkx_document: Optional[Mapping[str, object]] = None
            hkx_context_model_entry = resolve_hkx_preview_context_model_entry(entry, related_references)
            try:
                hkx_document = build_hkx_editable_geometry_document(data, entry.path, descriptor_hints)
                if hkx_context_model_entry is not None:
                    try:
                        context_cache_key = ""
                        if not semantic_sidecar_texts:
                            context_cache_key = _hkx_context_model_preview_cache_key(
                                hkx_context_model_entry,
                                visible_texture_mode=visible_texture_mode,
                                support_texture_slots=support_texture_slots,
                                quality_tier=normalized_quality_tier,
                            )
                        context_model = _get_hkx_context_model_preview_cache(context_cache_key)
                        if isinstance(context_model, ModelPreviewData):
                            hkx_visual_notes.append(f"HKX body context reused cached preview model for {hkx_context_model_entry.path}.")
                        else:
                            context_result = build_archive_preview_result(
                                hkx_context_model_entry,
                                (),
                                companion_entry=None,
                                texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                                texture_entries_by_basename=texture_entries_by_basename,
                                sidecar_entries_by_texture_path=sidecar_entries_by_texture_path,
                                sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename,
                                include_loose_preview_assets=False,
                                semantic_sidecar_texts=semantic_sidecar_texts,
                                visible_texture_mode=visible_texture_mode,
                                support_texture_slots=support_texture_slots,
                                quality_tier=normalized_quality_tier,
                                stop_event=stop_event,
                            )
                            raw_context_model = getattr(context_result, "preview_model", None)
                            context_model = (
                                _clone_hkx_context_model_preview(raw_context_model)
                                if isinstance(raw_context_model, ModelPreviewData)
                                else raw_context_model
                            )
                            if isinstance(context_model, ModelPreviewData) and context_cache_key:
                                _remember_hkx_context_model_preview_cache(context_cache_key, context_model)
                        if isinstance(context_model, ModelPreviewData):
                            selected_overlay = build_hkx_physics_overlay_from_document(
                                hkx_document,
                                source_path=entry.path,
                                normalization_center=tuple(getattr(context_model, "normalization_center", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                                normalization_scale=float(getattr(context_model, "normalization_scale", 1.0) or 1.0),
                                skeleton_bone_positions=skeleton_bone_positions,
                            )
                            context_summary = (
                                f"{entry.path}\n"
                                "HKX Body + Physics preview\n"
                                f"Body context: {hkx_context_model_entry.path}\n"
                                f"{context_model.mesh_count:,} body submesh(es)\n"
                                f"{context_model.face_count:,} body faces"
                            )
                            hkx_model_preview = replace(
                                context_model,
                                path=entry.path,
                                summary=context_summary,
                                physics_overlay=selected_overlay,
                            )
                            hkx_visual_notes.append(
                                f"HKX is physics/collision; body mesh loaded from {hkx_context_model_entry.path}."
                            )
                            if selected_overlay is not None:
                                hkx_visual_notes.append(
                                    f"Selected HKX physics overlay attached to body context: {len(selected_overlay.shapes):,} decoded shape(s)."
                                )
                            else:
                                hkx_visual_notes.append("Selected HKX physics overlay did not decode renderable shapes for the body context.")
                        else:
                            hkx_visual_notes.append(
                                f"HKX body context skipped: {hkx_context_model_entry.path} did not produce a renderable model preview."
                            )
                    except RunCancelled:
                        raise
                    except Exception as exc:
                        hkx_visual_notes.append(f"HKX body context skipped for {hkx_context_model_entry.path}: {exc}")
                if hkx_model_preview is None:
                    hkx_model_preview = build_hkx_model_preview_from_document(
                        hkx_document,
                        source_path=entry.path,
                        skeleton_bone_positions=skeleton_bone_positions,
                    )
                if hkx_model_preview is not None:
                    shape_count = len(getattr(getattr(hkx_model_preview, "physics_overlay", None), "shapes", ()) or ())
                    bone_count = len(getattr(getattr(hkx_model_preview, "physics_overlay", None), "bones", ()) or ())
                    if hkx_context_model_entry is not None and "HKX Body + Physics preview" in str(getattr(hkx_model_preview, "summary", "") or ""):
                        hkx_visual_notes.append(
                            "HKX Body + Physics visual preview generated "
                            f"{hkx_model_preview.mesh_count:,} body batch(es) with "
                            f"{shape_count:,} decoded physics shape(s)"
                            + (f" and {bone_count:,} skeleton bone(s)" if bone_count else "")
                            + "."
                        )
                    else:
                        hkx_visual_notes.append(
                            "HKX visual preview generated "
                            f"{hkx_model_preview.mesh_count:,} D3D11-ready batch(es) from "
                            f"{shape_count:,} decoded shape(s)"
                            + (f" and {bone_count:,} skeleton bone(s)" if bone_count else "")
                            + "."
                        )
            except RunCancelled:
                raise
            except Exception as exc:
                hkx_visual_notes.append(f"HKX visual preview generation skipped: {exc}")
            if hkx_model_preview is not None:
                if hkx_context_model_entry is not None and "HKX Body + Physics preview" in str(getattr(hkx_model_preview, "summary", "") or ""):
                    metadata_summary = (
                        f"{metadata_summary} | Havok | Body + Physics"
                        f" | {hkx_model_preview.mesh_count:,} body batch(es)"
                        f" | {hkx_model_preview.face_count:,} body faces"
                    )
                else:
                    metadata_summary = (
                        f"{metadata_summary} | Havok | {hkx_model_preview.mesh_count:,} preview batch(es)"
                        f" | {hkx_model_preview.face_count:,} faces"
                    )
            else:
                metadata_summary = f"{metadata_summary} | Havok"
            detail_extra = "\n\n".join(
                part
                for part in [
                    ("Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes." if "PartialRaw" in note_flags else ""),
                    ("Decrypted via deterministic ChaCha20 filename derivation." if "ChaCha20" in note_flags else ""),
                    "\n".join(hkx_preview.detail_lines),
                    "\n".join(hkx_visual_notes),
                    ("Companion and related files are listed below." if related_references else ""),
                ]
                if part
            )
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(entry, detail_extra),
                preview_text=hkx_preview.preview_text,
                preview_model=hkx_model_preview,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="model" if hkx_model_preview is not None else "text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        if extension in ARCHIVE_TEXT_EXTENSIONS:
            preview_bytes = data[:ARCHIVE_TEXT_PREVIEW_LIMIT]
            text = try_decode_text_like_archive_data(data) or preview_bytes.decode("utf-8", errors="replace")
            simplified_summary = build_simplified_text_asset_summary(
                text,
                extension=extension,
                virtual_path=entry.path,
            )
            related_references = build_archive_entry_related_references(
                entry,
                text=text,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            graph_references = build_archive_relationship_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            if extension in {".app_xml", ".prefabdata_xml"}:
                related_references = graph_references
            else:
                related_references = merge_archive_reference_rows(related_references, graph_references)
            extra_note = ""
            if len(data) > ARCHIVE_TEXT_PREVIEW_LIMIT:
                extra_note = f"\n\nPreview truncated to {format_byte_size(ARCHIVE_TEXT_PREVIEW_LIMIT)}."
            if "PartialRaw" in note_flags:
                extra_note = "\n\n".join(
                    part
                    for part in [
                        "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes.",
                        extra_note.strip(),
                    ]
                    if part
                )
            if "ChaCha20" in note_flags:
                extra_note = "\n\n".join(
                    part for part in ["Decrypted via deterministic ChaCha20 filename derivation.", extra_note.strip()] if part
                )
            if extension == ".obj":
                summary_text = summarize_obj_text(text)
                extra_note = "\n\n".join(part for part in [summary_text, extra_note.strip()] if part)
            if related_references:
                extra_note = "\n\n".join(
                    part for part in [extra_note.strip(), "Companion and related files are listed below."] if part
                )
            preview_text = text
            if simplified_summary:
                preview_text = f"{simplified_summary}\n\nRaw text preview:\n{text}"
            return ArchivePreviewResult(
                status="ok",
                title=entry.basename,
                metadata_summary=metadata_summary,
                detail_text=build_archive_entry_detail_text(
                    entry,
                    "\n\n".join(
                        part
                        for part in [
                            ("Preview fallback: sparse DDS padding was applied." if "SparseDDS" in note_flags else ""),
                            extra_note.strip(),
                        ]
                        if part
                    ),
                ),
                preview_text=preview_text,
                model_texture_references=related_references,
                asset_family_graph=build_archive_asset_family_graph(entry, related_references),
                preferred_view="text",
                loose_file_path=loose_file_path,
                loose_preview_image_path=loose_preview_image_path,
                loose_preview_media_path=loose_preview_media_path,
                loose_preview_media_kind=loose_preview_media_kind,
                loose_preview_title=loose_preview_title,
                loose_preview_metadata_summary=loose_preview_metadata_summary,
                loose_preview_detail_text=loose_preview_detail_text,
            )

        info_extra_parts: List[str] = []
        if "SparseDDS" in note_flags:
            info_extra_parts.append("Preview fallback: sparse DDS padding was applied.")
        if "PartialPAR" in note_flags:
            info_extra_parts.append(
                "Archive entry uses Partial PAR storage; preview uses reconstructed decompressed sections."
            )
        if "PartialRaw" in note_flags:
            info_extra_parts.append(
                "Archive entry uses non-DDS Partial storage; preview is based on raw stored bytes."
            )
        if "ChaCha20" in note_flags:
            info_extra_parts.append("Decrypted via deterministic ChaCha20 filename derivation.")
        model_preview = None
        model_texture_references: Tuple[ArchiveModelTextureReference, ...] = ()
        model_preview_error = ""
        parsed_mesh_for_references = None
        binary_texture_references: Tuple[str, ...] = ()
        sidecar_texture_references: Tuple[_ArchiveModelSidecarTextureBinding, ...] = ()
        sidecar_reference_paths: Tuple[str, ...] = ()
        sidecar_texts_by_normalized_path: Dict[str, Tuple[str, ...]] = {}
        sidecar_texts_by_basename: Dict[str, Tuple[str, ...]] = {}
        if extension in ARCHIVE_MODEL_EXTENSIONS:
            binary_refs_started_at = time.perf_counter()
            binary_texture_references = tuple(extract_binary_dds_references(data))
            add_timing("model_binary_ref_scan_s", binary_refs_started_at)
            sidecar_refs_started_at = time.perf_counter()
            (
                sidecar_texture_references,
                sidecar_reference_paths,
                sidecar_texts_by_normalized_path,
                sidecar_texts_by_basename,
            ) = _extract_archive_model_sidecar_texture_references(
                entry,
                archive_entries_by_basename=texture_entries_by_basename,
                stop_event=stop_event,
            )
            add_timing("model_sidecar_refs_s", sidecar_refs_started_at)
            if sidecar_texture_references:
                sidecar_count = len(sidecar_texture_references)
                sidecar_suffix = f" from {', '.join(sidecar_reference_paths[:2])}" if sidecar_reference_paths else ""
                if len(sidecar_reference_paths) > 2:
                    sidecar_suffix += " ..."
                info_extra_parts.append(
                    f"Companion material sidecar data contributed {sidecar_count:,} texture binding(s){sidecar_suffix}."
                )
                family_notice = _archive_texture_family_mismatch_summary(
                    entry.path,
                    tuple(str(getattr(binding, "texture_path", "") or "") for binding in sidecar_texture_references),
                    sidecar_paths=sidecar_reference_paths,
                )
                if family_notice:
                    info_extra_parts.append(family_notice)
                if extension in {".pam", ".pamlod", ".pac"}:
                    info_extra_parts.append(
                        "Companion sidecar data only describes material and texture bindings. Geometry preview still depends on recovering a renderable mesh layout from the selected payload or its mesh companion."
                    )
        if extension == ".pam":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, model_info = _build_pam_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    companion_entry=companion_entry,
                    quality_tier=normalized_quality_tier,
                    stop_event=stop_event,
                )
                if getattr(model_preview, "format", "").lower() == "pamlod":
                    lod_label = (
                        f"LOD {model_preview.lod_index + 1} of {model_preview.lod_count}"
                        if getattr(model_preview, "lod_count", 0) > 0 and getattr(model_preview, "lod_index", -1) >= 0
                        else "highest-detail LOD"
                    )
                    metadata_summary = f"{metadata_summary} | {lod_label} | {model_preview.face_count:,} faces"
                else:
                    metadata_summary = (
                        f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                        f" | {model_preview.face_count:,} faces"
                    )
                info_extra_parts.extend(model_info)
                if getattr(model_preview, "format", "").lower() == "pamlod":
                    info_extra_parts.append(
                        "Geometry preview uses the highest-detail recovered companion PAMLOD LOD only; lower-detail LODs are not stacked in the preview. "
                        "Texture and material references remain listed below."
                    )
                else:
                    info_extra_parts.append(
                        "Geometry preview uses recovered PAM submeshes with temporary material colors. "
                        "Texture and material references remain listed below."
                    )
            except RunCancelled:
                raise
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
            add_timing("model_geometry_s", geometry_started_at)
        elif extension == ".pamlod":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, model_info = _build_pamlod_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    companion_entry=companion_entry,
                    quality_tier=normalized_quality_tier,
                    stop_event=stop_event,
                )
                if getattr(model_preview, "format", "").lower() == "pam":
                    metadata_summary = (
                        f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                        f" | {model_preview.face_count:,} faces"
                    )
                else:
                    lod_label = (
                        f"LOD {model_preview.lod_index + 1} of {model_preview.lod_count}"
                        if getattr(model_preview, "lod_count", 0) > 0 and getattr(model_preview, "lod_index", -1) >= 0
                        else "highest-detail LOD"
                    )
                    metadata_summary = f"{metadata_summary} | {lod_label} | {model_preview.face_count:,} faces"
                info_extra_parts.extend(model_info)
                if getattr(model_preview, "format", "").lower() == "pam":
                    info_extra_parts.append(
                        "Geometry preview uses recovered companion PAM submeshes with temporary material colors. "
                        "Texture and material references remain listed below."
                    )
                else:
                    info_extra_parts.append(
                        "Geometry preview uses the highest-detail recovered PAMLOD LOD only; lower-detail LODs are not stacked in the preview. "
                        "Texture and material references remain listed below."
                    )
            except RunCancelled:
                raise
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
        elif extension == ".pac":
            geometry_started_at = time.perf_counter()
            try:
                model_preview, parsed_mesh, model_info = _build_pac_model_preview_with_fallback(
                    entry,
                    data,
                    note_flags,
                    quality_tier=normalized_quality_tier,
                    stop_event=stop_event,
                )
                parsed_mesh_for_references = parsed_mesh
                metadata_summary = (
                    f"{metadata_summary} | {model_preview.mesh_count:,} submesh(es)"
                    f" | {model_preview.face_count:,} faces"
                )
                info_extra_parts.extend(model_info)
                info_extra_parts.append(
                    "Geometry preview uses recovered PAC skinned mesh data. Texture and material references remain listed below."
                )
                if getattr(parsed_mesh, "has_bones", False):
                    unique_bones = {
                        int(bone_index)
                        for submesh in getattr(parsed_mesh, "submeshes", [])
                        for palette in getattr(submesh, "bone_indices", [])
                        for bone_index in palette
                        if int(bone_index) >= 0
                    }
                    if unique_bones:
                        info_extra_parts.append(
                            f"Recovered skinning data referencing {len(unique_bones):,} bone slot(s)."
                        )
                unique_material_names = {
                    str(getattr(submesh, "material", "") or "").strip()
                    for submesh in getattr(parsed_mesh, "submeshes", ())
                    if str(getattr(submesh, "material", "") or "").strip()
                }
                unique_texture_names = {
                    str(getattr(submesh, "texture", "") or "").strip()
                    for submesh in getattr(parsed_mesh, "submeshes", ())
                    if str(getattr(submesh, "texture", "") or "").strip()
                }
                if getattr(parsed_mesh, "has_uvs", False):
                    info_extra_parts.append("Recovered UV coordinates for textured preview and export.")
                if unique_material_names:
                    info_extra_parts.append(f"Recovered {len(unique_material_names):,} material slot name(s) from the PAC payload.")
                if unique_texture_names:
                    info_extra_parts.append(f"Recovered {len(unique_texture_names):,} embedded texture reference name(s) from the PAC payload.")
                if texture_entries_by_basename is not None:
                    companion_pab_entries = [
                        related_entry
                        for related_entry in _find_archive_model_related_entries(entry, texture_entries_by_basename)
                        if related_entry.extension == ".pab"
                    ]
                    if companion_pab_entries:
                        info_extra_parts.append(f"Matching skeleton companion detected: {companion_pab_entries[0].path}")
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual model preview failed to recover geometry: {exc}")
            add_timing("model_geometry_s", geometry_started_at)
        elif extension == ".pat":
            geometry_started_at = time.perf_counter()
            try:
                model_preview = build_pat_model_preview(data, entry.path, lod_index=0)
                metadata_summary = (
                    f"{metadata_summary} | PAT LOD {model_preview.lod_index + 1} of {model_preview.lod_count}"
                    f" | {model_preview.face_count:,} faces"
                )
                material_count = len(
                    {
                        str(getattr(mesh, "material_name", "") or "").strip()
                        for mesh in model_preview.meshes
                        if str(getattr(mesh, "material_name", "") or "").strip()
                    }
                )
                info_extra_parts.append(
                    "Geometry preview uses the highest-detail PAT LOD decoded from 32-byte plant mesh vertices."
                )
                if material_count:
                    info_extra_parts.append(
                        f"Recovered {material_count:,} PAT material slot(s) and texture basename hint(s)."
                    )
            except RunCancelled:
                raise
            except Exception as exc:
                model_preview_error = str(exc)
                info_extra_parts.append(f"Visual PAT preview failed to recover geometry: {exc}")
            add_timing("model_geometry_s", geometry_started_at)
        elif extension in ARCHIVE_MODEL_EXTENSIONS:
            info_extra_parts.append("Visual preview is not available for this model format yet.")
        if (
            model_preview is not None
            and sidecar_texture_references
            and parsed_mesh_for_references is None
            and extension in ARCHIVE_MODEL_EXTENSIONS
        ):
            try:
                from cdmw.modding.mesh_parser import parse_mesh

                parsed_mesh_for_references = parse_mesh(data, entry.path)
            except RunCancelled:
                raise
            except Exception:
                parsed_mesh_for_references = None
        if model_preview is not None:
            if model_preview.meshes:
                if normalized_quality_tier == "fast":
                    info_extra_parts.append(_FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE)
                elif normalized_visible_texture_mode == "mesh_base_first":
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                if normalized_quality_tier != "fast" and sidecar_texture_references:
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_sidecar_texture_preview_paths(
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            visible_texture_mode=normalized_visible_texture_mode,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_sidecar_texture_attach_s", attach_started_at)
                if normalized_quality_tier != "fast" and normalized_visible_texture_mode != "mesh_base_first":
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                if (
                    normalized_quality_tier != "fast"
                    and sidecar_texture_references
                    and normalized_visible_texture_mode == "mesh_base_first"
                ):
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_sidecar_texture_preview_paths(
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            visible_texture_mode="layer_aware_visible",
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            fallback_only=True,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_sidecar_fallback_attach_s", attach_started_at)
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_texture_preview_paths(
                            entry,
                            model_preview,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            override_existing_base=True,
                            prefer_material_name_for_base=True,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_base_texture_attach_s", attach_started_at)
                requested_support_texture_slots = {
                    str(value or "").strip().lower()
                    for value in (support_texture_slots or ())
                }
                normalized_support_texture_slots = tuple(
                    slot
                    for slot in ("normal", "material", "height", "emissive")
                    if slot in requested_support_texture_slots
                )
                if normalized_quality_tier != "fast" and normalized_support_texture_slots:
                    attach_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_model_support_texture_preview_paths(
                            entry,
                            model_preview,
                            parsed_mesh=parsed_mesh_for_references,
                            sidecar_texture_bindings=sidecar_texture_references,
                            texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                            texture_entries_by_basename=texture_entries_by_basename,
                            sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                            sidecar_texts_by_basename=sidecar_texts_by_basename,
                            support_slots=normalized_support_texture_slots,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_support_texture_attach_s", attach_started_at)
                if (
                    normalized_quality_tier != "fast"
                    and extension == ".pac"
                    and parsed_mesh_for_references is not None
                ):
                    cloth_started_at = time.perf_counter()
                    info_extra_parts.extend(
                        _attach_pbd_cloth_preview_to_model_preview(
                            entry,
                            model_preview,
                            parsed_mesh_for_references,
                            archive_entries_by_basename=texture_entries_by_basename,
                            stop_event=stop_event,
                        )
                    )
                    add_timing("model_pbd_cloth_s", cloth_started_at)
                texture_slot_detail = _build_model_preview_texture_slot_detail_text(model_preview)
                if texture_slot_detail:
                    info_extra_parts.append(texture_slot_detail)
        if extension in ARCHIVE_MODEL_EXTENSIONS and parsed_mesh_for_references is None:
            try:
                from cdmw.modding.mesh_parser import parse_mesh

                parsed_mesh_for_references = parse_mesh(data, entry.path)
            except RunCancelled:
                raise
            except Exception:
                parsed_mesh_for_references = None
        if (
            model_preview is not None
            or parsed_mesh_for_references is not None
            or binary_texture_references
            or sidecar_texture_references
            or extension in ARCHIVE_MODEL_EXTENSIONS
        ):
            references_started_at = time.perf_counter()
            model_texture_references = tuple(
                build_archive_model_texture_references(
                    entry,
                    model_preview,
                    parsed_mesh=parsed_mesh_for_references,
                    binary_texture_references=binary_texture_references,
                    sidecar_texture_references=sidecar_texture_references,
                    texture_entries_by_normalized_path=texture_entries_by_normalized_path,
                    texture_entries_by_basename=texture_entries_by_basename,
                    sidecar_texts_by_normalized_path=sidecar_texts_by_normalized_path,
                    sidecar_texts_by_basename=sidecar_texts_by_basename,
                )
            )
            graph_references = build_archive_relationship_references(
                entry,
                archive_entries_by_normalized_path=texture_entries_by_normalized_path,
                archive_entries_by_basename=texture_entries_by_basename,
            )
            model_texture_references = merge_archive_reference_rows(model_texture_references, graph_references)
            add_timing("model_texture_references_s", references_started_at)
            if enable_hkx_visual_preview and model_preview is not None and model_texture_references:
                overlay_started_at = time.perf_counter()
                overlay_notes = _attach_hkx_physics_overlay_to_model_preview(
                    model_preview,
                    model_texture_references,
                    stop_event=stop_event,
                )
                if overlay_notes:
                    info_extra_parts.extend(overlay_notes)
                add_timing("hkx_physics_overlay_s", overlay_started_at)
        binary_preview_started_at = time.perf_counter()
        preferred_view, preview_text, info_extra = build_archive_binary_preview_payload(
            entry,
            data,
            info_extra="\n".join(info_extra_parts),
        )
        shared_analysis = load_archive_content_analysis(entry)
        if shared_analysis is not None:
            shared_note = (
                f"Shared decoder baseline: {shared_analysis.analyzer_version} "
                f"({shared_analysis.content_kind}, {shared_analysis.maturity})\n"
                f"Normalized JSON: {shared_analysis.json_path}"
            )
            info_extra = "\n\n".join(part for part in (info_extra, shared_note) if part)
            if model_preview is None:
                preview_text = shared_analysis.text
                preferred_view = "text"
        header_preview = format_binary_header_preview(data[:ARCHIVE_BINARY_HEX_PREVIEW_LIMIT])
        detail_text = build_archive_entry_detail_text(
            entry,
            "\n\n".join(part for part in [info_extra, f"Binary header preview:\n{header_preview}"] if part).strip(),
        )
        add_timing("binary_preview_s", binary_preview_started_at)
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=metadata_summary,
            detail_text=detail_text,
            quality_tier=normalized_quality_tier,
            timings=timings,
            preview_text=preview_text,
            preview_model=model_preview,
            model_texture_references=model_texture_references,
            asset_family_graph=build_archive_asset_family_graph(entry, model_texture_references),
            preferred_view="model" if model_preview is not None else preferred_view,
            warning_badge="Model preview fallback" if model_preview is None and model_preview_error else "",
            warning_text=model_preview_error if model_preview is None and model_preview_error else "",
            loose_file_path=loose_file_path,
            loose_preview_image_path=loose_preview_image_path,
            loose_preview_media_path=loose_preview_media_path,
            loose_preview_media_kind=loose_preview_media_kind,
            loose_preview_title=loose_preview_title,
            loose_preview_metadata_summary=loose_preview_metadata_summary,
            loose_preview_detail_text=loose_preview_detail_text,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        try:
            raw_data = read_archive_entry_raw_data(entry)
        except Exception:
            raw_data = b""
        preferred_view = "info"
        preview_text = ""
        raw_extra_parts = [
            f"Decoded preview failed: {exc}",
            "Showing raw stored bytes instead.",
        ]
        if raw_data:
            raw_preferred_view, raw_preview_text, raw_extra = build_archive_binary_preview_payload(
                entry,
                raw_data,
            )
            preferred_view = raw_preferred_view
            preview_text = raw_preview_text
            if raw_extra:
                raw_extra_parts.append(raw_extra)
        raw_header_preview = format_binary_header_preview(raw_data[:ARCHIVE_BINARY_HEX_PREVIEW_LIMIT])
        return ArchivePreviewResult(
            status="ok",
            title=entry.basename,
            metadata_summary=metadata_summary,
            detail_text=build_archive_entry_detail_text(
                entry,
                "\n\n".join(part for part in [*raw_extra_parts, f"Binary header preview:\n{raw_header_preview}"] if part),
            ),
            quality_tier=normalized_quality_tier,
            preview_text=preview_text,
            preferred_view=preferred_view,
            warning_badge="Raw bytes",
            warning_text="Showing raw stored bytes because the decoded preview path failed.",
            loose_file_path=loose_file_path,
            loose_preview_image_path=loose_preview_image_path,
            loose_preview_media_path=loose_preview_media_path,
            loose_preview_media_kind=loose_preview_media_kind,
            loose_preview_title=loose_preview_title,
            loose_preview_metadata_summary=loose_preview_metadata_summary,
            loose_preview_detail_text=loose_preview_detail_text,
        )
