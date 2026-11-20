"""Find and scale the speed values a prefab holds (experimental, untested in game).

Only values in the catalogue (`cdmw.domain.archives.prefab_speed`) that the prefab walk
reaches and that `editable_kind` accepts are offered. A scaled value is written in its
own bytes with `encode_value`, so nothing moves; the result is decoded again and must
differ from the input only inside the edited spans.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.prefab_binary import PrefabBinaryError, PrefabDocument, decode_prefab_binary, read_reflect_header
from cdmw.domain.archives.prefab_speed import SPEED_MEMBER_NAMES, SPEED_TYPES, category_label, speed_member
from cdmw.domain.archives.prefab_values import decode_value, editable_kind, encode_value
from cdmw.models import ArchiveEntry

MIN_SCALE, MAX_SCALE = 0.01, 100.0


class PrefabSpeedError(ValueError):
    """A prefab speed edit that cannot be made; the message is for the user."""


@dataclass(frozen=True, slots=True)
class PrefabSpeedValue:
    object_index: int
    object_name: str
    type_name: str
    member: str
    label: str
    category: str
    kind: str
    value: object
    offset: int
    size: int
    #: The number's declared type, for encode_value.
    value_type: str

    def to_data(self) -> dict[str, object]:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        return {"object": self.object_index, "object_name": self.object_name, "type": self.type_name,
                "member": self.member, "label": self.label, "category": self.category,
                "category_label": category_label(self.category), "kind": self.kind, "value": value,
                "offset": self.offset}


@dataclass(frozen=True, slots=True)
class PrefabSpeedEdit:
    """Set the value at `offset` to `value` (a float, or a tuple for a vector)."""

    offset: int
    value: object


@dataclass(frozen=True, slots=True)
class PrefabSpeedHit:
    path: str
    categories: tuple[str, ...]
    types: tuple[str, ...]

    def to_data(self) -> dict[str, object]:
        return {"path": self.path, "categories": list(self.categories),
                "category_label": ", ".join(category_label(item) for item in self.categories),
                "category": self.categories[0] if self.categories else "", "types": list(self.types),
                "members": list(self.types)}


def speed_values(document: PrefabDocument) -> tuple[PrefabSpeedValue, ...]:
    """Every catalogue value the walk reached, in file order."""

    found: list[PrefabSpeedValue] = []
    for obj in document.objects:
        for number in obj.numbers:
            item = speed_member(obj.component_type, number.name)
            if item is None:
                continue
            kind = editable_kind(number.type_name, number.raw)
            if kind not in item.kinds:
                continue
            found.append(PrefabSpeedValue(obj.index, obj.name, obj.component_type, number.name, item.label,
                                          item.category, kind, decode_value(number.type_name, number.raw),
                                          number.offset, len(number.raw), number.type_name))
    return tuple(sorted(found, key=lambda value: value.offset))


def scaled(value: PrefabSpeedValue, factor: float) -> object:
    """`value` times `factor`, in the value's own shape."""

    if isinstance(value.value, tuple):
        return tuple(float(item) * float(factor) for item in value.value)
    return float(value.value) * float(factor)


def _check(value: object, what: str) -> None:
    items = value if isinstance(value, (tuple, list)) else (value,)
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise PrefabSpeedError(f"{what} must be finite numbers.")


def scale_edits(values: Iterable[PrefabSpeedValue], factor: float) -> tuple[PrefabSpeedEdit, ...]:
    _check(factor, "The factor")
    if not MIN_SCALE <= float(factor) <= MAX_SCALE:
        raise PrefabSpeedError(f"The factor must be between {MIN_SCALE:g} and {MAX_SCALE:g}.")
    return tuple(PrefabSpeedEdit(value.offset, scaled(value, factor)) for value in values)


def apply_speed_edits(data: bytes, edits: Sequence[PrefabSpeedEdit]) -> bytes:
    """Write each edit into its own bytes; refuse anything not a catalogue value.

    The prefab is decoded again afterwards: its length, every other byte and every
    other value stay the same, and each edited value reads back as asked.
    """

    data = bytes(data)
    try:
        document = decode_prefab_binary(data)
    except PrefabBinaryError as exc:
        raise PrefabSpeedError(f"The prefab could not be read: {exc}") from exc
    by_offset = {value.offset: value for value in speed_values(document)}
    buffer = bytearray(data)
    spans: list[tuple[int, int]] = []
    for edit in edits:
        value = by_offset.get(int(edit.offset))
        if value is None:
            raise PrefabSpeedError(f"Offset {edit.offset} is not a speed value this prefab holds.")
        _check(edit.value, f"{value.member}")
        try:
            raw = encode_value(value.value_type, data[value.offset:value.offset + value.size], edit.value)
        except (TypeError, ValueError) as exc:
            raise PrefabSpeedError(f"{value.member}: {exc}") from exc
        if len(raw) != value.size:
            raise PrefabSpeedError(f"{value.member} would change size")
        buffer[value.offset:value.offset + value.size] = raw
        spans.append((value.offset, value.size))
    patched = bytes(buffer)
    allowed = bytearray(len(data))
    for at, size in spans:
        allowed[at:at + size] = b"\1" * size
    if any(left != right and not allowed[index] for index, (left, right) in enumerate(zip(data, patched))):
        raise PrefabSpeedError("A byte outside the edited values changed.")
    after = decode_prefab_binary(patched)
    reread = {value.offset: value for value in speed_values(after)}
    if set(reread) != set(by_offset):
        raise PrefabSpeedError("The edited prefab does not read back with the same speed values.")
    for edit in edits:
        stored = reread[int(edit.offset)].value
        wanted = edit.value
        stored_items = stored if isinstance(stored, tuple) else (stored,)
        wanted_items = tuple(wanted) if isinstance(wanted, (tuple, list)) else (wanted,)
        if len(stored_items) != len(wanted_items) or any(
                not math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6) for a, b in zip(stored_items, wanted_items)):
            raise PrefabSpeedError(f"The value at {edit.offset} reads back as {stored!r}, not {wanted!r}.")
    return patched


