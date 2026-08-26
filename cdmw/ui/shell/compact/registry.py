"""Stable compact labels layered over the shell's existing tool keys."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompactToolSpec:
    key: str
    label: str
    category: str
    icon: str


COMPACT_CATEGORY_ORDER = ("Assets", "Authoring", "Textures", "Utilities")

COMPACT_TOOL_SPECS = (
    CompactToolSpec("archive_browser", "Browse Archives", "Assets", "folder"),
    CompactToolSpec("model_library", "Model Library", "Assets", "model"),
    CompactToolSpec("item_icons", "Item Icons", "Assets", "image"),
    CompactToolSpec("new_item_studio", "Create New Item", "Assets", "add"),
    CompactToolSpec("mesh_editor", "Mesh Editor", "Authoring", "mesh"),
    CompactToolSpec("placement_studio", "Placement & Animation", "Authoring", "person"),
    CompactToolSpec("texture_workflow", "Upscale & Process Textures", "Textures", "layers"),
    CompactToolSpec("replace_assistant", "Replace Textures", "Textures", "swap"),
    CompactToolSpec("recolor_variants", "Recolor Variants", "Textures", "droplet"),
    CompactToolSpec("texture_editor", "Texture Editor", "Textures", "brush"),
    CompactToolSpec("mod_package_retrofit", "Repackage Mods", "Utilities", "package"),
    CompactToolSpec("format_explorer", "Inspect File Formats", "Utilities", "document"),
    CompactToolSpec("translation_studio", "Edit Translations", "Utilities", "globe"),
    CompactToolSpec("research", "Asset Research", "Utilities", "book"),
    CompactToolSpec("text_search", "Search File Text", "Utilities", "search"),
)

_COMPACT_TOOL_SPECS_BY_KEY = {spec.key: spec for spec in COMPACT_TOOL_SPECS}
if len(_COMPACT_TOOL_SPECS_BY_KEY) != len(COMPACT_TOOL_SPECS):
    raise RuntimeError("Compact tool keys must be unique.")
if {spec.category for spec in COMPACT_TOOL_SPECS} != set(COMPACT_CATEGORY_ORDER):
    raise RuntimeError("Compact tool categories must match the stable category order.")


def compact_tool_spec(key: str) -> CompactToolSpec | None:
    return _COMPACT_TOOL_SPECS_BY_KEY.get(str(key or ""))


def compact_tool_label(key: str, fallback: str = "") -> str:
    spec = compact_tool_spec(key)
    return spec.label if spec is not None else str(fallback or key)


def compact_specs_for_category(category: str) -> tuple[CompactToolSpec, ...]:
    return tuple(spec for spec in COMPACT_TOOL_SPECS if spec.category == category)


__all__ = [
    "COMPACT_CATEGORY_ORDER",
    "COMPACT_TOOL_SPECS",
    "CompactToolSpec",
    "compact_specs_for_category",
    "compact_tool_label",
    "compact_tool_spec",
]
