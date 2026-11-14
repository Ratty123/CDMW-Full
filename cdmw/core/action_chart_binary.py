"""Reader and constrained writer for `.paac` action charts and the `.paacdesc` descriptor.

The layout follows the loader in CrimsonDesert.exe 1.0.0.3479 (game 2.04.03):
`ActionChartPackage` reads the file as one sequential stream and keeps pointers into
the buffer, so every record below is a flat struct and nothing stores a file offset.
Every read in the loader has a read-failure message naming the member it fills
("ActionChartPackage ... : <member>: %s"), which is where the section names come from.

    u32 animation_count
    animation_count x AnimationInfo
        0xA8 AnimationInfoData              +0x00 f32 start, +0x04 f32 end (seconds)
                                            +0x70 11 x (u16 offset, u16 count) arrays
                                            +0x9C u16 clip (table 1), +0xA2 u16 blend (table 5)
        11 arrays, widths 12 16 104 160 24 36 12 96 12 12 16, counts from the header
                                            (aiMoveSpeedInfo was 148 before game 2.05)
        u8 n; n x 20 frame event instance   f32 begin, f32 end, u32 dword offset into
                                            the frame event buffer, u32 sequence, u32 condition
    u32 n; n x 8,  u32 n; n x 4,  u32 n; n x 4
    10 x string table                       u16 count; count x (u8 len incl. NUL, bytes)
    f32 ActionSpeedRate, u32, u32, f32, u8 isEndBehaviorActionChart, u8 isNPCScheduleActionChart
    ShareValue                              string table, 10 x u16 counts (all zero shipped)
    CountInfo (10 bytes)                    u8 a, u8 sockets, u8 includes, u16 nodes, u16 n12
    a x u32, sockets x 40 (DefaultSocket), includes x u16 (sub-chart names, table 0),
    nodes x 0x120 (actionChart), n12 x 12
    conditionInstanceArray                  u32 n; n bytes, u32 m; m x u16
    branchInstanceArray                     u32 n; n x 0x38, u32 n; n x 8, u32 n; n x 32
    keyGuideInstanceArray                   u16 n; n x 0x1C, u32 n; n x 8
    _keyGuideFrameEventBuffer               u32 n; n bytes, u8 n; n x 20 instances
    _frameEventBuffer                       u32 n; n bytes
    _childFrameEventInstanceBuffer          u8 n; n x 20
    _contentsGroupTable                     u32 n; n bytes

Records refer to strings by table index, never by byte offset, and the string tables
come before every blob, so a string can change length by rewriting its table alone.
A node's animations are `[first, first + count)` (node +0x54 u32, +0xEE u16); across
the 558 shipped charts the nodes partition the animation list exactly. The loader
writes node +0x111 and branch32 +0x14 at load time, so their file values are scratch.
Frame-event buffers are dense runs of events with one size per kind
(`FRAME_EVENT_SIZES`), and frame-event instances share events by offset.

`commonactioninfo.paac` and `commonactioninfo_serialized.paac` go through different
loaders and are decoded to their sections; the serialized file's tail is a separate
reflection stream and stays an unexplained span.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable, Mapping, Optional, Sequence

ACTION_CHART_STRING_TABLES = (
    "names",
    "animations",
    "camera animations",
    "effects",
    "effect switches",
    "motion blending",
    "bones and sockets",
    "equipment types",
    "sequencers",
    "prefabs",
)
ANIMATION_TABLE = 1
BLEND_TABLE = 5
ANIMATION_HEADER_SIZE = 0xA8
NODE_SIZE = 0x120
FRAME_EVENT_INSTANCE_SIZE = 20
NO_INDEX = 0xFFFF
MAX_STRING_BYTES = 254

#: AnimationInfo arrays in stream order: member name and record width. The count of
#: array k is the byte at header +0x72 + 4k, the read the loader makes.
#: Game 2.05 (1.0.0.3663) widened `aiMoveSpeedInfoArray` from 0x94 to 0xA0 bytes: with it,
#: all 560 shipped charts decode; with the old width 99 fail (every chart with such a record).
ANIMATION_ARRAYS = (
    ("frameTag", 12),
    ("animationSpeedInfoArray", 16),
    ("moveSpeedInfoArray", 0x68),
    ("aiMoveSpeedInfoArray", 0xA0),
    ("verticalMoveSpeedInfoArray", 24),
    ("defenceInfoArray", 36),
    ("characterClimbTagInfoArray", 12),
    ("onHitEventInfoArray", 96),
    ("StumbleOnHitInfoArray", 12),
    ("aiReviseTurnInfoArray", 12),
    ("justTimeFrameTagInfo", 16),
)
#: The same arrays as games before 2.05 wrote them. Charts in mods made for those games
#: still use it, so a chart that does not decode in the current layout is read in this one.
ANIMATION_ARRAYS_2_04 = tuple(
    (name, 0x94 if name == "aiMoveSpeedInfoArray" else width) for name, width in ANIMATION_ARRAYS)
#: Layouts tried in order; the name ends up on `ActionChart.array_layout`.
_ARRAY_LAYOUTS = (("2.05", ANIMATION_ARRAYS), ("2.04", ANIMATION_ARRAYS_2_04))

#: Frame event kinds, indexed by the u16 at the start of each event. Read from the
#: client factory switch (185 cases) by the RTTI class each case constructs, minus
#: the `ClientFrameEvent` prefix. Kind numbers moved with the 2.04 update (the socket
#: event was 60 before it and is 62 now), so they are tied to this game version. Game 2.05
#: (1.0.0.3663) did not move them: Kliff's four weapon and riding charts kept per-kind
#: event counts identical across that update.
FRAME_EVENT_KINDS = (
    "Attack", "AttackThrow", "AttackCatch", "ReleaseCatch", "RemoteCatch", "UpdateCatch",
    "ReleaseRemoteCatch", "Projectile", "RemoveProjectile", "UseItem", "AIEvent", "Drop",
    "UpdateShareValue", "UpdateRandomShareValue", "CallMercenary", "CallMercenaryReservedSlot",
    "CallHyosi", "RegistMercenary", "Hide", "SpecialMode", "PushCharacterToInventory",
    "PushCharacterToEquipment", "DetectEvent", "GlobalStageSequencer", "ChangeEquipByQuickSlot",
    "ReflectProjectile", "DetachDockingGimmick", "ChangeDockingSocket", "GrowGimmick",
    "VaryFriendly", "PickUpItem", "DoInteraction", "RemoteCatchPullOutStart",
    "RemoteCatchPullOutSuccess", "RemoteCatchTransmutation", "SetCriminalAction",
    "UseSkillResourceStat", "SummonActor", "ReserveSummonAndRide", "ProjectileToNearActor",
    "FollowLearnTarget", "FollowLearnPlayer", "StealItem", "RewardFromCharacter",
    "CreateElementalArea", "SealToInventory", "SetPassableState", "SummonPortal", "Docking",
    "FeedFrom", "AttachDockingGimmick", "RemoteCatchPull", "GrowMercenaryByInteraction",
    "UseDispenserGimmick", "EquipItemFromGimmick", "CreatePlatformPortal",
    "UpdateItemChargeCount", "Effect", "Rotate", "EffectSwitch", "EffectSwitchControl", "Jump",
    "ModelAttachmentSocket", "Prefab", "ShowPart", "HidePart", "FaceAnimation", "SoundEvent",
    "VoiceSound", "KillSound", "CameraPreset", "GamePlayCameraEffect",
    "FollowTargetCameraEffect", "CameraAnimationEffect", "CameraPulse", "CameraShake",
    "CameraShakeSwitch", "CameraRotateSpeed", "RotateCamera", "AdditiveAnimation",
    "MaskAnimation", "SetGravity", "Blur", "SetPbdPreset", "SetRagdollPreset", "PhysicsBreak",
    "SetPartPhysicsMotionType", "SetAimRange", "MotionBlur", "WindVolume",
    "SplineClothGravity", "SplineClothPartStop", "RiderIK", "LookAt", "FootOffset",
    "QuickTimeEvent", "Vibrate", "VibrateSwitch", "PSTriggerEffect", "CameraShakeSine",
    "PlaySequencerConnectActor", "JointSpring", "GuideTargetIK", "LimbIK", "LaserAimIK",
    "SkeletalDynamicBlend", "ActivateJointSpring", "StretchJointSpring", "TransformShowPart",
    "CutMeshPartAll", "EaseAnimationSpeed", "ArrowAimIK", "ArmCompressor", "DrawGuideEffect",
    "DrawGuideEffectControl", "AimIK", "MoveBodyOffsetIK", "HoveringIK", "BoneAim",
    "MiniGameTrigger", "RopeSwingAnchorShot", "RemoteCatchDeliverEffect",
    "RemoteCatchEffectState", "RemoteCatchSeal", "EffectChangeMaterialParameter", "TimeScale",
    "ChangeMaterialParameter", "AttachReservedSlotItemMesh", "SnowboardParameter",
    "StickGimmick", "IK", "CharacterTriggerVolume", "SkidMark", "RemoteCatchFishingPull",
    "CameraLockOn", "ClothSimulation", "SlipParameter", "MoveImpact",
    "BlockCameraInputUntilNeutral", "GamePlayGauge", "TreePulling", "SendWarning", "UIEvent",
    "MagnetCharge", "UpdateGimmick", "UpdateMiniGame", "AiJumpTarget", "ChargeAimPosition",
    "StickToObject", "ConvergenceProjectile", "GimmickEventSwitch", "KeyframeMotion",
    "UpdateAimPosition", "PlayerBehaviorEnd", "GamePlayFade", "ProjectileChangeShot",
    "DeadEyeOption", "ChangeGlobalMaterialParameter", "SendDangerAlert", "AdditiveEffect",
    "HousingControl", "WaitTargetArea", "IllusionEffect", "CharacterMeshEffect",
    "ChangeFocusActor", "FindLiftable", "MakeBuoyancyHole", "Escape", "EnableInspect",
    "InspectTarget", "NakMessage", "SetVisualEquipItem", "None", "FrontTextureHigh",
    "ShowCatchSpawnTarget", "RootBoneIK", "CheckSpaceRayCast", "MotionBlendingParam",
    "ShowGaugeUi", "WindForce", "RemoteCatchPullSwitch", "MaterialParameterUpdateSwitch",
    "ShowAIDialog", "ChildFrameEventSwitch", "PostCharacterScale",
)
MODEL_ATTACHMENT_SOCKET_KIND = FRAME_EVENT_KINDS.index("ModelAttachmentSocket")
#: u16 kind, u16, u16, u16 flags, u16 (0xFFFF shipped), 2 bytes of padding.
FRAME_EVENT_HEADER_SIZE = 12

#: Bytes per event, header included, for every kind the shipped charts use. Each kind
#: has one size, and these sizes walk every frame-event and key-guide buffer of the
#: 558 charts to their last byte. A kind missing here has never been seen.
FRAME_EVENT_SIZES = {
    0: 16, 1: 16, 2: 16, 3: 16, 4: 108, 5: 44, 6: 16, 7: 308, 8: 16, 9: 44, 10: 84, 11: 264,
    12: 32, 13: 24, 14: 116, 15: 32, 17: 20, 18: 20, 19: 32, 20: 24, 21: 24, 22: 28, 23: 16,
    24: 12, 25: 244, 26: 24, 27: 16, 29: 20, 30: 16, 31: 12, 32: 16, 33: 16, 35: 24, 36: 16,
    37: 148, 38: 24, 39: 256, 40: 32, 41: 12, 42: 20, 43: 24, 44: 96, 45: 20, 46: 16, 47: 44,
    48: 56, 49: 20, 50: 28, 51: 48, 52: 12, 53: 56, 54: 24, 55: 56, 57: 360, 58: 64, 59: 368,
    61: 32, 62: 32, 63: 24, 64: 16, 65: 16, 66: 32, 67: 236, 68: 120, 69: 24, 70: 48, 71: 60,
    72: 40, 73: 16, 75: 60, 76: 76, 77: 20, 78: 28, 79: 40, 80: 32, 81: 20, 82: 72, 83: 16,
    84: 24, 85: 16, 87: 20, 89: 60, 91: 24, 92: 16, 93: 24, 94: 24, 95: 20, 96: 36, 97: 28,
    98: 28, 99: 68, 100: 20, 102: 24, 103: 52, 104: 36, 111: 16, 112: 20, 113: 588, 114: 340,
    115: 48, 116: 12, 117: 20, 118: 28, 121: 28, 122: 16, 123: 16, 124: 36, 125: 32, 126: 52,
    127: 24, 128: 44, 129: 36, 130: 24, 131: 216, 132: 36, 133: 40, 134: 16, 136: 44, 137: 32,
    138: 12, 139: 52, 140: 12, 141: 24, 144: 40, 145: 40, 146: 24, 147: 44, 148: 60, 149: 20,
    150: 28, 152: 68, 153: 12, 156: 188, 157: 20, 158: 12, 160: 16, 161: 56, 162: 84, 163: 76,
    164: 16, 165: 24, 166: 52, 167: 16, 168: 16, 170: 16, 171: 20, 173: 16, 174: 12, 176: 40,
    179: 24, 182: 20,
}

#: u16 string-table indices inside event payloads: kind -> ((role, byte offset, table), ...).
#: Each field indexes its table (or holds 0xFFFF) in every shipped event of its kind and
#: names plausible values there; the socket fields are also the placement studio's.
FRAME_EVENT_REFERENCES = {
    FRAME_EVENT_KINDS.index("ModelAttachmentSocket"): (("part", 20, 7), ("parent socket", 22, 6), ("child socket", 24, 6)),
    FRAME_EVENT_KINDS.index("Effect"): (("effect", 284, 3), ("bone", 290, 6)),
    FRAME_EVENT_KINDS.index("Prefab"): (("prefab", 12, 9), ("parent socket", 14, 6), ("child socket", 16, 6)),
    FRAME_EVENT_KINDS.index("ShowPart"): (("part", 12, 7),),
    FRAME_EVENT_KINDS.index("HidePart"): (("part", 12, 7),),
    FRAME_EVENT_KINDS.index("PlaySequencerConnectActor"): (("sequencer", 12, 8),),
}

LAYOUT_CHART = "chart"
LAYOUT_COMMON_ACTION_INFO = "commonactioninfo"
LAYOUT_COMMON_ACTION_INFO_SERIALIZED = "commonactioninfo_serialized"


class ActionChartError(ValueError):
    """The bytes do not follow the chart grammar, or an edit is outside the proven scope."""


@dataclass(frozen=True, slots=True)
class ChartSpan:
    """A run of bytes with the member it belongs to. Spans tile the file."""

    name: str
    offset: int
    size: int
    item_size: int = 0
    count: int = 0
    explained: bool = True


@dataclass(frozen=True, slots=True)
class StringTable:
    index: int
    role: str
    offset: int
    size: int
    raw: tuple[bytes, ...]

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(_text(item) for item in self.raw)

    def value(self, index: int) -> str:
        if index == NO_INDEX or not 0 <= index < len(self.raw):
            return ""
        return _text(self.raw[index])


@dataclass(frozen=True, slots=True)
class FrameEventRef:
    offset: int
    begin: float
    end: float
    dword_offset: int
    sequence: int
    condition: int


@dataclass(frozen=True, slots=True)
class ChartArray:
    name: str
    offset: int
    count: int
    width: int


@dataclass(frozen=True, slots=True)
class AnimationInfo:
    index: int
    offset: int
    start_time: float
    end_time: float
    clip_index: int
    blend_index: int
    arrays: tuple[ChartArray, ...]
    events: tuple[FrameEventRef, ...]

    def array(self, name: str) -> ChartArray:
        for item in self.arrays:
            if item.name == name:
                return item
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class ChartNode:
    index: int
    offset: int
    first_animation: int
    animation_count: int
    contents_group: int


@dataclass(frozen=True, slots=True)
class FrameEvent:
    """The fixed header of one event in a frame event buffer."""

    offset: int
    kind: int
    flags: int

    @property
    def kind_name(self) -> str:
        return FRAME_EVENT_KINDS[self.kind] if 0 <= self.kind < len(FRAME_EVENT_KINDS) else f"kind {self.kind}"


@dataclass(frozen=True, slots=True)
class ActionChart:
    layout: str
    size: int
    spans: tuple[ChartSpan, ...]
    tables: tuple[StringTable, ...] = ()
    animations: tuple[AnimationInfo, ...] = ()
    nodes: tuple[ChartNode, ...] = ()
    action_speed_rate: float = 1.0
    action_speed_rate_offset: int = -1
    end_behavior: bool = False
    npc_schedule: bool = False
    include_names: tuple[int, ...] = ()
    frame_event_buffer: Optional[ChartSpan] = None
    key_guide_event_buffer: Optional[ChartSpan] = None
    key_guide_events: tuple[FrameEventRef, ...] = ()
    child_events: tuple[FrameEventRef, ...] = ()
    counts: Mapping[str, int] = field(default_factory=dict)
    #: Which game's AnimationInfo array widths the chart was read with ("2.05" or "2.04").
    #: A chart with no aiMoveSpeedInfo record reads the same in both and reports "2.05".
    array_layout: str = "2.05"

    @property
    def explained_bytes(self) -> int:
        return sum(span.size for span in self.spans if span.explained)

    @property
    def unexplained_spans(self) -> tuple[ChartSpan, ...]:
        return tuple(span for span in self.spans if not span.explained)

    def table(self, index: int) -> StringTable:
        return self.tables[index]

    def clip_name(self, animation: AnimationInfo) -> str:
        return self.tables[ANIMATION_TABLE].value(animation.clip_index) if self.tables else ""

    def blend_name(self, animation: AnimationInfo) -> str:
        return self.tables[BLEND_TABLE].value(animation.blend_index) if self.tables else ""


def _text(raw: bytes) -> str:
    return raw[:-1].decode("utf-8", "replace") if raw.endswith(b"\0") else raw.decode("utf-8", "replace")


class _Stream:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.spans: list[ChartSpan] = []

    def take(self, size: int, name: str) -> bytes:
        if size < 0 or self.pos + size > len(self.data):
            raise ActionChartError(f"{name}: {size} bytes at offset {self.pos} run past the end ({len(self.data)} bytes)")
        start = self.pos
        self.pos += size
        return self.data[start:self.pos]

    def scalar(self, code: str, name: str):
        size = struct.calcsize("<" + code)
        start = self.pos
        value = struct.unpack("<" + code, self.take(size, name))[0]
        self.spans.append(ChartSpan(name, start, size))
        return value

    def records(self, count: int, width: int, name: str) -> int:
        start = self.pos
        self.take(count * width, name)
        if count * width:
            self.spans.append(ChartSpan(name, start, count * width, width, count))
        return start

    def counted(self, count_code: str, width: int, name: str) -> tuple[int, int]:
        count = self.scalar(count_code, name + " count")
        return self.records(count, width, name), count

    def strings(self, name: str, index: int = -1) -> StringTable:
        start = self.pos
        count = struct.unpack("<H", self.take(2, name))[0]
        raw = []
        for _ in range(count):
            length = self.take(1, name)[0]
            item = self.take(length, name)
            if not item or item[-1] != 0 or b"\0" in item[:-1]:
                raise ActionChartError(f"{name}: string at offset {self.pos - length} is not NUL-terminated")
            raw.append(item)
        self.spans.append(ChartSpan(name, start, self.pos - start, 0, count))
        role = ACTION_CHART_STRING_TABLES[index] if 0 <= index < len(ACTION_CHART_STRING_TABLES) else name
        return StringTable(index, role, start, self.pos - start, tuple(raw))

    def events(self, name: str) -> tuple[FrameEventRef, ...]:
        count = self.scalar("B", name + " count")
        start = self.records(count, FRAME_EVENT_INSTANCE_SIZE, name)
        refs = []
        for item in range(count):
            at = start + item * FRAME_EVENT_INSTANCE_SIZE
            begin, end, dword, sequence, condition = struct.unpack_from("<ffIII", self.data, at)
            refs.append(FrameEventRef(at, begin, end, dword, sequence, condition))
        return tuple(refs)


def _layout_for_path(virtual_path: str) -> str:
    name = PurePosixPath(str(virtual_path or "").replace("\\", "/")).name.lower()
    if name == "commonactioninfo_serialized.paac":
        return LAYOUT_COMMON_ACTION_INFO_SERIALIZED
    if name == "commonactioninfo.paac":
        return LAYOUT_COMMON_ACTION_INFO
    return LAYOUT_CHART


def action_chart_layout(virtual_path: str) -> str:
    """Which loader the game uses for a `.paac`, chosen by file name."""

    return _layout_for_path(virtual_path)


def decode_action_chart(data: bytes, *, virtual_path: str = "") -> ActionChart:
    """Decode a `.paac`. The file name picks the loader, as it does in the game."""

    data = bytes(data)
    layout = _layout_for_path(virtual_path)
    if layout == LAYOUT_COMMON_ACTION_INFO:
        return _decode_common_action_info(data)
    if layout == LAYOUT_COMMON_ACTION_INFO_SERIALIZED:
        return _decode_common_action_info_serialized(data)
    return _decode_chart(data)


def _decode_chart(data: bytes) -> ActionChart:
    """Read a chart in the current game's layout, else in the 2.04 one; report the current error."""

    first_error: Optional[ActionChartError] = None
    for name, arrays in _ARRAY_LAYOUTS:
        try:
            return _decode_chart_layout(data, arrays, name)
        except ActionChartError as error:
            first_error = first_error or error
    raise first_error


