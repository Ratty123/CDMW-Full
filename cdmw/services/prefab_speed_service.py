"""Find and scale the speed values a prefab holds (experimental, untested in game).

Only values in the catalogue (`cdmw.domain.archives.prefab_speed`) that the prefab walk
reaches and that `editable_kind` accepts are offered. A scaled value is written in its
own bytes with `encode_value`, so nothing moves; the result is decoded again and must
differ from the input only inside the edited spans. A prefab that is only partly read, or
whose layout the file does not decide, is never written (`write_state`).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.prefab_binary import (
    PrefabBinaryError,
    PrefabDocument,
    decode_prefab_binary,
    read_reflect_header,
    walk_is_determined,
)
from cdmw.domain.cancellation import raise_if_cancelled
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
    #: (category, label) of every speed value the walk really reaches; a prefab can declare a
    #: type and hold no value of it.
    reached: tuple[tuple[str, str], ...] = ()
    #: Why the prefab cannot be written ('' when it can): see `write_state`.
    state: str = ""

    def value_count(self, category: str = "") -> int:
        return sum(1 for item, _label in self.reached if not category or item == category)

    def labels(self, category: str = "") -> tuple[str, ...]:
        return tuple(dict.fromkeys(label for item, label in self.reached if not category or item == category))

    def to_data(self, category: str = "") -> dict[str, object]:
        return {"path": self.path, "categories": list(self.categories),
                "category_label": ", ".join(category_label(item) for item in self.categories),
                "category": self.categories[0] if self.categories else "", "types": list(self.types),
                "members": list(self.types), "values": self.value_count(category),
                "labels": list(self.labels(category)), "state": self.state}


@dataclass(frozen=True, slots=True)
class PrefabScaleOutcome:
    """One prefab of a batch: scaled bytes, or the reason it is left out."""

    path: str
    source: Optional[bytes]
    patched: Optional[bytes]
    values: int
    before: Optional[tuple[float, float]]  # lowest and highest value
    after: Optional[tuple[float, float]]
    reason: str  # '' when it changes

    def to_data(self) -> dict[str, object]:
        return {"path": self.path, "values": self.values, "before": list(self.before) if self.before else None,
                "after": list(self.after) if self.after else None, "reason": self.reason}


NOT_READ = "could not be read"
PARTLY_READ = "partly read"
UNDECIDED = "its layout cannot be decided from the file"
NO_VALUE = "no speed value reached"
ZERO_VALUES = "the values are 0"


def _state_of(data: bytes, document: PrefabDocument) -> str:
    if not document.walk_complete:
        return PARTLY_READ
    # Both checks are needed: a partial walk can still count as determined.
    return "" if walk_is_determined(data) else UNDECIDED


def write_state(data: bytes) -> str:
    """'' when the prefab's speed values may be written, else the reason, for the user."""

    data = bytes(data)
    try:
        document = decode_prefab_binary(data)
    except (PrefabBinaryError, ValueError, IndexError):
        return NOT_READ
    return _state_of(data, document)


