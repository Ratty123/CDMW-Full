"""Bounded, address-free layouts for the DLC and current static-table serialization."""
from dataclasses import replace
from types import MappingProxyType

from cdmw.core._compact_static_schema import READERS, TABLE_READERS
from cdmw.core.new_item_record import Cursor, RecordError


# (record bytes, walk steps). Faction and quest rows carry whole relation and
# stage graphs (largest shipped rows about 204 KiB and 1.5 MiB); deep condition
# trees and gimmick scripts need more steps or bytes than an item row.
_RECORD_LIMITS = {
    "faction": (1 << 20, 4_000_000),
    "questinfo": (4 << 20, 16_000_000),
    "conditioninfo": (65536, 1_000_000),
    "gimmickinfo": (1 << 20, 4_000_000),
    "gimmickgroupinfo": (1 << 20, 4_000_000),
    "factionnodespawninfo": (1 << 20, 4_000_000),
}
_DEFAULT_LIMITS = (65536, 200000)
# Condition logic nests AND/OR/NOT nodes; each level costs about four walk levels
# and the deepest shipped condition needs about 300.
_DEPTH_LIMIT = 400

# 1.0.0.3527 inserts two UTF-8 strings after _filterType. The executable hashes
# the socket name after reading its length and bytes; the wire value is text.
# Keep the earlier grammar for old packages and require exactly one complete walk.
# The two corrected spelling labels in that executable retain their existing API names.
_ITEMINFO_BASE = READERS[TABLE_READERS["iteminfo"]]
_SOUND_INSERT = next(i + 1 for i, op in enumerate(_ITEMINFO_BASE)
                     if isinstance(op, tuple) and op[:3] == ("field", "ItemInfo", "_filterType"))
_ITEMINFO_3527 = (
    *_ITEMINFO_BASE[:_SOUND_INSERT],
    ("field", "ItemInfo", "_soundNameOnMaxCharged", ("text",)),
    ("field", "ItemInfo", "_soundSocketNameOnMaxCharged", ("text",)),
    *_ITEMINFO_BASE[_SOUND_INSERT:],
)


def _insert_after(program, owner, name, *ops):
    at = next(i + 1 for i, op in enumerate(program)
              if isinstance(op, tuple) and op[:3] == ("field", owner, name))
    return (*program[:at], *ops, *program[at:])


_PAGE_BASE = READERS[808][1][2]
assert _PAGE_BASE[-1][:3] == ("field", "PageData", "_rightPageRelatedKnowledgeInfo")
_PAGE_3732 = (*_PAGE_BASE, ("field", "PageData", "_uiTextureRotationType", ("raw", 1)))
_ITEMINFO_3732 = tuple(
    ("field", "ItemInfo", op[2], ("presence", ("seq", ("array", 4, _PAGE_3732))))
    if isinstance(op, tuple) and op[0] == "field" and op[2] in ("_fixedPageDataList", "_dynamicPageDataList")
    else op
    for op in _insert_after(_ITEMINFO_3527, "ItemInfo", "_discardable",
                            ("field", "ItemInfo", "_discardSingleCount", ("raw", 1))))
assert READERS[513] == ("optional", 808)

_DROPSET_BASE = READERS[TABLE_READERS["dropsetinfo"]]
_VEHICLE_INSERT = next(i + 1 for i, op in enumerate(_DROPSET_BASE)
                       if isinstance(op, tuple) and op[:3] == ("field", "DropSetInfo", "_isEqualPercent"))
_DROPSET_3663 = (
    *_DROPSET_BASE[:_VEHICLE_INSERT],
    ("field", "DropSetInfo", "_isToVehicle", ("raw", 1)),
    *_DROPSET_BASE[_VEHICLE_INSERT:],
)
# 1.0.0.3663 reads two further GimmickInfo members after _lookAtDataList. Every
# shipped row stores each as one zero byte, so each is read as an absent
# presence-flagged value; a present value has no qualified shape and is refused.
_GIMMICKINFO_BASE = READERS[TABLE_READERS["gimmickinfo"]]
_CONSTRAINT_INSERT = next(i + 1 for i, op in enumerate(_GIMMICKINFO_BASE)
                          if isinstance(op, tuple) and op[:3] == ("field", "GimmickInfo", "_lookAtDataList"))
