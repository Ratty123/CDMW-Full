from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from cdmw.core.common import raise_if_cancelled
from cdmw.core.research_report import export_research_analysis_report
from cdmw.core.research_archive_analysis import (
    _build_family_members_by_relative_path,
    build_archive_research_snapshot,
    classify_texture_path,
    derive_texture_group_key,
)
from cdmw.core.research_references import _reference_path_keys, build_ui_constraint_reference_rows
from cdmw.domain.research.classification import _normalized_parts, system_area_from_path
from cdmw.domain.research.contracts import (
    AtlasDetectionRow,
    MaterialTextureReferenceRow,
    MipAnalysisRow,
    NormalValidationRow,
    TextureBudgetClassSummary,
    TextureBudgetGroupSummary,
    TextureBudgetProfileSummary,
    TextureBudgetRow,
    TexturePreviewStats,
    TextureUsageHeatRow,
)
from cdmw.core.texture_pipeline.discovery import collect_dds_files
from cdmw.core.texture_pipeline.inspection import parse_dds
from cdmw.core.texture_pipeline.planning import (
    _build_loose_sidecar_index,
    _collect_loose_sidecar_texts,
    build_texture_processing_plan,
)
from cdmw.core.texture_pipeline.preview import collect_compare_relative_paths, ensure_dds_preview_png
from cdmw.core.texture_pipeline.runtime_config import normalize_config_for_planning
from cdmw.domain.textures.output import max_mips_for_size
from cdmw.domain.textures.plan import describe_processing_path_kind
from cdmw.domain.textures.profiles import _SCALAR_HIGH_PRECISION_MASK_SUBTYPES
from cdmw.core.upscale_profiles import is_png_intermediate_high_risk
from cdmw.models import AppConfig, ArchiveEntry, TextureProcessingPlan

try:
    from PySide6.QtGui import QColor, QImage
except Exception:  # pragma: no cover - GUI/runtime fallback
    QImage = None  # type: ignore[assignment]
    QColor = None  # type: ignore[assignment]


NORMAL_FRIENDLY_FORMATS = {
    "BC5_UNORM",
    "BC5_SNORM",
    "BC7_UNORM",
    "R8G8B8A8_UNORM",
    "B8G8R8A8_UNORM",
}

NORMAL_SUSPICIOUS_FORMATS = {
    "BC1_UNORM",
    "BC1_UNORM_SRGB",
    "BC2_UNORM",
    "BC2_UNORM_SRGB",
    "BC3_UNORM_SRGB",
    "BC7_UNORM_SRGB",
}

_TERRAIN_LIKE_TOKENS = (
    "terrain",
    "landscape",
    "ground",
    "grass",
    "rock",
    "cliff",
    "soil",
    "mud",
    "road",
    "field",
    "nature",
)

_TEXTURE_TYPE_BASELINE_RISK: Dict[str, int] = {
    "color": 10,
    "ui": 18,
    "emissive": 20,
    "impostor": 24,
    "unknown": 35,
    "normal": 65,
    "height": 72,
    "roughness": 74,
    "mask": 78,
    "vector": 88,
}

def build_texture_usage_heatmap(
    entries: Sequence[ArchiveEntry],
    *,
    limit_per_scope: int = 24,
) -> List[TextureUsageHeatRow]:
    snapshot = build_archive_research_snapshot(
        entries,
        classification_limit=0,
        group_limit=0,
        heatmap_limit_per_scope=limit_per_scope,
    )
    rows = snapshot.get("heatmap_rows", [])
    return rows if isinstance(rows, list) else []

def _risk_band_for_score(score: float) -> str:
    if score >= 75:
        return "Very High"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Moderate"
    return "Lower Risk"

def _build_ui_constraint_path_keys(entries: Sequence[ArchiveEntry]) -> set[str]:
    keys: set[str] = set()
    try:
        for row in build_ui_constraint_reference_rows(entries):
            if isinstance(row, MaterialTextureReferenceRow):
                keys.update(_reference_path_keys(row.related_path))
    except Exception:
        return set()
    return keys

def _is_terrain_like_group(group_key: str, system_area: str) -> bool:
    lowered = group_key.replace("\\", "/").lower()
    return system_area == "world" or any(token in lowered for token in _TERRAIN_LIKE_TOKENS)

