from __future__ import annotations

import re
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple

from cdmw.constants import *
from cdmw.models import *
from cdmw.core.common import *
from cdmw.core.chainner import *
from cdmw.core.mod_package import (
    ModPackageExportOptions,
    mod_package_expanded_export_options,
    mod_package_export_options_for_profiles,
    mod_package_export_options_for_manager,
    mod_package_profile_uses_manager_metadata,
    resolve_mod_package_profile_root,
    write_mod_package_manifest,
)
from cdmw.core.realesrgan_ncnn import *
from cdmw.core.upscale_postprocess import (
    build_source_match_plan_for_decision,
    describe_post_upscale_correction_mode,
)
from cdmw.core.upscale_profiles import (
    copy_mod_ready_loose_tree,
    is_png_intermediate_high_risk,
    is_technical_texture_type,
    should_upscale_texture,
)
from cdmw.core.texture_pipeline.config import (
    ensure_existing_dir,
    ensure_existing_file,
    filter_matches,
    normalize_optional_path,
    normalize_required_path,
    parse_filter_patterns,
    require_existing_dir,
    require_existing_file,
    validate_choice as _validate_choice,
)
from cdmw.core.texture_pipeline.logging import write_csv_log
from cdmw.core.texture_pipeline.manifest import (
    build_incremental_manifest_entry,
    build_manifest_path,
    load_incremental_manifest,
    manifest_entry_matches,
    resolve_default_staging_png_root,
    save_incremental_manifest,
)
from cdmw.core.texture_pipeline.discovery import (
    collect_dds_files,
    find_png_matches,
    find_png_matches_across_roots,
    resolve_png,
)
from cdmw.core.texture_pipeline.inspection import (
    classify_crimson_dds_vpath_last4,
    crimson_dds_format_last4,
    describe_png_color_type,
    inspect_crimson_dds,
    parse_dds,
    png_has_alpha_channel,
    read_png_dimensions,
    read_png_header_info,
    validate_crimson_dds,
    validate_dds_payload_size,
)
from cdmw.core.texture_pipeline.package_export import (
    build_mod_package_export_options_from_config,
    resolve_default_mod_ready_export_root,
)
from cdmw.core.texture_pipeline.planning import (
    _build_loose_sidecar_index,
    _collect_loose_sidecar_texts,
    build_single_texture_processing_plan,
    build_texture_processing_plan,
)
from cdmw.core.texture_pipeline.preview import (
    _validate_high_precision_staged_png,
    build_compare_preview_pane_result,
    collect_compare_relative_paths,
    collect_relative_dds_paths,
    ensure_dds_display_preview_png,
    ensure_dds_preview_png,
    stage_dds_to_pngs,
)
from cdmw.core.texture_pipeline.preflight import (
    build_preflight_report_lines,
    build_texture_policy_preview_payload,
)
from cdmw.core.texture_pipeline.runtime_config import (
    _resolve_workflow_profiles_and_rules_from_config,
    _validate_workflow_rule_profile_links,
    normalize_config,
    normalize_config_for_planning,
    validate_backend_runtime_requirements,
)
from cdmw.core.texture_pipeline.workspace import (
    common_workspace_root_from_config,
    create_missing_directories_for_config,
    create_workspace_structure,
    suggested_workspace_paths,
)
from cdmw.domain.textures.plan import (
    _apply_workflow_profile_action_override,
    _build_backend_capability_matrix,
    _build_texture_processing_plan_entry,
    _dds_colorspace_intent_from_format,
    _decision_with_texture_rule_overrides,
    _effective_ncnn_settings,
    _effective_output_override,
    _infer_profile_key,
    _is_scalar_high_precision_candidate,
    _normalize_alpha_policy,
    _plan_path_kind,
    _profile_for_key,
    _semantic_override_components,
    _workflow_profile_for_rule,
    describe_processing_path_kind,
)
from cdmw.domain.textures.output import (
    _linear_variant,
    _resolve_plan_output_settings,
    _srgb_variant,
    apply_automatic_texture_rule_adjustments,
    apply_texture_rule_to_output_settings,
    apply_texture_workflow_output_override,
    max_mips_for_size,
    resolve_dds_output_settings,
    summarize_effective_dds_override,
    summarize_effective_ncnn_settings,
    summarize_texture_workflow_rule,
)
from cdmw.domain.textures.profiles import (
    _SCALAR_HIGH_PRECISION_MASK_SUBTYPES,
    build_default_texture_workflow_profiles,
    build_default_texture_workflow_rules,
    get_texture_processing_profile_keys,
    should_seed_default_texture_workflow_state,
    upgrade_default_texture_workflow_state,
)
from cdmw.domain.textures.rules import (
    _VALID_RULE_ALPHA_POLICIES,
    _VALID_RULE_COLORSPACE_OVERRIDES,
    _VALID_RULE_INTERMEDIATE_OVERRIDES,
    _VALID_RULE_MATCH_MODES,
    _VALID_WORKFLOW_PROFILE_ACTIONS,
    _coerce_optional_positive_int,
    _make_unique_workflow_profile_id,
    _normalize_rule_match_mode,
    _normalize_workflow_action_mode,
    _rule_matches_path,
    coerce_texture_workflow_profiles,
    coerce_texture_workflow_rules,
    find_matching_texture_rule,
    migrate_legacy_texture_rules_to_structured,
    parse_texture_rules,
)

def scan_dds_files(config: AppConfig, stop_event: Optional[threading.Event] = None) -> ScanResult:
    original_root = ensure_existing_dir(
        normalize_required_path(config.original_dds_root, "Original DDS root"),
        "Original DDS root",
    )
    include_filters = parse_filter_patterns(config.include_filters)
    files = collect_dds_files(original_root, include_filters, stop_event=stop_event)
    return ScanResult(total_files=len(files), files=files)


