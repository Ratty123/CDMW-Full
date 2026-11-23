"""Keep a Part's material presentation out of the mesh core's replies (2026-11-23).

Each Part's ``extra_attrs`` ride into the resident mesh core so they follow the Part
through Duplicate, Separate, Delete, Undo and Redo, and the core repeats them in the
part summary of every session reply. Two of them are material presentation the core
never reads: ``preview_native_material_overrides`` (which carries the Part's bound
Preview Core material source) and ``preview_material_texture_inputs``. On the
Demenissian Council Robes they were 1.8 MB a Part, so every reply (an edit's apply,
its Morph state, each read-back) was a 40 MB JSON line that took about 1.1 s to pass
and parse, and one transform waited 6-12 s.

Going to the core, each of these values is replaced by a token naming its content;
coming back, each token is replaced by the value again. The core keeps treating the
attribute as opaque: it copies the token with the Part, and when it clears a Part's
material route it drops the attribute by name, token or not. A token this process did
not issue is an error, never a value: a Part must not silently lose its materials.

Tokens are kept for the life of the process. The core's sessions and its clipboard can
hold a Part's attributes past the session that sent them, and a value is shared by
every Part and session with the same content.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping

#: Part attributes the mesh core carries without reading.
TOKENIZED_EXTRA_ATTRS = ("preview_native_material_overrides", "preview_material_texture_inputs")
#: Where a Part's attributes appear in requests and replies; Assign Material sends its
#: additions as ``material_extra_attrs``, which the core merges into the Part's own.
_ATTRIBUTE_KEYS = frozenset({"extra_attrs", "material_extra_attrs"})
TOKEN_PREFIX = "cdmw-native-attr:v1:"
#: Smaller values travel as they are; a token would not save anything.
_MIN_TOKENIZED_BYTES = 4096

_values: dict[str, object] = {}
_lock = threading.Lock()


class UnknownNativeAttrToken(RuntimeError):
    """The mesh core returned a token this process never issued."""


def _token_for(value: object) -> str | None:
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None  # not JSON as it stands; let the request carry and refuse it as before
    if len(text) < _MIN_TOKENIZED_BYTES:
        return None
    token = TOKEN_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _lock:
        _values.setdefault(token, value)
    return token


def _fresh(value: object) -> object:
    # A reply used to give each Part its own parsed copy. The callers replace these
    # values instead of changing them in place, so a new outer container suffices.
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _swap_extra_attrs(extra_attrs: Mapping[str, object], *, outgoing: bool) -> dict[str, object] | None:
    changed: dict[str, object] | None = None
    for name in TOKENIZED_EXTRA_ATTRS:
        if name not in extra_attrs:
            continue
        value = extra_attrs[name]
        if outgoing:
            if isinstance(value, str):
                continue
            replacement = _token_for(value)
            if replacement is None:
                continue
        else:
            if not (isinstance(value, str) and value.startswith(TOKEN_PREFIX)):
                continue
            with _lock:
                if value not in _values:
                    raise UnknownNativeAttrToken(
                        f"The mesh helper returned an unknown {name} reference; the Part's materials "
                        "cannot be restored."
                    )
                replacement = _fresh(_values[value])
        if changed is None:
            changed = dict(extra_attrs)
        changed[name] = replacement
    return changed


def _walk(value: object, *, outgoing: bool) -> object:
    """``value`` with every ``extra_attrs`` swapped; untouched containers are returned as they are."""

    if isinstance(value, dict):
        changed: dict[str, object] | None = None
        for key, item in value.items():
            if key in _ATTRIBUTE_KEYS and isinstance(item, Mapping):
                # A Part's attributes hold no Parts of their own; a restored value is
                # not walked again.
                swapped = _swap_extra_attrs(item, outgoing=outgoing)
                if swapped is None:
                    continue
                new_item = swapped
            else:
                new_item = _walk(item, outgoing=outgoing)
                if new_item is item:
                    continue
            if changed is None:
                changed = dict(value)
            changed[key] = new_item
        return value if changed is None else changed
    if isinstance(value, list):
        if not value or not isinstance(value[0], (dict, list)):
            return value  # numbers or strings: nothing below holds a Part's attributes
        new_list: list[object] | None = None
        for index, item in enumerate(value):
            new_item = _walk(item, outgoing=outgoing)
            if new_item is not item:
                if new_list is None:
                    new_list = list(value)
                new_list[index] = new_item
        return value if new_list is None else new_list
    return value


def tokenize_native_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """``payload`` with each Part's material presentation replaced by its token.

    The caller's payload is not changed; containers on the way to a swapped value
    are copied.
    """

    result = _walk(dict(payload), outgoing=True)
    return result  # type: ignore[return-value]


def restore_native_report(report: object) -> object:
    """``report`` with every token replaced by its value; raises ``UnknownNativeAttrToken``."""

    return _walk(report, outgoing=False)


def issued_token_count() -> int:
    with _lock:
        return len(_values)


__all__ = [
    "TOKENIZED_EXTRA_ATTRS",
    "TOKEN_PREFIX",
    "UnknownNativeAttrToken",
    "issued_token_count",
    "restore_native_report",
    "tokenize_native_payload",
]