def _decode_chart_layout(data: bytes, animation_arrays, array_layout: str) -> ActionChart:
    stream = _Stream(data)
    animations = []
    animation_count = stream.scalar("I", "animation count")
    if animation_count > len(data) // ANIMATION_HEADER_SIZE:
        raise ActionChartError(f"animation count {animation_count} cannot fit in {len(data)} bytes")
    for index in range(animation_count):
        header_at = stream.records(1, ANIMATION_HEADER_SIZE, "AnimationInfoData")
        header = data[header_at:header_at + ANIMATION_HEADER_SIZE]
        arrays = []
        for slot, (name, width) in enumerate(animation_arrays):
            count = header[0x72 + 4 * slot]
            arrays.append(ChartArray(name, stream.records(count, width, name), count, width))
        events = stream.events("_frameEventInstanceBuffer")
        for sequence, ref in enumerate(events):
            if ref.sequence != sequence:
                raise ActionChartError(f"animation {index}: frame event {sequence} carries sequence {ref.sequence}")
        start, end = struct.unpack_from("<ff", header, 0)
        clip, = struct.unpack_from("<H", header, 0x9C)
        blend, = struct.unpack_from("<H", header, 0xA2)
        animations.append(AnimationInfo(index, header_at, start, end, clip, blend, tuple(arrays), events))
    stream.counted("I", 8, "u64 list")
    stream.counted("I", 4, "u32 list A")
    stream.counted("I", 4, "u32 list B")
    tables = tuple(stream.strings(f"string table {index}", index) for index in range(len(ACTION_CHART_STRING_TABLES)))
    speed_at = stream.pos
    speed = stream.scalar("f", "ActionSpeedRate")
    stream.scalar("I", "u32 hash A")
    stream.scalar("I", "u32 hash B")
    stream.scalar("f", "f32 rate B")
    end_behavior = stream.scalar("B", "isEndBehaviorActionChart")
    npc_schedule = stream.scalar("B", "isNPCScheduleActionChart")
    stream.strings("ShareValue string table")
    share_counts = struct.unpack("<10H", data[stream.pos:stream.pos + 20]) if stream.pos + 20 <= len(data) else ()
    stream.records(1, 20, "ShareValue CountInfo")
    if any(share_counts):
        raise ActionChartError(f"ShareValue sections {share_counts} are not decoded (every shipped chart has none)")
    count_info = stream.take(10, "CountInfo")
    stream.spans.append(ChartSpan("CountInfo", stream.pos - 10, 10))
    word_count, socket_count, include_count = count_info[0], count_info[2], count_info[4]
    node_count, list12_count = struct.unpack_from("<HH", count_info, 6)
    stream.records(word_count, 4, "u32 list (CountInfo)")
    stream.records(socket_count, 40, "DefaultSocket")
    include_at = stream.records(include_count, 2, "_includeActionChartNameStringTableIndices")
    include_names = struct.unpack_from(f"<{include_count}H", data, include_at) if include_count else ()
    node_at = stream.records(node_count, NODE_SIZE, "actionChart")
    stream.records(list12_count, 12, "actionChart list (12 bytes)")
    nodes = []
    for index in range(node_count):
        at = node_at + index * NODE_SIZE
        first, = struct.unpack_from("<I", data, at + 0x54)
        count, = struct.unpack_from("<H", data, at + 0xEE)
        group, = struct.unpack_from("<H", data, at + 0x112)
        if first + count > animation_count:
            raise ActionChartError(f"node {index} names animations {first}..{first + count} of {animation_count}")
        nodes.append(ChartNode(index, at, first, count, group))
    stream.counted("I", 1, "conditionInstanceArray bytecode")
    stream.counted("I", 2, "conditionInstanceArray indices")
    _, branch_count = stream.counted("I", 0x38, "branchInstanceArray")
    stream.counted("I", 8, "branchInstanceArray u64 list")
    stream.counted("I", 32, "branchInstanceArray records (32 bytes)")
    stream.counted("H", 0x1C, "keyGuideInstanceArray")
    stream.counted("I", 8, "keyGuideInstanceArray u64 list")
    key_at, key_size = stream.counted("I", 1, "_keyGuideFrameEventBuffer")
    key_events = stream.events("_keyGuideFrameEventInstanceBuffer")
    event_at, event_size = stream.counted("I", 1, "_frameEventBuffer")
    child_events = stream.events("_childFrameEventInstanceBuffer")
    stream.counted("I", 1, "_contentsGroupTable")
    if stream.pos != len(data):
        raise ActionChartError(f"{len(data) - stream.pos} bytes follow the last chart section")
    for animation in animations:
        for ref in animation.events:
            if ref.dword_offset * 4 + FRAME_EVENT_HEADER_SIZE > event_size:
                raise ActionChartError(f"animation {animation.index}: frame event offset {ref.dword_offset * 4} is outside the buffer")
    return ActionChart(
        layout=LAYOUT_CHART,
        size=len(data),
        spans=tuple(stream.spans),
        tables=tables,
        animations=tuple(animations),
        nodes=tuple(nodes),
        action_speed_rate=speed,
        action_speed_rate_offset=speed_at,
        end_behavior=bool(end_behavior),
        npc_schedule=bool(npc_schedule),
        include_names=tuple(include_names),
        frame_event_buffer=ChartSpan("_frameEventBuffer", event_at, event_size),
        key_guide_event_buffer=ChartSpan("_keyGuideFrameEventBuffer", key_at, key_size),
        key_guide_events=key_events,
        child_events=child_events,
        counts={
            "animations": animation_count,
            "nodes": node_count,
            "branches": branch_count,
            "frame events": sum(len(item.events) for item in animations),
            "sockets": socket_count,
            "included charts": include_count,
        },
        array_layout=array_layout,
    )


