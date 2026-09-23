"""Bounded, versioned messages for the optional Rust New Item presentation.

This protocol carries presentation data and allowlisted input only. The Python
workflow continues to own draft revisions, workers, output and confirmations.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

PROTOCOL = "cdmw_new_item_ui_v1"
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
MAX_ACTION_BYTES = 8 * 1024 * 1024
MAX_TEXT_CHARS = 65536
MAX_EDITABLE_TEXT_CHARS = 1024 * 1024
MAX_NODES = 12000
MAX_DEPTH = 64
PAGE_ROWS = 128
MAX_COLUMNS = 128
ACTIONS = frozenset({
    "activate", "toggle", "text", "number", "choose", "tab", "select",
    "cell", "check_cell", "sort", "expand", "range", "menu", "link",
    "copy", "finish_edit", "submit", "close_dialog", "split", "resize_column", "key", "crop",
})


class PresentationProtocolError(ValueError):
    """A request cannot safely be applied to the current presentation."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PresentationProtocolError(f"Duplicate message field: {key}")
        result[key] = value
    return result


def decode_message(payload: bytes, *, limit: int = MAX_MESSAGE_BYTES) -> dict[str, Any]:
    if len(payload) > limit:
        raise PresentationProtocolError("Presentation message exceeds its byte limit.")
    try:
        result = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object,
                            parse_constant=lambda value: (_ for _ in ()).throw(
                                PresentationProtocolError(f"Invalid numeric value: {value}")))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PresentationProtocolError(f"Invalid presentation JSON: {error}") from error
    if not isinstance(result, dict) or result.get("protocol") != PROTOCOL:
        raise PresentationProtocolError("Unsupported New Item presentation protocol.")
    return result


def encode_message(message: dict[str, Any]) -> bytes:
    payload = json.dumps({"protocol": PROTOCOL, **message}, ensure_ascii=False,
                         allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise PresentationProtocolError("Presentation state exceeds its byte limit.")
    return payload + b"\n"


def integer(value: Any, *, minimum: int = 0, maximum: int = 2**53 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise PresentationProtocolError("Expected a bounded integer.")
    return value


def number(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise PresentationProtocolError("Expected a finite number.")
    return float(value)


def text_value(value: Any, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise PresentationProtocolError("Expected bounded text without NUL characters.")
    return value


@dataclass(frozen=True, slots=True)
class InputAction:
    session: str
    request: int
    control: str
    revision: int
    action: str
    value: Any = None

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "InputAction":
        if message.get("protocol") != PROTOCOL or message.get("type") != "input":
            raise PresentationProtocolError("Expected a New Item input message.")
        action = message.get("action")
        if action not in ACTIONS:
            raise PresentationProtocolError("Unknown presentation action.")
        return cls(text_value(message.get("session"), maximum=64),
                   integer(message.get("request"), minimum=1),
                   text_value(message.get("control"), maximum=64),
                   integer(message.get("revision"), minimum=1), action, message.get("value"))


class JsonLineReader:
    """Incremental framing with a bounded unfinished line; EOF never applies input."""

    def __init__(self, limit: int = MAX_ACTION_BYTES):
        self.limit = limit
        self.buffer = bytearray()

    def feed(self, data: bytes) -> tuple[dict[str, Any], ...]:
        messages = []
        for part in data.splitlines(keepends=True):
            self.buffer.extend(part)
            if len(self.buffer) > self.limit:
                self.buffer.clear()
                raise PresentationProtocolError("Helper input exceeds its byte limit.")
            if self.buffer.endswith(b"\n"):
                line = bytes(self.buffer).strip()
                self.buffer.clear()
                if line:
                    messages.append(decode_message(line, limit=self.limit))
        return tuple(messages)
