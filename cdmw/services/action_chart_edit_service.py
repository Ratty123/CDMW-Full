"""Edit a shipped `.paac` action chart and write it as a DMM loose mod.

The writes are the constrained ones `cdmw.core.action_chart_binary` proves: clip
retargets rebuild the animation string table (any length), and timing edits rewrite
f32 values in place from `EDITABLE_CHART_FIELDS`. Nothing else in the chart changes.
Every result is decoded again and compared with the shipped chart, so what the user
reviews is what the new bytes say, not what was asked for.

Clip strings are stored relative to `character/motion/`, where 65,305 of the 65,320
clip references in the shipped charts resolve (game 2.04.03).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator, Mapping, Optional

from cdmw.core.action_chart_binary import (
    ANIMATION_TABLE,
    LAYOUT_CHART,
    ActionChart,
    ActionChartError,
    ChartValueEdit,
    action_chart_layout,
    apply_chart_value_edits,
    chart_value_offset,
    decode_action_chart,
    frame_event_at,
    retarget_animation,
)
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.domain.archives.mutation import ArchivePatchRequest
from cdmw.models import ArchiveEntry, ModPackageInfo

CLIP_ROOT = "character/motion/"
ACTION_CHART_EXTENSION = ".paac"

#: Per-animation fields in the order the editor lists them; `item` counts records.
_ARRAY_FIELDS = (
    ("animationSpeedInfoArray", ("speed.start_time", "speed.end_time", "speed.rate")),
    ("frameTag", ("frame_tag.start_time", "frame_tag.end_time")),
    ("justTimeFrameTagInfo", ("just_time.start_time", "just_time.end_time")),
)


@dataclass(frozen=True, slots=True)
class ClipRetarget:
    """Point every use of clip `old` at clip `new`, both as the chart stores them."""

    old: str
    new: str


@dataclass(frozen=True, slots=True)
class ActionChartEditRequest:
    retargets: tuple[ClipRetarget, ...] = ()
    values: tuple[ChartValueEdit, ...] = ()

    @property
    def empty(self) -> bool:
        return not any(item.old != item.new for item in self.retargets) and not self.values


@dataclass(frozen=True, slots=True)
class ChartValueRow:
    """One editable f32 as the chart holds it. `animation` is -1 for the chart's own rate."""

    field: str
    animation: int
    item: int
    value: float
    event_kind: str = ""

    @property
    def key(self) -> tuple[str, int, int]:
        return self.field, self.animation, self.item

    def edit(self, value: float) -> ChartValueEdit:
        return ChartValueEdit(self.field, float(value), animation=max(self.animation, 0), item=self.item)


@dataclass(frozen=True, slots=True)
class ClipRow:
    index: int
    clip: str
    uses: int


@dataclass(frozen=True, slots=True)
class ClipChange:
    index: int
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class ValueChange:
    row: ChartValueRow
    old: float


