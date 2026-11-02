"""Edit a shipped `.paac` action chart and write it as a DMM mod.

Every write is one `cdmw.core.action_chart_binary` proves:

- a string-table entry replaced everywhere it is used (any of the ten tables);
- one animation given its own clip or blend space (the new path is appended);
- a frame event's named references (socket, part, effect, prefab, sequencer) and a
  socket event's mode and blend time, on a copy of a shared event or on every user;
- f32 timing values from `EDITABLE_CHART_FIELDS`.

The result is decoded again and compared with the shipped chart, so what the user
reviews is what the new bytes say. Export writes the chart as a DMM archive-group
mod (`0036/0.pamt` + `0.paz`, manifest.json, modinfo.json), the layout DMM mounts.

Clip strings are stored relative to `character/motion/`, where 65,305 of the 65,320
clip references in the shipped charts resolve (game 2.04.03). Blend spaces and camera
clips are full archive paths, sequencers `sequencer/<name>.paseq`; effects, sockets
and parts are names the chart defines.
"""

from __future__ import annotations

import json
import struct
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator, Mapping, Optional

from cdmw.core.action_chart_binary import (
    ACTION_CHART_STRING_TABLES,
    ANIMATION_TABLE,
    BLEND_TABLE,
    FRAME_EVENT_REFERENCES,
    LAYOUT_CHART,
    MODEL_ATTACHMENT_SOCKET_KIND,
    NO_INDEX,
    ActionChart,
    ActionChartError,
    ChartValueEdit,
    EventEdit,
    action_chart_layout,
    apply_chart_value_edits,
    apply_event_edits,
    chart_value_offset,
    decode_action_chart,
    decode_action_package_description,
    event_edit_fields,
    event_users,
    frame_event_at,
    retarget_chart_string,
    set_animation_resources,
    socket_event_payload,
    walk_frame_events,
)
from cdmw.domain.archives.mutation import ArchivePatchRequest
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.models import ArchiveEntry

CLIP_ROOT = "character/motion/"
ACTION_CHART_EXTENSION = ".paac"
CHART_ROOT = "actionchart/bin__/"
#: DMM treats this group inside a package as a standalone overlay and picks its slot.
DMM_ARCHIVE_GROUP = "0036"
CDMW_GENERATOR = "Crimson Desert Mod Workbench"
#: Tables whose entries are names the chart defines rather than files.
NAME_TABLES = frozenset({3, 6, 7, 9})

#: Per-animation fields in the order the editor lists them; `item` counts records.
_ARRAY_FIELDS = (
    ("animationSpeedInfoArray", ("speed.start_time", "speed.end_time", "speed.rate")),
    ("frameTag", ("frame_tag.start_time", "frame_tag.end_time")),
    ("justTimeFrameTagInfo", ("just_time.start_time", "just_time.end_time")),
)
#: How a table's strings name archive files: (prefix, suffix) around the stored value.
_PATH_FORMS = (
    ("", ""),
    (CLIP_ROOT, ""),
    ("sequencer/", ".paseq"),
    (CHART_ROOT, ACTION_CHART_EXTENSION),
    ("character/prefab/", ""),
    ("object/prefab/", ""),
)


# --- requests and results -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StringRetarget:
    """Replace entry `old` of string table `table` with `new`; every user changes."""

    table: int
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class AnimationResourceEdit:
    """Give one animation its own clip and/or blend space (None keeps it, "" clears a blend)."""

    animation: int
    clip: Optional[str] = None
    blend: Optional[str] = None


@dataclass(frozen=True, slots=True)
class EventFieldEdit:
    """Set one field of an animation's frame event; see `event_edit_fields`."""

    animation: int
    event: int
    field: str
    value: object
    only_this_animation: bool = True


@dataclass(frozen=True, slots=True)
class ActionChartEditRequest:
    retargets: tuple[StringRetarget, ...] = ()
    resources: tuple[AnimationResourceEdit, ...] = ()
    events: tuple[EventFieldEdit, ...] = ()
    values: tuple[ChartValueEdit, ...] = ()

    @property
    def empty(self) -> bool:
        return (not any(item.old != item.new for item in self.retargets) and not self.resources
                and not self.events and not self.values)


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
class StringRow:
    table: int
    index: int
    value: str
    uses: Optional[int]


@dataclass(frozen=True, slots=True)
class EventRow:
    """One frame event of one animation, with what it names and which animations share it."""

    animation: int
    item: int
    kind: int
    kind_name: str
    begin: float
    end: float
    fields: tuple[tuple[str, object], ...]
    shared_by: tuple[int, ...]

    def field_value(self, name: str) -> object:
        return dict(self.fields).get(name)


@dataclass(frozen=True, slots=True)
class StringChange:
    table: int
    index: int
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class ResourceChange:
    animation: int
    field: str  # "clip" or "blend"
    old: str
    new: str


@dataclass(frozen=True, slots=True)
class EventChange:
    animation: int
    item: int
    kind_name: str
    field: str
    old: object
    new: object