_GIMMICKINFO_3663 = (
    *_GIMMICKINFO_BASE[:_CONSTRAINT_INSERT],
    ("field", "GimmickInfo", "_autoTargetingConstraintDataList", ("presence", ("unsupported",))),
    ("field", "GimmickInfo", "_gimmickConstraintDataList", ("presence", ("unsupported",))),
    *_GIMMICKINFO_BASE[_CONSTRAINT_INSERT:],
)
# ConditionData's u16 type switch. 1.0.0.3663 adds type 144, so the older types
# 144 to 500 arrive as 145 to 501.
_CONDITION_TYPES = 941
_CONDITION_SWITCH = READERS[_CONDITION_TYPES]
_NEW_CONDITION_TYPE = 144
assert _CONDITION_SWITCH[:2] == ("variant", 2) and sorted(_CONDITION_SWITCH[-1]) == list(range(502))
_CONDITION_SWITCH_3663 = (*_CONDITION_SWITCH[:-1], MappingProxyType({
    **{tag: case for tag, case in _CONDITION_SWITCH[-1].items() if tag < _NEW_CONDITION_TYPE},
    _NEW_CONDITION_TYPE: ("unsupported",),
    **{tag + 1: case for tag, case in _CONDITION_SWITCH[-1].items() if _NEW_CONDITION_TYPE <= tag < 501},
    502: ("unsupported",),
    503: ("unsupported",),
}))


def _reader_of(owner, name):
    found = [index for index, op in enumerate(READERS) if op[0] == "seq"
             and any(isinstance(child, tuple) and child[:3] == ("field", owner, name) for child in op[1:])]
    assert len(found) == 1, (owner, name, found)
    return found[0]


def _with_fields(program, owner, after, *fields):
    """`program` with new ("field", owner, name, op) entries after the last read of `after`."""
    ops = list(program[1:])
    at = 0 if not after else max(i for i, op in enumerate(ops)
                                 if isinstance(op, tuple) and op[:3] == ("field", owner, after)) + 1
    return ("seq", *ops[:at], *(("field", owner, name, op) for name, op in fields), *ops[at:])


def _without_field(program, owner, name):
    assert sum(1 for op in program[1:] if isinstance(op, tuple) and op[:3] == ("field", owner, name)) == 1
    return ("seq", *(op for op in program[1:] if not (isinstance(op, tuple) and op[:3] == ("field", owner, name))))


def _renamed(program, owner, old, new):
    assert sum(1 for op in program[1:] if isinstance(op, tuple) and op[:3] == ("field", owner, old)) == 1
    return ("seq", *((op[0], owner, new, op[3]) if isinstance(op, tuple) and op[:3] == ("field", owner, old) else op
                     for op in program[1:]))


def _root(kind):
    program = READERS[TABLE_READERS[kind]]
    assert program[0] == "seq"
    return program


_DETECT_SENSE = _reader_of("DetectSenseData", "_frontDistance")
_DETECTINFO_3732 = (*_root("detectinfo"), ("field", "DetectInfo", "_detectDetailData", ("presence", (
    "seq", ("field", "DetectDetailData", "_detectDetailDataListNew", ("repeat", 64, ("call", _DETECT_SENSE)))))))
_SKILLGROUP_3732 = _renamed(_with_fields(_root("skillgroupinfo"), "SkillGroupInfo", "_isBlocked",
                                         ("_groupType", ("raw", 1))),
                            "SkillGroupInfo", "_skillKeyList", "_skillInfoList")
_SPAWNPOOL_3732 = _with_fields(_root("spawningpoolautospawninfo"), "SpawningPoolAutoSpawnInfo", "_meshNameList",
                               ("_useSceneCollectSpawn", ("raw", 1)))
_UIMAP_3732 = _with_fields(
    _renamed(_without_field(_root("uimaptextureinfo"), "UIMapTextureInfo", "_isMovingPlatform"),
             "UIMapTextureInfo", "_platformZIndex", "_platformIconZIndex"),
    "UIMapTextureInfo", "_maxScale", ("_platformIconSize", ("raw", 8)), ("_platformIconCenterOffset", ("raw", 8)))
_FRAME_EVENT = _reader_of("FrameEventAttribute", "_moveSpeed")
_FRAME_EVENT_3732 = _with_fields(
    _with_fields(READERS[_FRAME_EVENT], "FrameEventAttribute", "_moveSpeed",
                 ("_aiMoveAcc", ("raw", 4)), ("_aiMoveDcc", ("raw", 4))),
    "FrameEventAttribute", "_jumpHeight", ("_aiMoveSpeed", ("raw", 4)))
