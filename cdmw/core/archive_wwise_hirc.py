"""Decodes the HIRC object graph of a Wwise sound bank (bank version 150).

A bank's HIRC chunk is a count followed by `u8 type, u32 size, u32 id, body`
objects. The body layouts follow wwiser's parser
(https://github.com/bnnm/wwiser, `wparser.py`), restricted to the version every
shipped Crimson Desert bank uses. Each object is read with bounds checks and is
reported as `parsed` only when its body is consumed to the exact byte; a type
this reader does not model keeps its framing as `framed`, and a modelled type
that does not end on its declared size is a `mismatch`, never a guess.

Alongside the decoded values the reader records where each editable value lives
in the bank, so a writer can change a property in place without re-serialising
anything around it. Those locations are only ever produced for objects that
parsed exactly.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from cdmw.core.archive_wwise_bank import HIRC_OBJECT_TYPES, is_sound_bank, read_bank_chunks

#: The only bank version this reader models; every shipped bank uses it.
SUPPORTED_BANK_VERSION = 150

KIND_STATE = 1
KIND_SOUND = 2
KIND_ACTION = 3
KIND_EVENT = 4
KIND_RANDOM_SEQUENCE = 5
KIND_SWITCH = 6
KIND_ACTOR_MIXER = 7
KIND_LAYER = 9
KIND_MUSIC_TRACK = 11

PARSED = "parsed"
FRAMED = "framed"
MISMATCH = "mismatch"

#: AkPropID for bank version 150 (wwiser `AkPropID_150`).
PROPERTY_NAMES = {
    0x00: "Volume", 0x01: "Pitch", 0x02: "LPF", 0x03: "HPF", 0x04: "BusVolume", 0x05: "MakeUpGain",
    0x06: "Priority", 0x07: "MuteRatio", 0x08: "UserAuxSendVolume0", 0x09: "UserAuxSendVolume1",
    0x0A: "UserAuxSendVolume2", 0x0B: "UserAuxSendVolume3", 0x0C: "GameAuxSendVolume",
    0x0D: "OutputBusVolume", 0x0E: "OutputBusHPF", 0x0F: "OutputBusLPF", 0x10: "UserAuxSendLPF0",
    0x11: "UserAuxSendLPF1", 0x12: "UserAuxSendLPF2", 0x13: "UserAuxSendLPF3", 0x14: "UserAuxSendHPF0",
    0x15: "UserAuxSendHPF1", 0x16: "UserAuxSendHPF2", 0x17: "UserAuxSendHPF3", 0x18: "GameAuxSendLPF",
    0x19: "GameAuxSendHPF", 0x1A: "ReflectionBusVolume", 0x1B: "HDRBusThreshold", 0x1C: "HDRBusRatio",
    0x1D: "HDRBusReleaseTime", 0x1E: "HDRActiveRange", 0x1F: "MidiTransposition", 0x20: "MidiVelocityOffset",
    0x21: "PlaybackSpeed", 0x22: "InitialDelay", 0x23: "Positioning_Pan_X_2D", 0x24: "Positioning_Pan_Y_2D",
    0x25: "Positioning_Pan_Z_2D", 0x26: "Positioning_Pan_X_3D", 0x27: "Positioning_Pan_Y_3D",
    0x28: "Positioning_Pan_Z_3D", 0x29: "Positioning_CenterPercent", 0x2A: "Positioning_TypeBlend",
    0x2B: "Positioning_EnableAttenuation", 0x2C: "Positioning_Cone_AttenuationOnOff",
    0x2D: "Positioning_Cone_Attenuation", 0x2E: "Positioning_Cone_LPF", 0x2F: "Positioning_Cone_HPF",
    0x30: "BypassFX", 0x31: "BypassAllFX", 0x32: "Available_0", 0x33: "Available_1", 0x34: "Available_2",
    0x35: "MaxNumInstances", 0x36: "BypassAllMetadata", 0x37: "PlayMechanismSpecialTransitionsValue",
    0x38: "PriorityDistanceOffset", 0x39: "DelayTime", 0x3A: "TransitionTime", 0x3B: "Probability",
    0x3C: "DialogueMode", 0x3D: "HDRBusGameParam", 0x3E: "HDRBusGameParamMin", 0x3F: "HDRBusGameParamMax",
    0x40: "LoopStart", 0x41: "LoopEnd", 0x42: "TrimInTime", 0x43: "TrimOutTime", 0x44: "FadeInTime",
    0x45: "FadeOutTime", 0x46: "FadeInCurve", 0x47: "FadeOutCurve", 0x48: "LoopCrossfadeDuration",
    0x49: "CrossfadeUpCurve", 0x4A: "CrossfadeDownCurve", 0x4B: "MidiTrackingRootNote",
    0x4C: "MidiPlayOnNoteType", 0x4D: "MidiKeyRangeMin", 0x4E: "MidiKeyRangeMax",
    0x4F: "MidiVelocityRangeMin", 0x50: "MidiVelocityRangeMax", 0x51: "MidiChannelMask",
    0x52: "MidiTempoSource", 0x53: "MidiTargetNode", 0x54: "Loop", 0x55: "AttenuationID",
}

#: Action type families by high byte (wwiser `CAkAction__Create`, v150 table).
ACTION_FAMILIES = {
    0x01: "Stop", 0x02: "Pause", 0x03: "Resume", 0x04: "Play", 0x05: "PlayAndContinue", 0x06: "Mute",
    0x07: "Unmute", 0x08: "SetPitch", 0x09: "ResetPitch", 0x0A: "SetVolume", 0x0B: "ResetVolume",
    0x0C: "SetBusVolume", 0x0D: "ResetBusVolume", 0x0E: "SetLPF", 0x0F: "ResetLPF", 0x10: "UseState",
    0x11: "UnuseState", 0x12: "SetState", 0x13: "SetGameParameter", 0x14: "ResetGameParameter",
    0x19: "SetSwitch", 0x1A: "Break", 0x1B: "Trigger", 0x1C: "Break", 0x1D: "Trigger", 0x1E: "Seek",
    0x1F: "Release", 0x20: "SetHPF", 0x21: "PlayEvent", 0x22: "ResetPlaylist", 0x30: "ResetHPF",
    0x31: "SetFX", 0x32: "ResetSetFX", 0x33: "BypassFX", 0x34: "BypassFX", 0x35: "BypassFX",
    0x36: "BypassFX", 0x37: "BypassFX",
}

_ACTIVE = {0x01, 0x02, 0x03, 0x22}
_PLAY = {0x04, 0x05}
_SET_VALUE = {0x06, 0x07}
_SET_PROPERTY = {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x20, 0x30}
_SET_GAME_PARAMETER = {0x13, 0x14}
_NO_PARAMS = {0x10, 0x11, 0x1A, 0x1B, 0x1C, 0x1D, 0x1F, 0x21}
_PAUSE_OR_RESUME_OR_STOP = {0x01, 0x02, 0x03}
_BYPASS_FX = {0x33, 0x34, 0x35, 0x36, 0x37}
_SET_FX = {0x31, 0x32}

_MAXIMUM_OBJECTS = 200_000
_MAXIMUM_LIST = 1 << 20


class _HircError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class HircValue:
    """One value the bank stores in a fixed-size slot, and where that slot is.

    `offset` is absolute in the bank. `encoding` is the struct format of the
    slot (`<f`, `<I`, `<i`, `<H`), so a writer replaces exactly those bytes.
    """

    name: str
    offset: int
    encoding: str
    value: float | int


@dataclass(slots=True, frozen=True)
class HircProperty:
    """An AkPropBundle entry: a 4-byte union whose meaning depends on the id."""

    prop_id: int
    offset: int
    raw: int

    @property
    def name(self) -> str:
        return PROPERTY_NAMES.get(self.prop_id, f"prop 0x{self.prop_id:02X}")

    @property
    def as_float(self) -> float:
        return struct.unpack("<f", struct.pack("<I", self.raw))[0]


@dataclass(slots=True, frozen=True)
class HircRangedProperty:
    """A randomizer range: the value is offset by a random amount in [min, max]."""

    prop_id: int
    min_offset: int
    min_raw: int
    max_offset: int
    max_raw: int

    @property
    def name(self) -> str:
        return PROPERTY_NAMES.get(self.prop_id, f"prop 0x{self.prop_id:02X}")


@dataclass(slots=True, frozen=True)
class HircSource:
    """A Sound's media reference (AkBankSourceData)."""

    plugin_id: int
    plugin_offset: int
    stream_type: int
    source_id: int
    in_memory_size: int
    in_memory_size_offset: int
    source_bits: int


