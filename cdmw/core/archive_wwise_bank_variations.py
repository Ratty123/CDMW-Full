"""Adds or removes a sound variation in a random/sequence container (bank version 150).

A variation is a Sound object that a random/sequence container lists as a
child and in its playlist. Adding one copies an existing child Sound (so it
inherits that sibling's routing, positioning and properties), gives it new
object and media ids, embeds the new media in this bank, and lists it in the
container. The rebuilt bank keeps the layout every shipped bank has: children
before parents in HIRC, children lists sorted by id, media sorted by id on
16-byte boundaries in DATA.

Removing a variation is the inverse, refused while anything else in the bank
names the Sound. Removing each shipped variation and adding it back reproduces
its bank byte for byte, which is the evidence for this layout; whether the game
plays an added variation has not been checked in game.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from cdmw.core.archive_wwise_bank import read_bank_chunks, read_embedded_media
from cdmw.core.archive_wwise_bank_edit import (
    BankEditResult,
    WwiseBankEditError,
    _require_graph,
    codec_plugin_for_media,
)
from cdmw.core.archive_wwise_hirc import (
    KIND_RANDOM_SEQUENCE,
    KIND_SOUND,
    PARSED,
    HircGraph,
    HircNode,
    read_hirc_graph,
)

_MEDIA_ALIGNMENT = 16
_REPLACEABLE_CODECS = {0x00010001, 0x00020001, 0x00040001}
#: Wwise's default playlist weight (50 in the authoring tool).
DEFAULT_PLAYLIST_WEIGHT = 50000


@dataclass(slots=True, frozen=True)
class _Variation:
    sound: bytes
    """The whole Sound object: type, size, id and body."""

    hirc_index: int
    playlist_index: int
    weight: int
    media: Optional[Tuple[int, bytes]]


def fnv1_32(name: str) -> int:
    """Wwise's ShortID hash: 32-bit FNV-1 of the lower-cased name."""

    value = 2166136261
    for byte in name.lower().encode("utf-8"):
        value = (value * 16777619) & 0xFFFFFFFF
        value ^= byte
    return value


def allocate_wwise_id(name: str, taken: Iterable[int]) -> int:
    """A ShortID for `name` that no bank object or media already uses."""

    used = set(taken)
    for attempt in range(1000):
        candidate = fnv1_32(name if attempt == 0 else f"{name}_{attempt}")
        if candidate and candidate not in used:
            return candidate
    raise WwiseBankEditError(f"No unused id could be made for {name!r}.")


def bank_ids(data: bytes) -> set[int]:
    """Every object, media and source id a bank uses."""

    graph = read_hirc_graph(data)
    ids = {node.object_id for node in graph.nodes}
    ids.update(source.source_id for node in graph.nodes for source in node.sources)
    ids.update(item.source_id for item in read_embedded_media(data))
    return ids


def _node(graph: HircGraph, object_id: int, kind: int, label: str) -> HircNode:
    matches = [node for node in graph.nodes if node.object_id == object_id]
    if len(matches) != 1:
        raise WwiseBankEditError(f"The bank has {len(matches)} HIRC objects with id {object_id}; expected one {label}.")
    node = matches[0]
    if node.kind != kind or node.status != PARSED:
        raise WwiseBankEditError(f"Object {object_id} is not a decoded {label}.")
    return node


def _media_table(data: bytes) -> Dict[int, bytes]:
    chunks = {chunk.identifier: chunk for chunk in read_bank_chunks(data)[0]}
    payload = chunks.get("DATA")
    table: Dict[int, bytes] = {}
    for item in read_embedded_media(data):
        if payload is None or item.offset + item.size > payload.size:
            raise WwiseBankEditError(f"Embedded media {item.source_id} runs past the DATA chunk.")
        table[item.source_id] = bytes(data[payload.offset + item.offset : payload.offset + item.offset + item.size])
    return table


def _container_body(data: bytes, container: HircNode, children: Sequence[int], playlist: Sequence[Tuple[int, int]]) -> bytes:
    start = container.offset + 9
    children_at = container.details["children"]
    playlist_at = container.details["playlist"]
    if children_at + 4 + 4 * len(container.children) != playlist_at:
        raise WwiseBankEditError(f"Container {container.object_id} does not store its playlist right after its children.")
    playlist_end = playlist_at + 2 + 8 * len(container.playlist)
    return (
        data[start:children_at]
        + struct.pack("<I", len(children))
        + b"".join(struct.pack("<I", child) for child in children)
        + struct.pack("<H", len(playlist))
        + b"".join(struct.pack("<Ii", child, weight) for child, weight in playlist)
        + data[playlist_end : container.end]
    )