_PATROL_GROUP = _reader_of("PatrolGroupSetData", "_partyDataList")
_PATROL_GROUP_3732 = _with_fields(READERS[_PATROL_GROUP], "PatrolGroupSetData", "",
                                  ("_spawnGroupType", ("raw", 1)), ("_formationInfo", ("raw", 4)))
_MISSION_RESULT = _reader_of("MissionResultData", "_missionResultType")
_MISSION_RESULT_3732 = _with_fields(READERS[_MISSION_RESULT], "MissionResultData", "_completeStageInfo",
                                    ("_levelGimmickSceneObjectInfo", ("raw", 4)))
_SEQUENCER_STAGE = _reader_of("StageInfo_SequencerStage", "_stageGameEventDataList")
_STAGE_EVENTS = next(op[3][1] for op in READERS[_SEQUENCER_STAGE][1:]
                     if isinstance(op, tuple) and op[:3] == ("field", "StageInfo_SequencerStage", "_stageGameEventDataList"))
assert READERS[_STAGE_EVENTS][0] == "array" and READERS[_STAGE_EVENTS][2][1] == ("raw", 4), READERS[_STAGE_EVENTS]
_STAGE_EVENTS_3732 = ("array", 4, (*READERS[_STAGE_EVENTS][2], ("raw", 4)))

_NO_OVERRIDES = MappingProxyType({})
_LAYOUTS_3732 = {
    "detectinfo": (_DETECTINFO_3732, {}),
    "skillgroupinfo": (_SKILLGROUP_3732, {}),
    "spawningpoolautospawninfo": (_SPAWNPOOL_3732, {}),
    "uimaptextureinfo": (_UIMAP_3732, {}),
    "statusinfo": (_root("statusinfo"), {_FRAME_EVENT: _FRAME_EVENT_3732}),
    "factionspawndatainfo": (_root("factionspawndatainfo"), {_PATROL_GROUP: _PATROL_GROUP_3732}),
    "missioninfo": (_root("missioninfo"), {_MISSION_RESULT: _MISSION_RESULT_3732}),
    "stageinfo": (_root("stageinfo"), {_STAGE_EVENTS: _STAGE_EVENTS_3732}),
}


# 1.0.0.3840 transforms:
# - Every root row drops inline `_stringKey` (moved to `.staticinfoheader`) and
#   places u32 `_staticInfoIndex` immediately after inline `_key`.
# - Many condition fields inline `Condition` (`optional(1107)`) instead of u32
#   hashes (`call(21)`), while `READERS[21]` itself remains `raw(4)` for tables
#   that still store hashed condition keys.
def _to_3840_root(program):
    assert program[0] == "seq"
    key_field = next(op for op in program[1:]
                     if isinstance(op, tuple) and op[0] == "field" and op[2] == "_key")
    owner = key_field[1]
    stripped = [op for op in program[1:]
                if not (isinstance(op, tuple) and op[0] == "field" and op[2] == "_stringKey")]
    at = next(i + 1 for i, op in enumerate(stripped)
              if isinstance(op, tuple) and op[:3] == ("field", owner, "_key"))
    return ("seq", *stripped[:at], ("field", owner, "_staticInfoIndex", ("raw", 4)), *stripped[at:])


def _inline_cond_fields(op):
    if op == ("call", 21):
        return ("optional", 1107)
    if isinstance(op, MappingProxyType):
        return MappingProxyType({k: _inline_cond_fields(v) for k, v in op.items()})
    if isinstance(op, dict):
        return {k: _inline_cond_fields(v) for k, v in op.items()}
    if isinstance(op, tuple):
        return tuple(_inline_cond_fields(c) for c in op)
    return op


_ITEMINFO_3840 = _to_3840_root(_ITEMINFO_3732)
ITEMINFO_GENERATIONS = (
    ("pre-3527", _ITEMINFO_BASE),
    ("3527", _ITEMINFO_3527),
    ("3732", _ITEMINFO_3732),
    ("3840", _ITEMINFO_3840),
)

_DROPINFO_3840 = _inline_cond_fields(READERS[842])
_COND_OPTION_3840 = _inline_cond_fields(READERS[48])
_FACTION_STATE_3840 = _inline_cond_fields(READERS[126])
_DETECT_REACTION_OVERRIDE_3840 = _inline_cond_fields(READERS[417])
_FAIL_MESSAGE_DATA_3840 = _inline_cond_fields(READERS[644])
_BUFF_COND_844_3840 = _inline_cond_fields(READERS[844])
_BUFF_COND_924_3840 = _inline_cond_fields(READERS[924])