def _decode_common_action_info(data: bytes) -> ActionChart:
    stream = _Stream(data)
    for key_code, group in (("I", "action group A"), ("H", "action group B")):
        groups = stream.scalar("I", f"{group} count")
        for _ in range(groups):
            stream.scalar(key_code, f"{group} key")
            stream.counted("I", 0x58, f"{group} records")
    stream.counted("I", 1, "condition bytecode")
    stream.counted("I", 2, "condition indices")
    stream.counted("I", 1, "data buffer")
    table = stream.strings("string table", 0)
    if stream.pos != len(data):
        raise ActionChartError(f"{len(data) - stream.pos} bytes follow the last commonactioninfo section")
    return ActionChart(LAYOUT_COMMON_ACTION_INFO, len(data), tuple(stream.spans), tables=(table,))


def _decode_common_action_info_serialized(data: bytes) -> ActionChart:
    stream = _Stream(data)
    count = stream.scalar("I", "serialized entries")
    for _ in range(count):
        stream.counted("I", 1, "serialized entry")
        stream.records(1, 16, "serialized entry tail")
    stream.counted("I", 8, "u64 list")
    spans = list(stream.spans)
    if stream.pos < len(data):
        spans.append(ChartSpan("reflection stream (not decoded)", stream.pos, len(data) - stream.pos, explained=False))
    return ActionChart(LAYOUT_COMMON_ACTION_INFO_SERIALIZED, len(data), tuple(spans))