@dataclass(slots=True, frozen=True)
class HircPlaylistItem:
    object_id: int
    weight: int
    weight_offset: int


@dataclass(slots=True)
class HircNode:
    """One HIRC object. Fields that do not apply to its type stay empty."""

    kind: int
    object_id: int
    offset: int
    """Where the object's type byte sits in the bank."""

    size: int
    """The declared size of the object after its 5-byte type and size header."""

    status: str = FRAMED
    mismatch_reason: str = ""
    parent_id: int = 0
    bus_id: int = 0
    children: Tuple[int, ...] = ()
    properties: Tuple[HircProperty, ...] = ()
    ranged_properties: Tuple[HircRangedProperty, ...] = ()
    sources: Tuple[HircSource, ...] = ()
    """A Sound's one media reference, or every source a music track plays."""

    action_type: int = 0
    target_id: int = 0
    actions: Tuple[int, ...] = ()
    playlist: Tuple[HircPlaylistItem, ...] = ()
    values: Tuple[HircValue, ...] = ()
    """Further fixed-size values, such as loop counts and action targets."""

    details: Dict[str, int] = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.offset + 5 + self.size

    @property
    def source(self) -> Optional[HircSource]:
        return self.sources[0] if self.kind == KIND_SOUND and self.sources else None

    @property
    def action_name(self) -> str:
        return ACTION_FAMILIES.get(self.action_type >> 8, f"action 0x{self.action_type:04X}")

    def property(self, prop_id: int) -> Optional[HircProperty]:
        for item in self.properties:
            if item.prop_id == prop_id:
                return item
        return None

    def value(self, name: str) -> Optional[HircValue]:
        for item in self.values:
            if item.name == name:
                return item
        return None