_FIELDINFO_3840 = _with_fields(
    _to_3840_root(_root("fieldinfo")), "FieldInfo", "_uiMapTextureStart",
    ("_fixedEntryPosition", ("raw", 12)),
)

_FORMATION_RAW = _to_3840_root(_without_field(_root("formationinfo"), "FormationInfo", "_isSuperStrict"))
_FORMATION_3840 = ("seq", *(
    ("array", 4, ("seq",
                  ("field", "FormationInfo", "_memberDataList", ("raw", 12)),
                  ("field", "FormationInfo", "_memberDataList", ("raw", 12)),
                  ("field", "FormationInfo", "_memberDataList", ("raw", 4)),
                  ("field", "FormationInfo", "_memberDataList", ("raw", 4)),
                  ("field", "FormationInfo", "_memberDataList", ("raw", 1))))
    if isinstance(op, tuple) and op[0] == "array"
    else op
    for op in _FORMATION_RAW[1:]
))

_HOUSING_3840 = _with_fields(
    _to_3840_root(_root("housingobjectinfo")), "HousingObjectInfo", "_isOpenBoundaryWall",
    ("_placementRule", ("raw", 1)),
)
_LEVEL_ACTION_POINT_3840 = _with_fields(
    _to_3840_root(_root("levelactionpointinfo")), "LevelActionPointInfo", "_isBlocked",
    ("_allowWithoutNavi", ("raw", 1)),
)
_UIMAP_3840 = _with_fields(
    _without_field(_to_3840_root(_UIMAP_3732), "UIMapTextureInfo", "_filterType"),
    "UIMapTextureInfo", "_uiSmallTextureName", ("_uiFilterDataKey", ("raw", 4)),
)
_MINIGAME_3840 = _with_fields(
    _to_3840_root(_root("minigamedatainfo")), "MiniGameDataInfo", "_name",
    ("_gamePlaySkillKeyAndLevelList", ("array", 4, ("raw", 8))),
)
_FRAME_EVENT_3840 = ("seq", *(
    ("field", "FrameEventAttribute", "_changingRotationSpeed", ("raw", 8))
    if isinstance(op, tuple) and op[:3] == ("field", "FrameEventAttribute", "_changingRotationSpeed")
    else op
    for op in _FRAME_EVENT_3732[1:]
))
_SKILL_3840 = _renamed(_to_3840_root(_root("skill")), "SkillInfo", "_skillGroupKeyList", "_skillGroupInfoList")

_CHARACTER_3840 = _with_fields(
    _to_3840_root(_root("characterinfo")), "CharacterInfo", "_activityPresetInfo",
    ("_interactionCategoryGroupInfoForPlayer", ("raw", 2)),
)
_CHAR_LEVEL_3840 = _without_field(READERS[52], "CharacterLevelData", "_frameEventAttrGroupInfoName")
_INTERACTION_OVERRIDE_3840 = _without_field(READERS[205], "InteractionOverrideData", "_interactionDialogSetOverrideData")

_CHALLENGE_EVENT_3840 = _with_fields(
    READERS[197], "ChallengeEventData", "_haveCountStageInfo",
    ("_haveCountMarriedCharacterInfo", ("call", 361)),
    ("_haveCountPlayerCharacterInfo", ("call", 361)),
)
_STAGE_PLAY_DESC_3840 = _with_fields(
    READERS[320], "StageInfo_PlayDesc", "_levelName",
    ("_channelLevelNameHash", ("raw", 4)),
)
_SPAWN_TARGET_3840 = _with_fields(
    READERS[313], "AutoSpawnTargetData", "_usingActionPoint",
    ("_disableRoaming", ("raw", 1)),
)
_SPAWN_CHAR_3840 = _with_fields(
    READERS[310], "AutoSpawnCharacterData", "_subZoneTagHash",
    ("_spawnActionPointTagHash", ("raw", 4)),
)