# --- frame events -------------------------------------------------------------------


def frame_event_at(chart: ActionChart, data: bytes, ref: FrameEventRef) -> FrameEvent:
    buffer = chart.frame_event_buffer
    if buffer is None:
        raise ActionChartError("this chart has no frame event buffer")
    at = buffer.offset + ref.dword_offset * 4
    kind, _, _, flags = struct.unpack_from("<4H", data, at)
    return FrameEvent(at, kind, flags)


@dataclass(frozen=True, slots=True)
class SocketEventPayload:
    """ModelAttachmentSocket payload: the 20 bytes after the 12-byte event header."""

    blend_time: float
    equipment_type: int
    part: int
    parent: int
    child: int
    mode: int
    all_parts: int
    disabled: int
    slot: int


def socket_event_payload(data: bytes, event: FrameEvent) -> SocketEventPayload:
    if event.kind != MODEL_ATTACHMENT_SOCKET_KIND:
        raise ActionChartError(f"event at {event.offset} is {event.kind_name}, not ModelAttachmentSocket")
    return SocketEventPayload(*struct.unpack_from("<fIHHHBBBb", data, event.offset + FRAME_EVENT_HEADER_SIZE))


def walk_frame_events(data: bytes, buffer: ChartSpan) -> tuple[FrameEvent, ...]:
    """Every event in a frame-event buffer, in order, using `FRAME_EVENT_SIZES`."""

    events = []
    at = 0
    while at < buffer.size:
        kind, _, _, flags = struct.unpack_from("<4H", data, buffer.offset + at)
        size = FRAME_EVENT_SIZES.get(kind)
        if size is None:
            raise ActionChartError(f"frame event kind {kind} at buffer offset {at} has no known size")
        events.append(FrameEvent(buffer.offset + at, kind, flags))
        at += size
    if at != buffer.size:
        raise ActionChartError(f"frame events run {at - buffer.size} bytes past their buffer")
    return tuple(events)


