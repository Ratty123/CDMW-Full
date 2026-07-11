from __future__ import annotations

import hashlib
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.core.common import raise_if_cancelled, run_process_with_cancellation
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.texture_decode_cache import (
    preview_cache_locks,
    preview_pair_is_valid,
    preview_png_is_valid,
    preview_staging_dir,
    publish_preview_pair,
)
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


def build_preview_png_command(
    texconv_path: Path,
    dds_path: Path,
    output_dir: Path,
    *,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> List[str]:
    cmd = [
        str(texconv_path),
        "-nologo",
        "-y",
        "-f",
        "R8G8B8A8_UNORM",
        "-ft",
        "png",
        "-o",
        str(output_dir),
    ]
    if width is not None and height is not None and width > 0 and height > 0:
        cmd.extend(["-w", str(int(width)), "-h", str(int(height))])
    cmd.append(str(dds_path))
    return cmd


def _ensure_texconv_preview_cached(
    texconv_path: Path,
    dds_path: Path,
    *,
    cache_key: str,
    preview_path: Path,
    width: Optional[int] = None,
    height: Optional[int] = None,
    slot_kind: str = "base",
    max_dimension: int = 0,
    display: bool = False,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    label = "display preview" if display else "preview"
    with preview_cache_locks((f"texconv:{cache_key}",)):
        raise_if_cancelled(stop_event, f"{label.capitalize()} generation cancelled for {dds_path.name}.")
        if preview_pair_is_valid(preview_path):
            return preview_path
        with preview_staging_dir(preview_path.parent) as staging:
            cmd = build_preview_png_command(
                texconv_path,
                dds_path,
                staging,
                width=width,
                height=height,
            )
            return_code, stdout, stderr = run_process_with_cancellation(cmd, stop_event=stop_event)
            if return_code != 0:
                detail = stderr.strip() or stdout.strip() or f"texconv failed with exit code {return_code}"
                raise ValueError(f"Could not generate {label} for {dds_path.name}: {detail}")
            candidates = [staging / f"{dds_path.stem}.png"]
            candidates.extend(path for path in sorted(staging.glob("*.png")) if path not in candidates)
            staged = next((path for path in candidates if preview_png_is_valid(path)), None)
            if staged is None:
                article = "a display PNG preview" if display else "a PNG preview"
                raise ValueError(f"texconv did not produce {article} for {dds_path.name}.")
            from cdmw.core.texture_native import texconv_preview_report

            report = texconv_preview_report(
                dds_path,
                staged,
                slot_kind=slot_kind,
                max_dimension=max_dimension,
            )
            publish_preview_pair(staged, preview_path, report)
        request_app_temp_cache_prune()
        return preview_path


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


def build_staging_png_command(
    texconv_path: Path,
    dds_path: Path,
    output_dir: Path,
    entry: TextureProcessingPlan,
) -> List[str]:
    return [
        str(texconv_path),
        "-nologo",
        "-y",
        "-f",
        _staging_png_format_for_plan(entry),
        "-ft",
        "png",
        "-o",
        str(output_dir),
        str(dds_path),
    ]


def ensure_dds_preview_png(
    texconv_path: Optional[Path],
    dds_path: Path,
    *,
    stop_event: Optional[threading.Event] = None,
) -> Path:
    try:
        from cdmw.core.texture_native import ensure_native_dds_preview_png

        native_preview = ensure_native_dds_preview_png(
            dds_path.resolve(),
            max_dimension=4096,
            slot_kind="base",
            normal_space="auto",
        )
        if native_preview is not None:
            return native_preview
    except Exception:
        native_preview = None

    if texconv_path is None:
        raise ValueError(
            f"DirectXTex native DDS preview is unavailable and no optional texconv fallback was provided for {dds_path.name}."
        )
    stat = dds_path.stat()
    texconv_stat = texconv_path.stat()
    cache_key = hashlib.sha256(
        (
            f"{dds_path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
            f"::{texconv_path.resolve()}::{texconv_stat.st_size}::{texconv_stat.st_mtime_ns}"
        ).encode("utf-8")
    ).hexdigest()
    cache_dir = app_temp_cache_path("preview_cache", cache_key)
    preview_path = cache_dir / f"{dds_path.stem}.png"
    return _ensure_texconv_preview_cached(
        texconv_path,
        dds_path,
        cache_key=cache_key,
        preview_path=preview_path,
        stop_event=stop_event,
    )


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
    texconv_path: Optional[Path],
    dds_path: Path,
    *,
    dds_info: Optional[DdsInfo] = None,
    max_dimension: int = _COMPARE_DISPLAY_PREVIEW_MAX_DIMENSION,
    slot_kind: str = "base",
    srgb: str = "auto",
    normal_space: str = "auto",
    stop_event: Optional[threading.Event] = None,
) -> Path:
    resolved_info: Optional[DdsInfo] = dds_info
    try:
        if resolved_info is None:
            resolved_info = parse_dds(dds_path)
    except Exception as exc:
        if dds_info is not None:
            raise
        resolved_info = None
    try:
        from cdmw.core.texture_native import ensure_native_dds_preview_png

        native_preview = ensure_native_dds_preview_png(
            dds_path.resolve(),
            max_dimension=max_dimension,
            slot_kind=slot_kind,
            srgb=srgb,
            normal_space=normal_space,
        )
        if native_preview is not None:
            return native_preview
    except Exception:
        native_preview = None
    if texconv_path is None:
        raise ValueError(
            f"DirectXTex native DDS display preview is unavailable and no optional texconv fallback was provided for {dds_path.name}."
        )
    if resolved_info is None:
        preview_path = ensure_dds_preview_png(texconv_path, dds_path, stop_event=stop_event)
        try:
            from cdmw.core.texture_native import texconv_preview_report, write_native_texture_report_sidecar

            write_native_texture_report_sidecar(
                preview_path,
                texconv_preview_report(dds_path, preview_path, slot_kind=slot_kind, max_dimension=max_dimension),
            )
        except Exception:
            pass
        return preview_path
    resize_dims = _preview_resize_dimensions(
        resolved_info.width,
        resolved_info.height,
        max_dimension=max_dimension,
    )
    if resize_dims is None:
        preview_path = ensure_dds_preview_png(texconv_path, dds_path, stop_event=stop_event)
        try:
            from cdmw.core.texture_native import texconv_preview_report, write_native_texture_report_sidecar

            write_native_texture_report_sidecar(
                preview_path,
                texconv_preview_report(dds_path, preview_path, slot_kind=slot_kind, max_dimension=max_dimension),
            )
        except Exception:
            pass
        return preview_path

    stat = dds_path.stat()
    texconv_stat = texconv_path.stat()
    target_width, target_height = resize_dims
    cache_key = hashlib.sha256(
        (
            f"display::{dds_path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
            f"::{texconv_path.resolve()}::{texconv_stat.st_size}::{texconv_stat.st_mtime_ns}"
            f"::{target_width}x{target_height}"
        ).encode("utf-8")
    ).hexdigest()
    cache_dir = app_temp_cache_path("preview_cache_display", cache_key)
    preview_path = cache_dir / f"{dds_path.stem}.png"
    return _ensure_texconv_preview_cached(
        texconv_path,
        dds_path,
        cache_key=cache_key,
        preview_path=preview_path,
        width=target_width,
        height=target_height,
        slot_kind=slot_kind,
        max_dimension=max_dimension,
        display=True,
        stop_event=stop_event,
    )


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
                    config.texconv_path,
                    dds_path,
                    dds_info=dds_info,
                    max_dimension=0,
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
    texconv_path: Optional[Path],
    dds_path: Optional[Path],
    missing_message: str,
    planner_summary: str = "",
    *,
    stop_event: Optional[threading.Event] = None,
) -> ComparePreviewPaneResult:
    if dds_path is None or not dds_path.exists():
        return ComparePreviewPaneResult(status="missing", message=missing_message)

    try:
        metadata_summary = ""
        dds_info: Optional[DdsInfo] = None
        try:
            dds_info = parse_dds(dds_path.resolve())
            metadata_summary = f"Format: {dds_info.texconv_format} | Size: {dds_info.width}x{dds_info.height} | Mips: {dds_info.mip_count}"
        except Exception:
            metadata_summary = "DDS metadata unavailable."
        if planner_summary.strip():
            metadata_summary = f"{metadata_summary} | {planner_summary.strip()}"
        preview_png = ensure_dds_display_preview_png(
            texconv_path.resolve() if texconv_path is not None and texconv_path.is_file() else None,
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