@dataclass(frozen=True, slots=True)
class ValueChange:
    row: ChartValueRow
    old: float


@dataclass(frozen=True, slots=True)
class ActionChartChanges:
    """Differences between the shipped chart and the edited bytes, both decoded."""

    strings: tuple[StringChange, ...] = ()
    resources: tuple[ResourceChange, ...] = ()
    events: tuple[EventChange, ...] = ()
    values: tuple[ValueChange, ...] = ()
    appended: tuple[tuple[int, str], ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.strings or self.resources or self.events or self.values)

    @property
    def count(self) -> int:
        return len(self.strings) + len(self.resources) + len(self.events) + len(self.values)


@dataclass(frozen=True, slots=True)
class ActionChartEditResult:
    data: bytes
    chart: ActionChart
    changes: ActionChartChanges


# --- paths and loading --------------------------------------------------------------


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


def chart_archive_path(chart: str) -> str:
    """The archive path of a chart named in a `.paacdesc` or a sub-chart string."""

    return CHART_ROOT + str(chart or "").replace("\\", "/").strip("/") + ACTION_CHART_EXTENSION


def _normal(path: object) -> str:
    return str(path or "").replace("\\", "/").strip().strip("/")


def _extension(value: str) -> str:
    suffix = PurePosixPath(value).suffix.lower()
    return suffix if 1 < len(suffix) <= 16 else ""


# --- resource catalog (suggestions and missing-file warnings) -----------------------


@dataclass(frozen=True, slots=True)
class TableCatalog:
    """How one string table names files, and the names it may take.

    `form` is a (prefix, suffix) pair around archive paths, "names" for tables that
    hold names the chart defines (effects, sockets, parts, prefabs), or "" when unknown.
    """

    table: int
    form: object
    suggestions: tuple[str, ...]
    known: frozenset[str]

    @property
    def names_files(self) -> bool:
        return isinstance(self.form, tuple)

    def knows(self, value: str) -> Optional[bool]:
        if not self.form:
            return None
        return str(value or "").lower() in self.known


def _value_for_path(path: str, prefix: str, suffix: str) -> Optional[str]:
    lower = path.lower()
    if not lower.startswith(prefix) or (suffix and not lower.endswith(suffix)):
        return None
    value = path[len(prefix):len(path) - len(suffix)] if suffix else path[len(prefix):]
    return value or None


def build_resource_catalog(chart: ActionChart, paths_by_extension: Mapping[str, Iterable[str]]) -> dict[int, TableCatalog]:
    """Work out, per string table, which archive files its values name.

    A form is chosen when it resolves at least half of the table's current values.
    Tables of effects, sockets, parts and prefabs that name no files suggest this
    chart's own names instead.
    """

    wanted: set[str] = set()
    for table in chart.tables:
        for value in table.values:
            for prefix, suffix in _PATH_FORMS:
                ext = _extension(prefix + value + suffix)
                if ext:
                    wanted.add(ext)
    paths = {ext: [_normal(path) for path in paths_by_extension.get(ext, ())] for ext in wanted}
    lowered = {ext: {path.lower() for path in items} for ext, items in paths.items()}
    catalogs: dict[int, TableCatalog] = {}
    for table in chart.tables:
        values = table.values
        best: tuple[int, object] = (0, "")
        for prefix, suffix in _PATH_FORMS:
            hits = 0
            for value in values:
                full = (prefix + value + suffix).lower()
                if full in lowered.get(_extension(full), ()):
                    hits += 1
            if hits > best[0]:
                best = (hits, (prefix, suffix))
        own = tuple(sorted(set(values), key=str.lower))
        if values and best[0] * 2 >= len(values):
            prefix, suffix = best[1]
            exts = {_extension(prefix + value + suffix) for value in values} - {""}
            names = sorted({name for ext in exts for path in paths.get(ext, ())
                            if (name := _value_for_path(path, prefix, suffix))}, key=str.lower)
            catalogs[table.index] = TableCatalog(table.index, best[1], tuple(names), frozenset(n.lower() for n in names))
        elif table.index in NAME_TABLES:
            catalogs[table.index] = TableCatalog(table.index, "names", own, frozenset(v.lower() for v in own))
        else:
            catalogs[table.index] = TableCatalog(table.index, "", own, frozenset())
    return catalogs


def unknown_resources(request: ActionChartEditRequest, catalogs: Mapping[int, TableCatalog]) -> tuple[tuple[int, str], ...]:
    """(table, value) pairs a request names that the catalog does not know."""

    named: list[tuple[int, str]] = [(item.table, item.new) for item in request.retargets if item.old != item.new]
    for item in request.resources:
        if item.clip:
            named.append((ANIMATION_TABLE, item.clip))
        if item.blend:
            named.append((BLEND_TABLE, item.blend))
    for item in request.events:
        table = event_field_table(item.field)
        if table is not None and isinstance(item.value, str) and item.value:
            named.append((table, item.value))
    missing: list[tuple[int, str]] = []
    for table, value in named:
        catalog = catalogs.get(table)
        if catalog is not None and catalog.knows(value) is False and (table, value) not in missing:
            missing.append((table, value))
    return tuple(missing)