_ACTION_POINT_ACCESSOR_3840 = (
    "seq",
    ("field", "ActionPointAccessor", "_actionPointKey", ("raw", 4)),
    ("raw", 76),
)
_ACTION_POINT_3840 = _with_fields(
    _without_field(
        _without_field(
            _without_field(
                _without_field(READERS[69], "ActionPoint", "_sceneObjectUuid"),
                "ActionPoint", "_socketIndex"),
            "ActionPoint", "_parentSceneObjectUuid"),
        "ActionPoint", "_parentGamePlayTriggerZone"),
    "ActionPoint", "_levelName",
    ("_gimmickActorKey", ("raw", 4)),
)
_NPC_ACT_253_3840 = _with_fields(
    READERS[253], "NPCActivityInstruction", "_instructionType",
    ("_parentInstructionLocator", ("raw", 1)),
    ("_parentInstructionLocator", ("raw", 1)),
    ("_parentInstructionLocator", ("raw", 4)),
    ("_debugTaskNumber", ("raw", 4)),
    ("_debugStepNumber", ("raw", 4)),
)
_NPC_ACT_255_3840 = _with_fields(
    READERS[255], "NPCActivityInstruction", "_instructionType",
    ("_parentInstructionLocator", ("raw", 1)),
    ("_parentInstructionLocator", ("raw", 1)),
    ("_parentInstructionLocator", ("raw", 4)),
    ("_debugTaskNumber", ("raw", 4)),
    ("_debugStepNumber", ("raw", 4)),
)
_TRIGGER_FUNC_3840 = _with_fields(
    _without_field(
        _without_field(
            _without_field(READERS[185], "GamePlayTriggerFunctionData", "_visitCapacityList"),
            "GamePlayTriggerFunctionData", "_stayHour"),
        "GamePlayTriggerFunctionData", "_stayMinute"),
    "GamePlayTriggerFunctionData", "_visitProbability",
    ("_subZoneDataList", ("array", 4, ("unsupported",))),
)
_GIMMICKINFO_3840 = _with_fields(
    _to_3840_root(_GIMMICKINFO_3663), "GimmickInfo", "_isShowInteractionByTrigger",
    ("_syncChannelWithPlayer", ("raw", 1)),
    ("_isAttackThrowable", ("raw", 1)),
)
_FORCE_FIELD_1118_3840 = (*READERS[1118], ("raw", 4), ("raw", 4))
_INTERACTIONINFO_3840 = _with_fields(
    _without_field(_to_3840_root(_root("interactioninfo")), "InteractionInfo", "_dialogSetInfo"),
    "InteractionInfo", "_childInteractionInfoList",
    ("_targetInteractionInfoList", ("array", 4, ("raw", 4))),
)