@dataclass(frozen=True, slots=True)
class EventReference:
    role: str
    table: int
    index: int
    value: str


def event_references(chart: ActionChart, data: bytes, event: FrameEvent) -> tuple[EventReference, ...]:
    """The string-table entries an event names, for the kinds in `FRAME_EVENT_REFERENCES`."""

    found = []
    for role, offset, table in FRAME_EVENT_REFERENCES.get(event.kind, ()):
        index, = struct.unpack_from("<H", data, event.offset + offset)
        found.append(EventReference(role, table, index, chart.tables[table].value(index)))
    return tuple(found)


def event_users(chart: ActionChart, ref: FrameEventRef) -> tuple[int, ...]:
    """Indices of the animations whose frame events point at the same event as `ref`."""

    return tuple(sorted({animation.index for animation in chart.animations
                         for other in animation.events if other.dword_offset == ref.dword_offset}))


# --- descriptor -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionPackage:
    name: str
    main_chart: str
    main_slot: str
    sub_packages: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ActionPackageDescription:
    strings: tuple[str, ...]
    packages: tuple[ActionPackage, ...]


def decode_action_package_description(data: bytes) -> ActionPackageDescription:
    """`.paacdesc`: string table, u32 packages, u32 subs, packages x 10, subs x 4.

    A package is (u16 sub count, u16 first sub, u16 main chart, u16 main slot, u16 name)
    and a sub-package (u16 chart, u16 slot name), all string indices.
    """

    stream = _Stream(bytes(data))
    table = stream.strings("string table")
    package_count = stream.scalar("I", "package count")
    sub_count = stream.scalar("I", "sub-package count")
    package_at = stream.records(package_count, 10, "packageDesctionDataArray")
    sub_at = stream.records(sub_count, 4, "subPackageInstanceArray")
    if stream.pos != len(stream.data):
        raise ActionChartError(f"{len(stream.data) - stream.pos} bytes follow the descriptor")

    def text(index: int) -> str:
        if index >= len(table.raw):
            raise ActionChartError(f"descriptor string index {index} is out of range")
        return _text(table.raw[index])

    subs = [struct.unpack_from("<2H", stream.data, sub_at + 4 * item) for item in range(sub_count)]
    packages = []
    for item in range(package_count):
        count, first, chart, slot, name = struct.unpack_from("<5H", stream.data, package_at + 10 * item)
        if first + count > sub_count:
            raise ActionChartError(f"package {item} names sub-packages {first}..{first + count} of {sub_count}")
        packages.append(ActionPackage(
            text(name), text(chart), text(slot),
            tuple((text(subs[index][1]), text(subs[index][0])) for index in range(first, first + count)),
        ))
    return ActionPackageDescription(table.values, tuple(packages))


