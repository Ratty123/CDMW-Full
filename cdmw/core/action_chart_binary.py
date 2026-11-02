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
        11 arrays, widths 12 16 104 148 24 36 12 96 12 12 16, counts from the header
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
ANIMATION_ARRAYS = (
    ("frameTag", 12),
    ("animationSpeedInfoArray", 16),
    ("moveSpeedInfoArray", 0x68),
    ("aiMoveSpeedInfoArray", 0x94),
    ("verticalMoveSpeedInfoArray", 24),
    ("defenceInfoArray", 36),
    ("characterClimbTagInfoArray", 12),
    ("onHitEventInfoArray", 96),
    ("StumbleOnHitInfoArray", 12),
    ("aiReviseTurnInfoArray", 12),
    ("justTimeFrameTagInfo", 16),
)

#: Frame event kinds, indexed by the u16 at the start of each event. Read from the
#: client factory switch (185 cases) by the RTTI class each case constructs, minus
#: the `ClientFrameEvent` prefix. Kind numbers moved with the 2.04 update (the socket
#: event was 60 before it and is 62 now), so they are tied to this game version.
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
    stream = _Stream(data)
    animations = []
    animation_count = stream.scalar("I", "animation count")
    if animation_count > len(data) // ANIMATION_HEADER_SIZE:
        raise ActionChartError(f"animation count {animation_count} cannot fit in {len(data)} bytes")
    for index in range(animation_count):
        header_at = stream.records(1, ANIMATION_HEADER_SIZE, "AnimationInfoData")
        header = data[header_at:header_at + ANIMATION_HEADER_SIZE]
        arrays = []
        for slot, (name, width) in enumerate(ANIMATION_ARRAYS):
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


def replace_chart_strings(data: bytes, table: int, replacements: Mapping[int, str], *, virtual_path: str = "") -> bytes:
    """Rewrite entries of one string table at any length.

    The table is rebuilt and spliced in; every other byte moves as one block. The
    result must decode with the same sections, and every byte outside the table must
    match the original, or the edit is refused.
    """

    data = bytes(data)
    chart = _require_chart(data, virtual_path)
    if not 0 <= table < len(chart.tables):
        raise ActionChartError(f"string table {table} does not exist")
    source = chart.tables[table]
    raw = list(source.raw)
    for index, value in replacements.items():
        if not 0 <= index < len(raw):
            raise ActionChartError(f"string table {table} has no entry {index}")
        raw[index] = _encode_value(value)
    rebuilt = _encode_strings(raw)
    start, end = source.offset, source.offset + source.size
    patched = data[:start] + rebuilt + data[end:]
    after = _require_chart(patched)
    if patched[:start] != data[:start] or patched[start + len(rebuilt):] != data[end:]:
        raise ActionChartError("bytes outside the string table changed")
    if after.tables[table].raw != tuple(raw):
        raise ActionChartError("the rebuilt string table does not read back")
    before_shape = [(span.name, span.size) for span in chart.spans if span.offset != start]
    after_shape = [(span.name, span.size) for span in after.spans if span.offset != start]
    if before_shape != after_shape:
        raise ActionChartError("the chart's sections changed shape after the edit")
    return patched


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
    "FRAME_EVENT_KINDS",
    "FrameEvent",
    "FrameEventRef",
    "MODEL_ATTACHMENT_SOCKET_KIND",
    "SocketEventPayload",
    "StringTable",
    "apply_chart_value_edits",
    "decode_action_chart",
    "decode_action_package_description",
    "frame_event_at",
    "replace_chart_strings",
    "retarget_animation",
    "retarget_chart_string",
    "socket_event_payload",
]
