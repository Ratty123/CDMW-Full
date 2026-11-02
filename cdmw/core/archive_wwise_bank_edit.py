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
    0x05: "<f",  # MakeUpGain (dB)
    0x06: "<f",  # Priority
    0x08: "<f",  # UserAuxSendVolume0
    0x09: "<f",  # UserAuxSendVolume1
    0x0A: "<f",  # UserAuxSendVolume2
    0x0B: "<f",  # UserAuxSendVolume3
    0x0C: "<f",  # GameAuxSendVolume
    0x22: "<f",  # InitialDelay (s)
    0x29: "<f",  # Positioning_CenterPercent
    0x39: "<I",  # DelayTime (ms)
    0x3A: "<I",  # TransitionTime (ms)
    0x54: "<I",  # Loop (count, 0 = infinite)
}
_PROPERTY_IDS = {name: prop_id for prop_id, name in PROPERTY_NAMES.items()}

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


def _verify_same_shape(before: HircGraph, data: bytes) -> HircGraph:
    after = read_hirc_graph(data)
    if not after.framing_complete or len(after.nodes) != len(before.nodes):
        raise WwiseBankEditError("The edited bank no longer frames like the original; nothing was written.")
    for old, new in zip(before.nodes, after.nodes):
        if (old.kind, old.object_id, old.size, old.status) != (new.kind, new.object_id, new.size, new.status):
            raise WwiseBankEditError(f"Object {old.object_id} decodes differently after the edit; nothing was written.")
    return after


def _media_users(graph: HircGraph, data: bytes, source_id: int) -> List[Tuple[HircNode, HircSource]]:
    """Every decoded source that plays this media, all of which must load it from memory.

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
        for source in node.sources:
            if source.source_id != source_id:
                continue
            if source.stream_type != _STREAM_IN_MEMORY:
                raise WwiseBankEditError(
                    f"Object {node.object_id} prefetches or streams media {source_id}; the bank keeps a prefix or "
                    "prefetch size whose rule is not established, so this media cannot be replaced safely."
                )
            if source.plugin_id not in _REPLACEABLE_CODECS:
                raise WwiseBankEditError(
                    f"Object {node.object_id} plays media {source_id} through plugin 0x{source.plugin_id:08X}, "
                    "not a codec this writer can retarget."
                )
            users.append((node, source))
    return users


def _retarget(output: bytearray, users: Iterable[Tuple[HircNode, HircSource]], plugin_id: int, media_size: int) -> List[str]:
    changes: List[str] = []
    for node, source in users:
        struct.pack_into("<I", output, source.plugin_offset, plugin_id)
        struct.pack_into("<I", output, source.in_memory_size_offset, media_size)
        label = "sound" if node.kind == KIND_SOUND else "music track"
        changes.append(
            f"{label} {node.object_id}: media {source.source_id} size {source.in_memory_size} -> {media_size}"
            + (f", codec 0x{source.plugin_id:08X} -> 0x{plugin_id:08X}" if source.plugin_id != plugin_id else "")
        )
    return changes


def bank_media_references(data: bytes, source_id: int) -> Tuple[bool, int]:
    """Whether a bank embeds this media, and how many of its objects play it."""

    embedded = any(media.source_id == source_id for media in read_embedded_media(data))
    graph = read_hirc_graph(data)
    return embedded, len(graph.sounds_for_source(source_id))


def retarget_loose_media(data: bytes, source_id: int, media: bytes) -> BankEditResult:
    """Points every in-memory source playing a loose `.wem` at its replacement.

    Refuses when the bank also embeds that media (use `replace_embedded_media`)
    or when any Sound or music track prefetches or streams it.
    """

    if any(item.source_id == source_id for item in read_embedded_media(data)):
        raise WwiseBankEditError(f"The bank embeds media {source_id}; replace the embedded copy instead.")
    graph = _require_graph(data)
    plugin_id = codec_plugin_for_media(media)
    users = _media_users(graph, data, source_id)
    output = bytearray(data)
    changes = _retarget(output, users, plugin_id, len(media))
    result = bytes(output)
    _verify_same_shape(graph, result)
    return BankEditResult(result, tuple(changes))


def replace_embedded_media(data: bytes, source_id: int, media: bytes) -> BankEditResult:
    """Swaps one embedded sound and rebuilds DIDX and DATA around it."""

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
    if not any(item.source_id == source_id for item in embedded):
        raise WwiseBankEditError(f"The bank does not embed media {source_id}.")
    for item in embedded:
        if item.offset + item.size > payload.size:
            raise WwiseBankEditError(f"Embedded media {item.source_id} runs past the DATA chunk.")

    users = _media_users(graph, data, source_id)
    patched = bytearray(data)
    changes = _retarget(patched, users, plugin_id, len(media))

    records = bytearray()
    blob = bytearray()
    for item in embedded:
        if len(blob) % _MEDIA_ALIGNMENT:
            blob.extend(b"\x00" * (_MEDIA_ALIGNMENT - len(blob) % _MEDIA_ALIGNMENT))
        content = media if item.source_id == source_id else data[payload.offset + item.offset : payload.offset + item.offset + item.size]
        records.extend(struct.pack("<III", item.source_id, len(blob), len(content)))
        blob.extend(content)
    changes.append(f"embedded media {source_id}: {next(i.size for i in embedded if i.source_id == source_id)} -> {len(media)} bytes")

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
    rebuilt_chunks = {chunk.identifier: chunk for chunk in read_bank_chunks(result)[0]}
    new_payload = rebuilt_chunks["DATA"]
    for item in embedded:
        expected = media if item.source_id == source_id else data[payload.offset + item.offset : payload.offset + item.offset + item.size]
        record = replaced[item.source_id]
        if result[new_payload.offset + record.offset : new_payload.offset + record.offset + record.size] != expected:
            raise WwiseBankEditError(f"Embedded media {item.source_id} does not read back intact; nothing was written.")
    return BankEditResult(result, tuple(changes))


__all__ = [
    "BankEditResult",
    "CODEC_PLUGIN_BY_FORMAT_TAG",
    "EDITABLE_PROPERTY_ENCODINGS",
    "HircEdit",
    "WwiseBankEditError",
    "apply_hirc_edits",
    "bank_media_references",
    "codec_plugin_for_media",
    "media_format_tag",
    "replace_embedded_media",
    "retarget_loose_media",
]
