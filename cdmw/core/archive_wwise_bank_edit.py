"""Constrained writes to a Wwise sound bank (bank version 150).

Three edits are admitted, each checked against a fresh decode of the result:

* replacing a fixed-size HIRC value in place: an existing property, a
  randomizer range bound, a container's loop/transition values or playlist
  weight, or a Set-property action's value. Only property ids whose stored type
  was measured across the shipped banks are writable, and nothing is added or
  removed, so no object, chunk or offset changes size;
* replacing a sound the bank embeds. DATA is rebuilt with every sound on the
  16-byte boundary the shipped banks use, DIDX gets the new offsets and sizes,
  and every Sound or music-track source in the bank that loads that media
  from memory gets the new media size and the codec the new media declares;
* retargeting a sound whose media lives in a loose `.wem`: every source that
  loads it from memory gets the new file size and codec. In the shipped banks
  the in-memory size equals the media's byte size for every in-memory Sound, so
  a replaced loose `.wem` without this edit leaves the bank describing the old
  file.

Sources that prefetch or stream their media are refused: the bank holds a
prefix or a prefetch size whose rule is not established. So is media an
undecoded object might name. Adding or removing objects, events or sounds is
refused as well; none of that has been proven safe.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cdmw.core.archive_wwise_bank import read_bank_chunks, read_embedded_media
from cdmw.core.archive_wwise_hirc import (
    KIND_MUSIC_TRACK,
    KIND_SOUND,
    PARSED,
    PROPERTY_NAMES,
    SUPPORTED_BANK_VERSION,
    HircGraph,
    HircNode,
    HircSource,
    read_hirc_graph,
)

#: Property ids whose stored type was measured on every occurrence in the shipped
#: banks (2026-11-02): floats in dB, cents, percent or seconds, integers in
#: milliseconds or loop counts (0 loops forever).
EDITABLE_PROPERTY_ENCODINGS: Dict[int, str] = {
    0x00: "<f",  # Volume (dB)
    0x01: "<f",  # Pitch (cents)
    0x02: "<f",  # LPF
    0x03: "<f",  # HPF
    0x04: "<f",  # BusVolume (dB)
    0x05: "<f",  # MakeUpGain (dB)
    0x06: "<f",  # Priority
    0x08: "<f",  # UserAuxSendVolume0
    0x09: "<f",  # UserAuxSendVolume1
    0x0A: "<f",  # UserAuxSendVolume2
    0x0B: "<f",  # UserAuxSendVolume3
    0x0C: "<f",  # GameAuxSendVolume
    0x22: "<f",  # InitialDelay (s)
    0x0D: "<f",  # OutputBusVolume (dB)
    0x29: "<f",  # Positioning_CenterPercent
    0x39: "<i",  # DelayTime (ms; ranges go negative)
    0x3A: "<i",  # TransitionTime (ms)
    0x54: "<I",  # Loop (count, 0 = infinite)
}
_PROPERTY_IDS = {name: prop_id for prop_id, name in PROPERTY_NAMES.items()}

#: Which editable properties each HIRC type stores somewhere in the shipped banks
#: (2026-11-02). A property is only added to a type that is seen carrying it.
ADDABLE_PROPERTIES_BY_KIND: Dict[int, frozenset] = {
    2: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0C, 0x22, 0x29, 0x54}),
    3: frozenset({0x39, 0x3A}),
    5: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0C, 0x22, 0x29}),
    6: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0C, 0x22, 0x29}),
    7: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x29}),
    8: frozenset({0x00, 0x03, 0x04, 0x05, 0x08, 0x0D, 0x29}),
    9: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x06, 0x08, 0x0C, 0x22, 0x29}),
    10: frozenset({0x00, 0x03, 0x05, 0x06, 0x08}),
    11: frozenset({0x00, 0x05, 0x06, 0x54}),
    12: frozenset({0x00, 0x06, 0x29}),
    13: frozenset({0x00, 0x05, 0x06, 0x29}),
    18: frozenset({0x04, 0x05, 0x0D, 0x29}),
}
#: The same for randomizer ranges.
ADDABLE_RANGES_BY_KIND: Dict[int, frozenset] = {
    2: frozenset({0x01, 0x02, 0x22}),
    3: frozenset({0x39, 0x3A}),
    5: frozenset({0x00, 0x01, 0x02, 0x03, 0x05, 0x22}),
    6: frozenset({0x00, 0x01}),
    7: frozenset({0x01, 0x05}),
    9: frozenset({0x01, 0x05, 0x22}),
}

#: Codec plugin ids by the RIFF format tag of the media that plays through them.
#: Vorbis and ADPCM (PTADPCM media) are what the shipped banks declare; PCM is
#: Wwise's built-in codec and is never declared by a shipped bank.
CODEC_PLUGIN_BY_FORMAT_TAG = {
    0xFFFF: 0x00040001,
    0x0001: 0x00010001,
    0xFFFE: 0x00010001,
    0x8311: 0x00020001,
}
_REPLACEABLE_CODECS = set(CODEC_PLUGIN_BY_FORMAT_TAG.values())
_MEDIA_ALIGNMENT = 16
_STREAM_IN_MEMORY = 0


class WwiseBankEditError(ValueError):
    """An edit the constrained writer refuses, with the reason."""


@dataclass(slots=True, frozen=True)
class HircEdit:
    """One in-place value change.

    `target` is `property:<Name>`, `range:<Name>:min` / `range:<Name>:max`,
    `value:<name>` for a container or action value the decoder lists, or
    `weight:<child object id>` for a random/sequence playlist entry.
    """

    object_id: int
    target: str
    value: float | int


@dataclass(slots=True, frozen=True)
class HircPropertyChange:
    """Adds, changes or removes a stored property or randomizer range.

    `target` is `property:<Name>` with a number, or `range:<Name>` with a
    `(min, max)` pair; `None` removes it, so the object inherits it again.
    Properties are kept sorted by id, as every shipped bank stores them.
    """

    object_id: int
    target: str
    value: object = None


@dataclass(slots=True, frozen=True)
class BankEditResult:
    data: bytes
    changes: Tuple[str, ...]


def media_format_tag(media: bytes) -> Optional[int]:
    """The RIFF `fmt ` format tag of a `.wem`, or None when it is not one."""

    if len(media) < 12 or media[:4] != b"RIFF" or media[8:12] != b"WAVE":
        return None
    offset = 12
    while offset + 8 <= len(media):
        identifier = media[offset : offset + 4]
        size = struct.unpack_from("<I", media, offset + 4)[0]
        if identifier == b"fmt " and size >= 2 and offset + 10 <= len(media):
            return struct.unpack_from("<H", media, offset + 8)[0]
        offset += 8 + size + (size & 1)
    return None


def codec_plugin_for_media(media: bytes) -> int:
    tag = media_format_tag(media)
    if tag is None:
        raise WwiseBankEditError("The replacement is not a RIFF/WAVE Wwise media file.")
    if not _has_data_chunk(media):
        raise WwiseBankEditError("The replacement media has no data chunk.")
    plugin = CODEC_PLUGIN_BY_FORMAT_TAG.get(tag)
    if plugin is None:
        raise WwiseBankEditError(
            f"Replacement media format 0x{tag:04X} is not one this game's banks play "
            "(Wwise Vorbis, Wwise ADPCM or PCM)."
        )
    return plugin


def _has_data_chunk(media: bytes) -> bool:
    offset = 12
    while offset + 8 <= len(media):
        size = struct.unpack_from("<I", media, offset + 4)[0]
        if media[offset : offset + 4] == b"data":
            return offset + 8 + size <= len(media)
        offset += 8 + size + (size & 1)
    return False


@dataclass(slots=True, frozen=True)
class _MediaLayout:
    tag: int
    header_end: int
    """Where the first decodable unit starts: Vorbis audio packets, or PCM/ADPCM blocks."""

    data_end: int
    bytes_per_second: float
    block_align: int


def _media_layout(media: bytes) -> Optional[_MediaLayout]:
    fmt_offset = data_offset = data_size = None
    offset = 12
    while offset + 8 <= len(media):
        identifier = media[offset : offset + 4]
        size = struct.unpack_from("<I", media, offset + 4)[0]
        if identifier == b"fmt " and size >= 16:
            fmt_offset = offset + 8
        if identifier == b"data":
            data_offset, data_size = offset + 8, size
            break
        offset += 8 + size + (size & 1)
    if fmt_offset is None or data_offset is None or media[:4] != b"RIFF":
        return None
    tag, _channels, rate, byte_rate, block_align = struct.unpack_from("<HHIIH", media, fmt_offset)
    data_end = data_offset + data_size
    if tag == 0xFFFF:
        if fmt_offset + 0x30 > len(media):
            return None
        samples = struct.unpack_from("<I", media, fmt_offset + 0x18)[0]
        audio_offset = struct.unpack_from("<I", media, fmt_offset + 0x2C)[0]
        header_end = data_offset + audio_offset
        seconds = samples / rate if rate and samples else 0.0
        audio_bytes = data_size - audio_offset
        return _MediaLayout(tag, header_end, data_end, audio_bytes / seconds if seconds else 0.0, 0)
    return _MediaLayout(tag, data_offset, data_end, float(byte_rate), max(1, block_align))


def _unit_boundaries(media: bytes, layout: _MediaLayout, limit: int):
    """Byte offsets where a decodable unit ends, up to `limit` (Vorbis: u16-sized packets)."""

    position = layout.header_end
    yield position
    if layout.tag == 0xFFFF:
        while position + 2 <= layout.data_end and position < limit:
            position += 2 + struct.unpack_from("<H", media, position)[0]
            if position > layout.data_end:
                return
            yield position
    else:
        while position < limit and position + layout.block_align <= layout.data_end:
            position += layout.block_align
            yield position


def stream_prefix_size(original_media: bytes, original_size: int, media: bytes) -> int:
    """The in-memory size a prefetched or streamed source needs for replacement media.

    In the shipped banks such a size is the stream's headers plus a few audio
    packets, ending exactly on a packet boundary (2,210 of 2,211 sources). The
    replacement keeps the same playing time, cut at its own next unit boundary.
    """

    before, after = _media_layout(original_media), _media_layout(media)
    if before is None or after is None:
        raise WwiseBankEditError("The original or replacement media header cannot be read to size its stream prefix.")
    if original_size < before.header_end or original_size > before.data_end:
        raise WwiseBankEditError(f"The bank's stream prefix of {original_size:,} bytes does not fit the original media.")
    if original_size not in set(_unit_boundaries(original_media, before, original_size)):
        raise WwiseBankEditError(
            f"The bank's stream prefix of {original_size:,} bytes does not end on a packet boundary of the original media."
        )
    if before.bytes_per_second <= 0 or after.bytes_per_second <= 0:
        raise WwiseBankEditError("The media's length is unknown, so its stream prefix cannot be scaled.")
    seconds = (original_size - before.header_end) / before.bytes_per_second
    target = after.header_end + seconds * after.bytes_per_second
    boundary = after.header_end
    for boundary in _unit_boundaries(media, after, int(math.ceil(target))):
        if boundary >= target - 1e-6:
            break
    return min(boundary, after.data_end)


def _require_graph(data: bytes) -> HircGraph:
    graph = read_hirc_graph(data)
    if graph.version != SUPPORTED_BANK_VERSION:
        raise WwiseBankEditError(f"Bank version {graph.version} is not version {SUPPORTED_BANK_VERSION}; refusing to edit it.")
    if not graph.framing_complete:
        raise WwiseBankEditError("The bank's HIRC objects do not frame completely; refusing to edit it.")
    return graph


def _encode(encoding: str, value: float | int) -> bytes:
    if encoding == "<f":
        number = float(value)
        if not math.isfinite(number):
            raise WwiseBankEditError(f"{value!r} is not a finite number.")
        packed = struct.pack("<f", number)
        if not math.isfinite(struct.unpack("<f", packed)[0]):
            raise WwiseBankEditError(f"{value!r} does not fit a 32-bit float.")
        return packed
    if isinstance(value, float) and not value.is_integer():
        raise WwiseBankEditError(f"{value!r} must be a whole number.")
    try:
        return struct.pack(encoding, int(value))
    except struct.error as error:
        raise WwiseBankEditError(f"{value!r} does not fit this field: {error}") from error


def _slot_for(node: HircNode, edit: HircEdit) -> Tuple[int, str]:
    kind, _, rest = edit.target.partition(":")
    if kind == "property":
        prop_id = _PROPERTY_IDS.get(rest)
        if prop_id is None or prop_id not in EDITABLE_PROPERTY_ENCODINGS:
            raise WwiseBankEditError(f"Property {rest!r} is not one with a measured, fixed type.")
        existing = node.property(prop_id)
        if existing is None:
            raise WwiseBankEditError(
                f"Object {node.object_id} does not store {rest}; adding a property changes the object's size."
            )
        return existing.offset, EDITABLE_PROPERTY_ENCODINGS[prop_id]
    if kind == "range":
        name, _, bound = rest.partition(":")
        prop_id = _PROPERTY_IDS.get(name)
        if prop_id is None or prop_id not in EDITABLE_PROPERTY_ENCODINGS or bound not in {"min", "max"}:
            raise WwiseBankEditError(f"Range {rest!r} is not an editable property bound.")
        for item in node.ranged_properties:
            if item.prop_id == prop_id:
                offset = item.min_offset if bound == "min" else item.max_offset
                return offset, EDITABLE_PROPERTY_ENCODINGS[prop_id]
        raise WwiseBankEditError(f"Object {node.object_id} has no randomizer range for {name}.")
    if kind == "value":
        slot = node.value(rest)
        if slot is None:
            raise WwiseBankEditError(f"Object {node.object_id} has no fixed-size value named {rest!r}.")
        return slot.offset, slot.encoding
    if kind == "weight":
        try:
            child = int(rest)
        except ValueError as error:
            raise WwiseBankEditError(f"Playlist entry {rest!r} is not an object id.") from error
        for item in node.playlist:
            if item.object_id == child:
                if int(edit.value) < 0:
                    raise WwiseBankEditError("A playlist weight cannot be negative.")
                return item.weight_offset, "<i"
        raise WwiseBankEditError(f"Object {node.object_id} has no playlist entry {child}.")
    raise WwiseBankEditError(f"Edit target {edit.target!r} is not recognised.")


def apply_hirc_edits(data: bytes, edits: Sequence[HircEdit]) -> BankEditResult:
    """Applies in-place value edits; nothing moves, so offsets stay valid."""

    graph = _require_graph(data)
    nodes = graph.by_id()
    output = bytearray(data)
    changes: List[str] = []
    for edit in edits:
        matches = [node for node in graph.nodes if node.object_id == int(edit.object_id)]
        if not matches:
            raise WwiseBankEditError(f"The bank has no HIRC object {edit.object_id}.")
        if len(matches) > 1:
            raise WwiseBankEditError(f"The bank has {len(matches)} HIRC objects with id {edit.object_id}; the edit is ambiguous.")
        node = nodes[int(edit.object_id)]
        if node.status != PARSED:
            raise WwiseBankEditError(f"Object {edit.object_id} did not decode exactly; refusing to edit it.")
        offset, encoding = _slot_for(node, edit)
        packed = _encode(encoding, edit.value)
        output[offset : offset + len(packed)] = packed
        changes.append(f"object {node.object_id}: {edit.target} = {edit.value}")
    result = bytes(output)
    _verify_same_shape(graph, result)
    return BankEditResult(result, tuple(changes))


def _bundle_entries(data: bytes, offset: int, value_size: int) -> Tuple[Dict[int, bytes], int]:
    count = data[offset]
    ids = data[offset + 1 : offset + 1 + count]
    values = offset + 1 + count
    entries = {prop_id: bytes(data[values + i * value_size : values + (i + 1) * value_size]) for i, prop_id in enumerate(ids)}
    if len(entries) != count:
        raise WwiseBankEditError("A property bundle stores the same id twice; refusing to rebuild it.")
    return entries, values + count * value_size


def _encode_bundle(entries: Dict[int, bytes]) -> bytes:
    if len(entries) > 255:
        raise WwiseBankEditError("An object cannot store more than 255 properties.")
    ids = sorted(entries)
    return bytes([len(ids)]) + bytes(ids) + b"".join(entries[prop_id] for prop_id in ids)


def _property_change(node: HircNode, change: HircPropertyChange, props: Dict[int, bytes], ranges: Dict[int, bytes]) -> str:
    kind, _, name = change.target.partition(":")
    prop_id = _PROPERTY_IDS.get(name)
    if kind not in {"property", "range"} or prop_id is None:
        raise WwiseBankEditError(f"Change target {change.target!r} is not a property or range name.")
    if prop_id not in EDITABLE_PROPERTY_ENCODINGS:
        raise WwiseBankEditError(f"Property {name!r} is not one with a measured, fixed type.")
    encoding = EDITABLE_PROPERTY_ENCODINGS[prop_id]
    table, allowed = (props, ADDABLE_PROPERTIES_BY_KIND) if kind == "property" else (ranges, ADDABLE_RANGES_BY_KIND)
    if change.value is None:
        if prop_id not in table:
            raise WwiseBankEditError(f"Object {node.object_id} stores no {change.target}; nothing to remove.")
        del table[prop_id]
        return f"object {node.object_id}: removed {change.target}"
    if prop_id not in table and prop_id not in allowed.get(node.kind, frozenset()):
        raise WwiseBankEditError(
            f"No shipped object of type {node.kind} stores {change.target}, so it is not added to object {node.object_id}."
        )
    if kind == "property":
        table[prop_id] = _encode(encoding, change.value)
    else:
        try:
            low, high = change.value
        except (TypeError, ValueError) as error:
            raise WwiseBankEditError(f"A range needs a (min, max) pair, not {change.value!r}.") from error
        if float(low) > float(high):
            raise WwiseBankEditError(f"Range minimum {low} is above its maximum {high}.")
        table[prop_id] = _encode(encoding, low) + _encode(encoding, high)
    return f"object {node.object_id}: {change.target} = {change.value}"


def change_hirc_properties(data: bytes, changes: Sequence[HircPropertyChange]) -> BankEditResult:
    """Adds, changes or removes stored properties; objects and the HIRC chunk are resized.

    Nothing outside HIRC refers to a byte position inside it, so the other
    chunks are copied as they are.
    """

    graph = _require_graph(data)
    by_object: Dict[int, List[HircPropertyChange]] = {}
    for change in changes:
        by_object.setdefault(int(change.object_id), []).append(change)
    targets: Dict[int, HircNode] = {}
    for object_id in by_object:
        matches = [node for node in graph.nodes if node.object_id == object_id]
        if not matches:
            raise WwiseBankEditError(f"The bank has no HIRC object {object_id}.")
        if len(matches) > 1:
            raise WwiseBankEditError(f"The bank has {len(matches)} HIRC objects with id {object_id}; the change is ambiguous.")
        node = matches[0]
        if node.status != PARSED or "property_bundle" not in node.details:
            raise WwiseBankEditError(f"Object {object_id} has no decoded property bundle; refusing to change it.")
        targets[node.offset] = node

    descriptions: List[str] = []
    rebuilt_objects = bytearray()
    expected: Dict[int, Tuple[Dict[int, bytes], Dict[int, bytes]]] = {}
    for node in graph.nodes:
        original = data[node.offset : node.end]
        if node.offset not in targets:
            rebuilt_objects.extend(original)
            continue
        props_at = node.details["property_bundle"]
        props, props_end = _bundle_entries(data, props_at, 4)
        ranged_at = node.details.get("ranged_bundle")
        ranges: Dict[int, bytes] = {}
        ranges_end = props_end
        if ranged_at is not None:
            if ranged_at != props_end:
                raise WwiseBankEditError(f"Object {node.object_id} does not store its ranges right after its properties.")
            ranges, ranges_end = _bundle_entries(data, ranged_at, 8)
        for change in by_object[node.object_id]:
            if change.target.startswith("range:") and ranged_at is None:
                raise WwiseBankEditError(f"Object {node.object_id} has no randomizer ranges.")
            descriptions.append(_property_change(node, change, props, ranges))
        body = (
            data[node.offset + 9 : props_at]
            + _encode_bundle(props)
            + (_encode_bundle(ranges) if ranged_at is not None else b"")
            + data[ranges_end : node.end]
        )
        rebuilt_objects.extend(struct.pack("<BII", node.kind, len(body) + 4, node.object_id))
        rebuilt_objects.extend(body)
        expected[node.object_id] = (props, ranges)

    chunks, consumed = read_bank_chunks(data)
    if consumed != len(data):
        raise WwiseBankEditError("The bank has bytes after its last chunk; refusing to rebuild it.")
    output = bytearray()
    for chunk in chunks:
        if chunk.identifier == "HIRC":
            body = data[chunk.offset : chunk.offset + 4] + bytes(rebuilt_objects)
        else:
            body = data[chunk.offset : chunk.offset + chunk.size]
        output.extend(chunk.identifier.encode("ascii") + struct.pack("<I", len(body)) + body)
    result = bytes(output)

    after = read_hirc_graph(result)
    if not after.framing_complete or [(n.kind, n.object_id) for n in after.nodes] != [(n.kind, n.object_id) for n in graph.nodes]:
        raise WwiseBankEditError("The rebuilt bank does not frame like the original; nothing was written.")
    for old, new in zip(graph.nodes, after.nodes):
        if new.status != old.status:
            raise WwiseBankEditError(f"Object {old.object_id} decodes differently after the change; nothing was written.")
        if old.object_id in expected:
            props, ranges = expected[old.object_id]
            stored = {item.prop_id: struct.pack("<I", item.raw) for item in new.properties}
            stored_ranges = {item.prop_id: struct.pack("<II", item.min_raw, item.max_raw) for item in new.ranged_properties}
            if stored != props or stored_ranges != ranges:
                raise WwiseBankEditError(f"Object {old.object_id} does not read back its properties; nothing was written.")
        elif result[new.offset : new.end] != data[old.offset : old.end]:
            raise WwiseBankEditError(f"Object {old.object_id} changed although it was not edited; nothing was written.")
    return BankEditResult(result, tuple(descriptions))


def _verify_same_shape(before: HircGraph, data: bytes) -> HircGraph:
    after = read_hirc_graph(data)
    if not after.framing_complete or len(after.nodes) != len(before.nodes):
        raise WwiseBankEditError("The edited bank no longer frames like the original; nothing was written.")
    for old, new in zip(before.nodes, after.nodes):
        if (old.kind, old.object_id, old.size, old.status) != (new.kind, new.object_id, new.size, new.status):
            raise WwiseBankEditError(f"Object {old.object_id} decodes differently after the edit; nothing was written.")
    return after


def _media_users(graph: HircGraph, data: bytes, source_id: int) -> List[Tuple[HircNode, HircSource]]:
    """Every decoded source that plays this media.

    An object this reader does not decode could also name the id (a plugin's
    media list, say), so a match inside one refuses the edit rather than
    leaving it describing the old media.
    """

    needle = struct.pack("<I", int(source_id))
    users: List[Tuple[HircNode, HircSource]] = []
    for node in graph.nodes:
        if node.status != PARSED:
            if needle in data[node.offset + 9 : node.end]:
                raise WwiseBankEditError(
                    f"HIRC object {node.object_id} (type {node.kind}) is not decoded and may refer to media "
                    f"{source_id}; refusing to change that media."
                )
            continue
        if source_id in node.plugin_media:
            raise WwiseBankEditError(
                f"Effect {node.object_id} loads media {source_id} as plugin data, not as a sound; refusing to change it."
            )
        for source in node.sources:
            if source.source_id != source_id:
                continue
            if source.plugin_id not in _REPLACEABLE_CODECS:
                raise WwiseBankEditError(
                    f"Object {node.object_id} plays media {source_id} through plugin 0x{source.plugin_id:08X}, "
                    "not a codec this writer can retarget."
                )
            users.append((node, source))
    streams = {source.stream_type == _STREAM_IN_MEMORY for _node, source in users}
    if len(streams) > 1:
        raise WwiseBankEditError(
            f"Media {source_id} is both held in memory and prefetched or streamed in this bank; "
            "no shipped bank does that, so it is refused."
        )
    return users


def _new_size(source: HircSource, media: bytes, original_media: Optional[bytes]) -> int:
    if source.stream_type == _STREAM_IN_MEMORY:
        return len(media)
    if original_media is None:
        raise WwiseBankEditError(
            f"Media {source.source_id} is prefetched or streamed; its original file is needed to size the new prefix."
        )
    return stream_prefix_size(original_media, source.in_memory_size, media)


def _retarget(
    output: bytearray,
    users: Iterable[Tuple[HircNode, HircSource]],
    plugin_id: int,
    media: bytes,
    original_media: Optional[bytes],
) -> List[str]:
    changes: List[str] = []
    for node, source in users:
        size = _new_size(source, media, original_media)
        struct.pack_into("<I", output, source.plugin_offset, plugin_id)
        struct.pack_into("<I", output, source.in_memory_size_offset, size)
        label = "sound" if node.kind == KIND_SOUND else "music track"
        stream = "" if source.stream_type == _STREAM_IN_MEMORY else " (stream prefix)"
        changes.append(
            f"{label} {node.object_id}: media {source.source_id} size{stream} {source.in_memory_size} -> {size}"
            + (f", codec 0x{source.plugin_id:08X} -> 0x{plugin_id:08X}" if source.plugin_id != plugin_id else "")
        )
    return changes


def bank_media_references(data: bytes, source_id: int) -> Tuple[bool, int, int]:
    """Whether a bank embeds this media, how many decoded objects play it, and how
    many undecoded objects hold its id (a bank that names it there cannot be judged)."""

    embedded = any(media.source_id == source_id for media in read_embedded_media(data))
    graph = read_hirc_graph(data)
    needle = struct.pack("<I", int(source_id))
    undecoded = sum(1 for node in graph.nodes if node.status != PARSED and needle in data[node.offset + 9 : node.end])
    return embedded, len(graph.sounds_for_source(source_id)), undecoded


def bank_music_track_users(data: bytes, source_id: int) -> int:
    """How many music tracks in a bank play this media; their clips keep the original's timing."""

    return sum(1 for node in read_hirc_graph(data).sounds_for_source(source_id) if node.kind == KIND_MUSIC_TRACK)