@dataclass(frozen=True, slots=True)
class ActionChartChanges:
    """Differences between the shipped chart and the edited bytes, both decoded."""

    clips: tuple[ClipChange, ...] = ()
    values: tuple[ValueChange, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.clips and not self.values


@dataclass(frozen=True, slots=True)
class ActionChartEditResult:
    data: bytes
    chart: ActionChart
    changes: ActionChartChanges


def is_action_chart_path(virtual_path: str) -> bool:
    return PurePosixPath(str(virtual_path or "").replace("\\", "/").lower()).suffix == ACTION_CHART_EXTENSION


def is_editable_action_chart_path(virtual_path: str) -> bool:
    """A `.paac` read by the chart loader; the two commonactioninfo tables are not."""

    return is_action_chart_path(virtual_path) and action_chart_layout(virtual_path) == LAYOUT_CHART


def load_editable_chart(data: bytes, virtual_path: str) -> ActionChart:
    """Decode a chart the editor can change; the commonactioninfo tables are refused."""

    if action_chart_layout(virtual_path) != LAYOUT_CHART:
        name = PurePosixPath(str(virtual_path).replace("\\", "/")).name
        raise ActionChartError(f"{name} is a shared action table, not an action chart, and cannot be edited.")
    return decode_action_chart(bytes(data), virtual_path=virtual_path)


def clip_archive_path(clip: str) -> str:
    return CLIP_ROOT + str(clip or "").replace("\\", "/").lstrip("/")


def chart_clip_names(archive_paths: Iterable[str]) -> tuple[str, ...]:
    """The clip strings a chart may name: every archive `.paa` under the clip root."""

    names = set()
    for path in archive_paths:
        text = str(path or "").replace("\\", "/").strip().strip("/")
        if text.lower().startswith(CLIP_ROOT) and text.lower().endswith(".paa"):
            names.add(text[len(CLIP_ROOT):])
    return tuple(sorted(names, key=str.lower))


def unknown_clips(request: ActionChartEditRequest, known_clips: Iterable[str]) -> tuple[str, ...]:
    """New clip names that no shipped `.paa` matches (case-insensitive)."""

    known = {str(name).lower() for name in known_clips}
    return tuple(item.new for item in request.retargets if item.old != item.new and item.new.lower() not in known)


def clip_rows(chart: ActionChart) -> tuple[ClipRow, ...]:
    uses = [0] * len(chart.tables[ANIMATION_TABLE].raw)
    for animation in chart.animations:
        if 0 <= animation.clip_index < len(uses):
            uses[animation.clip_index] += 1
    return tuple(ClipRow(index, value, uses[index]) for index, value in enumerate(chart.tables[ANIMATION_TABLE].values))


def _read_f32(data: bytes, chart: ActionChart, field: str, animation: int, item: int) -> float:
    at = chart_value_offset(chart, ChartValueEdit(field, 0.0, animation=max(animation, 0), item=item))
    return struct.unpack_from("<f", data, at)[0]


def chart_rate_row(chart: ActionChart) -> ChartValueRow:
    return ChartValueRow("chart.action_speed_rate", -1, 0, chart.action_speed_rate)


def animation_value_rows(chart: ActionChart, data: bytes, index: int) -> tuple[ChartValueRow, ...]:
    """Every editable value of one animation, read from `data`."""

    animation = chart.animations[index]
    rows = [
        ChartValueRow("animation.start_time", index, 0, animation.start_time),
        ChartValueRow("animation.end_time", index, 0, animation.end_time),
    ]
    for array_name, fields in _ARRAY_FIELDS:
        for item in range(animation.array(array_name).count):
            rows.extend(ChartValueRow(field, index, item, _read_f32(data, chart, field, index, item)) for field in fields)
    for item, ref in enumerate(animation.events):
        try:
            kind = frame_event_at(chart, data, ref).kind_name
        except (ActionChartError, IndexError, ValueError, struct.error):
            kind = ""
        rows.append(ChartValueRow("event.begin", index, item, ref.begin, kind))
        rows.append(ChartValueRow("event.end", index, item, ref.end, kind))
    return tuple(rows)


def iter_value_rows(chart: ActionChart, data: bytes) -> Iterator[ChartValueRow]:
    yield chart_rate_row(chart)
    for index in range(len(chart.animations)):
        yield from animation_value_rows(chart, data, index)


def _same_f32(left: float, right: float) -> bool:
    return struct.pack("<f", left) == struct.pack("<f", right)


def compare_charts(original: bytes, edited: bytes, *, virtual_path: str) -> ActionChartChanges:
    """Decode both copies and list each clip string and editable value that differs."""

    before = load_editable_chart(original, virtual_path)
    after = load_editable_chart(edited, virtual_path)
    old_clips = before.tables[ANIMATION_TABLE].values
    new_clips = after.tables[ANIMATION_TABLE].values
    if len(old_clips) != len(new_clips) or len(before.animations) != len(after.animations):
        raise ActionChartError("the edited chart no longer has the shipped chart's shape")
    clips = tuple(ClipChange(index, old, new) for index, (old, new) in enumerate(zip(old_clips, new_clips)) if old != new)
    values = tuple(
        ValueChange(row, old.value)
        for old, row in zip(iter_value_rows(before, bytes(original)), iter_value_rows(after, bytes(edited)))
        if not _same_f32(old.value, row.value)
    )
    return ActionChartChanges(clips, values)


def apply_action_chart_edits(
    data: bytes,
    request: ActionChartEditRequest,
    *,
    virtual_path: str,
    original: Optional[bytes] = None,
) -> ActionChartEditResult:
    """Apply retargets, then value edits, and read the result back.

    `original` is the shipped chart the changes are listed against; it defaults to
    `data`, the copy being edited. Raises `ActionChartError` when an edit is outside
    the proven scope or does not read back as asked.
    """

    data = bytes(data)
    patched = data
    load_editable_chart(patched, virtual_path)
    for retarget in request.retargets:
        if retarget.old == retarget.new:
            continue
        patched, _count = retarget_animation(patched, retarget.old, retarget.new, virtual_path=virtual_path)
    values = tuple(request.values)
    if values:
        patched = apply_chart_value_edits(patched, values, virtual_path=virtual_path)
    chart = load_editable_chart(patched, virtual_path)
    clips = set(chart.tables[ANIMATION_TABLE].values)
    for retarget in request.retargets:
        if retarget.old != retarget.new and retarget.new not in clips:
            raise ActionChartError(f"the chart does not read back clip {retarget.new!r}")
    for edit in values:
        stored = _read_f32(patched, chart, edit.field, edit.animation if edit.field != "chart.action_speed_rate" else -1, edit.item)
        if not _same_f32(stored, edit.value):
            raise ActionChartError(f"{edit.field} reads back as {stored:g}, not {edit.value:g}")
    changes = compare_charts(data if original is None else original, patched, virtual_path=virtual_path)
    return ActionChartEditResult(patched, chart, changes)


def export_action_chart_mod(
    entry: ArchiveEntry,
    original: bytes,
    edited: bytes,
    *,
    parent_root: Path,
    package_info: ModPackageInfo,
    export_options: object = None,
    create_no_encrypt_file: bool = True,
    on_log: Optional[Callable[[str], None]] = None,
) -> ArchiveLooseExportResult:
    """Write the edited chart at its game path in a loose DMM mod folder.

    The chart is checked once more before it is written: it must decode as an
    action chart and differ from the shipped copy only in clip strings and the
    editable values. The game archives are never touched.
    """

    from cdmw.core.archive_loose_export import export_archive_payloads_to_mod_ready_loose

    if not is_action_chart_path(entry.path):
        raise ActionChartError(f"{entry.path} is not an action chart")
    changes = compare_charts(original, edited, virtual_path=entry.path)
    if changes.empty:
        raise ActionChartError("the chart has no changes to export")
    if on_log is not None:
        on_log(f"Source action chart: {entry.path}")
        on_log(f"{len(changes.clips)} clip retarget(s), {len(changes.values)} value change(s), read back from the edited chart.")
    return export_archive_payloads_to_mod_ready_loose(
        [ArchivePatchRequest(entry, bytes(edited))],
        parent_root=Path(parent_root),
        package_info=package_info,
        export_options=export_options,
        create_no_encrypt_file=create_no_encrypt_file,
        on_log=on_log,
    )


def request_from_pending(
    retargets: Mapping[str, str],
    values: Mapping[tuple[str, int, int], float],
) -> ActionChartEditRequest:
    """Build a request from the editor's pending maps: clip -> new clip, row key -> value."""

    edits = tuple(
        ChartValueEdit(field, float(value), animation=max(animation, 0), item=item)
        for (field, animation, item), value in values.items()
    )
    return ActionChartEditRequest(
        tuple(ClipRetarget(old, new) for old, new in retargets.items() if old != new),
        edits,
    )


def change_summary(changes: ActionChartChanges, *, limit: int = 12) -> str:
    """A one-paragraph package description of the changes (plain data, not UI text)."""

    parts: list[str] = []
    for change in changes.clips[:limit]:
        parts.append(f"{change.old} -> {change.new}")
    for change in changes.values[: max(0, limit - len(parts))]:
        row = change.row
        where = "chart" if row.animation < 0 else f"animation {row.animation}"
        item = f" #{row.item + 1}" if row.field.split(".")[0] in {"speed", "frame_tag", "just_time", "event"} else ""
        parts.append(f"{row.field}{item} ({where}): {change.old:g} -> {row.value:g}")
    hidden = len(changes.clips) + len(changes.values) - len(parts)
    if hidden > 0:
        parts.append(f"and {hidden} more")
    return "; ".join(parts)


__all__ = [
    "ACTION_CHART_EXTENSION",
    "CLIP_ROOT",
    "ActionChartChanges",
    "ActionChartEditRequest",
    "ActionChartEditResult",
    "ChartValueRow",
    "ClipChange",
    "ClipRetarget",
    "ClipRow",
    "ValueChange",
    "animation_value_rows",
    "apply_action_chart_edits",
    "change_summary",
    "chart_clip_names",
    "chart_rate_row",
    "clip_archive_path",
    "clip_rows",
    "compare_charts",
    "export_action_chart_mod",
    "is_action_chart_path",
    "is_editable_action_chart_path",
    "iter_value_rows",
    "load_editable_chart",
    "request_from_pending",
    "unknown_clips",
]