def _assemble(data: bytes, objects: Sequence[bytes], media: Dict[int, bytes]) -> bytes:
    chunks, consumed = read_bank_chunks(data)
    if consumed != len(data):
        raise WwiseBankEditError("The bank has bytes after its last chunk; refusing to rebuild it.")
    names = [chunk.identifier for chunk in chunks]
    if names.count("HIRC") != 1 or names.count("DIDX") > 1 or names.count("DATA") > 1:
        raise WwiseBankEditError("The bank's chunk list is not the shipped shape; refusing to rebuild it.")
    records = bytearray()
    blob = bytearray()
    for source_id in sorted(media):
        if len(blob) % _MEDIA_ALIGNMENT:
            blob.extend(b"\x00" * (_MEDIA_ALIGNMENT - len(blob) % _MEDIA_ALIGNMENT))
        records.extend(struct.pack("<III", source_id, len(blob), len(media[source_id])))
        blob.extend(media[source_id])
    hirc = struct.pack("<I", len(objects)) + b"".join(objects)

    def chunk(identifier: str, body: bytes) -> bytes:
        return identifier.encode("ascii") + struct.pack("<I", len(body)) + body

    had_media = "DIDX" in names
    output = bytearray()
    for item in chunks:
        if item.identifier == "DIDX":
            if media:
                output.extend(chunk("DIDX", bytes(records)))
        elif item.identifier == "DATA":
            if media:
                output.extend(chunk("DATA", bytes(blob)))
        elif item.identifier == "HIRC":
            if media and not had_media:
                # Shipped banks keep the media table right before HIRC.
                output.extend(chunk("DIDX", bytes(records)) + chunk("DATA", bytes(blob)))
            output.extend(chunk("HIRC", hirc))
        else:
            output.extend(chunk(item.identifier, data[item.offset : item.offset + item.size]))
    return bytes(output)


def _referrers(graph: HircGraph, sound_id: int, container_id: int) -> List[int]:
    others = []
    for node in graph.nodes:
        if node.object_id in {sound_id, container_id}:
            continue
        if sound_id in node.children or node.target_id == sound_id or any(item.object_id == sound_id for item in node.playlist):
            others.append(node.object_id)
    return others


def _remove(data: bytes, graph: HircGraph, container: HircNode, sound: HircNode) -> Tuple[bytes, _Variation]:
    if sound.object_id not in container.children:
        raise WwiseBankEditError(f"Sound {sound.object_id} is not a child of container {container.object_id}.")
    if len(container.children) < 2:
        raise WwiseBankEditError(f"Container {container.object_id} would be left without sounds.")
    others = _referrers(graph, sound.object_id, container.object_id)
    if others:
        raise WwiseBankEditError(f"Sound {sound.object_id} is also named by object {others[0]}; refusing to remove it.")
    positions = [i for i, item in enumerate(container.playlist) if item.object_id == sound.object_id]
    if len(positions) > 1:
        raise WwiseBankEditError(f"Container {container.object_id} lists sound {sound.object_id} more than once.")
    media = _media_table(data)
    source = sound.source
    embedded: Optional[Tuple[int, bytes]] = None
    if source is not None and source.source_id in media:
        users = [node for node in graph.nodes if any(item.source_id == source.source_id for item in node.sources)]
        if users == [sound]:
            embedded = (source.source_id, media.pop(source.source_id))
    playlist = [(item.object_id, item.weight) for item in container.playlist if item.object_id != sound.object_id]
    children = [child for child in container.children if child != sound.object_id]
    body = _container_body(data, container, children, playlist)
    objects: List[bytes] = []
    index = 0
    for position, node in enumerate(graph.nodes):
        if node is sound:
            index = position
            continue
        if node is container:
            objects.append(struct.pack("<BII", node.kind, len(body) + 4, node.object_id) + body)
        else:
            objects.append(data[node.offset : node.end])
    variation = _Variation(
        bytes(data[sound.offset : sound.end]),
        index,
        positions[0] if positions else -1,
        container.playlist[positions[0]].weight if positions else 0,
        embedded,
    )
    return _assemble(data, objects, media), variation


def _insert(data: bytes, graph: HircGraph, container: HircNode, variation: _Variation) -> bytes:
    sound_id = struct.unpack_from("<I", variation.sound, 5)[0]
    children = sorted(list(container.children) + [sound_id])
    playlist = [(item.object_id, item.weight) for item in container.playlist]
    if variation.playlist_index >= 0:
        playlist.insert(min(variation.playlist_index, len(playlist)), (sound_id, variation.weight))
    body = _container_body(data, container, children, playlist)
    objects = [data[node.offset : node.end] for node in graph.nodes]
    objects[graph.nodes.index(container)] = struct.pack("<BII", container.kind, len(body) + 4, container.object_id) + body
    if variation.hirc_index > graph.nodes.index(container):
        raise WwiseBankEditError("A sound must come before the container that lists it.")
    objects.insert(variation.hirc_index, variation.sound)
    media = _media_table(data)
    if variation.media is not None:
        if variation.media[0] in media:
            raise WwiseBankEditError(f"The bank already embeds media {variation.media[0]}.")
        media[variation.media[0]] = variation.media[1]
    return _assemble(data, objects, media)