def build_texture_budget_analysis(
    original_root: Path,
    rebuilt_root: Path,
    *,
    processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
    archive_entries: Sequence[ArchiveEntry] = (),
    ui_constraint_related_paths: Sequence[str] = (),
    stop_event: Optional[object] = None,
) -> Dict[str, object]:
    if not original_root.exists() or not rebuilt_root.exists():
        return {
            "budget_rows": [],
            "budget_class_rows": [],
            "budget_group_rows": [],
            "budget_profile": None,
        }
    family_members_by_path = build_mip_analysis_family_members_by_path(
        original_root,
        rebuilt_root,
        stop_event=stop_event,
    )
    (
        sidecars_by_group,
        sidecars_by_folder,
        sidecars_by_texture_path,
        sidecars_by_texture_basename,
        sidecar_text_cache,
    ) = _build_loose_sidecar_index(original_root, stop_event=stop_event)
    if ui_constraint_related_paths:
        ui_constraint_keys: set[str] = set()
        for path_value in ui_constraint_related_paths:
            if not isinstance(path_value, str):
                continue
            ui_constraint_keys.update(_reference_path_keys(path_value))
    else:
        ui_constraint_keys = _build_ui_constraint_path_keys(archive_entries) if archive_entries else set()
    rows: List[TextureBudgetRow] = []
    compare_relative_paths = sorted(family_members_by_path.keys())
    sidecar_texts_by_relative_path: Dict[str, Tuple[str, ...]] = {}
    for relative_path_text in compare_relative_paths:
        sidecar_texts_by_relative_path[relative_path_text] = tuple(
            _collect_loose_sidecar_texts(
                original_root,
                Path(relative_path_text),
                sidecars_by_group=sidecars_by_group,
                sidecars_by_folder=sidecars_by_folder,
                sidecars_by_texture_path=sidecars_by_texture_path,
                sidecars_by_texture_basename=sidecars_by_texture_basename,
                text_cache=sidecar_text_cache,
                stop_event=stop_event,
            )
        )
    for relative_path_text in compare_relative_paths:
        raise_if_cancelled(stop_event)
        relative_path = Path(relative_path_text)
        original_path = original_root / relative_path
        rebuilt_path = rebuilt_root / relative_path
        if not original_path.exists() or not rebuilt_path.exists():
            continue
        try:
            original_dds = parse_dds(original_path)
            rebuilt_dds = parse_dds(rebuilt_path)
        except Exception:
            continue
        family_members = family_members_by_path.get(relative_path_text, ())
        texture_type = classify_texture_path(
            relative_path_text,
            family_members=family_members,
            sidecar_texts=sidecar_texts_by_relative_path.get(relative_path_text, ()),
        )[0]
        group_key = derive_texture_group_key(relative_path_text)
        system_area = system_area_from_path(relative_path_text)
        parts = _normalized_parts(relative_path_text)
        folder_bucket = "/".join(parts[:3]) if len(parts) >= 3 else ("/".join(parts) or "(root)")
        original_bytes = int(original_path.stat().st_size)
        rebuilt_bytes = int(rebuilt_path.stat().st_size)
        byte_delta = rebuilt_bytes - original_bytes
        byte_ratio = (rebuilt_bytes / max(1, original_bytes)) if original_bytes > 0 else 0.0
        original_pixels = max(1, original_dds.width * original_dds.height)
        rebuilt_pixels = max(1, rebuilt_dds.width * rebuilt_dds.height)
        pixel_ratio = rebuilt_pixels / original_pixels
        mip_delta = rebuilt_dds.mip_count - original_dds.mip_count
        format_changed = original_dds.texconv_format != rebuilt_dds.texconv_format
        changed = bool(
            byte_delta
            or original_dds.width != rebuilt_dds.width
            or original_dds.height != rebuilt_dds.height
            or mip_delta
            or format_changed
        )
        plan_entry = (processing_plan_lookup or {}).get(relative_path_text)
        explicit_ui_constraint = bool(_reference_path_keys(relative_path_text) & ui_constraint_keys)
        risk_score = _TEXTURE_TYPE_BASELINE_RISK.get(texture_type, _TEXTURE_TYPE_BASELINE_RISK["unknown"])
        risk_signals = [f"Baseline {texture_type} risk {risk_score}."]
        if plan_entry is not None and str(plan_entry.path_kind or "").strip().lower() != "visible_color_png_path":
            risk_score += 12
            risk_signals.append(f"Planner path {plan_entry.path_kind} is not visible_color_png_path.")
        if plan_entry is not None and str(plan_entry.alpha_policy or "").strip().lower() in {"channel_data", "premultiplied"}:
            risk_score += 10
            risk_signals.append(f"Alpha policy {plan_entry.alpha_policy} is channel-sensitive.")
        if explicit_ui_constraint:
            risk_score += 10
            risk_signals.append("Explicit UI rect constraint exists.")
        if byte_ratio >= 2.0:
            risk_score += 12
            risk_signals.append(f"Byte ratio {byte_ratio:.2f}x >= 2.0.")
        elif byte_ratio >= 1.5:
            risk_score += 8
            risk_signals.append(f"Byte ratio {byte_ratio:.2f}x >= 1.5.")
        if rebuilt_dds.width > original_dds.width or rebuilt_dds.height > original_dds.height:
            risk_score += 6
            risk_signals.append("Rebuilt dimensions exceed original DDS size.")
            if rebuilt_dds.mip_count <= original_dds.mip_count:
                risk_score += 6
                risk_signals.append("Dimensions increased without a larger mip chain.")
        risk_score = max(0, min(100, int(risk_score)))
        ui_constraint_summary = (
            "Explicit UI rect reference found in archive XML." if explicit_ui_constraint else ""
        )
        rows.append(
            TextureBudgetRow(
                relative_path=relative_path_text,
                group_key=group_key,
                system_area=system_area,
                folder_bucket=folder_bucket,
                texture_type=texture_type,
                planner_profile=plan_entry.profile.key if plan_entry is not None else "",
                planner_path_kind=plan_entry.path_kind if plan_entry is not None else "",
                planner_alpha_policy=plan_entry.alpha_policy if plan_entry is not None else "",
                original_bytes=original_bytes,
                rebuilt_bytes=rebuilt_bytes,
                byte_delta=byte_delta,
                byte_ratio=byte_ratio,
                original_width=original_dds.width,
                original_height=original_dds.height,
                rebuilt_width=rebuilt_dds.width,
                rebuilt_height=rebuilt_dds.height,
                pixel_ratio=pixel_ratio,
                original_mips=original_dds.mip_count,
                rebuilt_mips=rebuilt_dds.mip_count,
                mip_delta=mip_delta,
                original_format=original_dds.texconv_format,
                rebuilt_format=rebuilt_dds.texconv_format,
                format_changed=format_changed,
                changed=changed,
                explicit_ui_constraint=explicit_ui_constraint,
                ui_constraint_summary=ui_constraint_summary,
                risk_score=risk_score,
                risk_band=_risk_band_for_score(risk_score),
                risk_signals=risk_signals,
            )
        )
    rows.sort(key=lambda row: (-row.byte_delta, row.relative_path.lower()))

    class_buckets: Dict[str, List[TextureBudgetRow]] = defaultdict(list)
    changed_rows = [row for row in rows if row.changed]
    for row in changed_rows:
        class_buckets[row.texture_type].append(row)
    class_rows: List[TextureBudgetClassSummary] = []
    for texture_type, bucket in sorted(class_buckets.items(), key=lambda item: (-sum(row.byte_delta for row in item[1]), item[0])):
        average_risk = sum(row.risk_score for row in bucket) / max(1, len(bucket))
        class_rows.append(
            TextureBudgetClassSummary(
                texture_type=texture_type,
                affected_count=len(bucket),
                total_byte_delta=sum(row.byte_delta for row in bucket),
                average_risk=average_risk,
                risk_band=_risk_band_for_score(average_risk),
                sample_paths=[row.relative_path for row in bucket[:3]],
            )
        )

    group_buckets: Dict[str, List[TextureBudgetRow]] = defaultdict(list)
    for row in changed_rows:
        if _is_terrain_like_group(row.group_key, row.system_area):
            group_buckets[row.group_key].append(row)
    group_rows: List[TextureBudgetGroupSummary] = []
    for group_key, bucket in sorted(group_buckets.items(), key=lambda item: item[0].lower()):
        total_original_bytes = sum(row.original_bytes for row in bucket)
        total_rebuilt_bytes = sum(row.rebuilt_bytes for row in bucket)
        total_byte_delta = total_rebuilt_bytes - total_original_bytes
        total_ratio = (total_rebuilt_bytes / max(1, total_original_bytes)) if total_original_bytes > 0 else 0.0
        average_byte_ratio = sum(row.byte_ratio for row in bucket) / max(1, len(bucket))
        max_byte_ratio = max((row.byte_ratio for row in bucket), default=0.0)
        average_width = sum(row.rebuilt_width for row in bucket) / max(1, len(bucket))
        average_height = sum(row.rebuilt_height for row in bucket) / max(1, len(bucket))
        large_2048_count = sum(1 for row in bucket if max(row.original_width, row.original_height, row.rebuilt_width, row.rebuilt_height) >= 2048)
        large_4096_count = sum(1 for row in bucket if max(row.original_width, row.original_height, row.rebuilt_width, row.rebuilt_height) >= 4096)
        average_risk = sum(row.risk_score for row in bucket) / max(1, len(bucket))
        risk_score = 20
        signals = ["Terrain-like path/system-area classification."]
        if len(bucket) >= 4:
            risk_score += 10
            signals.append(f"Group contains {len(bucket)} modified textures.")
        if total_ratio >= 2.0:
            risk_score += 25
            signals.append(f"Total group byte ratio {total_ratio:.2f}x >= 2.0.")
        elif total_ratio >= 1.5:
            risk_score += 15
            signals.append(f"Total group byte ratio {total_ratio:.2f}x >= 1.5.")
        if large_4096_count >= 1:
            risk_score += 10
            signals.append("At least one member is 4096 or larger.")
        if large_2048_count >= 2:
            risk_score += 10
            signals.append("Two or more members are 2048 or larger.")
        if average_risk >= 50:
            risk_score += 10
            signals.append(f"Average per-file risk {average_risk:.1f} is >= 50.")
        risk_score = max(0, min(100, risk_score))
        group_rows.append(
            TextureBudgetGroupSummary(
                group_key=group_key,
                system_area=bucket[0].system_area if bucket else "",
                texture_count=len(bucket),
                total_original_bytes=total_original_bytes,
                total_rebuilt_bytes=total_rebuilt_bytes,
                total_byte_delta=total_byte_delta,
                average_byte_ratio=average_byte_ratio,
                max_byte_ratio=max_byte_ratio,
                average_width=average_width,
                average_height=average_height,
                large_2048_count=large_2048_count,
                large_4096_count=large_4096_count,
                average_risk=average_risk,
                risk_score=risk_score,
                risk_band=_risk_band_for_score(risk_score),
                signals=signals,
            )
        )
    group_rows.sort(key=lambda row: (-row.risk_score, -row.total_byte_delta, row.group_key.lower()))

    total_original_bytes = sum(row.original_bytes for row in rows)
    total_rebuilt_bytes = sum(row.rebuilt_bytes for row in rows)
    total_byte_delta = total_rebuilt_bytes - total_original_bytes
    total_ratio = (total_rebuilt_bytes / max(1, total_original_bytes)) if total_original_bytes > 0 else 0.0
    changed_texture_count = len(changed_rows)
    upscaled_texture_count = sum(
        1
        for row in rows
        if row.rebuilt_width > row.original_width or row.rebuilt_height > row.original_height
    )
    high_risk_texture_fraction = (
        sum(1 for row in changed_rows if row.risk_score >= 50) / max(1, changed_texture_count)
        if changed_texture_count > 0
        else 0.0
    )
    highest_group_risk = max((row.risk_score for row in group_rows), default=0)
    reasons: List[str] = [
        f"Total byte ratio {total_ratio:.2f}x.",
        f"{changed_texture_count:,} changed texture(s), {upscaled_texture_count:,} upscaled texture(s).",
    ]
    if highest_group_risk:
        reasons.append(f"Highest terrain-like group risk score: {highest_group_risk}.")
    reasons.append(f"{high_risk_texture_fraction * 100.0:.1f}% of changed textures are High or Very High risk.")
    if total_ratio < 1.20 and highest_group_risk < 60 and high_risk_texture_fraction < 0.10:
        profile_label = "Conservative"
    elif total_ratio < 1.60 and highest_group_risk < 75 and high_risk_texture_fraction < 0.25:
        profile_label = "Balanced"
    elif total_ratio >= 2.30 or highest_group_risk >= 90 or high_risk_texture_fraction > 0.45:
        profile_label = "High Risk"
    else:
        profile_label = "Aggressive"
    profile = TextureBudgetProfileSummary(
        profile_label=profile_label,
        total_original_bytes=total_original_bytes,
        total_rebuilt_bytes=total_rebuilt_bytes,
        total_byte_delta=total_byte_delta,
        total_byte_ratio=total_ratio,
        changed_texture_count=changed_texture_count,
        upscaled_texture_count=upscaled_texture_count,
        high_risk_texture_fraction=high_risk_texture_fraction,
        highest_group_risk=highest_group_risk,
        reasons=reasons,
    )
    return {
        "budget_rows": rows,
        "budget_class_rows": class_rows,
        "budget_group_rows": group_rows,
        "budget_profile": profile,
    }