def event_field_table(field: str) -> Optional[int]:
    """The string table a named event field indexes, or None for value fields."""

    for references in FRAME_EVENT_REFERENCES.values():
        for role, _offset, table in references:
            if role == field:
                return table
    return None


# --- reading rows -------------------------------------------------------------------


def _read_f32(data: bytes, chart: ActionChart, field: str, animation: int, item: int) -> float:
    at = chart_value_offset(chart, ChartValueEdit(field, 0.0, animation=max(animation, 0), item=item))
    return struct.unpack_from("<f", data, at)[0]


def chart_rate_row(chart: ActionChart) -> ChartValueRow:
    return ChartValueRow("chart.action_speed_rate", -1, 0, chart.action_speed_rate)


def _event_fields(chart: ActionChart, data: bytes, ref, *, raw: bool = False) -> tuple[int, str, tuple[tuple[str, object], ...]]:
    """Kind and editable field values (names, mode, blend time) of the event `ref` points at.

    With `raw`, name fields are their string-table indices instead of the names.
    """

    try:
        event = frame_event_at(chart, data, ref)
    except (ActionChartError, IndexError, ValueError, struct.error):
        return -1, "", ()
    values: list[tuple[str, object]] = []
    for role, offset, table in FRAME_EVENT_REFERENCES.get(event.kind, ()):
        index, = struct.unpack_from("<H", data, event.offset + offset)
        values.append((role, index if raw else "" if index == NO_INDEX else chart.tables[table].value(index)))
    if event.kind == MODEL_ATTACHMENT_SOCKET_KIND:
        payload = socket_event_payload(data, event)
        values += [("mode", payload.mode), ("blend time", payload.blend_time)]
    return event.kind, event.kind_name, tuple(values)


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
        kind = _event_fields(chart, data, ref)[1]
        rows.append(ChartValueRow("event.begin", index, item, ref.begin, kind))
        rows.append(ChartValueRow("event.end", index, item, ref.end, kind))
    return tuple(rows)


def iter_value_rows(chart: ActionChart, data: bytes) -> Iterator[ChartValueRow]:
    yield chart_rate_row(chart)
    for index in range(len(chart.animations)):
        yield from animation_value_rows(chart, data, index)


def animation_event_rows(chart: ActionChart, data: bytes, index: int) -> tuple[EventRow, ...]:
    rows = []
    for item, ref in enumerate(chart.animations[index].events):
        kind, kind_name, values = _event_fields(chart, data, ref)
        rows.append(EventRow(index, item, kind, kind_name, ref.begin, ref.end, values, event_users(chart, ref)))
    return tuple(rows)


def string_rows(chart: ActionChart, data: bytes, table: int) -> tuple[StringRow, ...]:
    """Entries of one table with how many animations or events use each, where that is known."""

    raw = chart.tables[table].raw
    uses: Optional[list[int]] = None
    if table in (ANIMATION_TABLE, BLEND_TABLE):
        uses = [0] * len(raw)
        for animation in chart.animations:
            at = animation.clip_index if table == ANIMATION_TABLE else animation.blend_index
            if 0 <= at < len(uses):
                uses[at] += 1
    elif table == 0:
        uses = [0] * len(raw)
        for at in chart.include_names:
            if 0 <= at < len(uses):
                uses[at] += 1
    elif any(ref_table == table for refs in FRAME_EVENT_REFERENCES.values() for _r, _o, ref_table in refs):
        uses = [0] * len(raw)
        try:
            events = walk_frame_events(data, chart.frame_event_buffer) if chart.frame_event_buffer else ()
        except ActionChartError:
            events = ()
        for event in events:
            for _role, offset, ref_table in FRAME_EVENT_REFERENCES.get(event.kind, ()):
                if ref_table == table:
                    at, = struct.unpack_from("<H", data, event.offset + offset)
                    if 0 <= at < len(uses):
                        uses[at] += 1
    values = chart.tables[table].values
    return tuple(StringRow(table, index, value, None if uses is None else uses[index]) for index, value in enumerate(values))


# --- applying and comparing ---------------------------------------------------------


def _same_f32(left: float, right: float) -> bool:
    return struct.pack("<f", left) == struct.pack("<f", right)


def _same_value(left: object, right: object) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        try:
            return _same_f32(float(left), float(right))
        except (TypeError, ValueError):
            return False
    return left == right


def _event_probe_changed(before: ActionChart, after: ActionChart, original: bytes, edited: bytes, ref) -> bool:
    """True when the event a frame event still points at holds other editable bytes now."""

    try:
        old_event = frame_event_at(before, original, ref)
        new_event = frame_event_at(after, edited, ref)
    except (ActionChartError, IndexError, ValueError, struct.error):
        return False
    if old_event.kind != new_event.kind or not event_edit_fields(old_event.kind):
        return old_event.kind != new_event.kind
    probes = [(offset, 2) for _role, offset, _table in FRAME_EVENT_REFERENCES.get(old_event.kind, ())]
    if old_event.kind == MODEL_ATTACHMENT_SOCKET_KIND:
        probes += [(12, 4), (26, 1)]
    return any(original[old_event.offset + at:old_event.offset + at + size]
               != edited[new_event.offset + at:new_event.offset + at + size] for at, size in probes)