@dataclass(slots=True, frozen=True)
class HircGraph:
    version: int
    chunk_offset: int
    """Where the HIRC payload (its object count) starts; -1 when absent."""

    declared_count: int
    nodes: Tuple[HircNode, ...]
    framing_complete: bool
    """True when every declared object was framed and the chunk ended on the last one."""

    def by_id(self) -> Dict[int, HircNode]:
        return {node.object_id: node for node in self.nodes}

    def sounds_for_source(self, source_id: int) -> Tuple[HircNode, ...]:
        """Sounds and music tracks that play this media id."""

        return tuple(node for node in self.nodes if any(item.source_id == source_id for item in node.sources))


class _Reader:
    __slots__ = ("data", "pos", "end", "values", "properties", "ranged")

    def __init__(self, data: bytes, start: int, end: int) -> None:
        self.data = data
        self.pos = start
        self.end = end
        self.values: List[HircValue] = []
        self.properties: List[HircProperty] = []
        self.ranged: List[HircRangedProperty] = []

    def _take(self, size: int) -> int:
        start = self.pos
        if size < 0 or start + size > self.end:
            raise _HircError(f"read of {size} bytes at {start} passes the object end {self.end}")
        self.pos = start + size
        return start

    def u8(self) -> int:
        return self.data[self._take(1)]

    def u16(self) -> int:
        return struct.unpack_from("<H", self.data, self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.data, self._take(4))[0]

    def s32(self) -> int:
        return struct.unpack_from("<i", self.data, self._take(4))[0]

    def f32(self) -> float:
        return struct.unpack_from("<f", self.data, self._take(4))[0]

    def skip(self, size: int) -> None:
        self._take(size)

    def var(self) -> int:
        """Wwise's variable-size integer: 7 bits per byte, most significant first."""

        current = self.u8()
        value = current & 0x7F
        for _ in range(4):
            if not current & 0x80:
                return value
            current = self.u8()
            value = (value << 7) | (current & 0x7F)
        if current & 0x80:
            raise _HircError("variable-size integer longer than five bytes")
        return value

    def count(self, value: int, item_size: int) -> int:
        if value > _MAXIMUM_LIST or self.pos + value * item_size > self.end:
            raise _HircError(f"list of {value} items of {item_size} bytes passes the object end")
        return value

    def record(self, name: str, encoding: str) -> float | int:
        size = struct.calcsize(encoding)
        offset = self._take(size)
        value = struct.unpack_from(encoding, self.data, offset)[0]
        self.values.append(HircValue(name, offset, encoding, value))
        return value


