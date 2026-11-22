"""Add to existing mod on a DMM mod reads the earlier items' operations back.

A DMM export carries new parts, shop lines and group members only as operations in
"CDMW items - shops and groups.json". The mod base must apply them, or the next item
cannot use an earlier item as its template and the earlier items have no shops or groups.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from cdmw.core.itemgroupinfo_table import groups_containing
from cdmw.domain.new_item.spec import ModelSource, NewItemSpec, Placement, PlacementKind
from cdmw.services.dmm_mod_base import OPERATIONS_FILE, DmmOperationsError
from cdmw.services.new_item_mod_base import build_mod_base_snapshot
from cdmw.services.new_item_planning import ModelFiles


def _own_model_setup(tmp_path):
    from tests.test_new_item_provenance import TEMPLATE, _read, setup_game

    service, snapshot, _ = setup_game(tmp_path)
    pac = next(f for f in snapshot.family(TEMPLATE).files_for("pac") if f.exists)
    spec = NewItemSpec(template_key=TEMPLATE, internal_name="First", display_names={"eng": "First"},
                       model_source=ModelSource.IMPORTED, keep_template_physics=True)
    return service, snapshot, _read, service.plan(spec, snapshot, model=ModelFiles(pac_data=snapshot.payload(pac.path)))


@pytest.mark.parametrize("manager", ["CDUMM", "DMM"])
def test_own_model_item_keeps_its_parts_in_the_mod_base(tmp_path, manager):
    service, snapshot, read, first = _own_model_setup(tmp_path)
    new_parts = {Path(p).stem for p in first.new_paths if p.endswith(".prefab")}
    assert new_parts
    folder = tmp_path / "mod"
    service.export_loose(first, folder, manager=manager)
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=read)
    family = base.family(first.spec.item_key)
    stems = set(family.owned_stems) | set(family.borrowed_stems) | {family.model_stem}
    assert new_parts <= stems, (sorted(new_parts), sorted(stems))
    # The earlier item works as a template for the next one.
    second = service.plan(NewItemSpec(template_key=first.spec.item_key, internal_name="Second",
                                      display_names={"eng": "Second"}), base)
    assert second.spec.item_key != first.spec.item_key


def _targets(folder):
    return json.loads((folder / OPERATIONS_FILE).read_text(encoding="utf-8"))["targets"]


def _intents(folder):
    return [(target["file"], json.dumps(intent, sort_keys=True)) for target in _targets(folder)
            for intent in target["intents"]]


def test_a_second_dmm_export_restates_the_first_items_parts_once(tmp_path):
    service, snapshot, read, first = _own_model_setup(tmp_path)
    folder = tmp_path / "mod"
    service.export_loose(first, folder, manager="DMM")
    before = _intents(folder)
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=read)
    second = service.plan(NewItemSpec(template_key=first.spec.item_key, internal_name="Second",
                                      display_names={"eng": "Second"}), base)
    service.export_loose(second, folder, manager="DMM", replace_existing=True)
    after = _intents(folder)
    assert len(after) == len(set(after))
    assert set(before) <= set(after)


def _shop_spec(name, **changes):
    from tests.test_new_item_provenance import spec
    return replace(spec(name), placement=Placement(kind=PlacementKind.INSERT, store_name="Store_Pai_BlackMarket"),
                   **changes)


@pytest.mark.parametrize("dlc", [False, True])
def test_the_mod_base_has_the_earlier_items_shop_lines_and_groups(tmp_path, dlc):
    from tests.test_new_item_compact_dlc import setup

    service, snapshot = setup(tmp_path, dlc=dlc)
    first = service.plan(_shop_spec("DmmFirst"), snapshot, capture_independent=True)
    first_key = first.spec.item_key
    folder = tmp_path / "Armor"
    service.export_loose(first, folder, manager="DMM")
    assert {target["file"] for target in _targets(folder)} >= {"storeinfo.pabgb", "itemgroupinfo.pabgb"}
    before = _intents(folder)
    base = build_mod_base_snapshot(service, snapshot, folder, read_entry=snapshot.provenance.reader)
    assert base.store("Store_Pai_BlackMarket").entries_for(first_key)
    expected = {row.key for row in groups_containing(snapshot.item_groups, first.spec.template_key)}
    assert expected
    assert {row.key for row in groups_containing(base.item_groups, first_key)} == expected
    # A clone of the earlier item joins the same groups, and the second export keeps
    # the first item's operations exactly once.
    second = service.plan(replace(_shop_spec("DmmSecond"), template_key=first_key), base)
    service.export_loose(second, folder, manager="DMM", replace_existing=True)
    after = _intents(folder)
    assert len(after) == len(set(after))
    assert set(before) <= set(after)
    groups = {(intent["key"], intent["new"]) for target in _targets(folder) if target["file"] == "itemgroupinfo.pabgb"
              for intent in target["intents"]}
    assert {key for key, item in groups if item == second.spec.item_key} == expected
    stock = [intent["new"]["value"]["raw_q"] for target in _targets(folder) if target["file"] == "storeinfo.pabgb"
             for intent in target["intents"]]
    assert sorted(stock) == sorted([first_key, second.spec.item_key])


def _write(folder, targets):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / OPERATIONS_FILE).write_text(json.dumps(dict(format=3, targets=targets)), encoding="utf-8")


def test_operations_cdmw_did_not_write_are_refused(tmp_path):
    from cdmw.services.dmm_mod_base import fold_operations, read_operations
    from tests.test_new_item_compact_dlc import TEMPLATE, setup

    service, snapshot = setup(tmp_path)
    group = lambda item, **extra: dict(op="array_append", key=17011, field="item_info_list", new=item, **extra)  # noqa: E731
    for targets, message in (
        ([dict(file="iteminfo.pabgb", intents=[])], "does not write"),
        ([dict(file="itemgroupinfo.pabgb", intents=[group(1990000, extra=1)])], "does not write"),
        ([dict(file="itemgroupinfo.pabgb", intents=[group(TEMPLATE)])], "not one of the mod's own"),
        ([dict(file="itemgroupinfo.pabgb", intents=[dict(group(1990000), key=4242)])], "does not have"),
    ):
        folder = tmp_path / f"case{len(message)}"
        _write(folder, targets)
        with pytest.raises(DmmOperationsError, match=message):
            fold_operations(snapshot, {}, read_operations(folder))
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / OPERATIONS_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(DmmOperationsError, match="not a DMM V3"):
        read_operations(tmp_path / "bad")
    assert read_operations(tmp_path / "none") is None


def test_stock_bytes_inverts_stock_value(tmp_path):
    from cdmw.core.dmm_item_fields import stock_bytes, stock_value
    from cdmw.core.new_item_record import RecordError
    from cdmw.core.storeinfo_table import encode_stock_entry
    from tests.test_new_item_compact_dlc import setup

    _service, snapshot = setup(tmp_path)
    for entry in snapshot.store("Store_Pai_BlackMarket").entries:
        raw = encode_stock_entry(entry)
        assert stock_bytes(stock_value(raw)) == raw
    value = stock_value(raw)
    with pytest.raises(RecordError):
        stock_bytes({**value, "effect_list": "x"})


def test_append_stock_renumbers_stock_index_on_dlc_override(tmp_path):
    from types import SimpleNamespace

    from cdmw.core.dmm_item_fields import stock_value
    from cdmw.core.storeinfo_table import encode_stock_entry, parse_store_table
    from cdmw.services.dmm_mod_base import fold_operations
    from tests.compact_item_fixtures import store, table
    from tests.test_new_item_compact_dlc import ROOT, setup
    from tests.test_new_item_service import TEMPLATE

    _service, snapshot = setup(tmp_path, dlc=True)
    dlc_body, dlc_head = table([(2003, store(2003, "Store_Pai_BlackMarket", [TEMPLATE, TEMPLATE + 1]))], 2)
    payloads = {
        (ROOT + "storeinfo.dlc_01.staticinfobody").lower(): SimpleNamespace(read_bytes=lambda data=dlc_body: data),
        (ROOT + "storeinfo.dlc_01.staticinfoheader").lower(): SimpleNamespace(read_bytes=lambda data=dlc_head: data),
    }
    base_entry = snapshot.store("Store_Pai_BlackMarket").entries[0]
    new_entry = replace(base_entry, item_key=1990001, stock_index=1)
    targets = [{"file": "storeinfo.pabgb", "intents": [
        {"op": "array_append", "key": 2003, "field": "stock_data_list",
         "new": stock_value(encode_stock_entry(new_entry))}]}]
    folded = fold_operations(snapshot, payloads, targets)
    out_body = folded[(ROOT + "storeinfo.dlc_01.staticinfobody").lower()]
    out_head = folded[(ROOT + "storeinfo.dlc_01.staticinfoheader").lower()]
    rows = parse_store_table(out_body, out_head, layout="current")
    assert [entry.stock_index for entry in rows[0].entries] == [0, 1, 2]
