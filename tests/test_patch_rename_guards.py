"""Name lookups a game patch has renamed out from under the app, checked on the installed game.

Each test here guards one entry of the local patch register (`docs/patch-regressions.md`
in the main checkout). The 1.0.0.3446 DLC update renamed player bodies, part roles, icon
strings and static tables; each rename switched a feature off without an error, and the
owned-fixture tests kept passing. These tests run the app's own lookups over the shipped
files, so a rename on a later patch fails here instead.

Read-only: archive indexes and entries are read, nothing is written and the game is not
launched. Floors are set a little under the 1.0.0.3663 counts noted beside them.
"""

from __future__ import annotations

import collections
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_game

_TABLE_ROOTS = ("gamedata/binary__/client/bin/", "gamedata/binarystaticinfo__/bin/", "gamedata/stringtable/binary__/")
_ICON_REGISTRY = "ui/xml/texture/cd_item_icon.xml"
_KLIFF_DESCRIPTION = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
_PAPPT_PATHS = ("character/bin__/partprefabtable.pappt", "character/bin__/partprefabtable_dlc_01.pappt")


class _Game:
    """The installed game's archive entries, by normalized path (first package wins)."""

    def __init__(self, root: Path) -> None:
        from tools.placement_studio import corpus

        self.entries = []
        self.by_path = {}
        for _package, entry in corpus._iter_archive_entries(root):
            self.entries.append(entry)
            self.by_path.setdefault(corpus.normalize_game_path(entry.path), entry)

    def read_entry(self, entry) -> bytes:
        from cdmw.core.archive_extraction import read_archive_entry_data

        return bytes(read_archive_entry_data(entry)[0])

    def read(self, path: str) -> bytes:
        entry = self.by_path.get(path)
        assert entry is not None, f"the installed game no longer ships {path}"
        return self.read_entry(entry)

    def table_sources(self):
        from cdmw.core.item_sources import resolve_item_data_sources
        from tools.placement_studio import corpus

        metadata = [e for e in self.entries if corpus.normalize_game_path(e.path).startswith(_TABLE_ROOTS)]
        return resolve_item_data_sources(metadata, read_entry=self.read_entry)


@pytest.fixture(scope="module")
def game() -> _Game:
    from tools.placement_studio import corpus

    root = Path(os.environ.get("CDMW_GAME_ROOT") or corpus.game_root())
    if not root.is_dir():
        pytest.skip("needs the installed game")
    return _Game(root)


@pytest.fixture(scope="module")
def sources(game):
    return game.table_sources()


@pytest.fixture(scope="module")
def pappt_slots(game) -> collections.Counter:
    from cdmw.core.pappt_format import parse_pappt

    slots = collections.Counter()
    for path in _PAPPT_PATHS:
        for record in parse_pappt(game.read(path), name=path).records:
            slots.update(part.name for part in record.parts)
    return slots


# --------------------------------------------------------------------------- P-17


def test_p17_hair_tools_find_each_characters_head_and_base_body(game):
    """Hair Tools' reference matcher finds every playable character's heads and bodies.

    1.0.0.3446 renamed `cd_phw_00_nude_*` to `phw_00_nude_*` and Hair Tools found no body.
    On 1.0.0.3663 the matcher accepts 96/6 (Kliff), 139/14 (Damiane) and 12/4 (Oongka)
    heads/bodies; Oongka's heads still carry `cd_`.
    """

    from cdmw.domain.hair_characters import HAIR_CHARACTERS

    paths = [p for p in game.by_path if p.startswith("character/model/1_pc/") and p.endswith(".pac")]
    for profile in HAIR_CHARACTERS:
        assert profile.appearance_path in game.by_path, (profile.name, profile.appearance_path)
        assert profile.mesh_param_path in game.by_path, (profile.name, profile.mesh_param_path)
        heads = [p for p in paths if profile.accepts_reference(p, "head")]
        bodies = [p for p in paths if profile.accepts_reference(p, "body")]
        assert len(heads) >= 5 and len(bodies) >= 3, (profile.name, len(heads), len(bodies))
        # Every shipped nude PAC of the family must still match, whichever prefix it has:
        # a new prefix (or a second rename) would leave some or all of them unmatched.
        nude = [p for p in paths if p.startswith(f"character/model/1_pc/{profile.reference_family}/")
                and "/nude/" in p and "_00_nude_" in p.rsplit("/", 1)[1]]
        assert sorted(nude) == sorted(bodies), (profile.name, sorted(set(nude) - set(bodies))[:5])