def _prop_bundle(reader: _Reader) -> None:
    count = reader.count(reader.u8(), 5)
    ids = [reader.u8() for _ in range(count)]
    for prop_id in ids:
        offset = reader._take(4)
        reader.properties.append(HircProperty(prop_id, offset, struct.unpack_from("<I", reader.data, offset)[0]))


def _ranged_bundle(reader: _Reader) -> None:
    count = reader.count(reader.u8(), 9)
    ids = [reader.u8() for _ in range(count)]
    for prop_id in ids:
        low = reader._take(4)
        high = reader._take(4)
        reader.ranged.append(
            HircRangedProperty(
                prop_id,
                low,
                struct.unpack_from("<I", reader.data, low)[0],
                high,
                struct.unpack_from("<I", reader.data, high)[0],
            )
        )


def _rtpc_curves(reader: _Reader) -> None:
    for _ in range(reader.count(reader.u16(), 12)):
        reader.skip(4 + 1 + 1)  # RTPC id, type, accumulation
        reader.var()  # parameter id
        reader.skip(4 + 1)  # curve id, scaling
        reader.skip(12 * reader.count(reader.u16(), 12))


def _state_chunk(reader: _Reader) -> None:
    for _ in range(reader.count(reader.var(), 3)):
        reader.var()
        reader.skip(2)  # accumulation type, in dB
    for _ in range(reader.count(reader.var(), 6)):
        reader.skip(4 + 1)  # state group id, sync type
        for _ in range(reader.count(reader.var(), 6)):
            reader.skip(4)  # state id
            count = reader.count(reader.u16(), 6)
            reader.skip(count * 6)


def _positioning(reader: _Reader) -> None:
    bits = reader.u8()
    if not bits & 1 or not (bits >> 1) & 1:
        return
    reader.skip(1)  # uBits3d
    if (bits >> 5) & 3 == 0:
        return
    reader.skip(1 + 4)  # path mode, transition time
    reader.skip(16 * reader.count(reader.u32(), 16))
    items = reader.count(reader.u32(), 8 + 12)
    reader.skip(items * 8 + items * 12)


def _node_base(reader: _Reader, node: HircNode) -> None:
    reader.skip(1)  # override parent FX
    effects = reader.u8()
    if effects:
        reader.skip(1 + reader.count(effects, 6) * 6)
    reader.skip(1)  # override parent metadata
    reader.skip(reader.count(reader.u8(), 6) * 6)
    node.bus_id = reader.u32()
    node.parent_id = reader.u32()
    reader.skip(1)  # priority and MIDI bits
    _prop_bundle(reader)
    _ranged_bundle(reader)
    _positioning(reader)
    aux = reader.u8()
    if (aux >> 3) & 1:
        reader.skip(16)
    reader.skip(4)  # reflections aux bus
    reader.skip(6)  # advanced settings
    _state_chunk(reader)
    _rtpc_curves(reader)


def _children(reader: _Reader) -> Tuple[int, ...]:
    return tuple(reader.u32() for _ in range(reader.count(reader.u32(), 4)))