def export_texture_analysis_report(
    report_path: Path,
    mip_rows: Sequence[MipAnalysisRow],
    normal_rows: Sequence[NormalValidationRow],
    *,
    budget_rows: Sequence[TextureBudgetRow] = (),
    budget_class_rows: Sequence[TextureBudgetClassSummary] = (),
    budget_group_rows: Sequence[TextureBudgetGroupSummary] = (),
    budget_profile: Optional[TextureBudgetProfileSummary] = None,
    stop_event: Optional[object] = None,
) -> Path:
    return export_research_analysis_report(
        report_path,
        mip_rows,
        normal_rows,
        budget_rows=budget_rows,
        budget_class_rows=budget_class_rows,
        budget_group_rows=budget_group_rows,
        budget_profile=budget_profile,
        stop_event=stop_event,
    )

def build_processing_plan_lookup(
    app_config: AppConfig,
    *,
    original_root_override: Optional[Path] = None,
    stop_event: Optional[object] = None,
) -> Dict[str, TextureProcessingPlan]:
    working_config = AppConfig(**asdict(app_config))
    if original_root_override is not None:
        working_config.original_dds_root = str(original_root_override)
    normalized = normalize_config_for_planning(working_config)
    if not normalized.original_dds_root.exists():
        return {}
    dds_files = collect_dds_files(normalized.original_dds_root, (), stop_event=stop_event)
    plan = build_texture_processing_plan(normalized, dds_files)
    return {entry.relative_path.as_posix(): entry for entry in plan}

def _format_bytes(value: int) -> str:
    if value <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    unit_index = 0
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"

def _format_percent(value: float) -> str:
    return f"{value * 100.0:.1f}%"