def _table_3840_spec(kind):
    if kind in _LAYOUTS_3732:
        base_prog, base_over = _LAYOUTS_3732[kind]
    elif kind == "dropsetinfo":
        base_prog, base_over = _DROPSET_BASE, {}
    elif kind == "gimmickinfo":
        base_prog, base_over = _GIMMICKINFO_3663, {}
    elif kind == "iteminfo":
        base_prog, base_over = _ITEMINFO_3732, {}
    else:
        base_prog, base_over = _root(kind), {}

    overrides = dict(base_over)
    root = base_prog if kind in ("autospawnfilterinfo", "keymap") else _to_3840_root(base_prog)

    if kind == "activitypresetinfo":
        overrides[71] = _inline_cond_fields(READERS[71])
    elif kind == "allygroupinfo":
        root = _inline_cond_fields(root)
    elif kind == "autospawnfilterinfo":
        overrides[1183] = _to_3840_root(READERS[1183])
    elif kind == "keymap":
        overrides[1184] = _to_3840_root(READERS[1184])
    elif kind == "bankinfo":
        root = _inline_cond_fields(root)
    elif kind == "board":
        overrides[89] = _inline_cond_fields(READERS[89])
        overrides[724] = _inline_cond_fields(READERS[724])
    elif kind == "buffinfo":
        overrides[844] = _BUFF_COND_844_3840
        overrides[924] = _BUFF_COND_924_3840
    elif kind == "dropsetinfo":
        overrides[842] = _DROPINFO_3840
    elif kind == "dyecolorgroupinfo":
        overrides[725] = _inline_cond_fields(READERS[725])
    elif kind == "equipslotinfo":
        overrides[733] = _inline_cond_fields(READERS[733])
    elif kind == "faction":
        overrides[117] = _inline_cond_fields(READERS[117])
        overrides[711] = _inline_cond_fields(READERS[711])
        overrides[712] = _inline_cond_fields(READERS[712])
    elif kind == "factionnode":
        root = _inline_cond_fields(root)
        overrides[48] = _COND_OPTION_3840
        overrides[117] = _inline_cond_fields(READERS[117])
        overrides[126] = _FACTION_STATE_3840
        overrides[129] = _inline_cond_fields(READERS[129])
        overrides[694] = _inline_cond_fields(READERS[694])
        overrides[699] = _inline_cond_fields(READERS[699])
    elif kind == "factionreblockadinginfo":
        root = _inline_cond_fields(root)
    elif kind == "gameversiondatainfo":
        overrides[200] = _inline_cond_fields(READERS[200])
    elif kind == "globalgameevent":
        overrides[48] = _COND_OPTION_3840
    elif kind == "levelgimmicksceneobjectinfo":
        overrides[48] = _COND_OPTION_3840
    elif kind == "levelinfo":
        overrides[640] = _inline_cond_fields(READERS[640])
    elif kind == "multichangeinfo":
        overrides[644] = _FAIL_MESSAGE_DATA_3840
    elif kind == "questinfo":
        overrides[126] = _FACTION_STATE_3840
    elif kind == "storeinfo":
        overrides[842] = _DROPINFO_3840
        overrides[48] = _COND_OPTION_3840
    elif kind == "itemuseinfo":
        overrides[842] = _DROPINFO_3840
    elif kind == "fieldinfo":
        root = _FIELDINFO_3840
    elif kind == "formationinfo":
        root = _FORMATION_3840
    elif kind == "housingobjectinfo":
        root = _HOUSING_3840
    elif kind == "levelactionpointinfo":
        root = _LEVEL_ACTION_POINT_3840
    elif kind == "uimaptextureinfo":
        root = _UIMAP_3840
    elif kind == "minigamedatainfo":
        root = _MINIGAME_3840
    elif kind == "statusinfo":
        overrides[_FRAME_EVENT] = _FRAME_EVENT_3840
    elif kind == "skill":
        root = _SKILL_3840
        overrides[844] = _BUFF_COND_844_3840
        overrides[924] = _BUFF_COND_924_3840
    elif kind == "characterinfo":
        root = _CHARACTER_3840
        overrides[205] = _INTERACTION_OVERRIDE_3840
        overrides[52] = _CHAR_LEVEL_3840
        overrides[417] = _DETECT_REACTION_OVERRIDE_3840
    elif kind == "missioninfo":
        overrides[197] = _CHALLENGE_EVENT_3840
    elif kind == "stageinfo":
        overrides[320] = _STAGE_PLAY_DESC_3840
    elif kind in ("spawningpoolautospawninfo", "terrainregionautospawninfo"):
        overrides[313] = _SPAWN_TARGET_3840
        overrides[310] = _SPAWN_CHAR_3840
    elif kind == "actionpointinfo":
        overrides[69] = _ACTION_POINT_3840
        overrides[68] = _ACTION_POINT_ACCESSOR_3840
    elif kind == "npcactivityinfo":
        overrides[253] = _NPC_ACT_253_3840
        overrides[255] = _NPC_ACT_255_3840
    elif kind == "gameplaytrigger":
        overrides[185] = _TRIGGER_FUNC_3840
    elif kind == "gimmickinfo":
        root = _GIMMICKINFO_3840
        overrides[205] = _INTERACTION_OVERRIDE_3840
        overrides[842] = _DROPINFO_3840
        overrides[1118] = _FORCE_FIELD_1118_3840
    elif kind == "interactioninfo":
        root = _INTERACTIONINFO_3840
    elif kind == "failmessageinfo":
        overrides[644] = _FAIL_MESSAGE_DATA_3840

    return root, MappingProxyType(overrides)


def _build_table_generations():
    gens = {}
    for kind in TABLE_READERS:
        if kind == "stockdata":
            stock_over = MappingProxyType({842: _DROPINFO_3840, 48: _COND_OPTION_3840})
            gens[kind] = (
                ("stockdata", READERS[TABLE_READERS["stockdata"]], _NO_OVERRIDES),
                ("3840", READERS[TABLE_READERS["stockdata"]], stock_over),
            )
            continue
        entries = []
        if kind == "iteminfo":
            entries.extend((label, program, _NO_OVERRIDES) for label, program in ITEMINFO_GENERATIONS if label != "3840")
        elif kind == "gimmickinfo":
            entries.extend((("pre-3663", _GIMMICKINFO_BASE, _NO_OVERRIDES), ("3663", _GIMMICKINFO_3663, _NO_OVERRIDES)))
        elif kind in _LAYOUTS_3732:
            program, overrides = _LAYOUTS_3732[kind]
            entries.extend((("pre-3732", _root(kind), _NO_OVERRIDES), ("3732", program, MappingProxyType(overrides))))
        else:
            entries.append((kind, READERS[TABLE_READERS[kind]], _NO_OVERRIDES))
        root_3840, over_3840 = _table_3840_spec(kind)
        entries.append(("3840", root_3840, over_3840))
        gens[kind] = tuple(entries)
    return MappingProxyType(gens)