# --- writes -------------------------------------------------------------------------


def _encode_strings(raw: Sequence[bytes]) -> bytes:
    if len(raw) > 0xFFFF:
        raise ActionChartError("a string table holds at most 65,535 strings")
    out = bytearray(struct.pack("<H", len(raw)))
    for item in raw:
        out.append(len(item))
        out += item
    return bytes(out)


def _encode_value(value: str) -> bytes:
    text = str(value)
    if not text or not all(" " <= char <= "~" for char in text):
        raise ActionChartError(f"chart strings must be printable ASCII and not empty: {value!r}")
    encoded = text.encode("ascii") + b"\0"
    if len(encoded) > MAX_STRING_BYTES + 1:
        raise ActionChartError(f"chart strings hold at most {MAX_STRING_BYTES} characters: {value!r}")
    return encoded


def _require_chart(data: bytes, virtual_path: str = "") -> ActionChart:
    if _layout_for_path(virtual_path) != LAYOUT_CHART:
        raise ActionChartError("only standard action charts can be edited, not the commonactioninfo tables")
    return _decode_chart(bytes(data))


def _rewrite_table(data: bytes, chart: ActionChart, table: int, raw: Sequence[bytes]) -> bytes:
    """Splice a rebuilt string table in and prove nothing else changed but its position."""

    source = chart.tables[table]
    rebuilt = _encode_strings(raw)
    start, end = source.offset, source.offset + source.size
    patched = data[:start] + rebuilt + data[end:]
    after = _decode_chart(patched)
    if patched[:start] != data[:start] or patched[start + len(rebuilt):] != data[end:]:
        raise ActionChartError("bytes outside the string table changed")
    if after.tables[table].raw != tuple(raw):
        raise ActionChartError("the rebuilt string table does not read back")
    before_shape = [(span.name, span.size) for span in chart.spans if span.offset != start]
    after_shape = [(span.name, span.size) for span in after.spans if span.offset != start]
    if before_shape != after_shape:
        raise ActionChartError("the chart's sections changed shape after the edit")
    return patched


def replace_chart_strings(data: bytes, table: int, replacements: Mapping[int, str], *, virtual_path: str = "") -> bytes:
    """Rewrite entries of one string table at any length.

    The table is rebuilt and spliced in; every other byte moves as one block. The
    result must decode with the same sections, and every byte outside the table must
    match the original, or the edit is refused. A rewritten entry changes every
    record that names it; `set_animation_resources` and `apply_event_edits` change one.
    """

    data = bytes(data)
    chart = _require_chart(data, virtual_path)
    if not 0 <= table < len(chart.tables):
        raise ActionChartError(f"string table {table} does not exist")
    raw = list(chart.tables[table].raw)
    for index, value in replacements.items():
        if not 0 <= index < len(raw):
            raise ActionChartError(f"string table {table} has no entry {index}")
        raw[index] = _encode_value(value)
    return _rewrite_table(data, chart, table, raw)


def _string_index(data: bytes, chart: ActionChart, table: int, value: str) -> tuple[bytes, ActionChart, int]:
    """The index of `value` in `table`, appended at the end when the table lacks it.

    Appending leaves every existing index where it was, so no other record moves.
    An empty value means "none" (0xFFFF).
    """

    if value == "":
        return data, chart, NO_INDEX
    encoded = _encode_value(value)
    raw = chart.tables[table].raw
    if encoded in raw:
        return data, chart, raw.index(encoded)
    if len(raw) >= NO_INDEX:
        raise ActionChartError(f"string table {table} is full")
    patched = _rewrite_table(data, chart, table, list(raw) + [encoded])
    return patched, _decode_chart(patched), len(raw)


def _patch_fields(data: bytes, chart: ActionChart, fields: Sequence[tuple[int, str, object]]) -> bytes:
    """Write fixed-size values in place and prove only those bytes changed."""

    buffer = bytearray(data)
    allowed = bytearray(len(data))
    for at, code, value in fields:
        size = struct.calcsize("<" + code)
        struct.pack_into("<" + code, buffer, at, value)
        allowed[at:at + size] = b"\1" * size
    patched = bytes(buffer)
    for index, (left, right) in enumerate(zip(data, patched)):
        if left != right and not allowed[index]:
            raise ActionChartError(f"byte {index} changed outside the edited fields")
    after = _decode_chart(patched)
    if [(span.name, span.offset, span.size) for span in after.spans] != [(span.name, span.offset, span.size) for span in chart.spans]:
        raise ActionChartError("the chart's sections changed after a field edit")
    return patched