def test_p17_attachment_preview_finds_its_preferred_base_bodies(game):
    """Archive Browser's attachment preview finds a preferred body per family.

    Mirrors the preferred names in `ArchiveAttachmentVisualCoreMixin` (bare form first,
    then `cd_`). All five resolve in the bare form on 1.0.0.3663.
    """

    basenames = collections.defaultdict(set)
    for path in game.by_path:
        if path.startswith("character/model/1_pc/") and path.endswith(".pac"):
            basenames[path.rsplit("/", 1)[1]].add(path)
    preferred = {
        "phw": ("phw_00_nude_00_0001.pac", "phw_00_nude_00_0001_damian.pac"),
        "phm": ("phm_00_nude_10_0001.pac", "phm_00_nude_00_0001.pac", "phm_00_nude_00_4001.pac"),
    }
    for family, names in preferred.items():
        found = [path for name in names for form in (name, f"cd_{name}") for path in basenames.get(form, ())]
        assert found, f"no preferred {family} base body ships under either name: {names}"


# --------------------------------------------------------------------------- P-18


def test_p18_part_roles_are_read_from_current_player_weapon_prefabs(game, pappt_slots):
    """The prefab part-role reader still recognises the shipped weapon roles.

    1.0.0.3446 dropped `CD_` from every part role and the reader detected 0 of 1,280
    roles. On 1.0.0.3663: 1,353 placed player weapon prefabs, 1,351 roles (two traps
    have none), every role also a `.pappt` part slot.
    """

    from cdmw.core.archive_attachment_patches import (
        inspect_prefab_attachment_profile_fields,
        inspect_prefab_socket_name_fields,
    )
    from cdmw.domain.part_names import bare_part_name

    prefabs = sorted(p for p in game.by_path
                     if p.startswith("character/bin__/prefab/1_pc/") and "/weapon/" in p and p.endswith(".prefab"))
    placed, roles, missing = 0, collections.Counter(), []
    for path in prefabs:
        data = game.read(path)
        if len(inspect_prefab_socket_name_fields(data)) != 2:
            continue
        placed += 1
        fields = {field.field_name: field.value for field in inspect_prefab_attachment_profile_fields(data)}
        if "_partName" in fields:
            roles[fields["_partName"]] += 1
        else:
            missing.append(path)
    detected = sum(roles.values())
    assert placed >= 1300, placed
    assert detected >= placed * 0.99, (detected, placed, missing[:5])
    slots = {bare_part_name(name) for name in pappt_slots}
    unknown = sorted(role for role in roles if bare_part_name(role) not in slots)
    assert not unknown, f"prefab roles no .pappt slot has: {unknown[:10]}"


def test_p18_part_names_the_code_uses_still_exist_in_the_game(game, pappt_slots):
    """Part names the code keys on are still the game's names, in either form.

    `.pappt` held 26,201 part slots on 1.0.0.3663, none with `CD_`; the sword roles
    `MainWeapon_Sword_R`/`_L` filled 131/128 of them.
    """

    from cdmw.domain.part_names import find_part_name
    from tools.placement_studio.model import SWORD_ROW

    assert sum(pappt_slots.values()) >= 25000, sum(pappt_slots.values())
    for wanted in (SWORD_ROW, "MainWeapon_Sword_R", "MainWeapon_Sword_L", "MainWeapon_Sword_IN_R", "MainWeapon_Sword_IN_L"):
        assert find_part_name(pappt_slots, wanted), f".pappt has no part slot named {wanted} in either form"


def test_p18_dual_sword_templates_patch_kliffs_description(game):
    """The dual-sword templates still find Kliff's four sword rows.

    After the rename they patched nothing and said nothing. On 1.0.0.3663 each template
    changes 12 values across the four rows (the `_Aux` rows are gone from the game).
    """

    from cdmw.core.weapon_swap_templates import build_part_in_out_weapon_swap_template_patch
    from cdmw.domain.part_names import same_part_name

    text = game.read(_KLIFF_DESCRIPTION).decode("utf-8-sig")
    wanted = ("MainWeapon_Sword_R", "MainWeapon_Sword_IN_R", "MainWeapon_Sword_L", "MainWeapon_Sword_IN_L")
    for template in ("dual_onehand_back_crossed", "dual_onehand_back_parallel"):
        result = build_part_in_out_weapon_swap_template_patch(text, template)
        assert result.diffs, f"{template} changed nothing in {_KLIFF_DESCRIPTION}"
        for role in wanted:
            assert any(same_part_name(name, role) for name in result.patched_part_names), (template, role, result.patched_part_names)


# --------------------------------------------------------------------------- P-19