def _read_source(reader: _Reader) -> HircSource:
    plugin_offset = reader.pos
    plugin_id = reader.u32()
    stream_type = reader.u8()
    source_id = reader.u32()
    size_offset = reader.pos
    in_memory_size = reader.u32()
    bits = reader.u8()
    if plugin_id and plugin_id & 0xF == 2:
        reader.skip(reader.u32())
    return HircSource(plugin_id, plugin_offset, stream_type, source_id, in_memory_size, size_offset, bits)


def _except_list(reader: _Reader) -> None:
    reader.skip(5 * reader.count(reader.var(), 5))


def _read_action(reader: _Reader, node: HircNode) -> None:
    node.action_type = reader.u16()
    node.target_id = reader.u32()
    reader.skip(1)  # is bus
    _prop_bundle(reader)
    _ranged_bundle(reader)
    family = node.action_type >> 8
    if family in _ACTIVE:
        reader.skip(1)  # fade curve
        if family in _PAUSE_OR_RESUME_OR_STOP:
            reader.skip(1)
        _except_list(reader)
    elif family in _PLAY:
        reader.skip(1)  # fade curve
        node.details["bank_id"] = reader.u32()
        reader.skip(4)  # bank type
    elif family in _SET_VALUE:
        reader.skip(1)
        _except_list(reader)
    elif family in _SET_PROPERTY:
        reader.skip(1)  # fade curve
        node.details["value_meaning"] = reader.u8()
        reader.record("base", "<f")
        reader.record("min", "<f")
        reader.record("max", "<f")
        _except_list(reader)
    elif family in _SET_GAME_PARAMETER:
        reader.skip(1 + 1 + 1)  # fade curve, bypass transition, value meaning
        reader.record("base", "<f")
        reader.record("min", "<f")
        reader.record("max", "<f")
        _except_list(reader)
    elif family in (0x12, 0x19):
        node.details["group_id"] = reader.u32()
        node.details["state_id"] = reader.u32()
    elif family == 0x1E:
        reader.skip(1 + 12 + 1)
        _except_list(reader)
    elif family in _SET_FX:
        reader.skip(1 + 1 + 4 + 1)
        _except_list(reader)
    elif family in _BYPASS_FX:
        reader.skip(2)
        _except_list(reader)
    elif family not in _NO_PARAMS:
        raise _HircError(f"action type 0x{node.action_type:04X} is not modelled")


def _read_random_sequence(reader: _Reader, node: HircNode) -> None:
    _node_base(reader, node)
    reader.record("loop_count", "<H")
    reader.record("loop_mod_min", "<H")
    reader.record("loop_mod_max", "<H")
    reader.record("transition_time", "<f")
    reader.record("transition_time_mod_min", "<f")
    reader.record("transition_time_mod_max", "<f")
    reader.record("avoid_repeat_count", "<H")
    node.details["transition_mode"] = reader.u8()
    node.details["random_mode"] = reader.u8()
    node.details["mode"] = reader.u8()
    node.details["flags"] = reader.u8()
    node.children = _children(reader)
    items: List[HircPlaylistItem] = []
    for _ in range(reader.count(reader.u16(), 8)):
        object_id = reader.u32()
        offset = reader.pos
        items.append(HircPlaylistItem(object_id, reader.s32(), offset))
    node.playlist = tuple(items)


def _read_switch(reader: _Reader, node: HircNode) -> None:
    _node_base(reader, node)
    node.details["group_type"] = reader.u8()
    node.details["group_id"] = reader.u32()
    node.details["default_switch"] = reader.u32()
    reader.skip(1)
    node.children = _children(reader)
    for _ in range(reader.count(reader.u32(), 8)):
        reader.skip(4)
        reader.skip(4 * reader.count(reader.u32(), 4))
    reader.skip(14 * reader.count(reader.u32(), 14))