def set_animation_resources(data: bytes, animation: int, *, clip: Optional[str] = None, blend: Optional[str] = None,
                            virtual_path: str = "") -> bytes:
    """Point one animation at another clip and/or blend space; other animations keep theirs.

    A path the chart does not hold yet is appended to its table. `blend=""` clears the
    blend space (0xFFFF, as most shipped animations have). The header carries the clip
    index twice (+0x9C and +0x9E, equal in every shipped animation); both are written.
    """

    data = bytes(data)
    chart = _require_chart(data, virtual_path)
    if not 0 <= animation < len(chart.animations):
        raise ActionChartError(f"animation {animation} does not exist")
    fields: list[tuple[int, str, object]] = []
    if clip is not None:
        if clip == "":
            raise ActionChartError("an animation needs a clip")
        data, chart, index = _string_index(data, chart, ANIMATION_TABLE, clip)
        at = chart.animations[animation].offset
        fields += [(at + 0x9C, "H", index), (at + 0x9E, "H", index)]
    if blend is not None:
        data, chart, index = _string_index(data, chart, BLEND_TABLE, blend)
        fields.append((chart.animations[animation].offset + 0xA2, "H", index))
    return _patch_fields(data, chart, fields) if fields else data


#: Socket event payload fields that are not string references: name -> (offset, code).
_SOCKET_VALUE_FIELDS = {"mode": (26, "B"), "blend time": (12, "f")}


@dataclass(frozen=True, slots=True)
class EventEdit:
    """Set one field of the event an animation's frame event points at.

    `field` is a reference role from `FRAME_EVENT_REFERENCES` (value: a string, "" for
    none) or, on ModelAttachmentSocket events, "mode" (0 In, 1 Out, 2 explicit sockets)
    or "blend time" (seconds).
    """

    animation: int
    event: int
    field: str
    value: object


def event_edit_fields(kind: int) -> tuple[str, ...]:
    roles = tuple(role for role, _offset, _table in FRAME_EVENT_REFERENCES.get(kind, ()))
    return roles + (tuple(_SOCKET_VALUE_FIELDS) if kind == MODEL_ATTACHMENT_SOCKET_KIND else ())


def _instances(chart: ActionChart, dword: int) -> int:
    return sum(1 for animation in chart.animations for ref in animation.events if ref.dword_offset == dword) + sum(
        1 for ref in chart.child_events if ref.dword_offset == dword)


