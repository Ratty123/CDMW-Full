"""Length-prefixed string handling for `.paac` action-chart binaries.

Strings are stored as::

    <len_byte = strlen + 1> <ASCII bytes> <0x00>

Verified across the golden corpus: 30 socket-name strings, 30 conforming, 0 anomalies.

Two consequences drive Tier C:

1. A same-length replacement leaves the prefix byte correct, so no length metadata goes
   stale. This is why the manual workflow's same-length rule works.
2. The prefix is a precondition, not just a description. Requiring
   ``data[start - 1] == len(name) + 1`` and a NUL terminator rejects coincidental byte
   matches inside compressed blobs — a corruption class a naive find/replace would hit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

_TOKEN = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,127}")


class PaacPatchError(RuntimeError):
    """Raised when a Tier C precondition fails. Never downgraded to a warning."""


@dataclass(frozen=True, slots=True)
class PaacString:
    """A length-prefixed string occurrence located in a `.paac` payload."""

    offset: int
    value: str

    @property
    def length(self) -> int:
        return len(self.value)


def is_length_prefixed(data: bytes, start: int, length: int) -> bool:
    """True when `data[start:start+length]` is a well-formed length-prefixed string."""

    if start < 1 or start + length >= len(data):
        return False
    return data[start - 1] == length + 1 and data[start + length] == 0x00


def index_strings(data: bytes, *, suffix: str = "") -> List[PaacString]:
    """Locate every length-prefixed string, optionally filtered by suffix."""

    found: List[PaacString] = []
    for match in _TOKEN.finditer(data):
        token = match.group()
        start = match.start()
        if not is_length_prefixed(data, start, len(token)):
            continue
        text = token.decode("ascii")
        if suffix and not text.endswith(suffix):
            continue
        found.append(PaacString(start, text))
    return found


def index_sockets(data: bytes) -> List[PaacString]:
    return index_strings(data, suffix="Socket")


def socket_histogram(data: bytes) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in index_sockets(data):
        counts[item.value] = counts.get(item.value, 0) + 1
    return counts


def retarget(data: bytes, old: str, new: str, *, offsets: Sequence[int] | None = None) -> bytes:
    """Replace socket name `old` with `new` in place.

    Enforces the Tier C invariants: equal length, a valid length prefix at every patch
    site, and byte identity everywhere outside the patched spans.
    """

    if len(old) != len(new):
        raise PaacPatchError(
            f"Tier C requires equal length: {old!r} ({len(old)}) != {new!r} ({len(new)})"
        )
    if not new.isascii():
        raise PaacPatchError(f"Replacement must be ASCII: {new!r}")
    if old == new:
        return data

    sites = list(offsets) if offsets is not None else [s.offset for s in index_sockets(data) if s.value == old]
    if not sites:
        raise PaacPatchError(f"No length-prefixed occurrence of {old!r} found")

    encoded_old = old.encode("ascii")
    encoded_new = new.encode("ascii")
    buffer = bytearray(data)
    for offset in sites:
        if not is_length_prefixed(data, offset, len(old)):
            raise PaacPatchError(
                f"Offset {offset} is not a length-prefixed string boundary; refusing to patch"
            )
        if bytes(buffer[offset : offset + len(old)]) != encoded_old:
            raise PaacPatchError(f"Offset {offset} does not hold {old!r}")
        buffer[offset : offset + len(old)] = encoded_new

    patched = bytes(buffer)
    if len(patched) != len(data):
        raise PaacPatchError("Patch changed file length")
    verify_outside_spans(data, patched, [(o, len(old)) for o in sites])
    return patched


def verify_outside_spans(
    original: bytes,
    patched: bytes,
    spans: Sequence[tuple[int, int]],
) -> None:
    """Assert the two payloads differ only inside the given (offset, length) spans."""

    if len(original) != len(patched):
        raise PaacPatchError("Length changed")
    allowed = bytearray(len(original))
    for offset, length in spans:
        allowed[offset : offset + length] = b"\x01" * length
    for index, (left, right) in enumerate(zip(original, patched)):
        if left != right and not allowed[index]:
            raise PaacPatchError(f"Unexpected byte change at offset {index} outside patched spans")


def diff_socket_renames(original: bytes, modified: bytes) -> List[tuple[str, str, int]]:
    """Recover same-length socket renames between two `.paac` payloads.

    Returns (old, new, offset) triples. Only meaningful when the payloads are the same
    length, which every Tier C edit guarantees.
    """

    if len(original) != len(modified):
        return []
    renames: List[tuple[str, str, int]] = []
    for item in index_sockets(original):
        chunk = modified[item.offset : item.offset + item.length]
        try:
            text = chunk.decode("ascii")
        except UnicodeDecodeError:
            continue
        if text != item.value and is_length_prefixed(modified, item.offset, item.length):
            renames.append((item.value, text, item.offset))
    return renames