def _read_layer(reader: _Reader, node: HircNode) -> None:
    _node_base(reader, node)
    node.children = _children(reader)
    for _ in range(reader.count(reader.u32(), 4)):
        reader.skip(4)  # layer id
        _rtpc_curves(reader)
        reader.skip(4 + 1)  # crossfade RTPC id and type
        for _ in range(reader.count(reader.u32(), 8)):
            reader.skip(4)
            reader.skip(12 * reader.count(reader.u32(), 12))
    reader.skip(1)  # continuous validation


def _read_music_track(reader: _Reader, node: HircNode) -> None:
    node.details["flags"] = reader.u8()
    node.sources = tuple(_read_source(reader) for _ in range(reader.count(reader.u32(), 14)))
    items = reader.count(reader.u32(), 44)
    if items:
        reader.skip(items * 44)  # track, source, event, play-at, trims, duration
        reader.skip(4)  # sub-track count
    for _ in range(reader.count(reader.u32(), 12)):
        reader.skip(4 + 4)  # clip index, automation type
        reader.skip(12 * reader.count(reader.u32(), 12))
    _node_base(reader, node)
    track_type = reader.u8()
    node.details["track_type"] = track_type
    if track_type == 3:
        reader.skip(1 + 4 + 4)
        reader.skip(4 * reader.count(reader.u32(), 4))
        reader.skip(32)
    reader.skip(4)  # look-ahead time


def _read_state(reader: _Reader, node: HircNode) -> None:
    count = reader.count(reader.u16(), 6)
    reader.skip(count * 6)


def _parse_body(data: bytes, node: HircNode) -> None:
    reader = _Reader(data, node.offset + 9, node.end)
    kind = node.kind
    if kind == KIND_SOUND:
        node.sources = (_read_source(reader),)
        _node_base(reader, node)
    elif kind == KIND_MUSIC_TRACK:
        _read_music_track(reader, node)
    elif kind == KIND_ACTION:
        _read_action(reader, node)
    elif kind == KIND_EVENT:
        node.actions = tuple(reader.u32() for _ in range(reader.count(reader.var(), 4)))
    elif kind == KIND_RANDOM_SEQUENCE:
        _read_random_sequence(reader, node)
    elif kind == KIND_SWITCH:
        _read_switch(reader, node)
    elif kind == KIND_ACTOR_MIXER:
        _node_base(reader, node)
        node.children = _children(reader)
    elif kind == KIND_LAYER:
        _read_layer(reader, node)
    elif kind == KIND_STATE:
        _read_state(reader, node)
    else:
        return
    if reader.pos != node.end:
        raise _HircError(f"body ended at {reader.pos}, {node.end - reader.pos} bytes before the declared end")
    node.properties = tuple(reader.properties)
    node.ranged_properties = tuple(reader.ranged)
    node.values = tuple(reader.values)
    node.status = PARSED


def read_hirc_graph(data: bytes) -> HircGraph:
    """Decodes every HIRC object of a version-150 bank.

    Other versions and banks without HIRC return an empty, incomplete graph
    rather than a guess at a layout this reader has not checked.
    """

    empty = HircGraph(0, -1, 0, (), False)
    if not is_sound_bank(data):
        return empty
    chunks, _consumed = read_bank_chunks(data)
    version = 0
    for chunk in chunks:
        if chunk.identifier == "BKHD" and chunk.size >= 4:
            version = struct.unpack_from("<I", data, chunk.offset)[0]
    hirc = next((chunk for chunk in chunks if chunk.identifier == "HIRC" and chunk.size >= 4), None)
    if hirc is None:
        return HircGraph(version, -1, 0, (), version == SUPPORTED_BANK_VERSION)
    if version != SUPPORTED_BANK_VERSION:
        return HircGraph(version, hirc.offset, 0, (), False)
    end = hirc.offset + hirc.size
    declared = struct.unpack_from("<I", data, hirc.offset)[0]
    cursor = hirc.offset + 4
    nodes: List[HircNode] = []
    for _ in range(min(declared, _MAXIMUM_OBJECTS)):
        if cursor + 9 > end:
            break
        kind, size = struct.unpack_from("<BI", data, cursor)
        if size < 4 or cursor + 5 + size > end:
            break
        node = HircNode(kind, struct.unpack_from("<I", data, cursor + 5)[0], cursor, size)
        try:
            _parse_body(data, node)
        except (_HircError, struct.error) as error:
            node.status = MISMATCH
            node.mismatch_reason = str(error)
            node.properties = ()
            node.ranged_properties = ()
            node.values = ()
            node.sources = ()
        nodes.append(node)
        cursor = node.end
    return HircGraph(version, hirc.offset, declared, tuple(nodes), len(nodes) == declared and cursor == end)