def _copy_event(data: bytes, chart: ActionChart, animation: int, event: int) -> tuple[bytes, ActionChart]:
    """Give one animation its own copy of a shared event, appended to the buffer."""

    buffer = chart.frame_event_buffer
    ref = chart.animations[animation].events[event]
    source = frame_event_at(chart, data, ref)
    size = FRAME_EVENT_SIZES.get(source.kind)
    if size is None:
        raise ActionChartError(f"{source.kind_name} events have no known size, so one cannot be copied")
    walk_frame_events(data, buffer)
    end = buffer.offset + buffer.size
    patched = bytearray(data[:end] + data[source.offset:source.offset + size] + data[end:])
    struct.pack_into("<I", patched, buffer.offset - 4, buffer.size + size)
    struct.pack_into("<I", patched, ref.offset + 8, buffer.size // 4)
    patched = bytes(patched)
    changed = set(range(buffer.offset - 4, buffer.offset)) | set(range(ref.offset + 8, ref.offset + 12))
    if any(patched[index] != data[index] for index in range(end) if index not in changed) or patched[end + size:] != data[end:]:
        raise ActionChartError("copying the event changed other bytes")
    after = _decode_chart(patched)
    walk_frame_events(patched, after.frame_event_buffer)
    return patched, after


def apply_event_edits(data: bytes, edits: Iterable[EventEdit], *, only_this_animation: bool = True,
                      virtual_path: str = "") -> bytes:
    """Edit event payloads in place.

    Events are shared between animations (816,918 frame events point at 71,553 events
    in the shipped charts), so by default an edited event that other frame events also
    use is first copied for this animation alone. With `only_this_animation=False`
    every user of the event sees the change.
    """

    data = bytes(data)
    chart = _require_chart(data, virtual_path)
    for edit in edits:
        if not 0 <= edit.animation < len(chart.animations):
            raise ActionChartError(f"animation {edit.animation} does not exist")
        animation = chart.animations[edit.animation]
        if not 0 <= edit.event < len(animation.events):
            raise ActionChartError(f"animation {edit.animation} has no frame event {edit.event}")
        event = frame_event_at(chart, data, animation.events[edit.event])
        roles = {role: (offset, table) for role, offset, table in FRAME_EVENT_REFERENCES.get(event.kind, ())}
        if edit.field in roles:
            if not isinstance(edit.value, str):
                raise ActionChartError(f"{edit.field} takes a name")
            offset, table = roles[edit.field]
            data, chart, value = _string_index(data, chart, table, edit.value)
            code = "H"
        elif event.kind == MODEL_ATTACHMENT_SOCKET_KIND and edit.field in _SOCKET_VALUE_FIELDS:
            offset, code = _SOCKET_VALUE_FIELDS[edit.field]
            value = edit.value
            if edit.field == "mode" and value not in (0, 1, 2):
                raise ActionChartError("socket mode must be 0 (In), 1 (Out) or 2 (explicit sockets)")
            if edit.field == "blend time" and not (
                    isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 60):
                raise ActionChartError("socket blend time must be between 0 and 60 seconds")
        else:
            raise ActionChartError(f"{event.kind_name} events have no editable field {edit.field!r}")
        ref = chart.animations[edit.animation].events[edit.event]
        if only_this_animation and _instances(chart, ref.dword_offset) > 1:
            data, chart = _copy_event(data, chart, edit.animation, edit.event)
            ref = chart.animations[edit.animation].events[edit.event]
        at = frame_event_at(chart, data, ref).offset
        data = _patch_fields(data, chart, [(at + offset, code, value)])
        chart = _decode_chart(data)
    return data


def retarget_chart_string(data: bytes, table: int, old: str, new: str, *, virtual_path: str = "") -> tuple[bytes, int]:
    """Replace every entry of `table` equal to `old` with `new`. Returns (bytes, count)."""

    chart = _require_chart(data, virtual_path)
    if not 0 <= table < len(chart.tables):
        raise ActionChartError(f"string table {table} does not exist")
    hits = {index: new for index, value in enumerate(chart.tables[table].values) if value == old}
    if not hits:
        raise ActionChartError(f"string table {table} ({chart.tables[table].role}) has no entry {old!r}")
    return replace_chart_strings(data, table, hits, virtual_path=virtual_path), len(hits)


def retarget_animation(data: bytes, old: str, new: str, *, virtual_path: str = "") -> tuple[bytes, int]:
    """Point every use of clip `old` at clip `new`; paths are as the chart stores them."""

    return retarget_chart_string(data, ANIMATION_TABLE, old, new, virtual_path=virtual_path)


#: Values that may be edited in place: field -> (record, byte offset, kind).
#: Times are seconds; the start/end pair of AnimationInfoData matches the clip's
#: `.paa` duration on every sampled clip, and the other pairs share that shape.
EDITABLE_CHART_FIELDS = {
    "chart.action_speed_rate": ("chart", 0, "rate"),
    "animation.start_time": ("animation", 0x00, "time"),
    "animation.end_time": ("animation", 0x04, "time"),
    "speed.start_time": ("animationSpeedInfoArray", 0x00, "time"),
    "speed.end_time": ("animationSpeedInfoArray", 0x04, "time"),
    "speed.rate": ("animationSpeedInfoArray", 0x08, "rate"),
    "frame_tag.start_time": ("frameTag", 0x00, "time"),
    "frame_tag.end_time": ("frameTag", 0x04, "time"),
    "just_time.start_time": ("justTimeFrameTagInfo", 0x00, "time"),
    "just_time.end_time": ("justTimeFrameTagInfo", 0x04, "time"),
    "event.begin": ("event", 0x00, "time"),
    "event.end": ("event", 0x04, "event_end"),
}
_PAIRS = {
    "animation": (0x00, 0x04),
    "animationSpeedInfoArray": (0x00, 0x04),
    "frameTag": (0x00, 0x04),
    "justTimeFrameTagInfo": (0x00, 0x04),
}


@dataclass(frozen=True, slots=True)
class ChartValueEdit:
    field: str
    value: float
    animation: int = 0
    item: int = 0


def _edit_offset(chart: ActionChart, edit: ChartValueEdit) -> tuple[int, str, int]:
    if edit.field not in EDITABLE_CHART_FIELDS:
        raise ActionChartError(f"{edit.field!r} is not an editable chart field")
    record, offset, kind = EDITABLE_CHART_FIELDS[edit.field]
    if record == "chart":
        return chart.action_speed_rate_offset, kind, -1
    if not 0 <= edit.animation < len(chart.animations):
        raise ActionChartError(f"animation {edit.animation} does not exist")
    animation = chart.animations[edit.animation]
    if record == "animation":
        return animation.offset + offset, kind, animation.offset
    if record == "event":
        if not 0 <= edit.item < len(animation.events):
            raise ActionChartError(f"animation {edit.animation} has no frame event {edit.item}")
        return animation.events[edit.item].offset + offset, kind, animation.events[edit.item].offset
    array = animation.array(record)
    if not 0 <= edit.item < array.count:
        raise ActionChartError(f"animation {edit.animation} has no {record} entry {edit.item}")
    base = array.offset + edit.item * array.width
    return base + offset, kind, base


def chart_value_offset(chart: ActionChart, edit: ChartValueEdit) -> int:
    """Where the f32 an edit would write lives; raises as the writer does for a missing target."""

    return _edit_offset(chart, edit)[0]


def apply_chart_value_edits(data: bytes, edits: Iterable[ChartValueEdit], *, virtual_path: str = "") -> bytes:
    """Write f32 values in place. Same length; only the edited 4-byte fields change."""

    data = bytes(data)
    chart = _require_chart(data, virtual_path)
    buffer = bytearray(data)
    touched: list[tuple[int, int]] = []
    records: dict[int, tuple[str, int]] = {}
    for edit in edits:
        value = float(edit.value)
        at, kind, base = _edit_offset(chart, edit)
        if not math.isfinite(value):
            raise ActionChartError(f"{edit.field} must be finite")
        if kind == "rate" and not 0 < value <= 100:
            raise ActionChartError(f"{edit.field} must be above 0 and at most 100")
        if kind == "time" and not 0 <= value <= 3600:
            raise ActionChartError(f"{edit.field} must be between 0 and 3600 seconds")
        if kind == "event_end" and value != -1 and not 0 <= value <= 3600:
            raise ActionChartError(f"{edit.field} must be -1 (instant) or between 0 and 3600 seconds")
        struct.pack_into("<f", buffer, at, value)
        touched.append((at, 4))
        record = EDITABLE_CHART_FIELDS[edit.field][0]
        if base >= 0:
            records[base] = (record, base)
    for record, base in records.values():
        if record == "event":
            begin, end = struct.unpack_from("<ff", buffer, base)
            if end != -1 and end < begin:
                raise ActionChartError(f"frame event at {base} would end before it begins")
        elif record in _PAIRS:
            start, end = (struct.unpack_from("<f", buffer, base + item)[0] for item in _PAIRS[record])
            if end < start:
                raise ActionChartError(f"{record} at {base} would end before it starts")
    patched = bytes(buffer)
    allowed = bytearray(len(data))
    for at, size in touched:
        allowed[at:at + size] = b"\1" * size
    for index, (left, right) in enumerate(zip(data, patched)):
        if left != right and not allowed[index]:
            raise ActionChartError(f"byte {index} changed outside the edited fields")
    after = _require_chart(patched)
    if [(span.name, span.offset, span.size) for span in after.spans] != [(span.name, span.offset, span.size) for span in chart.spans]:
        raise ActionChartError("the chart's sections changed after a value edit")
    return patched


__all__ = [
    "ACTION_CHART_STRING_TABLES",
    "ANIMATION_ARRAYS",
    "ANIMATION_ARRAYS_2_04",
    "ANIMATION_TABLE",
    "BLEND_TABLE",
    "ActionChart",
    "ActionChartError",
    "ActionPackage",
    "ActionPackageDescription",
    "AnimationInfo",
    "ChartArray",
    "ChartNode",
    "ChartSpan",
    "ChartValueEdit",
    "EDITABLE_CHART_FIELDS",
    "EventEdit",
    "EventReference",
    "FRAME_EVENT_KINDS",
    "FRAME_EVENT_REFERENCES",
    "FRAME_EVENT_SIZES",
    "FrameEvent",
    "FrameEventRef",
    "MODEL_ATTACHMENT_SOCKET_KIND",
    "SocketEventPayload",
    "StringTable",
    "action_chart_layout",
    "apply_chart_value_edits",
    "apply_event_edits",
    "chart_value_offset",
    "decode_action_chart",
    "decode_action_package_description",
    "event_edit_fields",
    "event_references",
    "event_users",
    "frame_event_at",
    "replace_chart_strings",
    "retarget_animation",
    "retarget_chart_string",
    "set_animation_resources",
    "socket_event_payload",
    "walk_frame_events",
]