def compare_charts(original: bytes, edited: bytes, *, virtual_path: str) -> ActionChartChanges:
    """Decode both copies and list what differs: strings, per-animation resources, events, values.

    A string replaced in its table is listed once, not once per user; strings the edits
    appended are listed apart. Events are compared by the indices and values they hold,
    so an event copied for one animation shows up only for the fields that changed.
    """

    before = load_editable_chart(original, virtual_path)
    after = load_editable_chart(edited, virtual_path)
    original, edited = bytes(original), bytes(edited)
    if len(before.animations) != len(after.animations):
        raise ActionChartError("the edited chart no longer has the shipped chart's animations")
    strings: list[StringChange] = []
    appended: list[tuple[int, str]] = []
    for old_table, new_table in zip(before.tables, after.tables):
        if len(new_table.raw) < len(old_table.raw):
            raise ActionChartError(f"string table {old_table.index} lost entries")
        old_values, new_values = old_table.values, new_table.values
        strings += [StringChange(old_table.index, index, old, new)
                    for index, (old, new) in enumerate(zip(old_values, new_values)) if old != new]
        appended += [(old_table.index, value) for value in new_values[len(old_values):]]
    resources: list[ResourceChange] = []
    events: list[EventChange] = []
    for old_anim, new_anim in zip(before.animations, after.animations):
        if old_anim.clip_index != new_anim.clip_index:
            resources.append(ResourceChange(old_anim.index, "clip", before.clip_name(old_anim), after.clip_name(new_anim)))
        if old_anim.blend_index != new_anim.blend_index:
            resources.append(ResourceChange(old_anim.index, "blend", before.blend_name(old_anim), after.blend_name(new_anim)))
        if len(old_anim.events) != len(new_anim.events):
            raise ActionChartError(f"animation {old_anim.index} changed its number of frame events")
        for item, (old_ref, new_ref) in enumerate(zip(old_anim.events, new_anim.events)):
            if old_ref.dword_offset == new_ref.dword_offset and not _event_probe_changed(
                    before, after, original, edited, old_ref):
                continue
            _kind, kind_name, old_fields = _event_fields(before, original, old_ref)
            _kind, _name, new_fields = _event_fields(after, edited, new_ref)
            old_raw = dict(_event_fields(before, original, old_ref, raw=True)[2])
            new_raw = dict(_event_fields(after, edited, new_ref, raw=True)[2])
            old_map = dict(old_fields)
            for name, new in new_fields:
                # A renamed table entry keeps its index; that rename is listed once, above.
                if not _same_value(old_raw.get(name), new_raw.get(name)):
                    events.append(EventChange(old_anim.index, item, kind_name, name, old_map.get(name), new))
    values = tuple(
        ValueChange(row, old.value)
        for old, row in zip(iter_value_rows(before, original), iter_value_rows(after, edited))
        if not _same_f32(old.value, row.value)
    )
    return ActionChartChanges(tuple(strings), tuple(resources), tuple(events), values, tuple(appended))


def _event_value(chart: ActionChart, data: bytes, animation: int, item: int, name: str) -> object:
    _kind, _name, values = _event_fields(chart, data, chart.animations[animation].events[item])
    return dict(values).get(name)


def apply_action_chart_edits(
    data: bytes,
    request: ActionChartEditRequest,
    *,
    virtual_path: str,
    original: Optional[bytes] = None,
) -> ActionChartEditResult:
    """Apply retargets, per-animation resources, event fields and values; read the result back.

    `original` is the shipped chart the changes are listed against; it defaults to
    `data`, the copy being edited. Raises `ActionChartError` when an edit is outside
    the proven scope or does not read back as asked.
    """

    data = bytes(data)
    patched = data
    load_editable_chart(patched, virtual_path)
    for retarget in request.retargets:
        if retarget.old != retarget.new:
            patched, _count = retarget_chart_string(patched, retarget.table, retarget.old, retarget.new,
                                                    virtual_path=virtual_path)
    for resource in request.resources:
        patched = set_animation_resources(patched, resource.animation, clip=resource.clip, blend=resource.blend,
                                          virtual_path=virtual_path)
    for edit in request.events:
        patched = apply_event_edits(patched, [EventEdit(edit.animation, edit.event, edit.field, edit.value)],
                                    only_this_animation=edit.only_this_animation, virtual_path=virtual_path)
    values = tuple(request.values)
    if values:
        patched = apply_chart_value_edits(patched, values, virtual_path=virtual_path)

    chart = load_editable_chart(patched, virtual_path)
    for retarget in request.retargets:
        if retarget.old != retarget.new and retarget.new not in chart.tables[retarget.table].values:
            raise ActionChartError(f"the chart does not read back {retarget.new!r}")
    for resource in request.resources:
        animation = chart.animations[resource.animation]
        if resource.clip is not None and chart.clip_name(animation) != resource.clip:
            raise ActionChartError(f"animation {resource.animation} does not read back clip {resource.clip!r}")
        if resource.blend is not None and chart.blend_name(animation) != resource.blend:
            raise ActionChartError(f"animation {resource.animation} does not read back blend space {resource.blend!r}")
    for edit in request.events:
        stored = _event_value(chart, patched, edit.animation, edit.event, edit.field)
        if not _same_value(stored, edit.value):
            raise ActionChartError(f"frame event {edit.event + 1} of animation {edit.animation} reads back "
                                   f"{edit.field} {stored!r}, not {edit.value!r}")
    for edit in values:
        animation = -1 if edit.field == "chart.action_speed_rate" else edit.animation
        stored = _read_f32(patched, chart, edit.field, animation, edit.item)
        if not _same_f32(stored, edit.value):
            raise ActionChartError(f"{edit.field} reads back as {stored:g}, not {edit.value:g}")
    changes = compare_charts(data if original is None else original, patched, virtual_path=virtual_path)
    return ActionChartEditResult(patched, chart, changes)