def hirc_graph_preview_lines(data: bytes, *, limit: int = 12) -> List[str]:
    """Preview lines: decode coverage, events with their actions, containers, editable values."""

    graph = read_hirc_graph(data)
    if not graph.nodes:
        if graph.version and graph.version != SUPPORTED_BANK_VERSION:
            return [f"- HIRC objects are not decoded for bank version {graph.version} (only {SUPPORTED_BANK_VERSION})."]
        return []
    parsed = [node for node in graph.nodes if node.status == PARSED]
    lines = [f"- HIRC decode: {len(parsed):,} of {len(graph.nodes):,} objects decoded to the byte"]
    framed = sorted({node.kind for node in graph.nodes if node.status == FRAMED})
    if framed:
        names = ", ".join(HIRC_OBJECT_TYPES.get(kind, f"type {kind}") for kind in framed)
        lines.append(f"  framed only, layout not modelled: {names}")
    mismatched = [node for node in graph.nodes if node.status == MISMATCH]
    if mismatched:
        lines.append(f"  did not decode: {len(mismatched):,} (first: object {mismatched[0].object_id}, {mismatched[0].mismatch_reason})")
    nodes = graph.by_id()
    events = [node for node in parsed if node.kind == KIND_EVENT]
    if events:
        lines.append(f"- Events (first {min(limit, len(events))} of {len(events):,}):")
        for event in events[:limit]:
            steps = []
            for action_id in event.actions[:4]:
                action = nodes.get(action_id)
                if action is None or action.kind != KIND_ACTION:
                    steps.append(f"action {action_id} (not in this bank)")
                else:
                    steps.append(f"{action.action_name} -> {action.target_id}")
            more = f", +{len(event.actions) - 4}" if len(event.actions) > 4 else ""
            lines.append(f"  event {event.object_id}: " + ("; ".join(steps) or "no actions") + more)
    containers = [node for node in parsed if node.kind == KIND_RANDOM_SEQUENCE]
    if containers:
        lines.append(f"- Random/sequence containers (first {min(limit, len(containers))} of {len(containers):,}):")
        for node in containers[:limit]:
            mode = "sequence" if node.details.get("mode") == 1 else "random"
            loops = node.value("loop_count")
            loop_text = "loops forever" if loops is not None and loops.value == 0 else f"plays {loops.value if loops else 1}x"
            lines.append(f"  container {node.object_id}: {mode}, {loop_text}, {len(node.playlist)} in its playlist")
    edited = Counter(item.name for node in parsed for item in node.properties)
    if edited:
        common = ", ".join(f"{name} {count:,}" for name, count in edited.most_common(8))
        lines.append(f"- Stored properties: {common}")
    return lines


__all__ = [
    "ACTION_FAMILIES",
    "FRAMED",
    "HircGraph",
    "HircNode",
    "HircPlaylistItem",
    "HircProperty",
    "HircRangedProperty",
    "HircSource",
    "HircValue",
    "KIND_ACTION",
    "KIND_ACTOR_MIXER",
    "KIND_EVENT",
    "KIND_LAYER",
    "KIND_MUSIC_TRACK",
    "KIND_RANDOM_SEQUENCE",
    "KIND_SOUND",
    "KIND_STATE",
    "KIND_SWITCH",
    "MISMATCH",
    "PARSED",
    "PROPERTY_NAMES",
    "SUPPORTED_BANK_VERSION",
    "hirc_graph_preview_lines",
    "read_hirc_graph",
]
