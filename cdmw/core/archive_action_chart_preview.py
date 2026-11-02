"""Read-only Archive Browser inspector for `.paac` action charts and `.paacdesc`.

Structure comes from `cdmw.core.action_chart_binary`, which follows the game's own
chart loader. The view lists what a moveset modder needs to find their way: the
animations each chart plays with their time ranges, the nodes that group them, the
frame events by kind, the string tables, and which values can be edited in place.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from cdmw.core.action_chart_binary import (
    ACTION_CHART_STRING_TABLES,
    EDITABLE_CHART_FIELDS,
    LAYOUT_CHART,
    ActionChart,
    ActionChartError,
    decode_action_chart,
    decode_action_package_description,
    frame_event_at,
)
from cdmw.core.archive_model_references import _StructuredBinaryPreviewBundle

ACTION_CHART_EXTENSIONS = frozenset({".paac", ".paacdesc"})
ANIMATION_ROW_LIMIT = 120
NODE_ROW_LIMIT = 40
TABLE_SAMPLE = 6
SECTION_ROW_LIMIT = 80


def _seconds(value: float) -> str:
    return f"{value:.3f}"


def _event_kinds(chart: ActionChart, data: bytes) -> Counter:
    kinds: Counter = Counter()
    for animation in chart.animations:
        for ref in animation.events:
            try:
                kinds[frame_event_at(chart, data, ref).kind_name] += 1
            except (ActionChartError, IndexError, ValueError):
                kinds["unreadable"] += 1
    return kinds


def _section_lines(chart: ActionChart) -> list[str]:
    """Bytes per member, in stream order; repeated members (one per animation) are summed."""

    totals: dict[tuple[str, bool], list[int]] = {}
    for span in chart.spans:
        row = totals.setdefault((span.name, span.explained), [0, 0, 0])
        row[0] += span.size
        row[1] += 1
        row[2] += span.count if span.item_size else 0
    lines = ["", "Sections (bytes, occurrences, records):"]
    for (name, explained), (size, occurrences, records) in list(totals.items())[:SECTION_ROW_LIMIT]:
        shape = f"  {records:,} records" if records else ""
        marker = "  [not decoded]" if not explained else ""
        lines.append(f"  {size:>11,}  x{occurrences:<6,} {name}{shape}{marker}")
    return lines


def _chart_lines(chart: ActionChart, data: bytes, virtual_path: str) -> list[str]:
    counts = chart.counts
    lines = [
        f"Action chart inspector for {virtual_path}",
        "",
        "Summary:",
        f"- Size: {chart.size:,} bytes, all of them read into named sections",
        f"- Animations: {counts.get('animations', 0):,} in {counts.get('nodes', 0):,} nodes",
        f"- Branches: {counts.get('branches', 0):,}",
        f"- Frame events on animations: {counts.get('frame events', 0):,}",
        f"- Chart speed rate (ActionSpeedRate): {chart.action_speed_rate:g}",
        f"- End-behaviour chart: {'yes' if chart.end_behavior else 'no'}; NPC schedule chart: {'yes' if chart.npc_schedule else 'no'}",
    ]
    names = chart.tables[0]
    included = [names.value(index) for index in chart.include_names]
    if included:
        lines.append(f"- Included charts: {', '.join(name for name in included if name)}")
    lines.extend(["", "String tables:"])
    for table in chart.tables:
        lines.append(f"- {table.index} {table.role}: {len(table.raw):,}")
        for value in table.values[:TABLE_SAMPLE]:
            lines.append(f"    {value}")
        if len(table.raw) > TABLE_SAMPLE:
            lines.append(f"    ... {len(table.raw) - TABLE_SAMPLE:,} more")
    lines.extend(["", "Animations (index: start-end seconds, clip, blend, frame events):"])
    for animation in chart.animations[:ANIMATION_ROW_LIMIT]:
        blend = chart.blend_name(animation)
        speed = animation.array("animationSpeedInfoArray").count
        extra = []
        if blend:
            extra.append(f"blend {blend}")
        if speed:
            extra.append(f"{speed} speed window{'s' if speed != 1 else ''}")
        if animation.events:
            extra.append(f"{len(animation.events)} events")
        suffix = f" ({', '.join(extra)})" if extra else ""
        lines.append(
            f"  {animation.index:>5}: {_seconds(animation.start_time)}-{_seconds(animation.end_time)}  "
            f"{chart.clip_name(animation) or '(no clip)'}{suffix}"
        )
    if len(chart.animations) > ANIMATION_ROW_LIMIT:
        lines.append(f"  ... {len(chart.animations) - ANIMATION_ROW_LIMIT:,} more animations")
    lines.extend(["", "Nodes (index: animations):"])
    for node in chart.nodes[:NODE_ROW_LIMIT]:
        last = node.first_animation + node.animation_count - 1
        span = f"{node.first_animation}-{last}" if node.animation_count > 1 else str(node.first_animation)
        group = f", contents group {node.contents_group}" if node.contents_group != 0xFFFF else ""
        lines.append(f"  {node.index:>5}: {span if node.animation_count else 'none'}{group}")
    if len(chart.nodes) > NODE_ROW_LIMIT:
        lines.append(f"  ... {len(chart.nodes) - NODE_ROW_LIMIT:,} more nodes")
    kinds = _event_kinds(chart, data)
    if kinds:
        lines.extend(["", "Frame events by kind:"])
        lines.extend(f"  {count:>7,}  {name}" for name, count in kinds.most_common())
    lines.extend(_section_lines(chart))
    lines.extend(["", "Editable in place (same length):"])
    lines.extend(f"  {name}" for name in EDITABLE_CHART_FIELDS)
    lines.append("  Any string table entry, at any length up to 254 characters")
    return lines


def _common_lines(chart: ActionChart, virtual_path: str) -> list[str]:
    lines = [
        f"Action chart inspector for {virtual_path}",
        "",
        "Summary:",
        f"- Layout: {chart.layout} (the shared action table, read by its own loader)",
        f"- Size: {chart.size:,} bytes; {chart.explained_bytes:,} read into named sections",
    ]
    for span in chart.unexplained_spans:
        lines.append(f"- Not decoded: {span.size:,} bytes at offset {span.offset:,} ({span.name})")
    lines.extend(_section_lines(chart))
    return lines


def _description_lines(data: bytes, virtual_path: str) -> list[str]:
    description = decode_action_package_description(data)
    lines = [
        f"Action package description inspector for {virtual_path}",
        "",
        "Summary:",
        f"- Packages: {len(description.packages):,}",
        f"- Strings: {len(description.strings):,}",
        "",
        "Packages (name: main slot = chart; weapon slots):",
    ]
    for package in description.packages:
        lines.append(f"  {package.name}: {package.main_slot} = {package.main_chart}")
        for slot, chart in package.sub_packages:
            lines.append(f"      {slot} = {chart}")
    return lines


def build_action_chart_preview(data: bytes, virtual_path: str, *, extension: str) -> _StructuredBinaryPreviewBundle:
    """Decode and describe one chart or descriptor.

    Raises `ActionChartError` when the bytes do not follow the grammar, so the caller
    keeps its strings fallback.
    """

    if str(extension or "").lower() == ".paacdesc":
        return _StructuredBinaryPreviewBundle(
            preview_text="\n".join(_description_lines(data, virtual_path)),
            detail_lines=(
                "Lists which action charts each character package uses for its main slot and weapon slots.",
                "This inspector is read-only.",
            ),
            metadata_label="Action Package Description",
        )
    chart = decode_action_chart(data, virtual_path=virtual_path)
    if chart.layout != LAYOUT_CHART:
        return _StructuredBinaryPreviewBundle(
            preview_text="\n".join(_common_lines(chart, virtual_path)),
            detail_lines=("Decoded with the game's commonactioninfo loader layout.", "This inspector is read-only."),
            metadata_label="Common Action Info",
        )
    detail: Sequence[str] = (
        "Decoded with the layout of the game's chart loader; every byte belongs to a named section.",
        "Times are in seconds. Node, branch and frame-event payload fields that are not named here are kept as raw bytes.",
        "This inspector is read-only.",
    )
    return _StructuredBinaryPreviewBundle(
        preview_text="\n".join(_chart_lines(chart, data, virtual_path)),
        detail_lines=tuple(detail),
        metadata_label=f"Action Chart ({chart.counts.get('animations', 0):,} animations)",
    )


__all__ = ["ACTION_CHART_EXTENSIONS", "ACTION_CHART_STRING_TABLES", "build_action_chart_preview"]