#: (label, root program, reader overrides) per table, oldest first.
TABLE_GENERATIONS = _build_table_generations()


def table_generations(kind):
    """(label, root program, reader overrides) for every layout `kind` is read with, oldest first."""
    return TABLE_GENERATIONS.get(kind) or ((kind, READERS[TABLE_READERS[kind]], _NO_OVERRIDES),)


def read_compact_layout(raw, kind="iteminfo", *, key_layout=None):
    all_programs = TABLE_GENERATIONS.get(kind) or ((kind, None, _NO_OVERRIDES),)
    if key_layout == "indexed":
        programs = tuple(entry for entry in all_programs if entry[0] == "3840")
    elif key_layout in ("named", "prefix"):
        programs = tuple(entry for entry in all_programs if entry[0] != "3840")
    else:
        programs = all_programs
    candidates, errors, failures = [], [], []
    try:
        return _select_compact_layout(raw, kind, programs, candidates, errors, failures, key_layout=key_layout)
    finally:
        # A kept exception's traceback holds this read's frames, and the list holds the
        # exception: a cycle that only the garbage collector could free. Snapshots read
        # tens of thousands of rows, and the window thread's collections then freed them.
        failures.clear()


def _select_compact_layout(raw, kind, programs, candidates, errors, failures, *, key_layout=None):
    for label, program, overrides in programs:
        drop_seen = set()
        widths = (2,) if label == "3840" else (2, 3)
        for enchant_width in widths:
            # A row without DropInfoData has identical layouts. Do not walk it twice.
            if enchant_width == 3 and not drop_seen and kind != "dropsetinfo":
                break
            condition_seen = set()
            for conditions_3663 in (False, True):
                if conditions_3663 and not condition_seen:
                    break
                try:
                    selected = (_DROPSET_3663
                                if kind == "dropsetinfo" and enchant_width == 3 and label != "3840"
                                else program)
                    layout = _read_compact_layout(raw, kind, selected, enchant_width=enchant_width, drop_seen=drop_seen,
                                                  conditions_3663=conditions_3663, condition_seen=condition_seen,
                                                  overrides=overrides)
                    effective_layout = "indexed" if label == "3840" else key_layout
                    if layout.key_layout != effective_layout:
                        layout = replace(layout, key_layout=effective_layout)
                    if layout not in candidates:
                        candidates.append(layout)
                except (RecordError, UnicodeError) as exc:
                    errors.append(f"{label}: {exc}")
                    failures.append(exc)
    if len(candidates) != 1:
        if kind != "iteminfo":
            if not candidates:
                # The newest layout tried is the one the current game writes.
                raise failures[-1]
            raise RecordError("Unsupported or ambiguous compact static layout.")
        detail = "; ".join(errors) if not candidates else "more than one known layout matches"
        raise RecordError(f"Unsupported or ambiguous compact ItemInfo layout ({detail}).")
    return candidates[0]


