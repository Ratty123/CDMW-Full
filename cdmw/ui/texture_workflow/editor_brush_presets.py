from __future__ import annotations

"""Brush preset state helpers for the standalone Texture Editor UI."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple


BUILTIN_TEXTURE_EDITOR_BRUSH_PRESET_ORDER = (
    "detail",
    "soft_paint",
    "hard_block",
    "texture",
    "speckle",
    "retouch",
)


@dataclass(frozen=True, slots=True)
class TextureEditorBrushPresetControlState:
    size: int
    hardness: int
    opacity: int
    flow: int
    spacing: int
    roundness: int
    angle_degrees: int
    smoothing: int
    tip: str
    pattern: str
    custom_tip_path: str
    size_step_mode: str


@dataclass(frozen=True, slots=True)
class TextureEditorSavedBrushPresetState:
    changed: bool
    custom_presets: Dict[str, Dict[str, object]]
    preset_name: str
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorCustomBrushTipState:
    changed: bool
    custom_tip_path: str
    brush_tip_key: str
    status_text: str
    error: bool


@dataclass(frozen=True, slots=True)
class TextureEditorBrushPresetComboEntry:
    label: str
    key: str


@dataclass(frozen=True, slots=True)
class TextureEditorBrushPresetComboState:
    entries: Tuple[TextureEditorBrushPresetComboEntry, ...]
    selected_key: str


def texture_editor_brush_preset_definitions() -> Dict[str, Dict[str, object]]:
    return {
        "detail": {"size": 4, "hardness": 90, "opacity": 100, "flow": 100, "spacing": 8, "tip": "round", "pattern": "solid", "roundness": 100, "angle": 0, "smoothing": 0, "size_step_mode": "fine"},
        "soft_paint": {"size": 28, "hardness": 35, "opacity": 70, "flow": 55, "spacing": 16, "tip": "round", "pattern": "solid", "roundness": 100, "angle": 0, "smoothing": 28, "size_step_mode": "normal"},
        "hard_block": {"size": 20, "hardness": 100, "opacity": 100, "flow": 100, "spacing": 12, "tip": "square", "pattern": "solid", "roundness": 100, "angle": 0, "smoothing": 0, "size_step_mode": "normal"},
        "texture": {"size": 18, "hardness": 75, "opacity": 78, "flow": 72, "spacing": 28, "tip": "round", "pattern": "grain", "roundness": 84, "angle": 0, "smoothing": 8, "size_step_mode": "normal"},
        "speckle": {"size": 14, "hardness": 58, "opacity": 82, "flow": 62, "spacing": 34, "tip": "round", "pattern": "speckle", "roundness": 100, "angle": 0, "smoothing": 0, "size_step_mode": "fine"},
        "retouch": {"size": 12, "hardness": 65, "opacity": 82, "flow": 48, "spacing": 14, "tip": "flat", "pattern": "solid", "roundness": 42, "angle": -32, "smoothing": 14, "size_step_mode": "fine"},
    }


def normalize_texture_editor_custom_brush_presets(raw: object) -> Dict[str, Dict[str, object]]:
    try:
        parsed = json.loads(str(raw or "{}").strip() or "{}")
    except Exception:
        parsed = {}
    output: Dict[str, Dict[str, object]] = {}
    if not isinstance(parsed, dict):
        return output
    for key, value in parsed.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        preset_key = key.strip().lower()
        if not preset_key or preset_key in {"custom"}:
            continue
        output[preset_key] = dict(value)
    return output


def serialize_texture_editor_custom_brush_presets(presets: Mapping[str, Mapping[str, object]]) -> str:
    normalized = {
        str(key).strip().lower(): dict(value)
        for key, value in presets.items()
        if str(key).strip() and str(key).strip().lower() != "custom"
    }
    return json.dumps(normalized, indent=2, sort_keys=True)


def merged_texture_editor_brush_presets(
    custom_presets: Mapping[str, Mapping[str, object]],
) -> Dict[str, Dict[str, object]]:
    presets = texture_editor_brush_preset_definitions()
    presets.update({str(key): dict(value) for key, value in custom_presets.items()})
    return presets


def texture_editor_brush_preset_label(key: object, *, custom: bool = False) -> str:
    label = str(key or "").replace("_", " ").title()
    return f"{label} *" if custom else label


def texture_editor_brush_preset_combo_state(
    custom_presets: Mapping[str, Mapping[str, object]],
    *,
    preserve_key: Optional[str],
    current_key: object,
) -> TextureEditorBrushPresetComboState:
    selected_key = str(preserve_key or current_key or "custom")
    entries = [TextureEditorBrushPresetComboEntry("Custom", "custom")]
    entries.extend(
        TextureEditorBrushPresetComboEntry(texture_editor_brush_preset_label(key), key)
        for key in BUILTIN_TEXTURE_EDITOR_BRUSH_PRESET_ORDER
    )
    entries.extend(
        TextureEditorBrushPresetComboEntry(texture_editor_brush_preset_label(key, custom=True), str(key))
        for key in sorted(custom_presets.keys())
    )
    return TextureEditorBrushPresetComboState(entries=tuple(entries), selected_key=selected_key)


def texture_editor_brush_preset_values(
    custom_presets: Mapping[str, Mapping[str, object]],
    preset_key: object,
) -> Optional[Dict[str, object]]:
    values = merged_texture_editor_brush_presets(custom_presets).get(str(preset_key or "").strip().lower())
    return None if values is None else dict(values)


def texture_editor_should_mark_brush_preset_custom(current_key: object) -> bool:
    return str(current_key or "") != "custom"


def texture_editor_brush_preset_control_state(
    values: Mapping[str, object],
) -> TextureEditorBrushPresetControlState:
    return TextureEditorBrushPresetControlState(
        size=int(values["size"]),
        hardness=int(values["hardness"]),
        opacity=int(values["opacity"]),
        flow=int(values["flow"]),
        spacing=int(values["spacing"]),
        roundness=int(values.get("roundness", 100)),
        angle_degrees=int(values.get("angle", 0)),
        smoothing=int(values.get("smoothing", 0)),
        tip=str(values["tip"]),
        pattern=str(values["pattern"]),
        custom_tip_path=str(values.get("custom_tip_path", "") or ""),
        size_step_mode=str(values.get("size_step_mode", "normal")),
    )


def normalized_texture_editor_custom_brush_preset_key(name: object) -> str:
    return "_".join(part for part in str(name or "").strip().lower().split() if part)


def texture_editor_brush_preset_missing_name_status_text() -> str:
    return "Enter a preset name first."


def texture_editor_brush_preset_saved_status_text(preset_name: object) -> str:
    return f"Saved brush preset '{preset_name}'."


def texture_editor_custom_brush_loaded_status_text() -> str:
    return "Loaded custom brush image stamp."


def texture_editor_custom_brush_cleared_status_text() -> str:
    return "Cleared custom brush image stamp."


def texture_editor_custom_brush_preset_from_controls(
    *,
    size: object,
    hardness: object,
    opacity: object,
    flow: object,
    spacing: object,
    tip: object,
    pattern: object,
    custom_tip_path: object,
    roundness: object,
    angle: object,
    smoothing: object,
    size_step_mode: object,
) -> Dict[str, object]:
    return {
        "size": int(size),
        "hardness": int(hardness),
        "opacity": int(opacity),
        "flow": int(flow),
        "spacing": int(spacing),
        "tip": str(tip or "round"),
        "pattern": str(pattern or "solid"),
        "custom_tip_path": str(custom_tip_path or "").strip(),
        "roundness": int(roundness),
        "angle": int(angle),
        "smoothing": int(smoothing),
        "size_step_mode": str(size_step_mode or "normal"),
    }


def texture_editor_saved_custom_brush_preset_state(
    custom_presets: Mapping[str, Mapping[str, object]],
    name: object,
    *,
    size: object,
    hardness: object,
    opacity: object,
    flow: object,
    spacing: object,
    tip: object,
    pattern: object,
    custom_tip_path: object,
    roundness: object,
    angle: object,
    smoothing: object,
    size_step_mode: object,
) -> TextureEditorSavedBrushPresetState:
    preset_name = normalized_texture_editor_custom_brush_preset_key(name)
    if not preset_name:
        return TextureEditorSavedBrushPresetState(
            changed=False,
            custom_presets={str(key): dict(value) for key, value in custom_presets.items()},
            preset_name="",
            status_text=texture_editor_brush_preset_missing_name_status_text(),
            error=True,
        )
    updated = {str(key): dict(value) for key, value in custom_presets.items()}
    updated[preset_name] = texture_editor_custom_brush_preset_from_controls(
        size=size,
        hardness=hardness,
        opacity=opacity,
        flow=flow,
        spacing=spacing,
        tip=tip,
        pattern=pattern,
        custom_tip_path=custom_tip_path,
        roundness=roundness,
        angle=angle,
        smoothing=smoothing,
        size_step_mode=size_step_mode,
    )
    return TextureEditorSavedBrushPresetState(
        changed=True,
        custom_presets=updated,
        preset_name=preset_name,
        status_text=texture_editor_brush_preset_saved_status_text(preset_name),
        error=False,
    )


def texture_editor_loaded_custom_brush_tip_state(path_text: object) -> TextureEditorCustomBrushTipState:
    raw_path = str(path_text or "").strip()
    if not raw_path:
        return TextureEditorCustomBrushTipState(
            changed=False,
            custom_tip_path="",
            brush_tip_key="",
            status_text="",
            error=False,
        )
    return TextureEditorCustomBrushTipState(
        changed=True,
        custom_tip_path=str(Path(raw_path).expanduser().resolve()),
        brush_tip_key="image_stamp",
        status_text=texture_editor_custom_brush_loaded_status_text(),
        error=False,
    )


def texture_editor_cleared_custom_brush_tip_state(
    current_path: object,
    *,
    current_tip: object,
) -> TextureEditorCustomBrushTipState:
    if not str(current_path or "").strip():
        return TextureEditorCustomBrushTipState(
            changed=False,
            custom_tip_path="",
            brush_tip_key=str(current_tip or ""),
            status_text="",
            error=False,
        )
    current_tip_key = str(current_tip or "round")
    return TextureEditorCustomBrushTipState(
        changed=True,
        custom_tip_path="",
        brush_tip_key="round" if current_tip_key == "image_stamp" else current_tip_key,
        status_text=texture_editor_custom_brush_cleared_status_text(),
        error=False,
    )


__all__ = [
    "BUILTIN_TEXTURE_EDITOR_BRUSH_PRESET_ORDER",
    "TextureEditorBrushPresetControlState",
    "TextureEditorBrushPresetComboEntry",
    "TextureEditorBrushPresetComboState",
    "TextureEditorCustomBrushTipState",
    "TextureEditorSavedBrushPresetState",
    "merged_texture_editor_brush_presets",
    "normalized_texture_editor_custom_brush_preset_key",
    "normalize_texture_editor_custom_brush_presets",
    "serialize_texture_editor_custom_brush_presets",
    "texture_editor_brush_preset_combo_state",
    "texture_editor_brush_preset_control_state",
    "texture_editor_brush_preset_definitions",
    "texture_editor_brush_preset_label",
    "texture_editor_brush_preset_values",
    "texture_editor_brush_preset_missing_name_status_text",
    "texture_editor_brush_preset_saved_status_text",
    "texture_editor_custom_brush_cleared_status_text",
    "texture_editor_custom_brush_loaded_status_text",
    "texture_editor_custom_brush_preset_from_controls",
    "texture_editor_cleared_custom_brush_tip_state",
    "texture_editor_loaded_custom_brush_tip_state",
    "texture_editor_saved_custom_brush_preset_state",
    "texture_editor_should_mark_brush_preset_custom",
]
