"""Bounded, presentation-only Rust Mesh Editor layout stored in the app cfg."""

from __future__ import annotations

import json
import math

MESH_LAYOUT_KEY = "ui/layout/v1/rust_mesh_editor"
PANEL_KEYS = ("cdmw_tool_rail", "cdmw_right_panels", "cdmw_pinned_tool_settings")


def validated_mesh_layout(value: object) -> dict:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in PANEL_KEYS:
        width = value.get(key)
        if type(width) in (int, float) and math.isfinite(width) and 64 <= width <= 8192:
            result[key] = float(width)
    positions = value.get("floating", {})
    if isinstance(positions, dict):
        positions = {
            key: point for key, point in positions.items()
            if isinstance(key, str) and 0 < len(key) <= 64
            and isinstance(point, list) and len(point) == 2
            and all(type(n) in (int, float) and math.isfinite(n) and abs(n) <= 32768 for n in point)
        }
        if positions:
            result["floating"] = dict(list(positions.items())[:32])
    return result


def load_mesh_layout(settings) -> dict:
    if str(settings.value("preferences/remember_splitter_sizes", True)).lower() in {"false", "0", "no", "off"}:
        return {}
    try:
        value = json.loads(str(settings.value(MESH_LAYOUT_KEY, "{}")))
    except (TypeError, ValueError):
        return {}
    return validated_mesh_layout(value)


def save_mesh_layout(settings, value: object) -> bool:
    if str(settings.value("preferences/remember_splitter_sizes", True)).lower() in {"false", "0", "no", "off"}:
        return False
    layout = validated_mesh_layout(value)
    if not layout:
        return False
    settings.setValue(MESH_LAYOUT_KEY, json.dumps(layout, separators=(",", ":")))
    return True