def change_summary(changes: ActionChartChanges, *, limit: int = 12) -> str:
    """A one-paragraph package description of the changes (plain data, not UI text)."""

    parts: list[str] = []
    for change in changes.strings:
        parts.append(f"{ACTION_CHART_STRING_TABLES[change.table]}: {change.old} -> {change.new}")
    for change in changes.resources:
        parts.append(f"animation {change.animation} {change.field}: {change.old or '-'} -> {change.new or '-'}")
    for change in changes.events:
        parts.append(f"animation {change.animation} event {change.item + 1} {change.field}: {change.old} -> {change.new}")
    for change in changes.values:
        row = change.row
        where = "chart" if row.animation < 0 else f"animation {row.animation}"
        parts.append(f"{row.field} ({where}): {change.old:g} -> {row.value:g}")
    hidden = len(parts) - limit
    parts = parts[:limit]
    if hidden > 0:
        parts.append(f"and {hidden} more")
    return "; ".join(parts)


# --- character packages (.paacdesc) -------------------------------------------------


@dataclass(frozen=True, slots=True)
class CharacterChartRow:
    package: str
    slot: str
    chart: str
    main: bool

    @property
    def archive_path(self) -> str:
        return chart_archive_path(self.chart)


def character_chart_rows(data: bytes) -> tuple[CharacterChartRow, ...]:
    """Every (character package, slot, chart) the action package description names."""

    rows = []
    for package in decode_action_package_description(data).packages:
        rows.append(CharacterChartRow(package.name, package.main_slot, package.main_chart, True))
        rows += [CharacterChartRow(package.name, slot, chart, False) for slot, chart in package.sub_packages]
    return tuple(rows)


# --- archive index ------------------------------------------------------------------

#: Extensions the editor looks up: charts, the descriptor, clips and the files tables name.
INDEX_EXTENSIONS = (".paa", ".paac", ".paacdesc", ".motionblending", ".paseq", ".prefab")


@dataclass(frozen=True, slots=True)
class ChartArchiveIndex:
    """The archive paths and entries the editor needs, from one scan of the game's tables."""

    root: Path
    paths_by_extension: Mapping[str, tuple[str, ...]]
    entries_by_path: Mapping[str, ArchiveEntry]

    def entry_for_path(self, path: str) -> Optional[ArchiveEntry]:
        return self.entries_by_path.get(_normal(path).lower())

    @property
    def description_entry(self) -> Optional[ArchiveEntry]:
        paths = self.paths_by_extension.get(".paacdesc", ())
        return self.entry_for_path(paths[0]) if paths else None


_INDEX_LOCK = threading.Lock()
_INDEX_CACHE: dict[str, tuple[tuple, ChartArchiveIndex]] = {}


def _pamt_stamp(root: Path) -> tuple:
    from cdmw.core.archive_format import discover_pamt_files

    stamps = []
    for path in discover_pamt_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(stamps))


