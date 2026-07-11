"""Transactional serialization for Texture Research analysis reports."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, TextIO

from cdmw.core.atomic_file import atomic_text_writer
from cdmw.core.common import raise_if_cancelled


REPORT_FIELDNAMES = (
    "report_type", "path", "root", "root_path", "original_format", "rebuilt_format",
    "original_size", "rebuilt_size", "original_mips", "rebuilt_mips", "planner_profile",
    "planner_path_kind", "planner_backend_mode", "planner_alpha_policy", "planner_preserve_reason",
    "format", "size", "issue_count", "summary", "relative_path", "group_key", "system_area",
    "folder_bucket", "texture_type", "original_bytes", "rebuilt_bytes", "byte_delta", "byte_ratio",
    "original_width", "original_height", "rebuilt_width", "rebuilt_height", "pixel_ratio", "mip_delta",
    "rebuilt_format_changed", "risk_score", "risk_band", "signals", "profile_label", "reason_count",
)


def _json_rows(rows: Sequence[object], stop_event: Optional[object]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for row in rows:
        raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
        payload.append(asdict(row))
    return payload


def _json_payload(
    mip_rows: Sequence[object],
    normal_rows: Sequence[object],
    budget_rows: Sequence[object],
    budget_class_rows: Sequence[object],
    budget_group_rows: Sequence[object],
    budget_profile: object | None,
    stop_event: Optional[object],
) -> dict[str, object]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mip_rows": _json_rows(mip_rows, stop_event),
        "normal_rows": _json_rows(normal_rows, stop_event),
        "budget_rows": _json_rows(budget_rows, stop_event),
        "budget_class_rows": _json_rows(budget_class_rows, stop_event),
        "budget_group_rows": _json_rows(budget_group_rows, stop_event),
        "budget_profile": asdict(budget_profile) if budget_profile is not None else None,
    }


def _mip_csv_row(row: object) -> dict[str, object]:
    return {
        "report_type": "mip", "path": row.relative_path,
        "original_format": row.original_format, "rebuilt_format": row.rebuilt_format,
        "original_size": row.original_size, "rebuilt_size": row.rebuilt_size,
        "original_mips": row.original_mips, "rebuilt_mips": row.rebuilt_mips,
        "planner_profile": row.planner_profile, "planner_path_kind": row.planner_path_kind,
        "planner_backend_mode": row.planner_backend_mode, "planner_alpha_policy": row.planner_alpha_policy,
        "planner_preserve_reason": row.planner_preserve_reason, "root_path": "",
        "issue_count": row.warning_count, "summary": " | ".join(row.warnings),
    }


def _normal_csv_row(row: object) -> dict[str, object]:
    return {
        "report_type": "normal", "path": row.path, "root": row.root_label, "root_path": row.root_path,
        "planner_profile": row.planner_profile, "planner_path_kind": row.planner_path_kind,
        "planner_backend_mode": row.planner_backend_mode, "planner_alpha_policy": row.planner_alpha_policy,
        "planner_preserve_reason": row.planner_preserve_reason, "format": row.texconv_format,
        "size": row.size_text, "issue_count": row.issue_count, "summary": " | ".join(row.issues),
    }


def _budget_csv_row(row: object) -> dict[str, object]:
    return {
        "report_type": "budget_file", "path": row.relative_path, "relative_path": row.relative_path,
        "group_key": row.group_key, "system_area": row.system_area, "folder_bucket": row.folder_bucket,
        "texture_type": row.texture_type, "planner_profile": row.planner_profile,
        "planner_path_kind": row.planner_path_kind, "planner_alpha_policy": row.planner_alpha_policy,
        "original_format": row.original_format, "rebuilt_format": row.rebuilt_format,
        "original_bytes": row.original_bytes, "rebuilt_bytes": row.rebuilt_bytes,
        "byte_delta": row.byte_delta, "byte_ratio": f"{row.byte_ratio:.4f}",
        "original_width": row.original_width, "original_height": row.original_height,
        "rebuilt_width": row.rebuilt_width, "rebuilt_height": row.rebuilt_height,
        "pixel_ratio": f"{row.pixel_ratio:.4f}", "original_mips": row.original_mips,
        "rebuilt_mips": row.rebuilt_mips, "mip_delta": row.mip_delta,
        "rebuilt_format_changed": "yes" if row.format_changed else "no",
        "risk_score": row.risk_score, "risk_band": row.risk_band,
        "signals": " | ".join(row.risk_signals), "summary": row.ui_constraint_summary,
    }


def _summary_csv_rows(
    class_rows: Sequence[object],
    group_rows: Sequence[object],
    profile: object | None,
) -> Iterable[Mapping[str, object]]:
    for row in class_rows:
        yield {
            "report_type": "budget_class", "texture_type": row.texture_type,
            "byte_delta": row.total_byte_delta, "risk_score": f"{row.average_risk:.2f}",
            "risk_band": row.risk_band, "summary": " | ".join(row.sample_paths),
        }
    for row in group_rows:
        yield {
            "report_type": "budget_group", "group_key": row.group_key, "system_area": row.system_area,
            "original_bytes": row.total_original_bytes, "rebuilt_bytes": row.total_rebuilt_bytes,
            "byte_delta": row.total_byte_delta, "byte_ratio": f"{row.average_byte_ratio:.4f}",
            "rebuilt_width": f"{row.average_width:.1f}", "rebuilt_height": f"{row.average_height:.1f}",
            "risk_score": row.risk_score, "risk_band": row.risk_band,
            "signals": " | ".join(row.signals),
            "summary": f"textures={row.texture_count}, 2048+={row.large_2048_count}, 4096+={row.large_4096_count}",
        }
    if profile is not None:
        yield {
            "report_type": "budget_profile", "profile_label": profile.profile_label,
            "original_bytes": profile.total_original_bytes, "rebuilt_bytes": profile.total_rebuilt_bytes,
            "byte_delta": profile.total_byte_delta, "byte_ratio": f"{profile.total_byte_ratio:.4f}",
            "risk_score": f"{profile.high_risk_texture_fraction:.4f}",
            "signals": " | ".join(profile.reasons), "reason_count": len(profile.reasons),
            "summary": (
                f"highest_group_risk={profile.highest_group_risk}, changed={profile.changed_texture_count}, "
                f"upscaled={profile.upscaled_texture_count}"
            ),
        }


def _write_json(handle: TextIO, payload: object, stop_event: Optional[object]) -> None:
    for chunk in json.JSONEncoder(indent=2).iterencode(payload):
        raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
        handle.write(chunk)


def _write_csv(
    handle: TextIO,
    mip_rows: Sequence[object],
    normal_rows: Sequence[object],
    budget_rows: Sequence[object],
    class_rows: Sequence[object],
    group_rows: Sequence[object],
    profile: object | None,
    stop_event: Optional[object],
) -> None:
    writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDNAMES)
    writer.writeheader()
    row_groups = (
        (_mip_csv_row(row) for row in mip_rows),
        (_normal_csv_row(row) for row in normal_rows),
        (_budget_csv_row(row) for row in budget_rows),
        _summary_csv_rows(class_rows, group_rows, profile),
    )
    for rows in row_groups:
        for row in rows:
            raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
            writer.writerow(row)


def export_research_analysis_report(
    report_path: Path,
    mip_rows: Sequence[object],
    normal_rows: Sequence[object],
    *,
    budget_rows: Sequence[object] = (),
    budget_class_rows: Sequence[object] = (),
    budget_group_rows: Sequence[object] = (),
    budget_profile: object | None = None,
    stop_event: Optional[object] = None,
) -> Path:
    suffix = report_path.suffix.lower()
    raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
    with atomic_text_writer(report_path, encoding="utf-8") as handle:
        if suffix == ".json":
            payload = _json_payload(
                mip_rows, normal_rows, budget_rows, budget_class_rows,
                budget_group_rows, budget_profile, stop_event,
            )
            _write_json(handle, payload, stop_event)
        else:
            _write_csv(
                handle, mip_rows, normal_rows, budget_rows, budget_class_rows,
                budget_group_rows, budget_profile, stop_event,
            )
        raise_if_cancelled(stop_event, "Texture analysis report export cancelled.")
    return report_path


__all__ = ["export_research_analysis_report"]
