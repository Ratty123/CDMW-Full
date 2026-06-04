from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence

from PySide6.QtGui import QImage


PREVIEW_COMPARISON_SCHEMA_VERSION = 1


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return result if math.isfinite(result) else fallback


def _load_image(path_value: object) -> QImage:
    path = Path(str(path_value or "")).expanduser()
    if not path.is_file():
        return QImage()
    image = QImage(str(path))
    if image.isNull():
        return QImage()
    return image.convertToFormat(QImage.Format.Format_RGBA8888)


def parse_roi(value: object) -> tuple[int, int, int, int]:
    if isinstance(value, Mapping):
        try:
            return (
                int(value.get("x", 0)),
                int(value.get("y", 0)),
                int(value.get("width", value.get("w", 0))),
                int(value.get("height", value.get("h", 0))),
            )
        except (TypeError, ValueError, OverflowError):
            return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        try:
            items = [int(item) for item in value[:4]]
        except (TypeError, ValueError, OverflowError):
            return ()
        return tuple(items) if len(items) == 4 else ()
    text = str(value or "").strip()
    if not text:
        return ()
    parts = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
    if len(parts) != 4:
        return ()
    try:
        return tuple(int(float(part)) for part in parts)
    except (TypeError, ValueError, OverflowError):
        return ()


def _clamp_roi(width: int, height: int, roi: object = ()) -> tuple[int, int, int, int]:
    parsed = parse_roi(roi)
    if not parsed:
        return (0, 0, max(0, width), max(0, height))
    x, y, roi_width, roi_height = parsed
    x0 = max(0, min(width, int(x)))
    y0 = max(0, min(height, int(y)))
    x1 = max(x0, min(width, x0 + max(0, int(roi_width))))
    y1 = max(y0, min(height, y0 + max(0, int(roi_height))))
    if x1 <= x0 or y1 <= y0:
        return (0, 0, max(0, width), max(0, height))
    return (x0, y0, x1, y1)


def _sample_points(width: int, height: int, *, roi: object = (), max_samples: int = 8192) -> Iterable[tuple[int, int]]:
    if width <= 0 or height <= 0:
        return
    x0, y0, x1, y1 = _clamp_roi(width, height, roi)
    roi_width = max(1, x1 - x0)
    roi_height = max(1, y1 - y0)
    total = max(1, roi_width * roi_height)
    stride = max(1, int(math.sqrt(total / max(1, max_samples))))
    for y in range(y0, y1, stride):
        for x in range(x0, x1, stride):
            yield x, y