def media_duration_seconds(media: bytes) -> Optional[float]:
    """Playing time from the stream header: Vorbis sample count, or PCM/ADPCM data size."""

    layout = _media_layout(media)
    if layout is None or layout.bytes_per_second <= 0:
        return None
    if layout.tag == 0xFFFF:
        fmt_rate = None
        offset = 12
        while offset + 8 <= len(media):
            size = struct.unpack_from("<I", media, offset + 4)[0]
            if media[offset : offset + 4] == b"fmt ":
                fmt_rate = struct.unpack_from("<I", media, offset + 12)[0], struct.unpack_from("<I", media, offset + 8 + 0x18)[0]
                break
            offset += 8 + size + (size & 1)
        if not fmt_rate or not fmt_rate[0]:
            return None
        return fmt_rate[1] / fmt_rate[0]
    data_start = layout.header_end
    return (layout.data_end - data_start) / layout.bytes_per_second


def retarget_loose_media(
    data: bytes,
    source_id: int,
    media: bytes,
    *,
    original_media: Optional[bytes] = None,
) -> BankEditResult:
    """Points every source playing a loose `.wem` at its replacement.

    In-memory sources get the new file size; prefetched and streamed sources a
    new prefix size, which needs the original file. Refuses when the bank also
    embeds that media (use `replace_embedded_media`).
    """

    if any(item.source_id == source_id for item in read_embedded_media(data)):
        raise WwiseBankEditError(f"The bank embeds media {source_id}; replace the embedded copy instead.")
    graph = _require_graph(data)
    plugin_id = codec_plugin_for_media(media)
    users = _media_users(graph, data, source_id)
    output = bytearray(data)
    changes = _retarget(output, users, plugin_id, media, original_media)
    result = bytes(output)
    _verify_same_shape(graph, result)
    return BankEditResult(result, tuple(changes))