def _check(result: bytes, before: HircGraph, *, added: Sequence[int] = (), removed: Sequence[int] = ()) -> HircGraph:
    after = read_hirc_graph(result)
    if not after.framing_complete or any(node.status != PARSED for node in after.nodes if node.object_id in added):
        raise WwiseBankEditError("The rebuilt bank does not decode; nothing was written.")
    expected = [node.object_id for node in before.nodes if node.object_id not in removed]
    actual = [node.object_id for node in after.nodes if node.object_id not in added]
    if expected != actual:
        raise WwiseBankEditError("The rebuilt bank lists different objects; nothing was written.")
    return after


def remove_sound_variation(data: bytes, container_id: int, sound_id: int) -> BankEditResult:
    """Takes one Sound out of a random/sequence container, and its media if nothing else plays it."""

    graph = _require_graph(data)
    container = _node(graph, container_id, KIND_RANDOM_SEQUENCE, "random/sequence container")
    sound = _node(graph, sound_id, KIND_SOUND, "sound")
    result, variation = _remove(data, graph, container, sound)
    _check(result, graph, removed=[sound_id])
    changes = [f"container {container_id}: removed sound {sound_id}"]
    if variation.media is not None:
        changes.append(f"removed embedded media {variation.media[0]} ({len(variation.media[1]):,} bytes)")
    return BankEditResult(result, tuple(changes))


def add_sound_variation(
    data: bytes,
    container_id: int,
    template_sound_id: int,
    media: bytes,
    *,
    new_sound_id: int,
    new_source_id: int,
    weight: Optional[int] = None,
) -> BankEditResult:
    """Adds a copy of a sibling Sound that plays new media embedded in this bank."""

    graph = _require_graph(data)
    container = _node(graph, container_id, KIND_RANDOM_SEQUENCE, "random/sequence container")
    template = _node(graph, template_sound_id, KIND_SOUND, "sound")
    if template.object_id not in container.children:
        raise WwiseBankEditError(f"Sound {template_sound_id} is not a child of container {container_id}.")
    source = template.source
    if source is None or source.plugin_id not in _REPLACEABLE_CODECS:
        raise WwiseBankEditError(f"Sound {template_sound_id} does not play media through a codec; pick another sibling.")
    used = bank_ids(data)
    for label, value in (("object", new_sound_id), ("media", new_source_id)):
        if not value or value in used:
            raise WwiseBankEditError(f"The new {label} id {value} is already used in this bank.")
    plugin = codec_plugin_for_media(media)
    sound = bytearray(data[template.offset : template.end])
    base = template.offset
    struct.pack_into("<I", sound, 5, new_sound_id)
    struct.pack_into("<I", sound, source.plugin_offset - base, plugin)
    sound[source.plugin_offset - base + 4] = 0  # held in memory, from this bank
    struct.pack_into("<I", sound, source.plugin_offset - base + 5, new_source_id)
    struct.pack_into("<I", sound, source.in_memory_size_offset - base, len(media))
    sound[source.in_memory_size_offset - base + 4] = source.source_bits & ~0x01  # embedded media is not per language
    template_weights = [item.weight for item in container.playlist if item.object_id == template.object_id]
    playlist_weight = int(weight) if weight is not None else (template_weights[0] if template_weights else DEFAULT_PLAYLIST_WEIGHT)
    if playlist_weight < 0:
        raise WwiseBankEditError("A playlist weight cannot be negative.")
    variation = _Variation(
        bytes(sound),
        graph.nodes.index(template) + 1,
        len(container.playlist),
        playlist_weight,
        (new_source_id, media),
    )
    result = _insert(data, graph, container, variation)
    after = _check(result, graph, added=[new_sound_id])
    added = after.by_id()[new_sound_id]
    if added.source is None or (added.source.source_id, added.source.in_memory_size) != (new_source_id, len(media)):
        raise WwiseBankEditError("The added sound does not read back; nothing was written.")
    if new_sound_id not in after.by_id()[container_id].children:
        raise WwiseBankEditError("The container does not list the added sound; nothing was written.")
    return BankEditResult(
        result,
        (
            f"container {container_id}: added sound {new_sound_id} (copy of {template_sound_id}, weight {playlist_weight})",
            f"embedded media {new_source_id} ({len(media):,} bytes)",
        ),
    )


__all__ = [
    "DEFAULT_PLAYLIST_WEIGHT",
    "add_sound_variation",
    "allocate_wwise_id",
    "bank_ids",
    "fnv1_32",
    "remove_sound_variation",
]