def image_color_stats(path_value: object, *, roi: object = ()) -> Dict[str, object]:
    image = _load_image(path_value)
    parsed_roi = parse_roi(roi)
    if image.isNull():
        return {
            "path": str(path_value or ""),
            "status": "missing_or_unreadable",
            "width": 0,
            "height": 0,
            "sample_roi": {},
            "sample_count": 0,
        }
    width = int(image.width())
    height = int(image.height())
    x0, y0, x1, y1 = _clamp_roi(width, height, parsed_roi)
    count = 0
    sum_r = sum_g = sum_b = 0.0
    sum_luma = sum_luma2 = 0.0
    sum_sat = 0.0
    highlights = shadows = gold = silver = green = red_count = blue_count = 0
    for x, y in _sample_points(width, height, roi=parsed_roi):
        color = image.pixelColor(x, y)
        if color.alphaF() <= 0.02:
            continue
        red_value = color.redF()
        green_value = color.greenF()
        blue_value = color.blueF()
        luma = (0.299 * red_value) + (0.587 * green_value) + (0.114 * blue_value)
        maximum = max(red_value, green_value, blue_value)
        minimum = min(red_value, green_value, blue_value)
        saturation = 0.0 if maximum <= 1e-6 else (maximum - minimum) / maximum
        count += 1
        sum_r += red_value
        sum_g += green_value
        sum_b += blue_value
        sum_luma += luma
        sum_luma2 += luma * luma
        sum_sat += saturation
        if luma >= 0.82:
            highlights += 1
        if luma <= 0.12:
            shadows += 1
        if red_value >= 0.54 and green_value >= 0.38 and blue_value <= 0.36 and red_value >= green_value * 0.92 and saturation >= 0.18:
            gold += 1
        if luma >= 0.42 and saturation <= 0.14 and abs(red_value - green_value) <= 0.10 and abs(green_value - blue_value) <= 0.10:
            silver += 1
        if green_value >= 0.28 and green_value >= red_value * 1.16 and green_value >= blue_value * 1.10 and saturation >= 0.20:
            green += 1
        if red_value >= 0.34 and red_value >= green_value * 1.35 and red_value >= blue_value * 1.35 and saturation >= 0.22:
            red_count += 1
        if blue_value >= 0.34 and blue_value >= red_value * 1.18 and blue_value >= green_value * 1.05 and saturation >= 0.22:
            blue_count += 1
    if count <= 0:
        return {
            "path": str(path_value or ""),
            "status": "empty",
            "width": width,
            "height": height,
            "sample_roi": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
            "sample_count": 0,
        }
    inv = 1.0 / float(count)
    mean_luma = sum_luma * inv
    variance = max(0.0, (sum_luma2 * inv) - (mean_luma * mean_luma))
    contrast = math.sqrt(variance)
    return {
        "path": str(Path(str(path_value or "")).expanduser()),
        "status": "ok",
        "width": width,
        "height": height,
        "sample_roi": {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0},
        "sample_count": count,
        "mean_rgb": [round(sum_r * inv, 6), round(sum_g * inv, 6), round(sum_b * inv, 6)],
        "luma_mean": round(mean_luma, 6),
        "luma_contrast": round(contrast, 6),
        "saturation_mean": round(sum_sat * inv, 6),
        "highlight_ratio": round(highlights * inv, 6),
        "shadow_ratio": round(shadows * inv, 6),
        "gold_ratio": round(gold * inv, 6),
        "silver_ratio": round(silver * inv, 6),
        "green_ratio": round(green * inv, 6),
        "red_ratio": round(red_count * inv, 6),
        "blue_ratio": round(blue_count * inv, 6),
        "masked_detail_score": round(contrast + ((sum_sat * inv) * 0.32), 6),
    }


def _diagnostics_for_pair(preview: Mapping[str, object], reference: Mapping[str, object], *, label: str) -> list[Dict[str, object]]:
    if preview.get("status") != "ok" or reference.get("status") != "ok":
        return [{"code": "comparison_unavailable", "target": label, "severity": "warning"}]
    diagnostics: list[Dict[str, object]] = []

    def add(code: str, delta: float, severity: str = "warning") -> None:
        diagnostics.append({"code": code, "target": label, "delta": round(float(delta), 6), "severity": severity})

    luma_delta = _safe_float(preview.get("luma_mean")) - _safe_float(reference.get("luma_mean"))
    saturation_delta = _safe_float(preview.get("saturation_mean")) - _safe_float(reference.get("saturation_mean"))
    highlight_delta = _safe_float(preview.get("highlight_ratio")) - _safe_float(reference.get("highlight_ratio"))
    detail_delta = _safe_float(preview.get("masked_detail_score")) - _safe_float(reference.get("masked_detail_score"))
    preview_mean = preview.get("mean_rgb", ()) if isinstance(preview.get("mean_rgb", ()), Sequence) else ()
    reference_mean = reference.get("mean_rgb", ()) if isinstance(reference.get("mean_rgb", ()), Sequence) else ()
    if luma_delta <= -0.12:
        add("too_dark", luma_delta)
    elif luma_delta >= 0.12:
        add("too_bright", luma_delta)
    if saturation_delta >= 0.10:
        add("too_saturated", saturation_delta)
    elif saturation_delta <= -0.10:
        add("too_dull", saturation_delta)
    if highlight_delta >= 0.055:
        add("too_glossy", highlight_delta)
    elif highlight_delta <= -0.055:
        add("too_matte", highlight_delta)
    for code, field in (
        ("missing_gold", "gold_ratio"),
        ("missing_silver", "silver_ratio"),
        ("missing_green", "green_ratio"),
        ("missing_red", "red_ratio"),
    ):
        reference_ratio = _safe_float(reference.get(field))
        preview_ratio = _safe_float(preview.get(field))
        if reference_ratio >= 0.035 and preview_ratio <= max(0.012, reference_ratio * 0.45):
            add(code, preview_ratio - reference_ratio)
    blue_delta = _safe_float(preview.get("blue_ratio")) - _safe_float(reference.get("blue_ratio"))
    mean_blue_delta = (
        _safe_float(preview_mean[2]) - _safe_float(reference_mean[2])
        if len(preview_mean) >= 3 and len(reference_mean) >= 3
        else 0.0
    )
    reference_red_ratio = _safe_float(reference.get("red_ratio"))
    preview_red_ratio = _safe_float(preview.get("red_ratio"))
    if (
        blue_delta >= 0.04
        and _safe_float(preview.get("blue_ratio")) >= max(0.045, _safe_float(reference.get("blue_ratio")) * 1.8)
    ) or (reference_red_ratio >= 0.18 and preview_red_ratio <= reference_red_ratio * 0.25 and mean_blue_delta >= 0.12):
        add("unexpected_blue", blue_delta)
    if detail_delta <= -0.08:
        add("missing_masked_details", detail_delta)
    return diagnostics


