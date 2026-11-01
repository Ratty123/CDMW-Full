"""Bone-offset table: lossless entry copies for New Item, and per-entry composition."""
from dataclasses import replace
from uuid import uuid4

import pytest

from cdmw.core.bone_offset_table import (
    BONE_OFFSET_PATH, BoneOffsetTableError, clone_prefab_entries, parse_bone_offset_table, prefab_entry_names,
)
from cdmw.domain.archives.overlay_merge import OverlayConflict, merge_overlay_files

# The shipped layout: BOM, CRLF, Korean comments, `</>` closers and the other sections.
TABLE = '''﻿<!--
\tOffset 종류 - FootOffset, BoneOffset
-->

<BoneOffsetByPrefab>
\t<!-- Test용 -->
\t<BoneDesc PrefabName="phm_00_nude_01_0002_macduff">
\t\t<Skeleton>
\t\t</>
\t</>
\t<!-- 템플릿 -->
\t<BoneDesc PrefabName="cd_phm_01_sword_0109_r">
\t\t<Skeleton Path="1_pc/1_phm/nude/phm_00_nude_01_0002.pabc">
\t\t\t<Bone boneName="Bip01 R Forearm" Scale="1.0 1.1 1.1" IsCharacterSpace="false"/>
\t\t</>
\t</>
\t<BoneDesc PrefabName="Cd_Phw_00_Ub_00_0145">
\t\t<Skeleton>
\t\t\t<Bone boneName="Bip01 L Thigh" Scale="1.000 0.930 0.970" IsCharacterSpace="false"/>
\t\t</>
\t</>
</>

<BoneOffset>
\t<BoneDesc Tag="Chest01">
\t\t<Bone boneName="Bip01 R Chest" Rotation="0.391341 -9.74206 2.1903"/>
\t</>
</>

<EditableBoneList>
\t<Bone boneName="Bip01 Head"/>
</>
'''.replace("\n", "\r\n").encode("utf-8")


def entry(name, bone="Bip01 Head", scale="1.5 1.5 1.5"):
    return (f'\t<BoneDesc PrefabName="{name}">\r\n\t\t<Skeleton>\r\n'
            f'\t\t\t<Bone boneName="{bone}" Scale="{scale}" IsCharacterSpace="false"/>\r\n\t\t</>\r\n\t</>\r\n').encode()


def add(data, *names):
    table = parse_bone_offset_table(data)
    return data[:table.insert] + b"".join(entry(name) for name in names) + data[table.insert:]


def test_reads_the_shipped_layout_and_keeps_everything_else():
    table = parse_bone_offset_table(TABLE)
    assert [e.key for e in table.entries] == [b"phm_00_nude_01_0002_macduff", b"cd_phm_01_sword_0109_r", b"cd_phw_00_ub_00_0145"]
    assert prefab_entry_names(TABLE) == {"phm_00_nude_01_0002_macduff", "cd_phm_01_sword_0109_r", "cd_phw_00_ub_00_0145"}
    assert TABLE[table.insert:].startswith(b"</>\r\n\r\n<BoneOffset>")
    frame = table.frame()
    assert b"PrefabName" not in frame and b'Tag="Chest01"' in frame and b"<!-- Test\xec\x9a\xa9 -->" in frame
    assert all(table.raw(e).startswith(b"\t<BoneDesc") and table.raw(e).endswith(b"</>\r\n") for e in table.entries)


def test_copies_an_entry_under_the_new_prefab_name_only():
    result = clone_prefab_entries(TABLE, {"cd_phm_01_sword_0109_r": "cd_phm_01_sword_9109_r", "cd_phm_01_sword_0109_l": "cd_phm_01_sword_9109_l"})
    table = parse_bone_offset_table(result)
    assert [e.key for e in table.entries][-1] == b"cd_phm_01_sword_9109_r"
    copied, source = table.raw(table.entries[-1]), table.raw(table.entries[1])
    assert copied == source.replace(b"cd_phm_01_sword_0109_r", b"cd_phm_01_sword_9109_r")
    assert result.replace(copied, b"", 1) == TABLE
    # A rebuild on an earlier export keeps the identical copy; the name match is case-insensitive.
    assert clone_prefab_entries(result, {"CD_PHM_01_SWORD_0109_R": "cd_phm_01_sword_9109_r"}) == result
    assert clone_prefab_entries(TABLE, {"unknown": "cd_new_0001"}) == TABLE
    # Variants copy one template prefab several times.
    variants = clone_prefab_entries(TABLE, [("cd_phm_01_sword_0109_r", "cd_variant_a"), ("cd_phm_01_sword_0109_r", "cd_variant_b")])
    assert {"cd_variant_a", "cd_variant_b"} <= prefab_entry_names(variants)


@pytest.mark.parametrize("mapping,match", [
    ({"cd_phm_01_sword_0109_r": "cd_phw_00_ub_00_0145"}, "different entry"),
    ({"cd_phm_01_sword_0109_r": "bad name"}, "Invalid prefab name"),
])
def test_refuses_to_overwrite_or_invent_names(mapping, match):
    with pytest.raises(BoneOffsetTableError, match=match):
        clone_prefab_entries(TABLE, mapping)


def test_refuses_an_ambiguous_source():
    doubled = add(TABLE, "cd_phm_01_sword_0109_r")
    with pytest.raises(BoneOffsetTableError, match="2 entries"):
        clone_prefab_entries(doubled, {"cd_phm_01_sword_0109_r": "cd_new_r"})