def scale_speed_values(data: bytes, factor: float, *, offsets: Optional[Iterable[int]] = None,
                       category: str = "") -> tuple[bytes, tuple[PrefabSpeedEdit, ...]]:
    """Scale the chosen speed values (all of them, or one category, or some offsets)."""

    values = speed_values(decode_prefab_binary(bytes(data)))
    wanted = {int(item) for item in offsets} if offsets is not None else None
    chosen = [value for value in values if (wanted is None or value.offset in wanted)
              and (not category or value.category == category)]
    if wanted is not None and len(chosen) != len(wanted):
        missing = sorted(wanted - {value.offset for value in chosen})
        raise PrefabSpeedError(f"Not speed values of this prefab: {', '.join(map(str, missing))}.")
    if not chosen:
        raise PrefabSpeedError("This prefab holds no speed value to scale.")
    edits = scale_edits(chosen, factor)
    return apply_speed_edits(data, edits), edits


# --- search -------------------------------------------------------------------------

_SEARCH_LOCK = threading.Lock()
_SEARCH_CACHE: dict[tuple, tuple[PrefabSpeedHit, ...]] = {}
_MEMBER_BYTES = tuple(name.encode("ascii") for name in sorted(SPEED_MEMBER_NAMES))
_TYPE_BYTES = tuple(name.encode("ascii") for name in sorted(SPEED_TYPES))


def prefab_speed_hit(path: str, data: bytes) -> Optional[PrefabSpeedHit]:
    """Whether a prefab's type table declares a catalogue type; reads no objects."""

    if not any(name in data for name in _TYPE_BYTES):
        return None
    try:
        header = read_reflect_header(data)
    except (PrefabBinaryError, ValueError, IndexError):
        return None
    declared = {item.type_name for item in header.types}
    types = tuple(sorted(declared & SPEED_TYPES))
    if not types:
        return None
    categories = []
    from cdmw.domain.archives.prefab_speed import SPEED_MEMBERS

    for (type_name, _member), item in SPEED_MEMBERS.items():
        if type_name in declared and item.category not in categories:
            categories.append(item.category)
    return PrefabSpeedHit(path, tuple(categories), types)


def search_speed_prefabs(
    entries: Iterable[ArchiveEntry],
    read: Callable[[ArchiveEntry], bytes],
    *,
    category: str = "",
    key: object = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[PrefabSpeedHit, ...]:
    """Prefabs whose type table declares a catalogue type, by category.

    Every prefab is read once; with `key` (such as the archive index) the full list is
    kept for the session, so later searches and other categories are instant.
    """

    entries = [entry for entry in entries if str(entry.path).lower().endswith(".prefab")]
    cache_key = (id(key), len(entries)) if key is not None else None
    hits = None
    if cache_key is not None:
        with _SEARCH_LOCK:
            hits = _SEARCH_CACHE.get(cache_key)
    if hits is None:
        found = []
        for number, entry in enumerate(entries):
            if stop_event is not None and stop_event.is_set():
                raise PrefabSpeedError("The prefab search was cancelled.")
            if on_progress is not None and number % 500 == 0:
                on_progress(number, len(entries))
            try:
                hit = prefab_speed_hit(str(entry.path).replace("\\", "/"), read(entry))
            except Exception:  # noqa: BLE001 - one unreadable prefab is skipped
                continue
            if hit is not None:
                found.append(hit)
        hits = tuple(sorted(found, key=lambda hit: hit.path.lower()))
        if cache_key is not None:
            with _SEARCH_LOCK:
                _SEARCH_CACHE.clear()
                _SEARCH_CACHE[cache_key] = hits
    return tuple(hit for hit in hits if not category or category in hit.categories)


def prefab_label(path: str) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).name


def values_by_category(values: Iterable[PrefabSpeedValue]) -> Mapping[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value.category] = counts.get(value.category, 0) + 1
    return counts


__all__ = [
    "MAX_SCALE",
    "MIN_SCALE",
    "PrefabSpeedEdit",
    "PrefabSpeedError",
    "PrefabSpeedHit",
    "PrefabSpeedValue",
    "apply_speed_edits",
    "prefab_label",
    "prefab_speed_hit",
    "scale_edits",
    "scale_speed_values",
    "scaled",
    "search_speed_prefabs",
    "speed_values",
    "values_by_category",
]