def compare_preview_images(
    preview_path: object,
    *,
    item_icon_path: object = "",
    in_game_path: object = "",
    preview_roi: object = (),
    item_icon_roi: object = (),
    in_game_roi: object = (),
) -> Dict[str, object]:
    preview_stats = image_color_stats(preview_path, roi=preview_roi)
    reference_stats: Dict[str, object] = {}
    comparisons: list[Dict[str, object]] = []
    diagnostics: list[Dict[str, object]] = []
    for label, path_value, roi in (("item_icon", item_icon_path, item_icon_roi), ("in_game", in_game_path, in_game_roi)):
        if not str(path_value or "").strip():
            continue
        stats = image_color_stats(path_value, roi=roi)
        reference_stats[label] = stats
        pair_diagnostics = _diagnostics_for_pair(preview_stats, stats, label=label)
        comparisons.append({"target": label, "diagnostics": pair_diagnostics})
        diagnostics.extend(pair_diagnostics)
    return {
        "schema_version": PREVIEW_COMPARISON_SCHEMA_VERSION,
        "preview_path": str(preview_path or ""),
        "item_icon_path": str(item_icon_path or ""),
        "in_game_path": str(in_game_path or ""),
        "preview_stats": preview_stats,
        "reference_stats": reference_stats,
        "comparisons": comparisons,
        "diagnostics": diagnostics,
    }


def write_preview_comparison_report(
    report: Mapping[str, object],
    *,
    json_path: object,
    csv_path: object = "",
) -> Dict[str, str]:
    json_output = Path(str(json_path)).expanduser()
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    outputs = {"json": str(json_output)}
    csv_text = str(csv_path or "").strip()
    if csv_text:
        csv_output = Path(csv_text).expanduser()
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        with csv_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["target", "code", "severity", "delta"])
            writer.writeheader()
            diagnostic_items = report.get("diagnostics", ()) if isinstance(report, Mapping) else ()
            for item in diagnostic_items:
                if isinstance(item, Mapping):
                    writer.writerow(
                        {
                            "target": str(item.get("target", "")),
                            "code": str(item.get("code", "")),
                            "severity": str(item.get("severity", "")),
                            "delta": str(item.get("delta", "")),
                        }
                    )
        outputs["csv"] = str(csv_output)
    return outputs


__all__ = [
    "PREVIEW_COMPARISON_SCHEMA_VERSION",
    "compare_preview_images",
    "image_color_stats",
    "parse_roi",
    "write_preview_comparison_report",
]