def chart_archive_index(
    root: Path | str,
    *,
    scan: Optional[Callable[[Path], Iterable[ArchiveEntry]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ChartArchiveIndex:
    """Index the game's charts, clips and related files; reused until a .pamt changes.

    The full scan takes seconds, so this runs on a worker and the result is kept per
    game folder for the session.
    """

    text = str(root or "").strip()
    if not text or not Path(text).is_dir():
        raise ActionChartError("Set the game folder in Archive Browser before editing action charts.")
    root = Path(text)
    stamp = _pamt_stamp(root)
    key = str(root.resolve()).lower()
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    if scan is None:
        from cdmw.core.archive_scan_cache import scan_archive_entries as scan
    raise_if_cancelled(stop_event, "Reading the game archives was cancelled.")
    wanted = set(INDEX_EXTENSIONS)
    paths: dict[str, list[str]] = {ext: [] for ext in wanted}
    entries: dict[str, ArchiveEntry] = {}
    for entry in scan(root):
        path = _normal(entry.path)
        ext = PurePosixPath(path.lower()).suffix
        if ext not in wanted:
            continue
        paths[ext].append(path)
        entries.setdefault(path.lower(), entry)
    raise_if_cancelled(stop_event, "Reading the game archives was cancelled.")
    index = ChartArchiveIndex(root, {ext: tuple(sorted(items, key=str.lower)) for ext, items in paths.items()}, entries)
    with _INDEX_LOCK:
        _INDEX_CACHE[key] = (stamp, index)
    return index


def character_rows_from_index(index: ChartArchiveIndex, read: Callable[[ArchiveEntry], bytes]) -> tuple["CharacterChartRow", ...]:
    entry = index.description_entry
    if entry is None:
        raise ActionChartError("The character action package description (.paacdesc) is not in the game archives.")
    return character_chart_rows(read(entry))


def chart_users(rows: Iterable["CharacterChartRow"], chart_path: str) -> tuple[str, ...]:
    wanted = _normal(chart_path).lower()
    return tuple(f"{row.package} ({row.slot})" for row in rows if row.archive_path.lower() == wanted)


@dataclass(frozen=True, slots=True)
class ClipInfo:
    clip: str
    archive_path: str
    duration: float
    frames: int


def clip_info(index: ChartArchiveIndex, clip: str, read: Callable[[ArchiveEntry], bytes]) -> ClipInfo:
    """Length and frame count of a clip as a chart names it (relative to character/motion/)."""

    from tools.paa_motion.format import parse_paa
    from tools.paa_motion.timing import duration_seconds

    entry = None
    for candidate in (CLIP_ROOT + _normal(clip), _normal(clip)):
        entry = index.entry_for_path(candidate)
        if entry is not None:
            break
    if entry is None:
        raise ActionChartError(f"{clip} is not in the game archives.")
    try:
        motion = parse_paa(read(entry), name=PurePosixPath(_normal(entry.path)).name)
        duration = float(duration_seconds(motion))
    except Exception as exc:  # noqa: BLE001 - a parse failure is reported, not raised raw
        raise ActionChartError(f"{clip} could not be read as an animation clip: {exc}") from exc
    return ClipInfo(clip, _normal(entry.path), duration, int(motion.frame_count))


# --- other charts that play a clip -----------------------------------------------


@dataclass(frozen=True, slots=True)
class ClipUse:
    """One chart that plays a clip, and how many of its animations do."""

    chart: str
    animations: int


@dataclass(frozen=True, slots=True)
class LinkedClipChange:
    """Replace clip `old` with `new` everywhere in another chart of the same mod."""

    chart: str
    old: str
    new: str


_USAGE_LOCK = threading.Lock()
_USAGE_CACHE: dict[int, tuple[ChartArchiveIndex, dict[str, tuple[ClipUse, ...]]]] = {}


def clip_usage_index(
    index: ChartArchiveIndex,
    read: Callable[[ArchiveEntry], bytes],
    *,
    stop_event: Optional[threading.Event] = None,
) -> Mapping[str, tuple[ClipUse, ...]]:
    """Which charts play each clip, across every standard chart in the game.

    Reading and decoding all charts takes a few seconds, so the result is kept for
    as long as `index` is the current one.
    """

    with _USAGE_LOCK:
        cached = _USAGE_CACHE.get(id(index))
    if cached is not None and cached[0] is index:
        return cached[1]
    uses: dict[str, list[ClipUse]] = {}
    for path in index.paths_by_extension.get(ACTION_CHART_EXTENSION, ()):
        if not is_editable_action_chart_path(path):
            continue
        raise_if_cancelled(stop_event, "Listing the charts that play a clip was cancelled.")
        entry = index.entry_for_path(path)
        if entry is None:
            continue
        try:
            data = read(entry)
            chart = load_editable_chart(data, path)
        except (ActionChartError, OSError, ValueError):
            continue
        for row in string_rows(chart, data, ANIMATION_TABLE):
            if row.uses:
                uses.setdefault(row.value.lower(), []).append(ClipUse(path, int(row.uses)))
    result = {clip: tuple(items) for clip, items in uses.items()}
    with _USAGE_LOCK:
        _USAGE_CACHE.clear()
        _USAGE_CACHE[id(index)] = (index, result)
    return result


def charts_playing_clip(
    index: ChartArchiveIndex,
    clip: str,
    read: Callable[[ArchiveEntry], bytes],
    *,
    stop_event: Optional[threading.Event] = None,
) -> tuple[ClipUse, ...]:
    return clip_usage_index(index, read, stop_event=stop_event).get(_normal(clip).lower(), ())


def apply_linked_clip_changes(data: bytes, chart_path: str, changes: Iterable[LinkedClipChange]) -> bytes:
    """Replace each linked clip everywhere in one chart; a change already made is skipped."""

    patched = bytes(data)
    for change in changes:
        if change.old == change.new or _normal(change.chart).lower() != _normal(chart_path).lower():
            continue
        values = load_editable_chart(patched, chart_path).tables[ANIMATION_TABLE].values
        if change.old not in values and change.new in values:
            continue
        patched, _count = retarget_chart_string(patched, ANIMATION_TABLE, change.old, change.new, virtual_path=chart_path)
    return patched


# --- chart mods CDMW wrote --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChartMod:
    folder: Path
    title: str
    author: str
    version: str
    description: str
    charts: Mapping[str, bytes]


def is_chart_mod(folder: Path) -> bool:
    try:
        manifest = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    generator = str(manifest.get("generator", "")) if isinstance(manifest, dict) else ""
    return (generator.startswith(CDMW_GENERATOR) and "action chart" in generator
            and manifest.get("structure") == "archive_group")


def read_chart_mod(folder: Path | str) -> ChartMod:
    """The charts an action chart mod CDMW wrote holds, read from its archive group."""

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt

    folder = Path(folder)
    if not is_chart_mod(folder):
        raise ActionChartError(f"{folder.name} is not an action chart mod CDMW wrote.")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    group = str(manifest.get("archive_group") or DMM_ARCHIVE_GROUP)
    pamt = folder / group / "0.pamt"
    if not pamt.is_file():
        raise ActionChartError(f"{folder.name} has no {group}/0.pamt.")
    charts: dict[str, bytes] = {}
    for entry in parse_archive_pamt(pamt):
        path = _normal(entry.path)
        if is_editable_action_chart_path(path):
            data = read_archive_entry_data(entry)[0]
            load_editable_chart(data, path)
            charts[path] = data
    if not charts:
        raise ActionChartError(f"{folder.name} holds no action charts.")
    return ChartMod(folder, str(manifest.get("title") or manifest.get("name") or folder.name),
                    str(manifest.get("author") or ""), str(manifest.get("version") or "1.0"),
                    str(manifest.get("description") or ""), charts)


# --- export -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionChartModResult:
    folder: Path
    replaced: bool
    title: str
    group: str
    changes: ActionChartChanges
    charts: tuple[str, ...] = ()


def _written_by_cdmw(folder: Path) -> bool:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(manifest, dict) and str(manifest.get("generator", "")).startswith(CDMW_GENERATOR)


def mod_destination(parent: Path, title: str) -> tuple[Path, bool]:
    """The mod folder for `title` under `parent`, and whether it replaces one CDMW wrote."""

    from cdmw.domain.packages.layout import sanitize_mod_package_folder_name

    folder = Path(parent) / sanitize_mod_package_folder_name(title)
    if not folder.exists():
        return folder, False
    if folder.is_dir() and _written_by_cdmw(folder):
        return folder, True
    raise ActionChartError(f"A folder named {folder.name} already exists and CDMW did not write it. "
                           "Choose another mod name.")


def _game_root(entry: ArchiveEntry) -> Optional[Path]:
    pamt = getattr(entry, "pamt_path", None)
    return Path(pamt).parent.parent if pamt else None


def write_action_chart_mod(
    entry: ArchiveEntry,
    original: bytes,
    edited: bytes,
    *,
    parent: Path,
    title: str,
    description: str = "",
    author: str = "",
    version: str = "1.0",
    keep_existing: bool = True,
    shipped_entries: Optional[Callable[[str], Optional[ArchiveEntry]]] = None,
    linked: Iterable[LinkedClipChange] = (),
    read_shipped: Optional[Callable[[ArchiveEntry], bytes]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> ActionChartModResult:
    """Write the edited chart as a DMM archive-group mod folder named after `title`.

    The chart is checked again first: it must decode as an action chart and differ from
    the shipped copy. It is built beside the target, read back from the written archive,
    then swapped in, so a failed build leaves an earlier version in place. A folder CDMW
    did not write is never replaced. The game archives are only read.

    With `keep_existing`, the other charts an earlier export put in the same mod stay
    in it, so one mod can carry a whole moveset; `shipped_entries` finds their game
    entries by path. The edited chart replaces its own earlier version.

    `linked` replaces clips in other charts of the same mod, on top of the version
    the mod already holds or else the shipped chart (`read_shipped` reads that).
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.atomic_file import atomic_publish_directory
    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package

    if not is_editable_action_chart_path(entry.path):
        raise ActionChartError(f"{entry.path} is not an editable action chart")
    title = str(title or "").strip()
    if not title:
        raise ActionChartError("Name the mod before exporting it.")
    changes = compare_charts(original, edited, virtual_path=entry.path)
    linked = tuple(item for item in linked if item.old != item.new)
    if changes.empty and not linked:
        raise ActionChartError("the chart has no changes to export")
    folder, replaced = mod_destination(parent, title)
    if on_log is not None:
        on_log(f"Source action chart: {entry.path}")
        on_log(f"{changes.count} change(s), read back from the edited chart.")
    edited = bytes(edited)
    own = _normal(entry.path).lower()
    # path -> (game entry, bytes); the edited chart goes in last so it wins.
    charts: dict[str, tuple[ArchiveEntry, bytes]] = {}

    def _shipped(path: str) -> ArchiveEntry:
        shipped = shipped_entries(path) if shipped_entries is not None else None
        if shipped is None:
            raise ActionChartError(f"{path} is not in the game archives. Export to a new mod name instead.")
        return shipped

    if replaced and keep_existing and is_chart_mod(folder):
        for path, data in read_chart_mod(folder).charts.items():
            if path.lower() != own:
                charts[path.lower()] = (_shipped(path), data)
                if on_log is not None:
                    on_log(f"Keeping {path} from the earlier export.")
    for path in sorted({_normal(item.chart) for item in linked}, key=str.lower):
        if path.lower() == own:
            continue
        shipped = _shipped(path)
        if path.lower() in charts:
            base = charts[path.lower()][1]
        elif read_shipped is not None:
            base = read_shipped(shipped)
        else:
            raise ActionChartError(f"{path} cannot be read to change its clips.")
        patched = apply_linked_clip_changes(base, path, linked)
        charts[path.lower()] = (shipped, patched)
        if on_log is not None:
            on_log(f"Changing clips in {path} as well.")
    if changes.empty:
        charts.pop(own, None)
    else:
        charts[own] = (entry, edited)
    requests = [ArchivePatchRequest(shipped, data) for shipped, data in charts.values()]
    if not requests:
        raise ActionChartError("the chart has no changes to export")
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cdmw-chart-", dir=folder.parent) as staging:
        stage = Path(staging) / folder.name
        stage.mkdir()
        shared = export_archive_overlay_package(
            requests, package_root=stage, group=DMM_ARCHIVE_GROUP,
            game_root=_game_root(entry), on_log=on_log, stop_event=stop_event,
        )
        wanted = {_normal(request.entry.path).lower(): bytes(request.payload_data) for request in requests}
        packaged = parse_archive_pamt(stage / shared.group / "0.pamt")
        if len(packaged) != len(wanted) or any(
                read_archive_entry_data(item)[0] != wanted.get(_normal(item.path).lower()) for item in packaged):
            raise ActionChartError("the written mod archive does not read back as the edited charts")
        description = str(description or "").strip() or f"Action chart edit for {entry.path}."
        manifest = {
            "format": "v1", "schema_version": 1, "kind": "archive_override_mod", "name": title, "title": title,
            "game": "Crimson Desert", "target_game": shared.target_game, "version": version, "author": author,
            "description": description, "generator": f"{CDMW_GENERATOR} - action chart editor",
            "files_dir": ".", "manager_targets": ["dmm"], "structure": "archive_group",
            "archive_group": shared.group, "file_count": shared.file_count, "overrides": list(shared.paths),
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (stage / "modinfo.json").write_text(json.dumps(
            {"name": title, "title": title, "version": version, "author": author, "description": description},
            indent=2) + "\n", encoding="utf-8")
        (stage / "README.txt").write_text(
            f"{title}\n\n{description}\n\nEdited action charts:\n" + "".join(f"  {path}\n" for path in shared.paths) +
            "Add this folder in DMM and enable it there. Action chart edits have not been confirmed in game; "
            "disable the mod in DMM to undo it. The game's own files were only read.\n", encoding="utf-8")
        raise_if_cancelled(stop_event, "Action chart export cancelled.")
        mod_destination(parent, title)  # Refuse a foreign folder that appeared meanwhile.
        atomic_publish_directory(stage, folder, replace_existing=True)
    return ActionChartModResult(folder, replaced, title, shared.group, changes, tuple(shared.paths))


__all__ = [
    "ACTION_CHART_EXTENSION",
    "CHART_ROOT",
    "CLIP_ROOT",
    "DMM_ARCHIVE_GROUP",
    "NAME_TABLES",
    "ActionChartChanges",
    "ActionChartEditRequest",
    "ActionChartEditResult",
    "ActionChartModResult",
    "ChartArchiveIndex",
    "ChartMod",
    "ClipInfo",
    "ClipUse",
    "LinkedClipChange",
    "INDEX_EXTENSIONS",
    "AnimationResourceEdit",
    "CharacterChartRow",
    "ChartValueRow",
    "EventChange",
    "EventFieldEdit",
    "EventRow",
    "ResourceChange",
    "StringChange",
    "StringRetarget",
    "StringRow",
    "TableCatalog",
    "ValueChange",
    "animation_event_rows",
    "animation_value_rows",
    "apply_linked_clip_changes",
    "charts_playing_clip",
    "clip_usage_index",
    "apply_action_chart_edits",
    "build_resource_catalog",
    "change_summary",
    "character_chart_rows",
    "character_rows_from_index",
    "chart_archive_index",
    "chart_users",
    "clip_info",
    "is_chart_mod",
    "read_chart_mod",
    "chart_archive_path",
    "chart_rate_row",
    "compare_charts",
    "event_field_table",
    "is_action_chart_path",
    "is_editable_action_chart_path",
    "iter_value_rows",
    "load_editable_chart",
    "mod_destination",
    "string_rows",
    "unknown_resources",
    "write_action_chart_mod",
]