def replace_embedded_media(
    data: bytes,
    source_id: int,
    media: bytes,
    *,
    original_media: Optional[bytes] = None,
) -> BankEditResult:
    """Swaps one embedded sound and rebuilds DIDX and DATA around it.

    An embedded copy that is a stream prefix (its data chunk runs past the end
    of the blob) is replaced by the replacement's own prefix of the same
    playing time, which needs the complete original file.
    """

    graph = _require_graph(data)
    plugin_id = codec_plugin_for_media(media)
    chunks, consumed = read_bank_chunks(data)
    if consumed != len(data):
        raise WwiseBankEditError("The bank has bytes after its last chunk; refusing to rebuild it.")
    by_name = {chunk.identifier: chunk for chunk in chunks}
    directory, payload = by_name.get("DIDX"), by_name.get("DATA")
    if directory is None or payload is None:
        raise WwiseBankEditError("The bank embeds no media.")
    if [chunk.identifier for chunk in chunks].count("DIDX") != 1 or [chunk.identifier for chunk in chunks].count("DATA") != 1:
        raise WwiseBankEditError("The bank has more than one media table; refusing to rebuild it.")
    embedded = read_embedded_media(data)
    if len(embedded) * 12 != directory.size:
        raise WwiseBankEditError("The media table size is not a whole number of records.")
    target = next((item for item in embedded if item.source_id == source_id), None)
    if target is None:
        raise WwiseBankEditError(f"The bank does not embed media {source_id}.")
    for item in embedded:
        if item.offset + item.size > payload.size:
            raise WwiseBankEditError(f"Embedded media {item.source_id} runs past the DATA chunk.")

    users = _media_users(graph, data, source_id)
    old_blob = data[payload.offset + target.offset : payload.offset + target.offset + target.size]
    # Sources that stream keep a prefix here; a prefetch of a short file can be the whole file.
    streaming = any(source.stream_type != _STREAM_IN_MEMORY for _node, source in users) if users else not _has_data_chunk(old_blob)
    if not streaming:
        if not _has_data_chunk(old_blob):
            raise WwiseBankEditError(f"The bank embeds only a prefix of media {source_id} but holds it in memory; refusing.")
        content = media
    else:
        if original_media is None:
            raise WwiseBankEditError(
                f"The bank embeds only a stream prefix of media {source_id}; its original file is needed to cut a new one."
            )
        if original_media[: len(old_blob)] != old_blob:
            raise WwiseBankEditError(f"The embedded prefix of media {source_id} is not a prefix of the original file.")
        content = media[: stream_prefix_size(original_media, len(old_blob), media)]
    patched = bytearray(data)
    changes = _retarget(patched, users, plugin_id, media, original_media)

    records = bytearray()
    blob = bytearray()
    for item in embedded:
        if len(blob) % _MEDIA_ALIGNMENT:
            blob.extend(b"\x00" * (_MEDIA_ALIGNMENT - len(blob) % _MEDIA_ALIGNMENT))
        piece = content if item.source_id == source_id else data[payload.offset + item.offset : payload.offset + item.offset + item.size]
        records.extend(struct.pack("<III", item.source_id, len(blob), len(piece)))
        blob.extend(piece)
    kind = "embedded media" if content is media else "embedded stream prefix"
    changes.append(f"{kind} {source_id}: {target.size} -> {len(content)} bytes")

    rebuilt = bytearray()
    for chunk in chunks:
        if chunk.identifier == "DIDX":
            body = bytes(records)
        elif chunk.identifier == "DATA":
            body = bytes(blob)
        else:
            body = bytes(patched[chunk.offset : chunk.offset + chunk.size])
        rebuilt.extend(chunk.identifier.encode("ascii"))
        rebuilt.extend(struct.pack("<I", len(body)))
        rebuilt.extend(body)
    result = bytes(rebuilt)

    _verify_same_shape(graph, result)
    replaced = {item.source_id: item for item in read_embedded_media(result)}
    if [item.source_id for item in read_embedded_media(result)] != [item.source_id for item in embedded]:
        raise WwiseBankEditError("The rebuilt media table lists different sounds; nothing was written.")
    new_payload = {chunk.identifier: chunk for chunk in read_bank_chunks(result)[0]}["DATA"]
    for item in embedded:
        expected = content if item.source_id == source_id else data[payload.offset + item.offset : payload.offset + item.offset + item.size]
        record = replaced[item.source_id]
        if result[new_payload.offset + record.offset : new_payload.offset + record.offset + record.size] != expected:
            raise WwiseBankEditError(f"Embedded media {item.source_id} does not read back intact; nothing was written.")
    return BankEditResult(result, tuple(changes))


__all__ = [
    "ADDABLE_PROPERTIES_BY_KIND",
    "ADDABLE_RANGES_BY_KIND",
    "BankEditResult",
    "CODEC_PLUGIN_BY_FORMAT_TAG",
    "EDITABLE_PROPERTY_ENCODINGS",
    "HircEdit",
    "HircPropertyChange",
    "WwiseBankEditError",
    "apply_hirc_edits",
    "bank_media_references",
    "bank_music_track_users",
    "change_hirc_properties",
    "codec_plugin_for_media",
    "media_duration_seconds",
    "media_format_tag",
    "replace_embedded_media",
    "retarget_loose_media",
    "stream_prefix_size",
]