def _read_compact_layout(raw, kind, program=None, *, enchant_width=2, drop_seen=None,
                         conditions_3663=False, condition_seen=None, overrides=None):
    from cdmw.core.item_layout import ItemLayout, Member, Span

    size_limit, step_limit = _RECORD_LIMITS.get(kind, _DEFAULT_LIMITS)
    if kind not in TABLE_READERS or not isinstance(raw, (bytes, bytearray)) or not 1 <= len(raw) <= size_limit:
        raise RecordError("Unsupported compact static record.")
    cursor = Cursor(raw)
    fields, members = {}, []
    steps = 0

    def walk(op, path=(), depth=0):
        nonlocal steps
        steps += 1
        if depth > _DEPTH_LIMIT or steps > step_limit:
            raise RecordError("Compact static record exceeds the layout limit.")
        code = op[0]
        if code == "unsupported":
            raise RecordError("This compact static variant has not been qualified.")
        if code == "raw":
            cursor.take(op[1])
        elif code == "text":
            # Gimmick tables embed state-handler XML longer than the 4 KiB item-text bound.
            cursor.take(cursor.count(limit=size_limit)).decode("utf-8")
        elif code == "seq":
            for child in op[1:]:
                walk(child, path, depth + 1)
        elif code == "call":
            if op[1] == _CONDITION_TYPES and conditions_3663:
                walk(_CONDITION_SWITCH_3663, path, depth + 1)
            else:
                walk(overrides[op[1]] if overrides and op[1] in overrides else READERS[op[1]], path, depth + 1)
        elif code in ("optional", "presence"):
            present = cursor.unpack("B")
            if present not in (0, 1):
                raise RecordError("Invalid compact static presence flag.")
            if present:
                if code == "optional":
                    walk(overrides[op[1]] if overrides and op[1] in overrides else READERS[op[1]], path, depth + 1)
                else:
                    walk(op[1], path, depth + 1)
        elif code in ("array", "repeat"):
            count = int.from_bytes(cursor.take(op[1]), "little") if code == "array" else op[1]
            if not 0 <= count <= 65536:
                raise RecordError(f"Compact static list exceeds the supported bound at {path}.")
            for index in range(count):
                walk(op[2], path + (index,), depth + 1)
        elif code == "field":
            _, owner, name, child = op
            if owner == "DropInfoData" and name == "_enchantLevel":
                # Build 1.0.0.3663 reads a further opaque byte after the i16
                # enchantment level, while 1.0.0.3840 restores the 2-byte width.
                child = ("raw", enchant_width)
                if drop_seen is not None:
                    drop_seen.add(True)
            start = cursor.pos
            try:
                walk(child, path + (name,), depth + 1)
            except (RecordError, UnicodeError) as exc:
                if kind == "iteminfo" and not path:
                    raise RecordError(f"ItemInfo.{name} at row offset 0x{start:X}: {exc}") from exc
                raise
            span = Span(start, cursor.pos)
            if not path:
                previous = fields.get(name)
                if previous is not None:
                    if previous.end != start:
                        raise RecordError("Ambiguous compact static field.")
                    span = Span(previous.start, cursor.pos)
                fields[name] = span
            else:
                members.append(Member(owner, name, path, span))
        elif code in ("variant", "tagged"):
            tag = int.from_bytes(cursor.take(op[1]), "little")
            if op is _CONDITION_SWITCH and tag >= _NEW_CONDITION_TYPE and condition_seen is not None:
                condition_seen.add(True)
            if tag not in op[-1]:
                raise RecordError("Unsupported compact static discriminant.")
            if code == "tagged":
                walk(op[2], path, depth + 1)
            walk(op[-1][tag], path, depth + 1)
        else:
            raise RecordError("Unknown compact static layout operation.")

    try:
        walk(program if program is not None else READERS[TABLE_READERS[kind]])
    finally:
        # walk calls itself through its own closure cell. Empty the cell so the cycle
        # does not keep this read's cursor, fields and members for a collection.
        walk = None
    cursor.finish()
    return ItemLayout(bytes(raw), kind, "compact", MappingProxyType(fields), tuple(members), ())


def _find_field_shape(op, field):
    # A module function, not a closure that calls itself: such a closure is a cycle.
    if op[0] == "field":
        return op[3] if op[2] == field else None
    if op[0] in ("seq", "repeat"):
        for child in op[1:]:
            if isinstance(child, tuple):
                found = _find_field_shape(child, field)
                if found is not None:
                    return found
    return None


def _field_shape(kind, field):
    op = _find_field_shape(READERS[TABLE_READERS[kind]], field)
    overrides = None
    for _label, program, gen_overrides in reversed(TABLE_GENERATIONS.get(kind, ())):
        if op is not None:
            break
        op = _find_field_shape(program, field)
        overrides = gen_overrides
    if op is None:
        raise RecordError("This compact static generation has no such field.")
    while op[0] == "call" or op[0] == "seq" and len(op) == 2:
        if op[0] == "call":
            op = overrides[op[1]] if overrides and op[1] in overrides else READERS[op[1]]
        else:
            op = op[1]
    return op


def field_payload(layout, field):
    """Return the declared field payload, or None for an absent optional value."""
    data = layout.data(field)
    if layout.generation == "compact" and _field_shape(layout.kind, field)[0] in ("optional", "presence"):
        return data[1:] if data[0] else None
    return data


def field_bytes(layout, field, payload):
    """Wrap an edited payload with the presence byte required by this field."""
    if layout.generation == "compact" and _field_shape(layout.kind, field)[0] in ("optional", "presence"):
        return b"\0" if payload is None else b"\1" + bytes(payload)
    if payload is None:
        raise RecordError("A required static field cannot be absent.")
    return bytes(payload)
