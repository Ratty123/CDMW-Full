"""Game table edits: row views across base and DLC copies, composed base tables, DMM folders."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.core.static_table_records import TableFieldEdit, decode_static_table
from cdmw.services.game_table_edits import (
    TableEditError,
    TableLayer,
    compose_table_edits,
    load_table_index,
    target_label,
    write_table_edit_mod,
)
from tests.compact_item_fixtures import table
from tests.test_static_table_records import inventory_row

REPO = Path(__file__).resolve().parents[1]
ROOT = "gamedata/binarystaticinfo__/bin/"


def layers():
    """Base rows 1-3; the DLC copy replaces row 2 (different starting slots) and adds row 9."""
    base_body, base_header = table([(1, inventory_row(1, "Money", 20, 240)), (2, inventory_row(2, "Character", 50, 240)),
                                    (3, inventory_row(3, "Quest", 300, 300))], width=2)
    dlc_body, dlc_header = table([(2, inventory_row(2, "Character", 60, 240)), (9, inventory_row(9, "DlcHouse", 10, 99))],
                                 width=2)
    return [TableLayer("inventory", base_header, base_body), TableLayer("inventory.dlc_01", dlc_header, dlc_body)]


def row(layer, key):
    return next(r for r in decode_static_table("inventory", layer.header, layer.body).records if r.key == key)


def test_rows_come_from_the_copy_the_game_reads():
    index = load_table_index("inventory", layers())

    rows = {r.key: r for r in index.rows}
    assert rows[2].layer == "inventory.dlc_01" and rows[2].editable
    assert {v.label: v.value for v in rows[2].values} == {"Starting slots": 60, "Maximum slots": 240}
    assert rows[9].layer == "inventory.dlc_01" and not rows[9].editable
    assert rows[1].layer == "inventory" and rows[1].editable


def test_base_rows_are_edited_in_place_and_dlc_rows_carry_their_dlc_version():
    source = layers()

    composed = compose_table_edits("inventory", source, [
        TableFieldEdit("inventory", 1, "_maxSlotCount", 500), TableFieldEdit("inventory", 2, "_maxSlotCount", 480)])

    assert composed.stem == "inventory"
    assert (row(composed, 1).field("_maxSlotCount").value, row(composed, 1).field("_defaultSlotCount").value) == (500, 20)
    # The DLC's starting slots (60) survive: DMM would otherwise copy the base version over the DLC row.
    assert (row(composed, 2).field("_maxSlotCount").value, row(composed, 2).field("_defaultSlotCount").value) == (480, 60)
    assert row(composed, 3).field("_maxSlotCount").value == 300
    assert [r.key for r in decode_static_table("inventory", composed.header, composed.body).records] == [1, 2, 3]


def test_rows_only_the_dlc_has_and_tables_without_a_base_copy_are_refused():
    with pytest.raises(TableEditError, match="exists only in the DLC copy"):
        compose_table_edits("inventory", layers(), [TableFieldEdit("inventory", 9, "_maxSlotCount", 120)])
    with pytest.raises(TableEditError, match="exactly one base table copy"):
        compose_table_edits("inventory", layers()[1:], [TableFieldEdit("inventory", 2, "_maxSlotCount", 120)])
    with pytest.raises(TableEditError, match="outside"):
        compose_table_edits("inventory", layers(), [TableFieldEdit("inventory", 1, "_maxSlotCount", 70000)])


def test_member_targets_get_readable_labels():
    assert target_label("_maxSlotCount") == "Maximum slots"
    assert target_label(("_list", 2, "_percent"), "DropInfoData") == "Drop 3: drop chance"
    assert target_label(("_equipItemInfoList", 0, "_deadDropPercent"), "CharacterEquipmentData") == \
        "Equipment 1: drop chance on death"


@pytest.fixture
def accelerator(monkeypatch):
    from cdmw.core.archive_accelerator import ARCHIVE_ACCELERATOR_BINARY_NAME, find_native_archive_accelerator

    if find_native_archive_accelerator() is None:
        for root in (REPO, *REPO.parents):
            candidate = root / "native" / "cdmw_archive_accelerator" / "build" / "Release" / ARCHIVE_ACCELERATOR_BINARY_NAME
            if candidate.is_file():
                monkeypatch.setenv("CDMW_ARCHIVE_ACCELERATOR_BIN", str(candidate))
                break
        else:
            pytest.skip("needs the native archive accelerator")


def test_the_edited_pair_is_written_as_a_dmm_archive_group_mod(tmp_path, monkeypatch, accelerator):
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.models import ArchiveEntry
    from cdmw.services.game_table_edits import composed_files

    monkeypatch.setenv("CDMW_TEMP_CACHE_ROOT", str(tmp_path / "cache"))
    folder = tmp_path / "game" / "0008"
    folder.mkdir(parents=True)
    source = layers()

    def stored(path, payload):
        paz = folder / f"{len(list(folder.glob('*.paz')))}.paz"
        paz.write_bytes(payload)
        return ArchiveEntry(path, folder / "0.pamt", paz, 0, len(payload), len(payload), 0, 0)

    base = source[0]
    base = TableLayer(base.stem, base.header, base.body, (stored(ROOT + "inventory.staticinfoheader", base.header),
                                                          stored(ROOT + "inventory.staticinfobody", base.body)))
    edits = [TableFieldEdit("inventory", 1, "_maxSlotCount", 500)]
    composed = compose_table_edits("inventory", [base, source[1]], edits)

    result = write_table_edit_mod(composed_files(composed), parent=tmp_path / "mods", title="Bigger bags", edits=edits)

    assert result.folder == tmp_path / "mods" / "Bigger bags" and not result.replaced
    packaged = {item.path: read_archive_entry_data(item)[0] for item in parse_archive_pamt(result.folder / "0036" / "0.pamt")}
    assert packaged == {ROOT + "inventory.staticinfobody": composed.body, ROOT + "inventory.staticinfoheader": composed.header}
    manifest = json.loads((result.folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["structure"] == "archive_group" and manifest["manager_targets"] == ["dmm"]
    assert manifest["table_edits"] == [{"table": "inventory", "key": 1, "target": "_maxSlotCount", "value": 500}]
    assert "Maximum slots = 500" in (result.folder / "README.txt").read_text(encoding="utf-8")
    again = write_table_edit_mod(composed_files(composed), parent=tmp_path / "mods", title="Bigger bags", edits=edits)
    assert again.replaced

    taken = tmp_path / "mods" / "Taken"
    taken.mkdir()
    with pytest.raises(TableEditError, match="did not write it"):
        write_table_edit_mod(composed_files(composed), parent=tmp_path / "mods", title="Taken", edits=edits)


def _planner(edits, *, independent=False):
    from cdmw.services.new_item_snapshot import TablePair

    def entry(name):
        return SimpleNamespace(path=ROOT + name)

    pairs = tuple(TablePair(entry(f"{layer.stem}.staticinfobody"), entry(f"{layer.stem}.staticinfoheader"),
                            layer.body, layer.header) for layer in layers())
    patched = {}
    planner = SimpleNamespace(
        spec=SimpleNamespace(table_edits=tuple(edits)), independent=independent,
        snapshot=SimpleNamespace(metadata_pairs={"inventory": pairs}),
        table_data=lambda pair: (patched.get(pair.payload_entry.path, pair.payload),
                                 patched.get(pair.header_entry.path, pair.header)),
        patch=lambda target, data, _what: patched.__setitem__(target.path, bytes(data)),
        log=lambda _line: None)
    return planner, patched


def test_create_new_item_plans_table_edits_into_the_base_table():
    from cdmw.services.new_item_table_edits import plan_table_edits

    planner, patched = _planner([TableFieldEdit("inventory", 2, "_maxSlotCount", 480)])

    plan_table_edits(planner)

    composed = TableLayer("inventory", patched[ROOT + "inventory.staticinfoheader"], patched[ROOT + "inventory.staticinfobody"])
    assert row(composed, 2).field("_maxSlotCount").value == 480
    assert set(patched) == {ROOT + "inventory.staticinfobody", ROOT + "inventory.staticinfoheader"}


def test_create_new_item_refuses_table_edits_for_item_packages():
    from cdmw.services.new_item_planning import NewItemPlanError
    from cdmw.services.new_item_table_edits import plan_table_edits

    planner, _patched = _planner([TableFieldEdit("inventory", 2, "_maxSlotCount", 480)], independent=True)
    with pytest.raises(NewItemPlanError, match="DMM mod folders only"):
        plan_table_edits(planner)