def convert_dds_to_pngs(
    config: AppConfig,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_total: Optional[Callable[[int], None]] = None,
    on_current_file: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, int, int, int], None]] = None,
    on_phase: Optional[Callable[[str, str, bool], None]] = None,
    on_phase_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> RunSummary:
    original_dds_root = ensure_existing_dir(
        normalize_required_path(config.original_dds_root, "Original DDS root"),
        "Original DDS root",
    )
    png_root = normalize_required_path(config.png_root, "PNG root")
    include_filters = parse_filter_patterns(config.include_filters)
    csv_log_path = normalize_optional_path(config.csv_log_path) if config.csv_log_enabled else None
    if config.csv_log_enabled and csv_log_path is None:
        raise ValueError("CSV log is enabled, but the CSV log path is empty.")

    png_root.mkdir(parents=True, exist_ok=True)

    def emit_log(message: str) -> None:
        if on_log:
            on_log(message)

    def emit_progress(processed: int, total: int, converted: int, skipped: int, failed: int) -> None:
        if on_progress:
            on_progress(processed, total, converted, skipped, failed)

    def emit_phase(name: str, detail: str, indeterminate: bool) -> None:
        if on_phase:
            on_phase(name, detail, indeterminate)

    def emit_phase_progress(current: int, total: int, detail: str) -> None:
        if on_phase_progress:
            on_phase_progress(current, total, detail)

    emit_log(
        "DDS -> PNG configuration: "
        f"dry_run={'on' if config.dry_run else 'off'}, "
        f"png_root={png_root}."
    )
    emit_log("Scanning DDS files...")
    dds_files = collect_dds_files(
        original_dds_root,
        include_filters,
        stop_event=stop_event,
    )
    total = len(dds_files)
    if total == 0:
        raise ValueError("No DDS files were found under the original root with the current filter.")

    emit_log(f"Found {total} DDS files to convert.")
    if on_total:
        on_total(total)
    emit_phase("DDS to PNG", f"Converting DDS files to PNG in {png_root}...", False)
    emit_phase_progress(0, total, f"0 / {total} DDS files")
    emit_progress(0, total, 0, 0, 0)

    results: List[JobResult] = []
    converted = 0
    skipped = 0
    failed = 0
    cancelled = False

    try:
        for index, dds_path in enumerate(dds_files, start=1):
            raise_if_cancelled(stop_event)
            rel_path = dds_path.relative_to(original_dds_root)
            rel_display = rel_path.as_posix()
            target_dir = png_root / rel_path.parent
            target_png = png_root / rel_path.with_suffix(".png")

            if on_current_file:
                on_current_file(rel_display)
            emit_progress(index - 1, total, converted, skipped, failed)
            emit_phase_progress(index - 1, total, f"{index - 1} / {total} DDS files")

            target_dir.mkdir(parents=True, exist_ok=True)

            should_skip = False
            if target_png.exists():
                try:
                    should_skip = target_png.stat().st_mtime_ns >= dds_path.stat().st_mtime_ns and target_png.stat().st_size > 0
                except OSError:
                    should_skip = False

            try:
                dds_info = parse_dds(dds_path)
            except RunCancelled:
                raise
            except Exception:
                dds_info = None

            if should_skip:
                skipped += 1
                note = "PNG is newer than source DDS"
                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str(target_png),
                        output_dir=str(target_dir),
                        width=dds_info.width if dds_info is not None else 0,
                        height=dds_info.height if dds_info is not None else 0,
                        original_mips=dds_info.mip_count if dds_info is not None else 0,
                        used_mips=dds_info.mip_count if dds_info is not None else 0,
                        dds_format=dds_info.dds_format if dds_info is not None else "",
                        status="skipped",
                        note=note,
                    )
                )
                emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                emit_progress(index, total, converted, skipped, failed)
                emit_phase_progress(index, total, f"{index} / {total} DDS files")
                continue

            action = "DRYRUN" if config.dry_run else "CONVERT"
            emit_log(f"[{index}/{total}] {action} {rel_display} -> {target_png.relative_to(png_root).as_posix()}")

            try:
                if config.dry_run:
                    converted += 1
                    status = "dry-run"
                    note = "planned DDS to PNG conversion"
                else:
                    preview_started = time.perf_counter()
                    preview_path = ensure_dds_display_preview_png(
                        dds_path,
                        dds_info=dds_info,
                        max_dimension=0,
                        stop_event=stop_event,
                    )
                    if Path(preview_path).resolve() != target_png.resolve():
                        shutil.copy2(preview_path, target_png)
                    try:
                        produced_size = target_png.stat().st_size
                    except OSError:
                        produced_size = 0
                    if produced_size <= 0:
                        failed += 1
                        status = "failed"
                        note = f"DDS preview backend did not produce expected PNG: {target_png}"
                    else:
                        converted += 1
                        status = "converted"
                        report = {}
                        try:
                            from cdmw.core.texture_native import read_native_texture_report_sidecar

                            report = read_native_texture_report_sidecar(Path(preview_path))
                        except Exception:
                            report = {}
                        backend = str(report.get("backend") or "directxtex_decode")
                        elapsed_seconds = time.perf_counter() - preview_started
                        note = f"DDS converted to PNG with {backend} in {elapsed_seconds:.1f}s ({produced_size:,} bytes)"

                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str(target_png),
                        output_dir=str(target_dir),
                        width=dds_info.width if dds_info is not None else 0,
                        height=dds_info.height if dds_info is not None else 0,
                        original_mips=dds_info.mip_count if dds_info is not None else 0,
                        used_mips=dds_info.mip_count if dds_info is not None else 0,
                        dds_format=dds_info.dds_format if dds_info is not None else "",
                        status=status,
                        note=note,
                    )
                )
                if status == "failed":
                    emit_log(f"[{index}/{total}] FAIL {rel_display} -> {note}")
            except RunCancelled:
                raise
            except Exception as exc:
                failed += 1
                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str(target_png),
                        output_dir=str(target_dir),
                        width=dds_info.width if dds_info is not None else 0,
                        height=dds_info.height if dds_info is not None else 0,
                        original_mips=dds_info.mip_count if dds_info is not None else 0,
                        used_mips=dds_info.mip_count if dds_info is not None else 0,
                        dds_format=dds_info.dds_format if dds_info is not None else "",
                        status="failed",
                        note=str(exc),
                    )
                )
                emit_log(f"[{index}/{total}] FAIL {rel_display} -> {exc}")

            emit_progress(index, total, converted, skipped, failed)
            emit_phase_progress(index, total, f"{index} / {total} DDS files")
    except RunCancelled as exc:
        cancelled = True
        emit_log(str(exc))

    if csv_log_path:
        write_csv_log(csv_log_path, results)
        emit_log(f"CSV log written to: {csv_log_path}")

    return RunSummary(
        total_files=total,
        converted=converted,
        skipped=skipped,
        failed=failed,
        cancelled=cancelled,
        log_csv_path=csv_log_path,
        results=results,
    )


