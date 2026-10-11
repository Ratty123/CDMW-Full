"""Incremental JSON I/O for large worker-owned documents.

Keep encoding and decoding in small Python steps so other Python threads (in
particular Qt callbacks) can run. The document has no byte quota; the buffer
size controls I/O, not which valid documents can be opened.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from collections.abc import Callable, Iterable
from typing import TextIO


JSON_IO_CHUNK = 64 * 1024


class JsonArray(list):
    """A repeatable, lazily produced array for the streaming writer."""

    def __init__(self, items: Callable[[], Iterable[object]]) -> None:
        super().__init__()
        self._items = items

    def __bool__(self) -> bool:
        sentinel = object()
        return next(iter(self), sentinel) is not sentinel

    def __iter__(self):
        return iter(self._items())


def write_json(stream: TextIO, value: object, *, max_bytes: int | None = None,
               check_cancelled: Callable[[], None] | None = None) -> None:
    parts: list[str] = []
    buffered = total = 0
    for part in _json_chunks(value, set()):
        size = len(part.encode("utf-8"))
        total += size
        if max_bytes is not None and total > max_bytes:
            raise ValueError("JSON exceeds its configured file limit")
        parts.append(part)
        buffered += size
        if buffered >= JSON_IO_CHUNK:
            if check_cancelled is not None:
                check_cancelled()
            stream.write("".join(parts))
            parts.clear()
            buffered = 0
    if check_cancelled is not None:
        check_cancelled()
    stream.write("".join(parts))


def _json_chunks(value, active):
    # JSONEncoder.iterencode still encodes a whole string in one C call. Native
    # snapshots embedded in a draft can themselves be large JSON strings.
    if isinstance(value, str):
        if len(value) <= JSON_IO_CHUNK:
            yield json.encoder.encode_basestring_ascii(value)
        else:
            yield '"'
            for start in range(0, len(value), JSON_IO_CHUNK):
                yield json.encoder.encode_basestring_ascii(value[start:start + JSON_IO_CHUNK])[1:-1]
            yield '"'
    elif value is None:
        yield "null"
    elif isinstance(value, bool):
        yield "true" if value else "false"
    elif isinstance(value, int):
        yield int.__repr__(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Out of range float values are not JSON compliant")
        yield float.__repr__(value)
    elif isinstance(value, (dict, list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError("Circular reference detected")
        active.add(identity)
        try:
            mapping = isinstance(value, dict)
            yield "{" if mapping else "["
            first = True
            for item in sorted(value) if mapping else value:
                if not first:
                    yield ","
                first = False
                if mapping:
                    if isinstance(item, str):
                        yield from _json_chunks(item, active)
                    elif item is None or isinstance(item, (bool, int, float)):
                        yield '"' + "".join(_json_chunks(item, active)) + '"'
                    else:
                        raise TypeError("JSON object keys must be strings or scalar values")
                    yield ":"
                    yield from _json_chunks(value[item], active)
                else:
                    yield from _json_chunks(item, active)
            yield "}" if mapping else "]"
        finally:
            active.remove(identity)
    else:
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


_STRING_SPECIAL = re.compile(r'["\\\x00-\x1f]')
_TOKEN_END = re.compile(r'[\s,\]}]')
_SPACE = re.compile(r'[ \t\r\n]*')


def read_json(stream: TextIO, *, object_hook: Callable[[dict], object] | None = None) -> object:
    """Read without retaining a second complete JSON text or a long C decoder call."""
    reader = _JsonReader(stream, object_hook)
    value = reader.value()
    if reader.peek():
        raise ValueError("Unexpected data after JSON document")
    return value


def json_sha256(value: object) -> str:
    """Hash canonical compact JSON without creating a complete encoded copy."""
    digest = hashlib.sha256()

    class Sink:
        def write(self, text: str):
            digest.update(text.encode("utf-8"))

    write_json(Sink(), value)
    return digest.hexdigest()


class _JsonReader:
    def __init__(self, stream: TextIO, object_hook):
        self.stream = stream
        self.object_hook = object_hook
        self.buffer = ""
        self.position = 0

    def fill(self) -> bool:
        if self.position < len(self.buffer):
            return True
        self.buffer = self.stream.read(JSON_IO_CHUNK)
        self.position = 0
        return bool(self.buffer)

    def peek(self) -> str:
        while self.fill():
            self.position = _SPACE.match(self.buffer, self.position).end()
            if self.position < len(self.buffer):
                return self.buffer[self.position]
        return ""

    def take(self) -> str:
        if not self.fill():
            raise ValueError("Incomplete JSON document")
        char = self.buffer[self.position]
        self.position += 1
        return char

    def string(self) -> str:
        if self.take() != '"':
            raise ValueError("JSON object keys must be strings")
        parts = []
        while self.fill():
            match = _STRING_SPECIAL.search(self.buffer, self.position)
            end = match.start() if match else len(self.buffer)
            if end > self.position:
                parts.append(self.buffer[self.position:end])
            self.position = end
            if match is None:
                continue
            char = self.take()
            if char == '"':
                return "".join(parts)
            if char != "\\":
                raise ValueError("Unescaped control character in JSON string")
            escape = self.take()
            if escape == "u":
                encoded = "\\u" + "".join(self.take() for _ in range(4))
                if any(char not in "0123456789abcdefABCDEF" for char in encoded[2:]):
                    raise ValueError("Invalid JSON Unicode escape")
                # Decode paired surrogates together, as the standard decoder does.
                code = int(encoded[2:], 16)
                if 0xD800 <= code <= 0xDBFF:
                    parts.append(chr(code))
                else:
                    decoded = json.loads('"' + encoded + '"')
                    if 0xDC00 <= code <= 0xDFFF and parts and parts[-1] and 0xD800 <= ord(parts[-1][-1]) <= 0xDBFF:
                        high = ord(parts[-1][-1])
                        parts[-1] = parts[-1][:-1]
                        decoded = chr(0x10000 + ((high - 0xD800) << 10) + code - 0xDC00)
                    parts.append(decoded)
            else:
                parts.append(json.loads('"\\' + escape + '"'))
        raise ValueError("Unterminated JSON string")

    def value(self):
        char = self.peek()
        if char == '"':
            return self.string()
        if char in ("{", "["):
            self.position += 1
            mapping = char == "{"
            end = "}" if mapping else "]"
            result = {} if mapping else []
            if self.peek() != end:
                while True:
                    if mapping:
                        self.peek()
                        key = self.string()
                        if self.peek() != ":":
                            raise ValueError("Missing colon in JSON object")
                        self.position += 1
                        result[key] = self.value()
                    else:
                        result.append(self.value())
                    separator = self.peek()
                    if separator == end:
                        break
                    if separator != ",":
                        raise ValueError("Missing comma in JSON document")
                    self.position += 1
            self.take()
            return self.object_hook(result) if mapping and self.object_hook else result
        parts = []
        while self.fill():
            match = _TOKEN_END.search(self.buffer, self.position)
            end = match.start() if match else len(self.buffer)
            parts.append(self.buffer[self.position:end])
            self.position = end
            if match:
                break
        token = "".join(parts)
        if not token:
            raise ValueError("Missing JSON value")
        return json.loads(token)
