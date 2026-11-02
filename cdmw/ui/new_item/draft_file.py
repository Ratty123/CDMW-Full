"""A Create New Item draft as JSON, so Drafts & Mods can reopen an item package's settings.

No Qt here. The file records every :class:`NewItemDraft` field with its type, and
reading it rebuilds only CDMW's own settings types: dataclasses and enums from
``cdmw.domain`` and this package's ``state`` module. A field the running version
no longer has is dropped and a field it added keeps its default, so a draft saved
by another version still opens.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import math
from enum import Enum
from importlib import import_module

from cdmw.ui.new_item.state import NewItemDraft

DRAFT_FORMAT = "cdmw_new_item_draft_v1"
MAX_DRAFT_BYTES = 128 * 1024 * 1024
_MAX_DEPTH = 32
_ALLOWED_MODULES = ("cdmw.domain.", "cdmw.ui.new_item.state")
#: Fields that describe this computer's session rather than the item.
_SESSION_FIELDS = frozenset({"authoring_errors"})


class DraftFileError(ValueError):
    """The draft cannot be written or read back."""


def _class_name(kind: type) -> str:
    return f"{kind.__module__}:{kind.__qualname__}"


def _allowed_module(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix) for prefix in _ALLOWED_MODULES)


def _encode(value: object, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise DraftFileError("The draft is nested too deeply.")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise DraftFileError("The draft holds a number that is not finite.")
        return value
    if isinstance(value, Enum):
        if not _allowed_module(type(value).__module__):
            raise DraftFileError(f"The draft holds an unsupported setting: {type(value).__name__}.")
        return {"$enum": _class_name(type(value)), "name": value.name}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        if not _allowed_module(type(value).__module__):
            raise DraftFileError(f"The draft holds an unsupported setting: {type(value).__name__}.")
        return {"$data": _class_name(type(value)),
                "fields": {field.name: _encode(getattr(value, field.name), depth + 1)
                           for field in dataclasses.fields(value) if field.init}}
    if isinstance(value, (bytes, bytearray)):
        return {"$bytes": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, tuple):
        return {"$tuple": [_encode(item, depth + 1) for item in value]}
    if isinstance(value, list):
        return [_encode(item, depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        return {"$set": [_encode(item, depth + 1) for item in value], "frozen": isinstance(value, frozenset)}
    if isinstance(value, dict):
        return {"$dict": [[_encode(key, depth + 1), _encode(item, depth + 1)] for key, item in value.items()]}
    raise DraftFileError(f"The draft holds a value that cannot be saved: {type(value).__name__}.")


def _resolve_class(name: object) -> type:
    if type(name) is not str or ":" not in name:
        raise DraftFileError("The draft names an unknown setting type.")
    module_name, _, qualname = name.partition(":")
    if not _allowed_module(module_name):
        raise DraftFileError(f"The draft names a setting type outside CDMW: {module_name}.")
    try:
        target: object = import_module(module_name)
        for part in qualname.split("."):
            target = getattr(target, part)
    except (ImportError, AttributeError) as exc:
        raise DraftFileError(f"This version of CDMW has no setting type {qualname}.") from exc
    if not isinstance(target, type):
        raise DraftFileError(f"{qualname} is not a setting type.")
    return target


def _decode(value: object, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise DraftFileError("The draft is nested too deeply.")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        return value
    if isinstance(value, list):
        return [_decode(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        raise DraftFileError("The draft holds an unknown value.")
    if set(value) == {"$tuple"} and isinstance(value["$tuple"], list):
        return tuple(_decode(item, depth + 1) for item in value["$tuple"])
    if set(value) == {"$bytes"} and type(value["$bytes"]) is str:
        try:
            return base64.b64decode(value["$bytes"].encode("ascii"), validate=True)
        except ValueError as exc:
            raise DraftFileError("The draft holds damaged binary data.") from exc
    if set(value) == {"$set", "frozen"} and isinstance(value["$set"], list):
        items = [_decode(item, depth + 1) for item in value["$set"]]
        return frozenset(items) if value["frozen"] else set(items)
    if set(value) == {"$dict"} and isinstance(value["$dict"], list):
        result = {}
        for pair in value["$dict"]:
            if not isinstance(pair, list) or len(pair) != 2:
                raise DraftFileError("The draft holds a damaged table.")
            key = _decode(pair[0], depth + 1)
            if isinstance(key, list):
                key = tuple(key)
            result[key] = _decode(pair[1], depth + 1)
        return result
    if set(value) == {"$enum", "name"}:
        kind = _resolve_class(value["$enum"])
        if not issubclass(kind, Enum) or type(value["name"]) is not str or value["name"] not in kind.__members__:
            raise DraftFileError(f"The draft holds an unknown choice for {kind.__name__}.")
        return kind[value["name"]]
    if set(value) == {"$data", "fields"} and isinstance(value["fields"], dict):
        kind = _resolve_class(value["$data"])
        if not dataclasses.is_dataclass(kind):
            raise DraftFileError(f"{kind.__name__} is not a setting type.")
        known = {field.name for field in dataclasses.fields(kind) if field.init}
        arguments = {name: _decode(raw, depth + 1) for name, raw in value["fields"].items() if name in known}
        try:
            return kind(**arguments)
        except (TypeError, ValueError) as exc:
            raise DraftFileError(f"The draft's {kind.__name__} setting is not valid here: {exc}") from exc
    raise DraftFileError("The draft holds an unknown value.")


def encode_draft(draft: NewItemDraft) -> bytes:
    """The draft as UTF-8 JSON; raises DraftFileError for a value it cannot record."""

    if not isinstance(draft, NewItemDraft):
        raise DraftFileError("Only a Create New Item draft can be saved.")
    fields = {field.name: _encode(getattr(draft, field.name))
              for field in dataclasses.fields(draft) if field.init and field.name not in _SESSION_FIELDS}
    data = json.dumps({"format": DRAFT_FORMAT, "draft": fields}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_DRAFT_BYTES:
        raise DraftFileError("The draft is too large to save.")
    return data


def decode_draft(data: bytes) -> NewItemDraft:
    """A draft read back from :func:`encode_draft`'s bytes."""

    if len(data) > MAX_DRAFT_BYTES:
        raise DraftFileError("The draft is too large to read.")
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DraftFileError("The draft file is damaged.") from exc
    if not isinstance(payload, dict) or payload.get("format") != DRAFT_FORMAT or not isinstance(payload.get("draft"), dict):
        raise DraftFileError("This is not a Create New Item draft.")
    known = {field.name for field in dataclasses.fields(NewItemDraft) if field.init} - _SESSION_FIELDS
    arguments = {name: _decode(raw) for name, raw in payload["draft"].items() if name in known}
    try:
        return NewItemDraft(**arguments)
    except (TypeError, ValueError) as exc:
        raise DraftFileError(f"The draft cannot be opened by this version of CDMW: {exc}") from exc


__all__ = ["DRAFT_FORMAT", "DraftFileError", "decode_draft", "encode_draft"]