def test_p19_item_icon_strings_resolve_in_the_icon_registry(game, sources):
    """ItemInfo icon strings are found and resolve in the icon registry, lower case included.

    1.0.0.3446 wrote many as `itemicon_prefab_<stem>`, which the family lookup missed.
    On 1.0.0.3663: base 5,635 icon strings (371 lower case), 5,634 resolve; DLC 1,395
    (125 lower case), 1,393 resolve. The registry has 9,400 names.
    """

    from cdmw.core.item_icon_registry import registered_icon_names
    from cdmw.core.item_model_family import ICON_STRING_PREFIX, find_icon_string
    from cdmw.core.iteminfo_row import parse_iteminfo_row
    from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index
    from cdmw.core.structured_binary_editor import parse_pabgh_table

    assert sources.static_layout
    registry = {name.casefold() for name in registered_icon_names(game.read(_ICON_REGISTRY))}
    assert len(registry) >= 9000, len(registry)

    def pair(stem):
        body, header = sources.tables[stem]
        return game.read_entry(body), game.read_entry(header)

    texts = {}
    for stem in sorted(s for s in sources.tables if s.split(".", 1)[0] == "stringinfo"):
        texts.update(stringinfo_index(parse_stringinfo(*pair(stem), name=stem)))
    item_stems = sorted(s for s in sources.tables if s.split(".", 1)[0] == "iteminfo")
    assert "iteminfo" in item_stems and len(item_stems) >= 2, item_stems

    rows = found = resolved = lower = lower_resolved = 0
    unresolved = []
    for stem in item_stems:
        payload, header = pair(stem)
        spans = parse_pabgh_table(header, payload=payload).row_spans(len(payload))
        keys = {row.row_id for row, _start, _end in spans}
        for _row, start, end in spans:
            rows += 1
            _key, text = find_icon_string(parse_iteminfo_row(payload[start:end], item_keys=keys), texts)
            if text is None:
                continue
            found += 1
            hit = text.casefold() in registry
            resolved += hit
            if not text.startswith(ICON_STRING_PREFIX):
                lower += 1
                lower_resolved += hit
            if not hit:
                unresolved.append(text)
    assert rows >= 8000, rows
    assert found >= 6500 and found >= rows * 0.75, (found, rows)
    assert resolved >= found * 0.995, (resolved, found, unresolved[:5])
    assert lower >= 300 and lower_resolved == lower, (lower, lower_resolved, unresolved[:5])


# --------------------------------------------------------------------------- P-09


def test_p09_every_table_the_app_reads_exists_under_its_current_or_legacy_name(sources):
    """Every static table the app reads by name resolves, and the legacy aliases still work.

    1.0.0.3446 renamed `skillinfo` to `skill` and `reserveslotinfo` to `reserveslot`; skill
    settings then read as removed by the update. 1.0.0.3663 ships 212 static table bodies,
    215 sources with the aliases.
    """

    from cdmw.core.item_sources import STATIC_TABLE_LEGACY_NAMES
    from cdmw.core.static_table_records import DECODED_TABLES, LEGACY_TABLE_STEMS, table_kind_for_stem
    from cdmw.services.new_item_behavior import BEHAVIOR_TABLES
    from cdmw.services.new_item_definition import REFERENCE_TABLES

    assert sources.static_layout, "the installed game no longer has the static table layout"
    tables = sources.tables

    # The two alias maps must describe the same renames, in opposite directions.
    assert dict(LEGACY_TABLE_STEMS) == {legacy: current for current, legacy in STATIC_TABLE_LEGACY_NAMES.items()}
    for current, legacy in STATIC_TABLE_LEGACY_NAMES.items():
        assert current in tables, f"the renamed table {current} is gone; find its new name"
        assert tables[legacy] is tables[current], (legacy, current)
        for stem in [s for s in tables if s.startswith(current + ".")]:
            assert tables[legacy + stem[len(current):]] is tables[stem], stem

    # Tables Create New Item reads by name: the snapshot, settings, behaviour and
    # definition indexes, dyes and equipment bonuses.
    named = {
        "iteminfo", "stringinfo", "storeinfo", "itemgroupinfo", "statusinfo", "equiptypeinfo", "multichangeinfo",
        "itemuseinfo", "dropsetinfo", "skillinfo", "reserveslotinfo", "conditioninfo", "sublevelinfo",
        "buffinfo", "effectinfo", "partprefabdyeslotinfo",
        *BEHAVIOR_TABLES, *REFERENCE_TABLES,
    }
    missing = sorted(name for name in named if name not in tables)
    assert not missing, f"tables the app reads by name are not shipped under that name: {missing}"

    # Every table with a closed record schema ships under its schema name (or a legacy
    # one the schema maps). `detectdetailinfo` has a reader but no shipped file on
    # 1.0.0.3663 under any name.
    not_shipped = {"detectdetailinfo"}
    shipped = {table_kind_for_stem(stem) for stem in tables}
    absent = sorted(kind for kind in DECODED_TABLES - not_shipped if kind not in shipped)
    assert not absent, f"decoded tables no longer shipped under a known name: {absent}"
    assert len(tables) >= 200, len(tables)