def speed_values(document: PrefabDocument, *, stated_only: bool = False) -> tuple[PrefabSpeedValue, ...]:
    """Every catalogue value the walk reached, in file order.

    With `stated_only`, values in objects whose type the reader had to infer are left out:
    those are shown, but never written.
    """

    found: list[PrefabSpeedValue] = []
    for obj in document.objects:
        if stated_only and obj.type_is_inferred:
            continue
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
    state = _state_of(data, document)
    if state:
        # Scaling only the values before the point where reading stopped would look like success.
        raise PrefabSpeedError(f"This prefab's values cannot be changed: {state}.")
    by_offset = {value.offset: value for value in speed_values(document, stated_only=True)}
    buffer = bytearray(data)
    spans: list[tuple[int, int]] = []
    for edit in edits:
        value = by_offset.get(int(edit.offset))
        if value is None:
            raise PrefabSpeedError(f"Offset {edit.offset} is not a speed value this prefab holds.")
        _check(edit.value, f"{value.member}")
        try:
            raw = encode_value(value.value_type, data[value.offset:value.offset + value.size], edit.value)
        except OverflowError:
            raise PrefabSpeedError(f"{value.member}: the value is too large for this field.") from None
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
    reread = {value.offset: value for value in speed_values(after, stated_only=True)}
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

    data = bytes(data)
    try:
        document = decode_prefab_binary(data)
    except PrefabBinaryError as exc:
        raise PrefabSpeedError(f"The prefab could not be read: {exc}") from exc
    state = _state_of(data, document)
    if state:
        raise PrefabSpeedError(f"This prefab's values cannot be changed: {state}.")
    values = speed_values(document, stated_only=True)
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
    # Declaring a type is not holding a value of it: read the prefab to see what is really there.
    try:
        document = decode_prefab_binary(bytes(data))
    except (PrefabBinaryError, ValueError, IndexError):
        return PrefabSpeedHit(path, tuple(categories), types, (), NOT_READ)
    reached = tuple((value.category, value.label) for value in speed_values(document, stated_only=True))
    return PrefabSpeedHit(path, tuple(categories), types, reached, _state_of(bytes(data), document))


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
    kept for the session, so later searches and other categories are instant. Prefabs
    that hold a value that can be written come first.
    """

    entries = [entry for entry in entries if str(entry.path).lower().endswith(".prefab")]
    cache_key = (id(key), len(entries)) if key is not None else None
    hits = None
    if cache_key is not None:
        with _SEARCH_LOCK:
            kept = _SEARCH_CACHE.get(cache_key)
            # The entry holds `key` itself, so its id cannot be reused by another object meanwhile.
            hits = kept[1] if kept is not None and kept[0] is key else None
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
                _SEARCH_CACHE[cache_key] = (key, hits)
    chosen = [hit for hit in hits if not category or category in hit.categories]
    return tuple(sorted(chosen, key=lambda hit: (bool(hit.state) or not hit.value_count(category), hit.path.lower())))


def scale_speed_prefabs(
    entries: Iterable[ArchiveEntry],
    read: Callable[[ArchiveEntry], bytes],
    factor: float,
    *,
    category: str = "",
    on_progress: Optional[Callable[[int, int], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> tuple[PrefabScaleOutcome, ...]:
    """Scale the speed values of many prefabs; each one changes or is left out with its reason.

    Nothing is written. A prefab is left out when it cannot be written (`write_state`), holds
    no value of `category` that is reached, or holds only values of 0.
    """

    scale_edits((), factor)  # the factor is checked once, before anything is read
    entries = list(entries)
    outcomes: list[PrefabScaleOutcome] = []
    for number, entry in enumerate(entries):
        raise_if_cancelled(stop_event, "Scaling the prefabs was cancelled.")
        if on_progress is not None:
            on_progress(number, len(entries))
        path = str(entry.path).replace("\\", "/")
        try:
            data = bytes(read(entry))
        except Exception as exc:  # noqa: BLE001 - one unreadable prefab is left out and named
            outcomes.append(PrefabScaleOutcome(path, None, None, 0, None, None, f"{NOT_READ}: {exc}"))
            continue
        state = write_state(data)
        if state:
            outcomes.append(PrefabScaleOutcome(path, data, None, 0, None, None, state))
            continue
        values = [value for value in speed_values(decode_prefab_binary(data), stated_only=True)
                  if not category or value.category == category]
        if not values:
            outcomes.append(PrefabScaleOutcome(path, data, None, 0, None, None, NO_VALUE))
            continue
        try:
            patched = apply_speed_edits(data, scale_edits(values, factor))
        except PrefabSpeedError as exc:
            outcomes.append(PrefabScaleOutcome(path, data, None, len(values), None, None, str(exc)))
            continue
        numbers = [float(item) for value in values
                   for item in (value.value if isinstance(value.value, tuple) else (value.value,))]
        before = (min(numbers), max(numbers))
        if patched == data:
            outcomes.append(PrefabScaleOutcome(path, data, None, len(values), before, before, ZERO_VALUES))
            continue
        after = (min(numbers) * float(factor), max(numbers) * float(factor))
        outcomes.append(PrefabScaleOutcome(path, data, patched, len(values), before,
                                           (min(after), max(after)), ""))
    if on_progress is not None:
        on_progress(len(entries), len(entries))
    return tuple(outcomes)


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
    "NOT_READ",
    "NO_VALUE",
    "PARTLY_READ",
    "PrefabScaleOutcome",
    "PrefabSpeedEdit",
    "PrefabSpeedError",
    "PrefabSpeedHit",
    "PrefabSpeedValue",
    "UNDECIDED",
    "ZERO_VALUES",
    "apply_speed_edits",
    "prefab_label",
    "prefab_speed_hit",
    "scale_edits",
    "scale_speed_prefabs",
    "scale_speed_values",
    "scaled",
    "search_speed_prefabs",
    "speed_values",
    "values_by_category",
    "write_state",
]