def overlay_texture_editor_pngs(
    texture_editor_png_root: Optional[Path],
    target_root: Path,
    relative_paths: Sequence[Path],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> int:
    if texture_editor_png_root is None:
        return 0
    if not texture_editor_png_root.exists() or not texture_editor_png_root.is_dir():
        return 0
    if texture_editor_png_root.resolve() == target_root.resolve():
        return 0

    copied = 0
    for relative_path in relative_paths:
        raise_if_cancelled(stop_event)
        relative_png = Path(PurePosixPath(relative_path).with_suffix(".png").as_posix())
        source_png = texture_editor_png_root / relative_png
        if not source_png.exists() or not source_png.is_file():
            continue
        destination_png = target_root / relative_png
        destination_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_png, destination_png)
        copied += 1
        if on_log is not None:
            on_log(
                f"Applied Texture Editor PNG override: {source_png.name} -> {destination_png.relative_to(target_root).as_posix()}"
            )

    if copied > 0 and on_log is not None:
        on_log(f"Applied {copied} Texture Editor PNG override(s) into {target_root}.")
    return copied


def rebuild_dds_files(
    config: AppConfig,
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_total: Optional[Callable[[int], None]] = None,
    on_current_file: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[int, int, int, int, int], None]] = None,
    on_phase: Optional[Callable[[str, str, bool], None]] = None,
    on_phase_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> RunSummary:
    normalized = normalize_config(config, validate_backend_runtime=False)
    normalized.output_root.mkdir(parents=True, exist_ok=True)
    active_png_root = normalized.png_root

    def emit_log(message: str) -> None:
        if on_log:
            on_log(message)

    def emit_progress(processed: int, total: int, converted: int, skipped: int, failed: int) -> None:
        if on_progress:
            on_progress(processed, total, converted, skipped, failed)

    def emit_phase(name: str, detail: str, indeterminate: bool) -> None:
        if on_phase:
            on_phase(name, detail, indeterminate)

    def emit_phase_progress(current: int, total: int, detail: str) -> None:
        if on_phase_progress:
            on_phase_progress(current, total, detail)

    emit_log(
        "Build configuration: "
        f"upscale_backend={normalized.upscale_backend}, "
        f"dds_staging={'enabled' if normalized.enable_dds_staging else 'disabled'}, "
        f"incremental_resume={'enabled' if normalized.enable_incremental_resume else 'disabled'}, "
        f"dry_run={'on' if normalized.dry_run else 'off'}, "
        f"dds_format_mode={normalized.dds_format_mode}, "
        f"dds_size_mode={normalized.dds_size_mode}, "
        f"dds_mip_mode={normalized.dds_mip_mode}, "
        f"overwrite_existing_dds={'on' if normalized.overwrite_existing_dds else 'off'}."
    )
    if normalized.enable_unsafe_technical_override:
        emit_log(
            "Expert unsafe technical override is enabled. Technical maps may be forced through the generic visible-color PNG/upscale path instead of being preserved."
        )
    if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER:
        emit_log(f"chaiNNer executable: {normalized.chainner_exe_path}")
        emit_log(f"chaiNNer chain: {normalized.chainner_chain_path}")
    elif normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
        emit_log(f"Real-ESRGAN NCNN executable: {normalized.ncnn_exe_path}")
        emit_log(f"Real-ESRGAN NCNN model folder: {normalized.ncnn_model_dir}")
        emit_log(f"Real-ESRGAN NCNN model: {normalized.ncnn_model_name}")
        emit_log(
            f"Real-ESRGAN NCNN scale/tile/preset: {normalized.ncnn_scale}x / tile {normalized.ncnn_tile_size} / {normalized.upscale_texture_preset}"
        )
        emit_log(f"Direct post-upscale correction: {normalized.upscale_post_correction_mode}")
    else:
        emit_log("Upscaling stage is disabled, so the app will rebuild DDS from the existing PNG root.")
    emit_log(
        f"Automatic texture rules={'enabled' if normalized.enable_automatic_texture_rules else 'disabled'}, "
        f"retry_smaller_tile={'enabled' if normalized.retry_smaller_tile_on_failure else 'disabled'}, "
        f"ready_mod_package={'enabled' if normalized.enable_mod_ready_loose_export else 'disabled'}."
    )
    if normalized.enable_mod_ready_loose_export and normalized.mod_ready_export_root is not None:
        expanded_options = mod_package_expanded_export_options(normalized.mod_ready_export_options, kind="dds_loose_mod")
        package_roots = [
            resolve_mod_package_profile_root(
                normalized.mod_ready_export_root,
                normalized.mod_ready_package_info,
                str(getattr(profile_options, "output_profile_suffix", "") or profile),
                multi_profile=bool(getattr(profile_options, "output_profile_suffix", "")),
            )
            for profile, profile_options in expanded_options
        ]
        emit_log(f"Mod package parent root: {normalized.mod_ready_export_root}")
        emit_log(f"Mod package folder: {', '.join(path.name for path in package_roots)}")
        emit_log(f"Create .no_encrypt file: {'yes' if normalized.mod_ready_create_no_encrypt_file else 'no'}")
    if normalized.texture_editor_png_root is not None:
        emit_log(
            f"Texture Editor PNG override root: {normalized.texture_editor_png_root} "
            "(matching relative PNGs here take precedence over PNG root)."
        )
    if normalized.enable_dds_staging:
        if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER:
            emit_log(
                f"File flow: Original DDS -> Staging PNG root ({normalized.dds_staging_root}) -> chaiNNer -> PNG root ({normalized.png_root}) -> DDS rebuild -> Output root ({normalized.output_root})"
            )
        elif normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
            emit_log(
                f"File flow: Original DDS -> Staging PNG root ({normalized.dds_staging_root}) -> Real-ESRGAN NCNN -> PNG root ({normalized.png_root}) -> DDS rebuild -> Output root ({normalized.output_root})"
            )
        else:
            emit_log(
                f"File flow: Original DDS -> PNG root ({normalized.png_root}). With no backend selected, processing stops after PNG conversion."
            )
    else:
        if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER:
            emit_log(
                f"File flow: Existing PNG root ({normalized.png_root}) -> chaiNNer -> PNG root ({normalized.png_root}) -> DDS rebuild -> Output root ({normalized.output_root})"
            )
        elif normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN:
            emit_log(
                f"File flow: Existing PNG root ({normalized.png_root}) -> Real-ESRGAN NCNN -> PNG root ({normalized.png_root}) -> DDS rebuild -> Output root ({normalized.output_root})"
            )
        else:
            emit_log(
                f"File flow: Existing PNG root ({normalized.png_root}) -> DDS rebuild -> Output root ({normalized.output_root})"
            )

    emit_log("Scanning DDS files...")
    dds_files = collect_dds_files(
        normalized.original_dds_root,
        normalized.include_filter_patterns,
        stop_event=stop_event,
    )
    total = len(dds_files)
    if total == 0:
        raise ValueError("No DDS files were found under the original root with the current filter.")

    emit_log(f"Found {total} DDS files matching the current filter.")
    if on_total:
        on_total(total)
    emit_progress(0, total, 0, 0, 0)

    backend_matrix = _build_backend_capability_matrix(normalized)
    processing_plan = build_texture_processing_plan(normalized, dds_files, backend_matrix=backend_matrix)
    plan_by_rel = {entry.relative_path.as_posix(): entry for entry in processing_plan}
    plan_entries_requiring_png = [entry for entry in processing_plan if entry.requires_png_processing]
    dds_files_requiring_png = [entry.dds_path for entry in plan_entries_requiring_png]
    staging_failures: Dict[str, str] = {}

    if normalized.upscale_backend == UPSCALE_BACKEND_NONE or dds_files_requiring_png:
        normalized = validate_backend_runtime_requirements(normalized)
    elif normalized.upscale_backend != UPSCALE_BACKEND_NONE:
        emit_log(
            "Backend/runtime validation was skipped because the current preset and automatic rules kept every matched DDS out of the PNG/upscale path."
        )

    chain_analysis = (
        analyze_chainner_chain(normalized.chainner_chain_path, normalized)
        if normalized.enable_chainner and normalized.chainner_chain_path and dds_files_requiring_png
        else None
    )
    if chain_analysis is not None:
        backend_matrix = _build_backend_capability_matrix(normalized, chain_analysis=chain_analysis)
        processing_plan = build_texture_processing_plan(normalized, dds_files, backend_matrix=backend_matrix)
        plan_by_rel = {entry.relative_path.as_posix(): entry for entry in processing_plan}
        plan_entries_requiring_png = [entry for entry in processing_plan if entry.requires_png_processing]
        dds_files_requiring_png = [entry.dds_path for entry in plan_entries_requiring_png]
    for line in build_preflight_report_lines(
        normalized,
        dds_files,
        processing_plan=processing_plan,
        chain_analysis=chain_analysis,
        backend_matrix=backend_matrix,
        texture_rules=normalized.texture_rules,
        stop_event=stop_event,
    ):
        emit_log(line)

    if normalized.enable_dds_staging and dds_files_requiring_png:
        staging_failures = stage_dds_to_pngs(
            normalized,
            plan_entries_requiring_png,
            on_log=on_log,
            on_phase=on_phase,
            on_phase_progress=on_phase_progress,
            on_current_file=on_current_file,
            stop_event=stop_event,
        )
        if staging_failures:
            emit_log(f"DDS staging completed with {len(staging_failures)} failed file(s); failed files will be reported in the rebuild summary.")
        if normalized.upscale_backend == UPSCALE_BACKEND_NONE and normalized.dds_staging_root is not None:
            active_png_root = normalized.dds_staging_root
    elif normalized.enable_dds_staging:
        emit_log("DDS staging skipped because no files require PNG/upscale processing under the current policy.")

    backend_processing_plan = [
        entry for entry in processing_plan if entry.relative_path.as_posix() not in staging_failures
    ]
    backend_plan_entries_requiring_png = [
        entry for entry in plan_entries_requiring_png if entry.relative_path.as_posix() not in staging_failures
    ]
    backend_dds_files_requiring_png = [entry.dds_path for entry in backend_plan_entries_requiring_png]

    if backend_dds_files_requiring_png:
        overlay_texture_editor_pngs(
            normalized.texture_editor_png_root,
            active_png_root,
            [entry.relative_path for entry in backend_plan_entries_requiring_png],
            on_log=on_log,
            stop_event=stop_event,
        )

    if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER and backend_dds_files_requiring_png:
        run_chainner_stage(
            normalized,
            input_root=active_png_root,
            expected_relative_paths=[entry.relative_path.with_suffix(".png") for entry in backend_plan_entries_requiring_png],
            expected_output_total=len(backend_dds_files_requiring_png),
            on_log=on_log,
            on_phase=on_phase,
            on_phase_progress=on_phase_progress,
            on_current_file=on_current_file,
            stop_event=stop_event,
        )
    elif normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN and backend_dds_files_requiring_png:
        run_realesrgan_ncnn_stage(
            normalized,
            processing_plan=backend_processing_plan,
            on_log=on_log,
            on_phase=on_phase,
            on_phase_progress=on_phase_progress,
            on_current_file=on_current_file,
            stop_event=stop_event,
        )
    elif normalized.upscale_backend != UPSCALE_BACKEND_NONE:
        emit_log("No files require direct PNG/upscale processing under the current preset and automatic rules. The selected backend will be skipped.")

    relative_png_index: Dict[str, Path] = {}
    basename_png_index: Dict[str, List[Path]] = {}
    png_count = 0
    if backend_dds_files_requiring_png:
        emit_phase("DDS Rebuild", "Indexing PNG files...", False)
        emit_phase_progress(0, 0, "Indexing PNG files...")
        emit_log("Indexing PNG files...")
        relative_png_index, basename_png_index, png_count = find_png_matches_across_roots(
            (
                active_png_root,
                normalized.texture_editor_png_root
                if normalized.texture_editor_png_root is not None
                and normalized.texture_editor_png_root.resolve() != active_png_root.resolve()
                else None,
            ),
            stop_event=stop_event,
        )
        emit_log(f"Indexed {png_count} PNG files.")
        if normalized.upscale_backend == UPSCALE_BACKEND_CHAINNER and png_count == 0 and backend_dds_files_requiring_png:
            chain_analysis = chain_analysis or ChainnerChainAnalysis()
            detail = ""
            if chain_analysis.warnings:
                detail = " " + " | ".join(chain_analysis.warnings[:3])
            raise ValueError(
                "chaiNNer finished, but no PNG files were found in the configured PNG root. "
                "The chain likely still points at old folders or writes somewhere else."
                + detail
            )
        if normalized.upscale_backend == UPSCALE_BACKEND_REALESRGAN_NCNN and png_count == 0 and backend_dds_files_requiring_png:
            raise ValueError(
                "Real-ESRGAN NCNN finished, but no PNG files were found in the configured PNG root. "
                "Verify the NCNN executable, model folder, and selected model."
            )
    else:
        emit_log("No policy-selected files require PNG matching. DDS rebuild will use preserve-original copy-through actions only.")
    emit_phase_progress(0, total, f"0 / {total} DDS files")
    emit_log(
        f"Found {total} DDS files to process. "
        f"{len(dds_files_requiring_png)} file(s) require PNG/upscale processing under the current policy."
    )
    emit_phase("DDS Rebuild", "Converting PNG files to DDS...", False)

    results: List[JobResult] = []
    converted = 0
    skipped = 0
    failed = 0
    cancelled = False
    manifest_entries: Dict[str, Dict[str, object]] = {}
    manifest_path: Optional[Path] = None
    if normalized.enable_incremental_resume:
        manifest_path = build_manifest_path(normalized.output_root)
        manifest_entries = load_incremental_manifest(manifest_path)
        emit_log(f"Incremental manifest: {manifest_path}")
    native_encoded_outputs: Dict[str, Dict[str, Any]] = {}

    def _resolved_output_key(path: Path) -> str:
        try:
            return str(path.expanduser().resolve())
        except OSError:
            return str(path)

    def _prebuild_directxtex_batch_outputs() -> None:
        nonlocal native_encoded_outputs
        if normalized.dry_run or not backend_dds_files_requiring_png:
            return
        try:
            from cdmw.core.texture_native import encode_dds_batch_with_directxtex, find_directxtex_texture_binary
        except Exception as exc:
            emit_log(f"Native DDS batch encode is unavailable ({exc}).")
            return
        if find_directxtex_texture_binary() is None:
            emit_log("Native DDS batch encode is unavailable because cd-texture-dx.exe is missing.")
            return
        jobs: List[Dict[str, object]] = []
        for dds_path in dds_files:
            raise_if_cancelled(stop_event)
            rel_path = dds_path.relative_to(normalized.original_dds_root)
            rel_display = rel_path.as_posix()
            if rel_display in staging_failures:
                continue
            plan_entry = plan_by_rel.get(rel_display)
            if plan_entry is None or plan_entry.action in {"preserve_original", "skip_by_rule"}:
                continue
            png_path, _match_note = resolve_png(
                rel_path,
                relative_png_index,
                basename_png_index,
                normalized.allow_unique_basename_fallback,
            )
            if png_path is None:
                continue
            try:
                if _validate_high_precision_staged_png(png_path, plan_entry) is not None:
                    continue
                png_width, png_height = read_png_dimensions(png_path)
                png_has_alpha = png_has_alpha_channel(png_path)
                output_settings = _resolve_plan_output_settings(
                    normalized,
                    plan_entry,
                    png_width,
                    png_height,
                    has_alpha=png_has_alpha,
                )
                target_file = normalized.output_root / rel_path
                if manifest_path is not None and manifest_entry_matches(
                    manifest_entries.get(rel_path.as_posix(), {}),
                    dds_path,
                    png_path,
                    target_file,
                    output_settings,
                ):
                    continue
                if target_file.exists() and not normalized.overwrite_existing_dds:
                    continue
                jobs.append(
                    {
                        "png_path": str(png_path),
                        "output_path": str(target_file),
                        "format": output_settings.dds_format,
                        "width": output_settings.width if output_settings.resize_to_dimensions else 0,
                        "height": output_settings.height if output_settings.resize_to_dimensions else 0,
                        "mip_count": output_settings.mip_count,
                        "overwrite": normalized.overwrite_existing_dds,
                        "source_color_policy": output_settings.source_color_policy,
                        "mip_alpha_policy": output_settings.mip_alpha_policy,
                        "alpha_coverage_reference": output_settings.alpha_coverage_reference,
                        "dds_alpha_mode": output_settings.dds_alpha_mode,
                    }
                )
            except RunCancelled:
                raise
            except Exception:
                continue
        if not jobs:
            return
        emit_log(f"Native DDS batch encode: processing {len(jobs):,} file(s).")
        try:
            native_encoded_outputs = encode_dds_batch_with_directxtex(
                jobs,
                on_log=on_log,
                stop_event=stop_event,
            )
        except RunCancelled:
            raise
        except Exception as exc:
            native_encoded_outputs = {}
            emit_log(f"Native DDS batch encode failed ({exc}).")
            return
        if native_encoded_outputs:
            emit_log(
                f"Native DDS batch encode produced {len(native_encoded_outputs):,} DDS file(s)."
            )
        else:
            emit_log("Native DDS batch encode produced no DDS files.")

    _prebuild_directxtex_batch_outputs()

    try:
        for index, dds_path in enumerate(dds_files, start=1):
            raise_if_cancelled(stop_event)

            rel_path = dds_path.relative_to(normalized.original_dds_root)
            rel_display = rel_path.as_posix()
            target_dir = normalized.output_root / rel_path.parent
            target_file = normalized.output_root / rel_path

            if on_current_file:
                on_current_file(rel_display)
            emit_progress(index - 1, total, converted, skipped, failed)
            emit_phase_progress(index - 1, total, f"{index - 1} / {total} DDS files")

            plan_entry = plan_by_rel.get(rel_display)
            if plan_entry is None:
                raise RuntimeError(f"Missing planner entry for DDS rebuild: {rel_display}")
            dds_info = plan_entry.dds_info
            decision = plan_entry.decision
            if rel_display in staging_failures:
                failed += 1
                note = f"DDS staging failed before rebuild: {staging_failures[rel_display]}"
                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str((normalized.dds_staging_root / rel_path.with_suffix(".png")) if normalized.dds_staging_root is not None else ""),
                        output_dir=str(target_dir),
                        width=dds_info.width,
                        height=dds_info.height,
                        original_mips=dds_info.mip_count,
                        used_mips=0,
                        dds_format=dds_info.dds_format,
                        status="failed",
                        note=note,
                    )
                )
                emit_log(f"[{index}/{total}] FAIL {rel_display} -> {note}")
                emit_progress(index, total, converted, skipped, failed)
                emit_phase_progress(index, total, f"{index} / {total} DDS files")
                continue
            if plan_entry.action in {"preserve_original", "skip_by_rule"}:
                if plan_entry.action == "skip_by_rule":
                    skipped += 1
                    note = plan_entry.action_reason
                    results.append(
                        JobResult(
                            original_dds=str(dds_path),
                            png="",
                            output_dir=str(target_dir),
                            width=dds_info.width,
                            height=dds_info.height,
                            original_mips=dds_info.mip_count,
                            used_mips=dds_info.mip_count,
                            dds_format=dds_info.dds_format,
                            status="skipped",
                            note=note,
                        )
                    )
                    emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                    emit_progress(index, total, converted, skipped, failed)
                    emit_phase_progress(index, total, f"{index} / {total} DDS files")
                    continue

                target_dir.mkdir(parents=True, exist_ok=True)
                note_parts = [
                    plan_entry.preserve_reason
                    or (
                        f"automatic policy preserved source DDS [{decision.texture_type}/{decision.semantic_subtype}]"
                        if decision.preserve_original_due_to_intermediate
                        else f"preset kept source DDS unchanged [{decision.texture_type}/{decision.semantic_subtype}]"
                    ),
                    f"planner profile={plan_entry.profile.key}",
                    f"planner path={plan_entry.path_kind}",
                    f"planner alpha_policy={plan_entry.alpha_policy}",
                    *decision.notes,
                ]
                if target_file.exists() and not normalized.overwrite_existing_dds:
                    skipped += 1
                    note = "; ".join(note_parts + ["existing DDS kept because overwrite is disabled"])
                    results.append(
                        JobResult(
                            original_dds=str(dds_path),
                            png="",
                            output_dir=str(target_dir),
                            width=dds_info.width,
                            height=dds_info.height,
                            original_mips=dds_info.mip_count,
                            used_mips=dds_info.mip_count,
                            dds_format=dds_info.dds_format,
                            status="skipped",
                            note=note,
                        )
                    )
                    emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                    emit_progress(index, total, converted, skipped, failed)
                    emit_phase_progress(index, total, f"{index} / {total} DDS files")
                    continue

                if normalized.dry_run:
                    converted += 1
                    status = "dry-run"
                    note = "; ".join(note_parts + ["planned DDS passthrough"])
                    emit_log(f"[{index}/{total}] DRYRUN COPY {rel_display} [{decision.texture_type}] -> original DDS passthrough")
                else:
                    shutil.copy2(dds_path, target_file)
                    converted += 1
                    status = "converted"
                    note = "; ".join(note_parts)
                    emit_log(f"[{index}/{total}] COPY {rel_display} [{decision.texture_type}] -> kept original DDS")

                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png="",
                        output_dir=str(target_dir),
                        width=dds_info.width,
                        height=dds_info.height,
                        original_mips=dds_info.mip_count,
                        used_mips=dds_info.mip_count,
                        dds_format=dds_info.dds_format,
                        status=status,
                        note=note,
                    )
                )
                emit_progress(index, total, converted, skipped, failed)
                emit_phase_progress(index, total, f"{index} / {total} DDS files")
                continue

            png_path, match_note = resolve_png(
                rel_path,
                relative_png_index,
                basename_png_index,
                normalized.allow_unique_basename_fallback,
            )

            if png_path is None:
                if plan_entry.path_kind == "technical_high_precision_path":
                    target_dir.mkdir(parents=True, exist_ok=True)
                    note_parts = [
                        "technical high-precision path fallback preserved the original DDS",
                        match_note,
                        f"planner profile={plan_entry.profile.key}",
                        f"planner path={plan_entry.path_kind}",
                        f"planner alpha_policy={plan_entry.alpha_policy}",
                    ]
                    if target_file.exists() and not normalized.overwrite_existing_dds:
                        skipped += 1
                        note = "; ".join(note_parts + ["existing DDS kept because overwrite is disabled"])
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png="",
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="skipped",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                    elif normalized.dry_run:
                        converted += 1
                        note = "; ".join(note_parts + ["planned DDS passthrough"])
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png="",
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="dry-run",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] DRYRUN COPY {rel_display} [{decision.texture_type}] -> high-precision PNG missing fallback")
                    else:
                        shutil.copy2(dds_path, target_file)
                        converted += 1
                        note = "; ".join(note_parts)
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png="",
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="converted",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] COPY {rel_display} [{decision.texture_type}] -> high-precision PNG missing fallback kept original DDS")
                else:
                    skipped += 1
                    results.append(
                        JobResult(
                            original_dds=str(dds_path),
                            png="",
                            output_dir=str(target_dir),
                            width=0,
                            height=0,
                            original_mips=0,
                            used_mips=0,
                            dds_format="",
                            status="skipped",
                            note=match_note,
                        )
                    )
                    emit_log(f"[{index}/{total}] SKIP {rel_display} -> {match_note}")
                emit_progress(index, total, converted, skipped, failed)
                emit_phase_progress(index, total, f"{index} / {total} DDS files")
                continue

            try:
                high_precision_validation_message = _validate_high_precision_staged_png(png_path, plan_entry)
                if high_precision_validation_message is not None:
                    target_dir.mkdir(parents=True, exist_ok=True)
                    note_parts = [
                        "technical high-precision path fallback preserved the original DDS",
                        high_precision_validation_message,
                        f"planner profile={plan_entry.profile.key}",
                        f"planner path={plan_entry.path_kind}",
                        f"planner alpha_policy={plan_entry.alpha_policy}",
                    ]
                    if target_file.exists() and not normalized.overwrite_existing_dds:
                        skipped += 1
                        note = "; ".join(note_parts + ["existing DDS kept because overwrite is disabled"])
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png=str(png_path),
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="skipped",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                    elif normalized.dry_run:
                        converted += 1
                        note = "; ".join(note_parts + ["planned DDS passthrough"])
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png=str(png_path),
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="dry-run",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] DRYRUN COPY {rel_display} [{decision.texture_type}] -> high-precision stage validation fallback")
                    else:
                        shutil.copy2(dds_path, target_file)
                        converted += 1
                        note = "; ".join(note_parts)
                        results.append(
                            JobResult(
                                original_dds=str(dds_path),
                                png=str(png_path),
                                output_dir=str(target_dir),
                                width=dds_info.width,
                                height=dds_info.height,
                                original_mips=dds_info.mip_count,
                                used_mips=dds_info.mip_count,
                                dds_format=dds_info.dds_format,
                                status="converted",
                                note=note,
                            )
                        )
                        emit_log(f"[{index}/{total}] COPY {rel_display} [{decision.texture_type}] -> high-precision stage validation fallback kept original DDS")
                    emit_progress(index, total, converted, skipped, failed)
                    emit_phase_progress(index, total, f"{index} / {total} DDS files")
                    continue

                png_width, png_height = read_png_dimensions(png_path)
                png_has_alpha = png_has_alpha_channel(png_path)
                notes = [match_note]
                output_settings = _resolve_plan_output_settings(
                    normalized,
                    plan_entry,
                    png_width,
                    png_height,
                    has_alpha=png_has_alpha,
                )
                notes.extend(
                    [
                        f"planner profile={plan_entry.profile.key}",
                        f"planner path={plan_entry.path_kind}",
                        f"planner alpha_policy={plan_entry.alpha_policy}",
                    ]
                )
                if plan_entry.backend_capability.reason:
                    notes.append(f"planner backend={plan_entry.backend_capability.reason}")
                notes.extend(output_settings.notes)

                if manifest_path is not None and manifest_entry_matches(
                    manifest_entries.get(rel_path.as_posix(), {}),
                    dds_path,
                    png_path,
                    target_file,
                    output_settings,
                ):
                    skipped += 1
                    note = "; ".join(notes + ["unchanged output detected by incremental manifest"])
                    results.append(
                        JobResult(
                            original_dds=str(dds_path),
                            png=str(png_path),
                            output_dir=str(target_dir),
                            width=output_settings.width,
                            height=output_settings.height,
                            original_mips=dds_info.mip_count,
                            used_mips=output_settings.mip_count,
                            dds_format=output_settings.dds_format,
                            status="skipped",
                            note=note,
                        )
                    )
                    emit_log(f"[{index}/{total}] SKIP {rel_display} -> unchanged output detected by incremental manifest")
                    emit_progress(index, total, converted, skipped, failed)
                    emit_phase_progress(index, total, f"{index} / {total} DDS files")
                    continue

                if target_file.exists() and not normalized.overwrite_existing_dds:
                    note = "output DDS already exists and overwrite is disabled"
                    skipped += 1
                    results.append(
                        JobResult(
                            original_dds=str(dds_path),
                            png=str(png_path),
                            output_dir=str(target_dir),
                            width=output_settings.width,
                            height=output_settings.height,
                            original_mips=dds_info.mip_count,
                            used_mips=output_settings.mip_count,
                            dds_format=output_settings.dds_format,
                            status="skipped",
                            note=note,
                        )
                    )
                    emit_log(f"[{index}/{total}] SKIP {rel_display} -> {note}")
                    emit_progress(index, total, converted, skipped, failed)
                    emit_phase_progress(index, total, f"{index} / {total} DDS files")
                    continue

                target_dir.mkdir(parents=True, exist_ok=True)

                action = "DRYRUN" if normalized.dry_run else "BUILD"
                emit_log(
                    f"[{index}/{total}] {action} {rel_display} "
                    f"-> format={output_settings.dds_format} mips={output_settings.mip_count} "
                    f"output={output_settings.width}x{output_settings.height} png={png_width}x{png_height}"
                )

                if normalized.dry_run:
                    converted += 1
                    status = "dry-run"
                    note = "; ".join(notes)
                else:
                    native_report = native_encoded_outputs.get(_resolved_output_key(target_file))
                    if native_report and target_file.is_file() and target_file.stat().st_size > 0:
                        output_size = target_file.stat().st_size
                        converted += 1
                        status = "converted"
                        encode_ms = native_report.get("encode_ms")
                        notes.append("DirectXTex native batch encode")
                        note = "; ".join(notes)
                        elapsed_text = f"{float(encode_ms) / 1000.0:.1f}s" if isinstance(encode_ms, (int, float)) else "native batch"
                        emit_log(
                            f"[{index}/{total}] BUILT {rel_display} with DirectXTex native batch in {elapsed_text} "
                            f"-> {target_file} ({output_size:,} bytes)"
                        )
                        if manifest_path is not None:
                            manifest_entries[rel_path.as_posix()] = build_incremental_manifest_entry(
                                dds_path,
                                png_path,
                                target_file,
                                output_settings,
                            )
                            save_incremental_manifest(manifest_path, manifest_entries)
                    else:
                        failed += 1
                        status = "failed"
                        detail = "Native DDS encode did not produce this output."
                        notes.append(detail)
                        note = "; ".join(notes)
                        emit_log(f"[{index}/{total}] FAIL {rel_display} -> {detail}")

                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str(png_path),
                        output_dir=str(target_dir),
                        width=output_settings.width,
                        height=output_settings.height,
                        original_mips=dds_info.mip_count,
                        used_mips=output_settings.mip_count,
                        dds_format=output_settings.dds_format,
                        status=status,
                        note=note,
                    )
                )
            except RunCancelled:
                raise
            except Exception as exc:
                failed += 1
                results.append(
                    JobResult(
                        original_dds=str(dds_path),
                        png=str(png_path),
                        output_dir=str(target_dir),
                        width=0,
                        height=0,
                        original_mips=0,
                        used_mips=0,
                        dds_format="",
                        status="failed",
                        note=str(exc),
                    )
                )
                emit_log(f"[{index}/{total}] FAIL {rel_display} -> {exc}")

            emit_progress(index, total, converted, skipped, failed)
            emit_phase_progress(index, total, f"{index} / {total} DDS files")
    except RunCancelled as exc:
        cancelled = True
        emit_log(str(exc))

    if normalized.csv_log_path:
        write_csv_log(normalized.csv_log_path, results)
        emit_log(f"CSV log written to: {normalized.csv_log_path}")

    if (
        normalized.enable_mod_ready_loose_export
        and normalized.mod_ready_export_root is not None
        and not cancelled
        and failed == 0
    ):
        emit_phase("Mod Package", "Writing ready mod package from final DDS output...", False)
        expanded_options = mod_package_expanded_export_options(
            normalized.mod_ready_export_options,
            kind="dds_loose_mod",
        )
        total_copied = 0
        total_skipped = 0
        total_failed = 0
        for profile, profile_options in expanded_options:
            final_package_root = resolve_mod_package_profile_root(
                normalized.mod_ready_export_root,
                normalized.mod_ready_package_info,
                str(getattr(profile_options, "output_profile_suffix", "") or profile),
                multi_profile=bool(getattr(profile_options, "output_profile_suffix", "")),
            )
            emit_log(f"Creating {profile} ready mod package under: {final_package_root}")
            export_result = copy_mod_ready_loose_tree(
                normalized.output_root,
                final_package_root,
                overwrite=True,
                dry_run=normalized.dry_run,
                on_log=None,
            )
            total_copied += export_result.copied_files
            total_skipped += export_result.skipped_files
            total_failed += export_result.failed_files
            if not normalized.dry_run:
                write_mod_package_manifest(
                    final_package_root,
                    normalized.mod_ready_package_info,
                    kind="dds_loose_mod",
                    extra_fields={"file_count": export_result.copied_files},
                    create_no_encrypt_file=profile_options.create_no_encrypt_file,
                    export_options=profile_options,
                )
        emit_log(
            "Ready mod package export complete: "
            f"copied={total_copied}, skipped={total_skipped}, failed={total_failed}"
        )

    return RunSummary(
        total_files=total,
        converted=converted,
        skipped=skipped,
        failed=failed,
        cancelled=cancelled,
        log_csv_path=normalized.csv_log_path,
        results=results,
    )


def run_cli(config: Optional[AppConfig] = None) -> int:
    active_config = config or default_config()

    def on_log(message: str) -> None:
        print(message)

    def on_total(total: int) -> None:
        print(f"Total DDS files found: {total}")

    try:
        summary = rebuild_dds_files(
            active_config,
            on_log=on_log,
            on_total=on_total,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("")
    print("Done.")
    print(f"Total DDS files: {summary.total_files}")
    print(f"Converted / planned: {summary.converted}")
    print(f"Skipped: {summary.skipped}")
    print(f"Failed: {summary.failed}")
    if summary.log_csv_path:
        print(f"CSV log: {summary.log_csv_path}")

    if summary.cancelled:
        return 1
    return 0 if summary.failed == 0 else 2