@pytest.mark.parametrize("data", [
    b"<BoneOffset></>",  # no prefab section
    TABLE + b"<BoneOffsetByPrefab></>",  # two
    TABLE.replace(b"\t</>\r\n</>\r\n\r\n<BoneOffset>", b"\t</>\r\n\r\n<BoneOffset>", 1),  # unclosed
    TABLE.replace(b'PrefabName="Cd_Phw_00_Ub_00_0145"', b'PrefabName="  "'),
    TABLE.replace(b"<EditableBoneList>", b"<!DOCTYPE x><EditableBoneList>"),
    TABLE.replace(b'<Bone boneName="Bip01 Head"/>', b"<Bone boneName=Bip01/>"),
    TABLE.replace(b"</>\r\n\r\n<EditableBoneList>", b"</Other>\r\n\r\n<EditableBoneList>"),
    b"<BoneOffsetByPrefab/>",
    b"\xff<BoneOffsetByPrefab></>",
])
def test_unsupported_tables_are_refused(data):
    with pytest.raises(BoneOffsetTableError):
        parse_bone_offset_table(data)


# ---- composition ------------------------------------------------------------------------

def compose(before, after, current):
    return merge_overlay_files({BONE_OFFSET_PATH: before}, {BONE_OFFSET_PATH: after}, {BONE_OFFSET_PATH: current})[BONE_OFFSET_PATH]


def test_two_installs_keep_both_entries_and_remove_independently():
    first, second = add(TABLE, "cd_item_a"), add(TABLE, "cd_item_b")
    both = compose(TABLE, second, first)
    assert prefab_entry_names(both) >= {"cd_item_a", "cd_item_b"}
    assert both == add(TABLE, "cd_item_a", "cd_item_b")
    assert compose(first, TABLE, both) == second
    assert compose(second, TABLE, both) == first


def test_a_changed_entry_merges_unless_both_change_it():
    changed = TABLE.replace(b'Scale="1.000 0.930 0.970"', b'Scale="1.000 0.900 0.900"')
    other = add(TABLE, "cd_item_a")
    assert compose(TABLE, changed, other) == add(changed, "cd_item_a")
    with pytest.raises(OverlayConflict):
        compose(TABLE, changed, TABLE.replace(b'Scale="1.000 0.930 0.970"', b'Scale="1.000 0.800 0.800"'))


def test_changes_outside_prefab_entries_still_conflict_when_both_differ():
    tagged = TABLE.replace(b"2.1903", b"2.0000")
    assert compose(TABLE, tagged, add(TABLE, "cd_item_a")) == add(tagged, "cd_item_a")
    with pytest.raises(OverlayConflict):
        compose(TABLE, tagged, TABLE.replace(b"2.1903", b"1.0000"))
    with pytest.raises(OverlayConflict, match="Unsupported bone offset table"):
        compose(TABLE, add(TABLE, "cd_item_a"), b"<broken")


# ---- New Item -----------------------------------------------------------------------------

@pytest.fixture
def keyed_game(monkeypatch):
    import tests.test_new_item_provenance as provenance
    original = provenance.current_files

    def files():
        result = original()
        result[BONE_OFFSET_PATH] = TABLE
        return result
    monkeypatch.setattr(provenance, "current_files", files)


def imported_plan(path, **options):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_archive_overlay_manager import shop_spec
    from tests.test_independent_items import imported_game
    from tests.test_new_item_service import PAC_XML, imported_pac
    service, snapshot = imported_game(path)
    choice = replace(shop_spec("FittedItem"), model_source=ModelSource.IMPORTED)
    model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
    return snapshot, service.plan(choice, snapshot, model=model, **options)


def test_new_item_carries_the_template_fit_to_its_copied_prefab(tmp_path, keyed_game):
    snapshot, plan = imported_plan(tmp_path)
    [record] = plan.manifest["bone_offsets"]
    assert record["source_prefab"] == "cd_phm_01_sword_0109_r"
    output = record["output_prefab"]
    assert any(path.endswith(f"/{output}.prefab") for path in plan.loose_files)
    table = parse_bone_offset_table(plan.loose_files[BONE_OFFSET_PATH])
    assert table.entries[-1].key == output.encode()
    assert b"Bip01 R Forearm" in table.raw(table.entries[-1])
    assert snapshot.payload(BONE_OFFSET_PATH) == TABLE


def test_new_item_without_a_keyed_template_leaves_the_table_alone(tmp_path):
    snapshot, plan = imported_plan(tmp_path)
    assert "bone_offsets" not in plan.manifest
    assert BONE_OFFSET_PATH not in plan.loose_files


def test_independent_items_compose_their_entries_and_uninstall_cleanly(tmp_path, keyed_game):
    from cdmw.services.independent_item_package import from_plan, package_bytes
    from tests.test_independent_items import Backups, imported_game, load_registry, prepare_install, prepare_remove, snapshot_of
    packages = [from_plan(imported_plan(tmp_path / f"author-{i}", capture_independent=True)[1], uuid4().hex) for i in range(2)]
    imported_game(tmp_path / "recipient")
    root = tmp_path / "recipient/game"
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package) for package in packages], root).preparation)
    stems = {load_registry(root)["items"][package.identity]["stem"] for package in packages}
    names = prefab_entry_names(snapshot_of(root).payload(BONE_OFFSET_PATH))
    assert len(stems) == 2 and all(any(name.startswith(stem.lower()) for name in names) for stem in stems)
    first = load_registry(root)["items"][packages[0].identity]["stem"].lower()
    backups.apply(prepare_remove(packages[0].identity, root))
    remaining = prefab_entry_names(snapshot_of(root).payload(BONE_OFFSET_PATH))
    assert not any(name.startswith(first) for name in remaining)
    assert len(remaining) == len(names) - 1