def _collect_preview_stats(image_path: Path) -> Optional[TexturePreviewStats]:
    if QImage is None:
        return None
    image = QImage(str(image_path))
    if image.isNull():
        return None
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return None

    step_x = max(1, width // 64)
    step_y = max(1, height // 64)
    sample_count = 0
    sum_r = sum_g = sum_b = sum_a = 0.0
    sum_luma = 0.0
    min_r = min_g = min_b = min_a = 255
    max_r = max_g = max_b = max_a = 0
    min_luma = 255.0
    max_luma = 0.0
    opaque_count = 0
    transparent_count = 0
    has_alpha = bool(image.hasAlphaChannel())

    for y in range(0, height, step_y):
        for x in range(0, width, step_x):
            color = QColor(image.pixel(x, y))
            r = color.red()
            g = color.green()
            b = color.blue()
            a = color.alpha()
            luma = (0.2126 * r) + (0.7152 * g) + (0.0722 * b)
            sample_count += 1
            sum_r += r
            sum_g += g
            sum_b += b
            sum_a += a
            sum_luma += luma
            min_r = min(min_r, r)
            min_g = min(min_g, g)
            min_b = min(min_b, b)
            min_a = min(min_a, a)
            max_r = max(max_r, r)
            max_g = max(max_g, g)
            max_b = max(max_b, b)
            max_a = max(max_a, a)
            min_luma = min(min_luma, luma)
            max_luma = max(max_luma, luma)
            if a >= 250:
                opaque_count += 1
            if a <= 5:
                transparent_count += 1

    if sample_count <= 0:
        return None

    return TexturePreviewStats(
        path=str(image_path),
        width=width,
        height=height,
        sample_count=sample_count,
        has_alpha=has_alpha,
        mean_r=sum_r / sample_count,
        mean_g=sum_g / sample_count,
        mean_b=sum_b / sample_count,
        mean_a=sum_a / sample_count,
        min_r=min_r,
        min_g=min_g,
        min_b=min_b,
        min_a=min_a,
        max_r=max_r,
        max_g=max_g,
        max_b=max_b,
        max_a=max_a,
        luma_mean=sum_luma / sample_count,
        luma_min=min_luma,
        luma_max=max_luma,
        opaque_fraction=opaque_count / sample_count,
        transparent_fraction=transparent_count / sample_count,
    )

def _preview_stats_summary(stats: Optional[TexturePreviewStats]) -> str:
    if stats is None:
        return "Preview statistics: unavailable."
    return (
        f"Preview {stats.width}x{stats.height}, sampled {stats.sample_count} px; "
        f"mean RGBA {stats.mean_r:.1f}/{stats.mean_g:.1f}/{stats.mean_b:.1f}/{stats.mean_a:.1f}; "
        f"range R {stats.min_r}-{stats.max_r}, G {stats.min_g}-{stats.max_g}, B {stats.min_b}-{stats.max_b}, A {stats.min_a}-{stats.max_a}; "
        f"luma {stats.luma_mean:.1f} (range {stats.luma_min:.1f}-{stats.luma_max:.1f}); "
        f"alpha opaque {_format_percent(stats.opaque_fraction)} / transparent {_format_percent(stats.transparent_fraction)}."
    )

def _compare_preview_stats(original: Optional[TexturePreviewStats], rebuilt: Optional[TexturePreviewStats]) -> List[str]:
    warnings: List[str] = []
    if original is None or rebuilt is None:
        if original is None and rebuilt is None:
            warnings.append("Preview statistics are unavailable for both files.")
        elif original is None:
            warnings.append("Original DDS preview could not be decoded for statistics.")
        else:
            warnings.append("Rebuilt DDS preview could not be decoded for statistics.")
        return warnings

    if original.has_alpha != rebuilt.has_alpha:
        warnings.append("Alpha-channel presence changed between original and rebuilt DDS.")

    alpha_delta = abs(original.opaque_fraction - rebuilt.opaque_fraction)
    if alpha_delta > 0.10:
        warnings.append(
            f"Alpha coverage changed by {_format_percent(alpha_delta)} between preview renders."
        )

    luma_delta = abs(original.luma_mean - rebuilt.luma_mean)
    if luma_delta > 12.0:
        warnings.append(f"Average brightness shifted by {luma_delta:.1f} luma points.")

    range_delta = abs((original.luma_max - original.luma_min) - (rebuilt.luma_max - rebuilt.luma_min))
    if range_delta > 18.0:
        warnings.append("Brightness range changed noticeably between original and rebuilt preview renders.")

    channel_deltas = {
        "R": abs(original.mean_r - rebuilt.mean_r),
        "G": abs(original.mean_g - rebuilt.mean_g),
        "B": abs(original.mean_b - rebuilt.mean_b),
        "A": abs(original.mean_a - rebuilt.mean_a),
    }
    if max(channel_deltas.values()) > 18.0:
        warnings.append(
            "Per-channel averages drifted: "
            + ", ".join(f"{name} {delta:.1f}" for name, delta in channel_deltas.items())
        )

    original_spans = {
        "R": original.max_r - original.min_r,
        "G": original.max_g - original.min_g,
        "B": original.max_b - original.min_b,
        "A": original.max_a - original.min_a,
    }
    rebuilt_spans = {
        "R": rebuilt.max_r - rebuilt.min_r,
        "G": rebuilt.max_g - rebuilt.min_g,
        "B": rebuilt.max_b - rebuilt.min_b,
        "A": rebuilt.max_a - rebuilt.min_a,
    }
    for channel in ("R", "G", "B", "A"):
        original_span = original_spans[channel]
        rebuilt_span = rebuilt_spans[channel]
        if original_span >= 16 and rebuilt_span <= max(4, original_span * 0.5):
            warnings.append(f"{channel} channel range collapsed in the rebuilt preview.")
            break

    if original.has_alpha and original.mean_a > 8 and rebuilt.mean_a <= 8:
        warnings.append("Original appears to use alpha, but the rebuilt preview is effectively opaque.")

    return warnings

def _planner_path_specific_mip_warnings(
    plan_entry: Optional[TextureProcessingPlan],
    original_dds: "DdsInfo",
    rebuilt_dds: "DdsInfo",
    texture_type: str,
) -> List[str]:
    if plan_entry is None:
        return []

    warnings: List[str] = []
    path_kind = str(plan_entry.path_kind or "").strip().lower()
    rebuilt_format = rebuilt_dds.texconv_format.upper()
    original_format = original_dds.texconv_format.upper()
    semantic_subtype = str(getattr(plan_entry.decision, "semantic_subtype", "") or "").strip().lower()
    scalar_friendly_semantic = (
        texture_type in {"height", "roughness"}
        or (texture_type == "mask" and semantic_subtype in _SCALAR_HIGH_PRECISION_MASK_SUBTYPES)
    )

    if path_kind == "technical_high_precision_path":
        if texture_type not in {"height", "roughness", "mask"}:
            warnings.append("Technical high-precision path was used for a non-scalar texture classification; verify planner routing.")
        if rebuilt_format.endswith("_SRGB"):
            warnings.append("Technical high-precision path rebuilt into an sRGB DDS format, which is suspicious for scalar technical data.")
        if scalar_friendly_semantic and rebuilt_format not in {"BC4_UNORM", "BC4_SNORM", "R8_UNORM", "R16_UNORM"}:
            warnings.append("Technical high-precision scalar map did not rebuild into a typical scalar-friendly DDS format.")
        if texture_type == "mask" and plan_entry.alpha_policy == "none" and rebuilt_dds.has_alpha:
            warnings.append("Technical high-precision mask path unexpectedly rebuilt with alpha capability.")
        if rebuilt_dds.width != original_dds.width or rebuilt_dds.height != original_dds.height:
            warnings.append("Technical high-precision path changed dimensions; verify that scalar data still aligns with the source.")
        if "FLOAT" in original_format or "SNORM" in original_format:
            warnings.append("Original DDS format is float/snorm, but the current high-precision path is still not a true float-preserving runtime path.")
    elif path_kind == "visible_color_png_path" and texture_type in {"height", "roughness", "mask", "vector"}:
        warnings.append("Technical texture appears to have used the generic visible-color path; verify planner routing.")

    return warnings

def _planner_path_specific_normal_warnings(
    plan_entry: Optional[TextureProcessingPlan],
    info: "DdsInfo",
) -> List[str]:
    if plan_entry is None:
        return []
    warnings: List[str] = []
    path_kind = str(plan_entry.path_kind or "").strip().lower()
    if path_kind == "technical_high_precision_path":
        warnings.append("Normal map was routed to the technical high-precision scalar path, which is suspicious.")
    elif path_kind == "visible_color_png_path":
        warnings.append("Normal map was routed to the generic visible-color path, which is suspicious.")
    if plan_entry.alpha_policy == "premultiplied":
        warnings.append("Normal map is marked premultiplied, which usually indicates incorrect semantic routing.")
    if ("FLOAT" in info.texconv_format.upper() or "SNORM" in info.texconv_format.upper()) and path_kind != "technical_preserve_path":
        warnings.append("Precision-sensitive normal format is not on the technical preserve path; verify planner routing.")
    return warnings

def _dedupe_preserve_order(messages: Sequence[str]) -> List[str]:
    seen: set[str] = set()
    deduped: List[str] = []
    for message in messages:
        normalized = str(message).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped

def _texture_specific_preview_warnings(
    relative_path: str,
    original: Optional[TexturePreviewStats],
    rebuilt: Optional[TexturePreviewStats],
    *,
    family_members: Sequence[str] = (),
    sidecar_texts: Sequence[str] = (),
) -> List[str]:
    if original is None or rebuilt is None:
        return []

    lowered = relative_path.lower()
    texture_type, _confidence, _reason = classify_texture_path(
        relative_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    warnings: List[str] = []

    if texture_type == "normal":
        if rebuilt.mean_b < original.mean_b - 12.0:
            warnings.append("Normal-map blue channel darkened noticeably in the rebuilt preview.")
        if abs(rebuilt.mean_r - original.mean_r) > 18.0 or abs(rebuilt.mean_g - original.mean_g) > 18.0:
            warnings.append("Normal-map red/green midpoint drifted noticeably in the rebuilt preview.")

    if texture_type == "mask" or any(token in lowered for token in ("_orm", "_rma", "_mra", "_mask", "_sp", "_ao", "_m.", "_ma", "_mg", "_o.", "_subsurface", "_emi")):
        original_channel_spread = max(original.mean_r, original.mean_g, original.mean_b) - min(original.mean_r, original.mean_g, original.mean_b)
        rebuilt_channel_spread = max(rebuilt.mean_r, rebuilt.mean_g, rebuilt.mean_b) - min(rebuilt.mean_r, rebuilt.mean_g, rebuilt.mean_b)
        if original_channel_spread >= 12.0 and rebuilt_channel_spread <= 4.0:
            warnings.append("Packed/mask channels appear flatter or more identical after rebuild.")
        if (
            abs(rebuilt.mean_r - rebuilt.mean_g) <= 2.0
            and abs(rebuilt.mean_g - rebuilt.mean_b) <= 2.0
            and original_channel_spread >= 10.0
        ):
            warnings.append("Packed/mask channels now look nearly identical; verify channel packing.")

    if any(token in lowered for token in ("_disp", "displacement", "_height", "_bump", "parallax", "_dmap", "_d.", "_d_", "_o.")):
        original_gray_spread = max(
            abs(original.mean_r - original.mean_g),
            abs(original.mean_g - original.mean_b),
            abs(original.mean_r - original.mean_b),
        )
        rebuilt_gray_spread = max(
            abs(rebuilt.mean_r - rebuilt.mean_g),
            abs(rebuilt.mean_g - rebuilt.mean_b),
            abs(rebuilt.mean_r - rebuilt.mean_b),
        )
        if original_gray_spread <= 6.0 and rebuilt_gray_spread >= 12.0:
            warnings.append("Grayscale technical map gained noticeable color drift in the rebuilt preview.")
        original_luma_range = original.luma_max - original.luma_min
        rebuilt_luma_range = rebuilt.luma_max - rebuilt.luma_min
        if original_luma_range >= 22.0 and rebuilt_luma_range <= original_luma_range * 0.60:
            warnings.append("Grayscale technical-map range compressed noticeably after rebuild.")

    if texture_type == "vector" or any(token in lowered for token in ("_dr", "_op", "_flow", "_velocity")):
        original_channel_spread = max(original.mean_r, original.mean_g, original.mean_b) - min(original.mean_r, original.mean_g, original.mean_b)
        rebuilt_channel_spread = max(rebuilt.mean_r, rebuilt.mean_g, rebuilt.mean_b) - min(rebuilt.mean_r, rebuilt.mean_g, rebuilt.mean_b)
        if original_channel_spread >= 12.0 and rebuilt_channel_spread <= 4.0:
            warnings.append("Vector/effect-map channels appear flatter after rebuild; verify directional data.")

    return warnings

def _compare_file_sizes(original_path: Path, rebuilt_path: Path) -> Tuple[str, List[str]]:
    original_size = original_path.stat().st_size if original_path.exists() else 0
    rebuilt_size = rebuilt_path.stat().st_size if rebuilt_path.exists() else 0
    if original_size <= 0 or rebuilt_size <= 0:
        return f"File sizes: { _format_bytes(original_size) } -> { _format_bytes(rebuilt_size) }", []
    ratio = rebuilt_size / max(1, original_size)
    summary = f"File sizes: {_format_bytes(original_size)} -> {_format_bytes(rebuilt_size)} ({ratio * 100.0:.1f}%)"
    warnings: List[str] = []
    if ratio < 0.70:
        warnings.append("Rebuilt DDS is substantially smaller than the original, which can indicate format or mip loss.")
    elif ratio > 1.50:
        warnings.append("Rebuilt DDS is substantially larger than the original, which can indicate format or mip growth.")
    return summary, warnings

def _format_preview_pair_section(label: str, stats: Optional[TexturePreviewStats]) -> List[str]:
    if stats is None:
        return [f"{label}: preview statistics unavailable."]
    return [
        f"{label}:",
        f"- { _preview_stats_summary(stats) }",
    ]

def _collect_matching_compare_relative_paths(
    original_root: Path,
    rebuilt_root: Path,
    *,
    stop_event: Optional[object] = None,
) -> List[str]:
    original_paths = {
        path.as_posix()
        for path in collect_compare_relative_paths(original_root, rebuilt_root, stop_event=stop_event)
    }
    if not original_paths:
        return []
    original_only = {
        path.relative_to(original_root).as_posix()
        for path in collect_dds_files(original_root, (), stop_event=stop_event)
    }
    rebuilt_only = {
        path.relative_to(rebuilt_root).as_posix()
        for path in collect_dds_files(rebuilt_root, (), stop_event=stop_event)
    }
    return sorted(original_paths.intersection(original_only).intersection(rebuilt_only))

def build_mip_analysis_family_members_by_path(
    original_root: Path,
    rebuilt_root: Path,
    *,
    stop_event: Optional[object] = None,
) -> Dict[str, Tuple[str, ...]]:
    return _build_family_members_by_relative_path(
        _collect_matching_compare_relative_paths(original_root, rebuilt_root, stop_event=stop_event)
    )

def build_mip_analysis_detail(
    original_root: Path,
    rebuilt_root: Path,
    row: MipAnalysisRow,
    *,
    texconv_path: Optional[Path] = None,
    family_members_by_path: Optional[Dict[str, Tuple[str, ...]]] = None,
    stop_event: Optional[object] = None,
) -> str:
    raise_if_cancelled(stop_event, "Mip analysis detail cancelled.")
    relative = Path(row.relative_path)
    original_path = original_root / relative
    rebuilt_path = rebuilt_root / relative
    (
        sidecars_by_group,
        sidecars_by_folder,
        sidecars_by_texture_path,
        sidecars_by_texture_basename,
        sidecar_text_cache,
    ) = _build_loose_sidecar_index(original_root, stop_event=stop_event)
    resolved_family_members = family_members_by_path
    if resolved_family_members is None:
        resolved_family_members = build_mip_analysis_family_members_by_path(
            original_root,
            rebuilt_root,
            stop_event=stop_event,
        )
    family_members = resolved_family_members.get(row.relative_path, ())
    sidecar_texts = tuple(
        _collect_loose_sidecar_texts(
            original_root,
            relative,
            sidecars_by_group=sidecars_by_group,
            sidecars_by_folder=sidecars_by_folder,
            sidecars_by_texture_path=sidecars_by_texture_path,
            sidecars_by_texture_basename=sidecars_by_texture_basename,
            text_cache=sidecar_text_cache,
            stop_event=stop_event,
        )
    )
    texture_type, confidence, reason = classify_texture_path(
        row.relative_path,
        family_members=family_members,
        sidecar_texts=sidecar_texts,
    )
    detail_lines: List[str] = [
        f"Relative path: {row.relative_path}",
        "",
        "What this result means:",
        "- This row compares one DDS file found in both Original DDS root and Output root.",
        "- It checks header-level DDS settings first, then uses DirectXTex/native previews when available for a safer visual check.",
        "",
        f"Texture semantic hint: {texture_type} ({confidence}% confidence, {reason})",
        f"Planner profile: {row.planner_profile or 'unavailable'}",
        f"Planner path: {row.planner_path_kind or 'unavailable'}",
        f"Planner path detail: {describe_processing_path_kind(row.planner_path_kind) if row.planner_path_kind else 'unavailable'}",
        f"Planner backend mode: {row.planner_backend_mode or 'unavailable'}",
        f"Planner alpha policy: {row.planner_alpha_policy or 'unavailable'}",
        f"Original DDS: {original_path}",
        f"Rebuilt DDS: {rebuilt_path}",
        f"Original header: {row.original_size} | {row.original_format} | mips={row.original_mips}",
        f"Rebuilt header: {row.rebuilt_size} | {row.rebuilt_format} | mips={row.rebuilt_mips}",
    ]
    if row.planner_preserve_reason:
        detail_lines.append(f"Planner preserve reason: {row.planner_preserve_reason}")
    raise_if_cancelled(stop_event, "Mip analysis detail cancelled.")
    size_summary, size_warnings = _compare_file_sizes(original_path, rebuilt_path)
    compare_warnings: List[str] = []
    detail_lines.extend(["", size_summary])
    try:
        original_preview = _collect_preview_stats(
            ensure_dds_preview_png(
                texconv_path if texconv_path is not None and texconv_path.exists() else None,
                original_path,
                stop_event=stop_event,
            )
        )
    except Exception as exc:
        raise_if_cancelled(stop_event, "Mip analysis detail cancelled.")
        original_preview = None
        detail_lines.append(f"Original preview: unavailable ({exc})")
    else:
        detail_lines.extend(["", *_format_preview_pair_section("Original preview", original_preview)])
    try:
        rebuilt_preview = _collect_preview_stats(
            ensure_dds_preview_png(
                texconv_path if texconv_path is not None and texconv_path.exists() else None,
                rebuilt_path,
                stop_event=stop_event,
            )
        )
    except Exception as exc:
        raise_if_cancelled(stop_event, "Mip analysis detail cancelled.")
        rebuilt_preview = None
        detail_lines.append(f"Rebuilt preview: unavailable ({exc})")
    else:
        detail_lines.extend(["", *_format_preview_pair_section("Rebuilt preview", rebuilt_preview)])
    detail_lines.append("")
    detail_lines.append("Preview comparison:")
    compare_warnings = _compare_preview_stats(original_preview, rebuilt_preview)
    if compare_warnings:
        detail_lines.extend(f"- {warning}" for warning in compare_warnings)
    else:
        detail_lines.append("- No obvious preview drift detected.")

    if original_path.exists() and rebuilt_path.exists():
        try:
            original_info = parse_dds(original_path)
            rebuilt_info = parse_dds(rebuilt_path)
        except Exception:
            original_info = None
            rebuilt_info = None
        if original_info is not None and rebuilt_info is not None:
            if original_info.texconv_format.endswith("_SRGB") != rebuilt_info.texconv_format.endswith("_SRGB"):
                detail_lines.append("")
                detail_lines.append("Color-space check:")
                detail_lines.append("- sRGB/linear usage changed between original and rebuilt DDS.")
            elif original_info.texconv_format != rebuilt_info.texconv_format:
                detail_lines.append("")
                detail_lines.append("Color-space check:")
                detail_lines.append("- DDS format changed; verify that color handling still matches the source.")

    if size_warnings:
        detail_lines.append("")
        detail_lines.append("Size warnings:")
        detail_lines.extend(f"- {warning}" for warning in size_warnings)

    already_reported_warnings = set(size_warnings)
    already_reported_warnings.update(compare_warnings)
    analysis_warnings = [warning for warning in row.warnings if warning not in already_reported_warnings]
    if analysis_warnings:
        detail_lines.append("")
        detail_lines.append("Additional analysis warnings:")
        detail_lines.extend(f"- {warning}" for warning in analysis_warnings)
    else:
        detail_lines.append("")
        detail_lines.append("Additional analysis warnings: none.")

    raise_if_cancelled(stop_event, "Mip analysis detail cancelled.")
    return "\n".join(detail_lines)

def build_normal_validation_detail(
    root: Path,
    row: NormalValidationRow,
    *,
    texconv_path: Optional[Path] = None,
    stop_event: Optional[object] = None,
) -> str:
    raise_if_cancelled(stop_event, "Normal validation detail cancelled.")
    source_path = root / row.path
    detail_lines: List[str] = [
        f"Relative path: {row.path}",
        "",
        "What this result means:",
        "- This row comes from scanning normal-like DDS files in one root independently.",
        "- It checks format, dimensions, preview stability, and normal-map integrity signals.",
        "",
        f"Root label: {row.root_label}",
        f"Source root: {root}",
        f"Source path: {source_path}",
        f"Format: {row.texconv_format}",
        f"Size: {row.size_text}",
        f"Planner profile: {row.planner_profile or 'unavailable'}",
        f"Planner path: {row.planner_path_kind or 'unavailable'}",
        f"Planner path detail: {describe_processing_path_kind(row.planner_path_kind) if row.planner_path_kind else 'unavailable'}",
        f"Planner backend mode: {row.planner_backend_mode or 'unavailable'}",
        f"Planner alpha policy: {row.planner_alpha_policy or 'unavailable'}",
    ]
    if row.planner_preserve_reason:
        detail_lines.append(f"Planner preserve reason: {row.planner_preserve_reason}")

    if source_path.exists():
        try:
            preview_stats = _collect_preview_stats(
                ensure_dds_preview_png(
                    texconv_path if texconv_path is not None and texconv_path.exists() else None,
                    source_path,
                    stop_event=stop_event,
                )
            )
        except Exception as exc:
            raise_if_cancelled(stop_event, "Normal validation detail cancelled.")
            preview_stats = None
            detail_lines.extend(["", f"Preview statistics: unavailable ({exc})"])
        else:
            detail_lines.extend(["", *_format_preview_pair_section("Preview", preview_stats)])
            if preview_stats is not None:
                normal_signals: List[str] = []
                if preview_stats.mean_b < max(preview_stats.mean_r, preview_stats.mean_g):
                    normal_signals.append("Blue channel is not dominant; possible swizzle or non-standard normal encoding.")
                if preview_stats.mean_b < 110:
                    normal_signals.append("Blue channel average is low; possible channel issue or flattened normal detail.")
                if abs(preview_stats.mean_r - 128.0) > 26 or abs(preview_stats.mean_g - 128.0) > 26:
                    normal_signals.append("Red/green averages drift far from the usual 128 midpoint.")
                if (preview_stats.max_r - preview_stats.min_r) < 14 and (preview_stats.max_g - preview_stats.min_g) < 14:
                    normal_signals.append("Red/green ranges are narrow; precision may have been reduced.")
                if preview_stats.has_alpha and preview_stats.opaque_fraction < 0.95:
                    normal_signals.append("Alpha channel has visible variation; verify that it is meant to store data.")
                if normal_signals:
                    detail_lines.append("")
                    detail_lines.append("Preview-based normal-map signals:")
                    detail_lines.extend(f"- {signal}" for signal in normal_signals)
    else:
        detail_lines.extend(
            [
                "",
                "Preview statistics: unavailable.",
                "- DirectXTex/native preview statistics are unavailable or the source file is missing, so image-based normal checks are disabled.",
            ]
        )

    if row.issues:
        detail_lines.append("")
        detail_lines.append("Validation issues:")
        detail_lines.extend(f"- {issue}" for issue in row.issues)
    else:
        detail_lines.append("")
        detail_lines.append("Validation issues: none detected.")

    if "FLOAT" in row.texconv_format.upper() or "SNORM" in row.texconv_format.upper():
        detail_lines.append("")
        detail_lines.append("Precision note:")
        detail_lines.append("- This texture type or source format is sensitive to PNG intermediates; compare carefully after rebuild.")

    raise_if_cancelled(stop_event, "Normal validation detail cancelled.")
    return "\n".join(detail_lines)

def analyze_mip_behavior(
    original_root: Path,
    rebuilt_root: Path,
    *,
    texconv_path: Optional[Path] = None,
    limit: int = 3000,
    processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
    stop_event: Optional[object] = None,
    family_members_by_path: Optional[Dict[str, Tuple[str, ...]]] = None,
) -> List[MipAnalysisRow]:
    rows: List[MipAnalysisRow] = []
    resolved_family_members = family_members_by_path
    if resolved_family_members is None:
        resolved_family_members = build_mip_analysis_family_members_by_path(
            original_root,
            rebuilt_root,
            stop_event=stop_event,
        )
    (
        sidecars_by_group,
        sidecars_by_folder,
        sidecars_by_texture_path,
        sidecars_by_texture_basename,
        sidecar_text_cache,
    ) = _build_loose_sidecar_index(original_root, stop_event=stop_event)
    compare_relative_paths = sorted(resolved_family_members.keys())
    sidecar_texts_by_relative_path: Dict[str, Tuple[str, ...]] = {}
    for relative_path_text in compare_relative_paths:
        sidecar_texts_by_relative_path[relative_path_text] = tuple(
            _collect_loose_sidecar_texts(
                original_root,
                Path(relative_path_text),
                sidecars_by_group=sidecars_by_group,
                sidecars_by_folder=sidecars_by_folder,
                sidecars_by_texture_path=sidecars_by_texture_path,
                sidecars_by_texture_basename=sidecars_by_texture_basename,
                text_cache=sidecar_text_cache,
                stop_event=stop_event,
            )
        )
    for relative_path_text in compare_relative_paths:
        raise_if_cancelled(stop_event)
        relative_path = Path(relative_path_text)
        original_path = original_root / relative_path
        rebuilt_path = rebuilt_root / relative_path
        family_members = resolved_family_members.get(relative_path_text, ())
        sidecar_texts = sidecar_texts_by_relative_path.get(relative_path_text, ())
        plan_entry = (processing_plan_lookup or {}).get(relative_path_text)
        try:
            original_dds = parse_dds(original_path)
            rebuilt_dds = parse_dds(rebuilt_path)
        except Exception as exc:
            rows.append(
                MipAnalysisRow(
                    relative_path=relative_path.as_posix(),
                    original_format="-",
                    rebuilt_format="-",
                    original_size="-",
                    rebuilt_size="-",
                    original_mips=0,
                    rebuilt_mips=0,
                    warning_count=1,
                    planner_profile=plan_entry.profile.key if plan_entry is not None else "",
                    planner_path_kind=plan_entry.path_kind if plan_entry is not None else "",
                    planner_backend_mode=plan_entry.backend_capability.execution_mode if plan_entry is not None else "",
                    planner_alpha_policy=plan_entry.alpha_policy if plan_entry is not None else "",
                    planner_preserve_reason=plan_entry.preserve_reason if plan_entry is not None else "",
                    warnings=[f"Could not parse DDS headers: {exc}"],
                )
            )
            continue

        warnings: List[str] = []
        original_size_bytes = original_path.stat().st_size if original_path.exists() else 0
        rebuilt_size_bytes = rebuilt_path.stat().st_size if rebuilt_path.exists() else 0
        if original_size_bytes > 0 and rebuilt_size_bytes > 0:
            size_ratio = rebuilt_size_bytes / max(1, original_size_bytes)
            if size_ratio < 0.70:
                warnings.append("Rebuilt DDS is substantially smaller than the original, which can indicate format or mip loss.")
            elif size_ratio > 1.50:
                warnings.append("Rebuilt DDS is substantially larger than the original, which can indicate format or mip growth.")
        if original_dds.texconv_format.endswith("_SRGB") != rebuilt_dds.texconv_format.endswith("_SRGB"):
            warnings.append("sRGB/linear usage changed between original and rebuilt DDS.")
        rebuilt_max = max_mips_for_size(rebuilt_dds.width, rebuilt_dds.height)
        if rebuilt_dds.mip_count < original_dds.mip_count:
            warnings.append(
                f"Rebuilt file has {original_dds.mip_count - rebuilt_dds.mip_count} fewer mip level(s) than the original."
            )
        if (rebuilt_dds.width > original_dds.width or rebuilt_dds.height > original_dds.height) and rebuilt_dds.mip_count <= original_dds.mip_count:
            warnings.append("Upscaled texture kept the same or fewer mips, which can waste added resolution.")
        if rebuilt_dds.mip_count < rebuilt_max:
            warnings.append(f"Rebuilt size supports up to {rebuilt_max} mips, but only {rebuilt_dds.mip_count} are present.")
        if rebuilt_dds.width < original_dds.width or rebuilt_dds.height < original_dds.height:
            warnings.append("Rebuilt dimensions are smaller than the original DDS.")
        if original_dds.texconv_format != rebuilt_dds.texconv_format:
            warnings.append("DDS format changed between original and rebuilt output.")
        if original_dds.has_alpha != rebuilt_dds.has_alpha:
            warnings.append("Alpha capability changed between original and rebuilt DDS.")
        texture_type = classify_texture_path(
            relative_path_text,
            family_members=family_members,
            sidecar_texts=sidecar_texts,
        )[0]
        warnings.extend(
            _planner_path_specific_mip_warnings(
                plan_entry,
                original_dds,
                rebuilt_dds,
                texture_type,
            )
        )
        if is_png_intermediate_high_risk(texture_type, original_dds.texconv_format):
            if plan_entry is not None and str(plan_entry.path_kind).strip().lower() == "technical_high_precision_path":
                warnings.append("Source format is precision-sensitive; the high-precision path reduces generic PNG loss risk, but careful review is still required.")
            else:
                warnings.append("Source format is precision-sensitive; PNG intermediates can hide detail loss.")
        original_preview: Optional[TexturePreviewStats]
        rebuilt_preview: Optional[TexturePreviewStats]
        resolved_texconv = texconv_path if texconv_path is not None and texconv_path.exists() else None
        try:
            original_preview = _collect_preview_stats(ensure_dds_preview_png(resolved_texconv, original_path, stop_event=stop_event))
        except Exception:
            original_preview = None
        try:
            rebuilt_preview = _collect_preview_stats(ensure_dds_preview_png(resolved_texconv, rebuilt_path, stop_event=stop_event))
        except Exception:
            rebuilt_preview = None
        warnings.extend(
            warning
            for warning in _compare_preview_stats(original_preview, rebuilt_preview)
            if "preview could not be decoded for statistics" not in warning.lower()
            and "preview statistics are unavailable for both files" not in warning.lower()
        )
        warnings.extend(
            _texture_specific_preview_warnings(
                relative_path_text,
                original_preview,
                rebuilt_preview,
                family_members=family_members,
                sidecar_texts=sidecar_texts,
            )
        )
        warnings = _dedupe_preserve_order(warnings)

        rows.append(
            MipAnalysisRow(
                relative_path=relative_path.as_posix(),
                original_format=original_dds.texconv_format,
                rebuilt_format=rebuilt_dds.texconv_format,
                original_size=f"{original_dds.width}x{original_dds.height}",
                rebuilt_size=f"{rebuilt_dds.width}x{rebuilt_dds.height}",
                original_mips=original_dds.mip_count,
                rebuilt_mips=rebuilt_dds.mip_count,
                warning_count=len(warnings),
                planner_profile=plan_entry.profile.key if plan_entry is not None else "",
                planner_path_kind=plan_entry.path_kind if plan_entry is not None else "",
                planner_backend_mode=plan_entry.backend_capability.execution_mode if plan_entry is not None else "",
                planner_alpha_policy=plan_entry.alpha_policy if plan_entry is not None else "",
                planner_preserve_reason=plan_entry.preserve_reason if plan_entry is not None else "",
                warnings=warnings,
            )
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda row: (-row.warning_count, row.relative_path))
    return rows

def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0

def _sample_image_channel_stats(image_path: Path) -> Optional[Dict[str, float]]:
    if QImage is None:
        return None
    image = QImage(str(image_path))
    if image.isNull():
        return None
    width = image.width()
    height = image.height()
    if width <= 0 or height <= 0:
        return None
    step_x = max(1, width // 64)
    step_y = max(1, height // 64)
    r_total = g_total = b_total = a_total = 0.0
    count = 0
    for y in range(0, height, step_y):
        for x in range(0, width, step_x):
            color = QColor(image.pixel(x, y))
            r_total += color.red()
            g_total += color.green()
            b_total += color.blue()
            a_total += color.alpha()
            count += 1
    if count <= 0:
        return None
    return {
        "r": r_total / count,
        "g": g_total / count,
        "b": b_total / count,
        "a": a_total / count,
    }

def validate_normal_maps(
    root: Path,
    *,
    root_label: Optional[str] = None,
    texconv_path: Optional[Path] = None,
    limit: int = 1500,
    processing_plan_lookup: Optional[Dict[str, TextureProcessingPlan]] = None,
    stop_event: Optional[object] = None,
) -> List[NormalValidationRow]:
    display_root_label = (root_label or root.name or str(root)).strip() or str(root)
    dds_files = collect_dds_files(root, (), stop_event=stop_event)
    (
        sidecars_by_group,
        sidecars_by_folder,
        sidecars_by_texture_path,
        sidecars_by_texture_basename,
        sidecar_text_cache,
    ) = _build_loose_sidecar_index(root, stop_event=stop_event)
    grouped_by_key: Dict[str, List[Path]] = defaultdict(list)
    for dds_path in dds_files:
        grouped_by_key[derive_texture_group_key(dds_path.relative_to(root).as_posix())].append(dds_path)
    sidecar_texts_by_relative_path: Dict[str, Tuple[str, ...]] = {}
    for dds_path in dds_files:
        relative_path = dds_path.relative_to(root)
        sidecar_texts_by_relative_path[relative_path.as_posix()] = tuple(
            _collect_loose_sidecar_texts(
                root,
                relative_path,
                sidecars_by_group=sidecars_by_group,
                sidecars_by_folder=sidecars_by_folder,
                sidecars_by_texture_path=sidecars_by_texture_path,
                sidecars_by_texture_basename=sidecars_by_texture_basename,
                text_cache=sidecar_text_cache,
                stop_event=stop_event,
            )
        )
    normal_candidate_count = sum(
        1
        for dds_path in dds_files
        if classify_texture_path(
            dds_path.relative_to(root).as_posix(),
            family_members=tuple(member.relative_to(root).as_posix() for member in grouped_by_key[derive_texture_group_key(dds_path.relative_to(root).as_posix())]),
            sidecar_texts=sidecar_texts_by_relative_path.get(dds_path.relative_to(root).as_posix(), ()),
        )[0]
        == "normal"
    )
    preview_stats_budget = 200 if normal_candidate_count > 200 else normal_candidate_count
    preview_stats_used = 0

    rows: List[NormalValidationRow] = []
    for dds_path in dds_files:
        raise_if_cancelled(stop_event)
        relative_path = dds_path.relative_to(root).as_posix()
        group_members = grouped_by_key.get(derive_texture_group_key(relative_path), [])
        family_member_paths = tuple(member.relative_to(root).as_posix() for member in group_members)
        sidecar_texts = sidecar_texts_by_relative_path.get(relative_path, ())
        texture_type, _confidence, _reason = classify_texture_path(
            relative_path,
            family_members=family_member_paths,
            sidecar_texts=sidecar_texts,
        )
        if texture_type != "normal":
            continue
        plan_entry = (processing_plan_lookup or {}).get(relative_path)
        issues: List[str] = []
        try:
            info = parse_dds(dds_path)
        except Exception as exc:
            rows.append(
                NormalValidationRow(
                    path=relative_path,
                    root_label=display_root_label,
                    root_path=str(root),
                    texconv_format="-",
                    size_text="-",
                    issue_count=1,
                    planner_profile=plan_entry.profile.key if plan_entry is not None else "",
                    planner_path_kind=plan_entry.path_kind if plan_entry is not None else "",
                    planner_backend_mode=plan_entry.backend_capability.execution_mode if plan_entry is not None else "",
                    planner_alpha_policy=plan_entry.alpha_policy if plan_entry is not None else "",
                    planner_preserve_reason=plan_entry.preserve_reason if plan_entry is not None else "",
                    issues=[f"DDS header parse failed: {exc}"],
                )
            )
            continue

        if info.texconv_format in NORMAL_SUSPICIOUS_FORMATS:
            issues.append(f"Format {info.texconv_format} is unusual for a normal map.")
        elif info.texconv_format not in NORMAL_FRIENDLY_FORMATS:
            issues.append(f"Format {info.texconv_format} may be valid, but is not a common normal-map choice.")
        if "SRGB" in info.texconv_format:
            issues.append("sRGB normal maps are usually suspicious.")
        if not _is_power_of_two(info.width) or not _is_power_of_two(info.height):
            issues.append("Dimensions are not power-of-two.")
        if ("BC" in info.texconv_format or info.texconv_format.startswith("R")) and (info.width % 4 != 0 or info.height % 4 != 0):
            issues.append("Compressed DDS dimensions are not aligned to a 4x4 block size.")
        issues.extend(_planner_path_specific_normal_warnings(plan_entry, info))

        color_partner = next(
            (
                candidate
                for candidate in group_members
                if candidate != dds_path
                and classify_texture_path(
                    candidate.relative_to(root).as_posix(),
                    family_members=family_member_paths,
                    sidecar_texts=sidecar_texts_by_relative_path.get(candidate.relative_to(root).as_posix(), ()),
                )[0]
                == "color"
            ),
            None,
        )
        if color_partner is not None:
            try:
                color_info = parse_dds(color_partner)
                if (color_info.width, color_info.height) != (info.width, info.height):
                    issues.append("Normal map size differs from its color/albedo partner.")
            except Exception:
                pass

        if preview_stats_used < preview_stats_budget:
            try:
                preview_path = ensure_dds_preview_png(texconv_path if texconv_path is not None and texconv_path.exists() else None, dds_path)
                stats = _collect_preview_stats(preview_path)
                if stats is not None:
                    preview_stats_used += 1
                    if stats.mean_b < 110:
                        issues.append("Blue channel average is low; possible swizzle or non-standard normal encoding.")
                    if abs(stats.mean_r - 128.0) < 8 and abs(stats.mean_g - 128.0) < 8 and stats.mean_b > 220:
                        pass
                    elif stats.mean_b < max(stats.mean_r, stats.mean_g):
                        issues.append("Blue channel is not dominant; possible channel issue.")
                    if stats.has_alpha and stats.opaque_fraction < 0.90:
                        issues.append("Normal preview shows alpha variation; verify whether alpha stores packed data or should be preserved.")
                    if (stats.max_r - stats.min_r) < 12 and (stats.max_g - stats.min_g) < 12:
                        issues.append("Red/green channel range is narrow; precision may have been reduced.")
                    if "FLOAT" in info.texconv_format.upper() or "SNORM" in info.texconv_format.upper():
                        issues.append("Precision-sensitive normal format detected; PNG intermediates can hide detail loss.")
            except Exception:
                pass

        rows.append(
            NormalValidationRow(
                path=relative_path,
                root_label=display_root_label,
                root_path=str(root),
                texconv_format=info.texconv_format,
                size_text=f"{info.width}x{info.height}",
                issue_count=len(issues),
                planner_profile=plan_entry.profile.key if plan_entry is not None else "",
                planner_path_kind=plan_entry.path_kind if plan_entry is not None else "",
                planner_backend_mode=plan_entry.backend_capability.execution_mode if plan_entry is not None else "",
                planner_alpha_policy=plan_entry.alpha_policy if plan_entry is not None else "",
                planner_preserve_reason=plan_entry.preserve_reason if plan_entry is not None else "",
                issues=issues or ["No obvious issues detected."],
            )
        )
        if len(rows) >= limit:
            break
    rows.sort(key=lambda row: (-row.issue_count, row.path))
    return rows

def _estimate_grid_signal(image_path: Path) -> int:
    if QImage is None:
        return 0
    image = QImage(str(image_path))
    if image.isNull() or image.width() < 64 or image.height() < 64:
        return 0
    width = image.width()
    height = image.height()
    vertical_hits = 0
    horizontal_hits = 0

    sample_rows = [height // 4, height // 2, (height * 3) // 4]
    sample_cols = [width // 4, width // 2, (width * 3) // 4]

    for x in range(1, width - 1):
        score = 0.0
        for y in sample_rows:
            left = QColor(image.pixel(x - 1, y))
            right = QColor(image.pixel(x, y))
            score += abs(left.red() - right.red()) + abs(left.green() - right.green()) + abs(left.blue() - right.blue())
        if score / max(1, len(sample_rows)) > 160:
            vertical_hits += 1
    for y in range(1, height - 1):
        score = 0.0
        for x in sample_cols:
            top = QColor(image.pixel(x, y - 1))
            bottom = QColor(image.pixel(x, y))
            score += abs(top.red() - bottom.red()) + abs(top.green() - bottom.green()) + abs(top.blue() - bottom.blue())
        if score / max(1, len(sample_cols)) > 160:
            horizontal_hits += 1
    return int((vertical_hits / max(1, width)) * 100) + int((horizontal_hits / max(1, height)) * 100)

def detect_texture_atlases(
    root: Path,
    *,
    texconv_path: Optional[Path] = None,
    limit: int = 500,
) -> List[AtlasDetectionRow]:
    dds_files = collect_dds_files(root, ())
    preview_grid_budget = 200
    preview_grid_used = 0
    candidates: List[AtlasDetectionRow] = []
    for dds_path in dds_files:
        relative_path = dds_path.relative_to(root).as_posix()
        lowered = relative_path.lower()
        score = 0
        signals: List[str] = []
        try:
            info = parse_dds(dds_path)
        except Exception:
            continue

        if any(token in lowered for token in ("atlas", "sheet", "sprite", "icons", "decal", "/ui/", "impostor")):
            score += 3
            signals.append("Name/path suggests atlas or sheet usage.")
        if max(info.width, info.height) >= 2048:
            score += 1
            signals.append("Large texture dimensions.")
        ratio = max(info.width / max(1, info.height), info.height / max(1, info.width))
        if ratio >= 2.0:
            score += 1
            signals.append("Wide or tall aspect ratio.")
        if info.width % 256 == 0 and info.height % 256 == 0 and min(info.width, info.height) >= 512:
            score += 1
            signals.append("Dimensions align well to repeated tile cells.")

        if preview_grid_used < preview_grid_budget:
            try:
                preview_path = ensure_dds_preview_png(texconv_path if texconv_path is not None and texconv_path.exists() else None, dds_path)
                grid_signal = _estimate_grid_signal(preview_path)
                preview_grid_used += 1
                if grid_signal >= 8:
                    score += 2
                    signals.append("Preview image has repeated straight-line separators.")
            except Exception:
                pass

        if score <= 0:
            continue
        candidates.append(
            AtlasDetectionRow(
                path=relative_path,
                root_label=root.name or str(root),
                size_text=f"{info.width}x{info.height}",
                score=score,
                signals=signals,
            )
        )
    candidates.sort(key=lambda row: (-row.score, row.path))
    return candidates[:limit]
