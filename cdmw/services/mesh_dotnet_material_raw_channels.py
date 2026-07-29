"""Raw support-map channels the resident .NET viewport consumes undecoded.

A normal or height input whose `.dds` is packaged verbatim is never decoded to a
preview PNG: `_generated_channels` discards the combiner's own output for that
channel, so decoding it would be work thrown away. The combiner still walks the
input, cannot open a `.dds` through `QImageReader`, and records it as unreadable
-- which `_material_compile_blockers` treats as a hard blocker. Keeping the
deferral and the note it produces in one place is what stops a deliberate skip
from reading as a failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QUrl


def _input_value(item: object, name: str, fallback: object = "") -> object:
    if isinstance(item, Mapping):
        return item.get(name, fallback)
    return getattr(item, name, fallback)


def _local_synthesis_dds_path(item: object) -> Path | None:
    for field_name in (
        "preview_texture_path",
        "source_dds_path",
        "source_texture_path",
    ):
        raw_path = str(_input_value(item, field_name) or "").strip()
        if not raw_path:
            continue
        if raw_path.casefold().startswith("file:"):
            raw_path = QUrl(raw_path).toLocalFile()
        try:
            path = Path(raw_path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if path.suffix.casefold() == ".dds" and path.is_file():
            return path
    return None


def _native_support_map_channel(
    item: object,
    raw_channels: Mapping[str, str],
) -> str:
    """Return the raw channel that already covers `item`, or "" when none does."""
    slot = str(_input_value(item, "slot_kind") or "").strip().casefold()
    semantic = str(_input_value(item, "semantic_type") or "").strip().casefold()
    if slot == "normal" or semantic == "normal":
        channel = "normal"
    elif slot in {"height", "displacement"} or semantic in {"height", "displacement"}:
        channel = "height"
    else:
        return ""
    raw_path = _local_synthesis_dds_path(
        {"source_dds_path": raw_channels.get(channel, "")}
    )
    return channel if raw_path is not None else ""


def _has_native_support_map(
    item: object,
    raw_channels: Mapping[str, str],
) -> bool:
    return bool(_native_support_map_channel(item, raw_channels))


def _relabel_deferred_raw_channel_notes(
    notes: tuple[object, ...],
    deferred_raw_channel_labels: Mapping[str, set[str]],
) -> list[str]:
    """Stop a skipped decode from reading as a texture that could not be opened.

    Left as `normal unreadable:<name>.dds`, the note aborted the whole material
    compile, so a preview whose textures were all present and resolved never
    reached the viewport and Solid (Textured) stayed flat.
    """
    rewritten: list[str] = []
    for note in notes:
        text = str(note or "")
        folded = text.casefold()
        for channel, labels in deferred_raw_channel_labels.items():
            prefix = f"{channel} unreadable:"
            if not labels or not folded.startswith(prefix):
                continue
            label = text[len(prefix):].strip()
            if label.casefold() in labels:
                text = f"{channel} not decoded, raw channel packaged:{label}"
            break
        rewritten.append(text)
    return rewritten


__all__ = [
    "_has_native_support_map",
    "_input_value",
    "_local_synthesis_dds_path",
    "_native_support_map_channel",
    "_relabel_deferred_raw_channel_notes",
]
