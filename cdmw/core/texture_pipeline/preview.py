from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.common import raise_if_cancelled
from cdmw.core.texture_legacy_compat import resolve_deprecated_preview_source
from cdmw.core.texture_pipeline.inspection import describe_png_color_type, parse_dds, read_png_header_info
from cdmw.models import ComparePreviewPaneResult, DdsInfo, NormalizedConfig, RunCancelled, TextureProcessingPlan

_COMPARE_DISPLAY_PREVIEW_MAX_DIMENSION = 1536

def collect_relative_dds_paths(
    root: Path,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    if not root.exists() or not root.is_dir():
        return []
    files: List[Path] = []
    for path in root.rglob("*"):
        raise_if_cancelled(stop_event, "DDS path scan cancelled by user.")
        if not path.is_file() or path.suffix.lower() != ".dds":
            continue
        files.append(path.relative_to(root))
    files.sort()
    return files


def collect_compare_relative_paths(
    original_root: Path,
    output_root: Path,
    stop_event: Optional[threading.Event] = None,
) -> List[Path]:
    combined = set(collect_relative_dds_paths(original_root, stop_event=stop_event))
    combined.update(collect_relative_dds_paths(output_root, stop_event=stop_event))
    return sorted(combined)


def _staging_png_format_for_plan(entry: TextureProcessingPlan) -> str:
    if entry.path_kind == "technical_high_precision_path":
        return "R16_UNORM"
    return "R8G8B8A8_UNORM"


def _validate_high_precision_staged_png(
    png_path: Path,
    plan_entry: TextureProcessingPlan,
) -> Optional[str]:
    if str(plan_entry.path_kind or "").strip().lower() != "technical_high_precision_path":
        return None
    try:
        _width, _height, bit_depth, color_type = read_png_header_info(png_path)
    except Exception as exc:
        return f"Could not validate high-precision staged PNG: {exc}"
    if bit_depth < 16:
        return f"Expected a 16-bit staged PNG for the technical high-precision path, but got {bit_depth}-bit {describe_png_color_type(color_type)}."
    if color_type not in {0, 4}:
        return f"Expected a grayscale staged PNG for the technical high-precision path, but got {describe_png_color_type(color_type)}."
    if str(plan_entry.alpha_policy or "").strip().lower() == "none" and color_type == 4:
        return "Technical high-precision path unexpectedly staged grayscale+alpha PNG data for an alpha-free scalar texture."
    return None


def ensure_dds_preview_png(
    source_or_obsolete_backend: Optional[Path],
    dds_path: Optional[Path] = None,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    source_path = resolve_deprecated_preview_source(source_or_obsolete_backend, dds_path).expanduser().resolve()
    try:
        from cdmw.core.texture_native import ensure_native_dds_preview_png

        native_preview = ensure_native_dds_preview_png(
            source_path,
            max_dimension=4096,
            slot_kind="base",
            normal_space="auto",
            stop_event=stop_event,
        )
        if native_preview is not None:
            return native_preview
    except RunCancelled:
        raise
    except Exception as exc:
        raise ValueError(f"Native DDS preview failed for {source_path.name}: {exc}") from exc
    raise ValueError(f"Native DDS preview failed for {source_path.name}.")


def _preview_resize_dimensions(
    width: int,
    height: int,
    *,
    max_dimension: int,
) -> Optional[Tuple[int, int]]:
    width = int(width)
    height = int(height)
    max_dimension = int(max_dimension)
    if width <= 0 or height <= 0 or max_dimension <= 0:
        return None
    longest = max(width, height)
    if longest <= max_dimension:
        return None
    scale = float(max_dimension) / float(longest)
    target_width = max(1, int(round(width * scale)))
    target_height = max(1, int(round(height * scale)))
    return target_width, target_height


def ensure_dds_display_preview_png(
    source_or_obsolete_backend: Optional[Path],
    dds_path: Optional[Path] = None,
    *,
    dds_info: Optional[DdsInfo] = None,
    max_dimension: int = _COMPARE_DISPLAY_PREVIEW_MAX_DIMENSION,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    output_pixel_type: str = "rgba8",
    stop_event: Optional[threading.Event] = None,
) -> Path:
    source_path = resolve_deprecated_preview_source(source_or_obsolete_backend, dds_path).expanduser().resolve()
    resolved_info: Optional[DdsInfo] = dds_info
    try:
        if resolved_info is None:
            resolved_info = parse_dds(source_path)
    except Exception as exc:
        if dds_info is not None:
            raise
        resolved_info = None
    try:
        from cdmw.core.texture_native import ensure_native_dds_preview_png

        native_preview = ensure_native_dds_preview_png(
            source_path,
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
            output_pixel_type=output_pixel_type,
            stop_event=stop_event,
        )
        if native_preview is not None:
            return native_preview
    except RunCancelled:
        raise
    except Exception as exc:
        raise ValueError(f"Native DDS display preview failed for {source_path.name}: {exc}") from exc
    raise ValueError(f"Native DDS display preview failed for {source_path.name}.")


def stage_dds_to_pngs(
    config: NormalizedConfig,
    processing_plan: Sequence[TextureProcessingPlan],
    *,
    on_log: Optional[Callable[[str], None]] = None,
    on_phase: Optional[Callable[[str, str, bool], None]] = None,
    on_phase_progress: Optional[Callable[[int, int, str], None]] = None,
    on_current_file: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, str]:
    if not config.enable_dds_staging or config.dds_staging_root is None:
        return {}

    stage_root = config.dds_staging_root
    stage_root.mkdir(parents=True, exist_ok=True)

    total = len(processing_plan)
    failures: Dict[str, str] = {}
    if on_phase:
        on_phase("DDS Staging", "Extracting DDS files to PNG...", False)
    if on_log:
        on_log(f"Phase 0/2: staging policy-selected DDS files to PNG in {stage_root}")
    if on_phase_progress:
        on_phase_progress(0, total, f"0 / {total} DDS staging files")

    for index, entry in enumerate(processing_plan, start=1):
        raise_if_cancelled(stop_event)
        dds_path = entry.dds_path
        relative_path = dds_path.relative_to(config.original_dds_root)
        rel_display = relative_path.as_posix()
        if on_current_file:
            on_current_file(f"Stage: {rel_display}")

        target_dir = stage_root / relative_path.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target_png = stage_root / relative_path.with_suffix(".png")

        should_skip = False
        if target_png.exists():
            try:
                should_skip = target_png.stat().st_mtime_ns >= dds_path.stat().st_mtime_ns and target_png.stat().st_size > 0
            except OSError:
                should_skip = False

        if should_skip:
            if on_log:
                on_log(f"[{index}/{total}] STAGE SKIP {rel_display} -> PNG is newer than source DDS")
            if on_phase_progress:
                on_phase_progress(index, total, f"{index} / {total} DDS staging files")
            continue

        if config.dry_run:
            if on_log:
                on_log(
                    f"[{index}/{total}] STAGE DRYRUN {rel_display} -> "
                    f"{_staging_png_format_for_plan(entry)} staging PNG"
                )
        else:
            try:
                stage_started = time.perf_counter()
                dds_info = None
                try:
                    dds_info = parse_dds(dds_path)
                except Exception:
                    dds_info = None
                preview_path = ensure_dds_display_preview_png(
                    dds_path,
                    dds_info=dds_info,
                    max_dimension=0,
                    output_pixel_type=(
                        "gray16"
                        if entry.path_kind == "technical_high_precision_path"
                        else "rgba8"
                    ),
                    stop_event=stop_event,
                )
                if Path(preview_path).resolve() != target_png.resolve():
                    shutil.copy2(preview_path, target_png)
                elapsed_seconds = time.perf_counter() - stage_started
                backend = "directxtex_decode"
                try:
                    from cdmw.core.texture_native import read_native_texture_report_sidecar

                    report = read_native_texture_report_sidecar(Path(preview_path))
                    backend = str(report.get("backend") or backend)
                except Exception:
                    pass
            except RunCancelled:
                raise
            except Exception as exc:
                detail = str(exc)
                failures[rel_display] = detail
                if on_log:
                    on_log(f"[{index}/{total}] STAGE FAIL {rel_display} -> {detail}")
                if on_phase_progress:
                    on_phase_progress(index, total, f"{index} / {total} DDS staging files")
                continue
            try:
                produced_size = target_png.stat().st_size
            except OSError:
                produced_size = 0
            if produced_size <= 0:
                detail = f"DDS preview backend did not produce expected staging PNG: {target_png}"
                failures[rel_display] = detail
                if on_log:
                    on_log(f"[{index}/{total}] STAGE FAIL {rel_display} -> {detail}")
                if on_phase_progress:
                    on_phase_progress(index, total, f"{index} / {total} DDS staging files")
                continue
            if entry.path_kind == "technical_high_precision_path":
                validation_message = _validate_high_precision_staged_png(target_png, entry)
                if validation_message is not None and on_log:
                    on_log(
                        f"[{index}/{total}] STAGE WARNING {rel_display} -> {validation_message}"
                    )
            if on_log:
                on_log(
                    f"[{index}/{total}] STAGE {rel_display} -> "
                    f"{_staging_png_format_for_plan(entry)} staging PNG with {backend} in {elapsed_seconds:.1f}s "
                    f"({produced_size:,} bytes)"
                )
        if on_phase_progress:
            on_phase_progress(index, total, f"{index} / {total} DDS staging files")

    return failures


def build_compare_preview_pane_result(
    source_or_obsolete_backend: Optional[Path],
    dds_path_or_missing_message: Optional[Path | str],
    missing_message: Optional[str] = None,
    planner_summary: str = "",
    *,
    stop_event: Optional[threading.Event] = None,
) -> ComparePreviewPaneResult:
    if missing_message is None:
        dds_path = Path(source_or_obsolete_backend) if source_or_obsolete_backend is not None else None
        resolved_missing_message = str(dds_path_or_missing_message or "")
    else:
        dds_path = (
            resolve_deprecated_preview_source(
                source_or_obsolete_backend,
                Path(dds_path_or_missing_message) if dds_path_or_missing_message is not None else None,
            )
            if dds_path_or_missing_message is not None
            else None
        )
        resolved_missing_message = missing_message
    if dds_path is None or not dds_path.exists():
        return ComparePreviewPaneResult(status="missing", message=resolved_missing_message)

    try:
        metadata_summary = ""
        dds_info: Optional[DdsInfo] = None
        try:
            dds_info = parse_dds(dds_path.resolve())
            metadata_summary = f"Format: {dds_info.dds_format} | Size: {dds_info.width}x{dds_info.height} | Mips: {dds_info.mip_count}"
        except Exception:
            metadata_summary = "DDS metadata unavailable."
        if planner_summary.strip():
            metadata_summary = f"{metadata_summary} | {planner_summary.strip()}"
        preview_png = ensure_dds_display_preview_png(
            dds_path.resolve(),
            dds_info=dds_info,
            stop_event=stop_event,
        )
        return ComparePreviewPaneResult(
            status="ok",
            title=dds_path.name,
            preview_png_path=str(preview_png),
            metadata_summary=metadata_summary,
        )
    except Exception as exc:
        return ComparePreviewPaneResult(status="error", message=str(exc))
