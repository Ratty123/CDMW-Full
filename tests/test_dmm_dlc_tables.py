"""Shop and group additions in the DLC's copies reach DMM through the base tables."""
import pytest

from cdmw.core.itemgroupinfo_table import parse_item_group_table
from cdmw.services.dmm_dlc_tables import DmmTableError, _stores, fold_dlc_additions
from dataclasses import replace

from cdmw.domain.new_item.spec import Placement, PlacementKind
from tests.test_new_item_compact_dlc import ROOT, setup, spec


def _shop_spec(name):
    return replace(spec(name), placement=Placement(kind=PlacementKind.INSERT, store_name="Store_Pai_BlackMarket"))


def _read(snapshot):
    return lambda path: snapshot.payload(path) if snapshot.has_entry(path) else None


def test_additions_to_dlc_copies_move_to_the_base_rows(tmp_path):
    service, snapshot = setup(tmp_path, dlc=True)
    plan = service.plan(_shop_spec("DmmFold"), snapshot, capture_independent=True)
    assert ROOT + "storeinfo.dlc_01.staticinfobody" in plan.loose_files
    folded = fold_dlc_additions(plan.loose_files, _read(snapshot))
    assert not [path for path in folded if ".dlc_01.staticinfo" in path and ("storeinfo" in path or "itemgroupinfo" in path)]
    key = plan.spec.item_key
    shops = _stores(folded[ROOT + "storeinfo.staticinfobody"], folded[ROOT + "storeinfo.staticinfoheader"])
    base_shops = _stores(snapshot.payload(ROOT + "storeinfo.staticinfobody"), snapshot.payload(ROOT + "storeinfo.staticinfoheader"))
    assert shops[2003].entries_for(key) and not base_shops[2003].entries_for(key)
    # The base row keeps its own lines; only the new one is added.
    assert [e.item_key for e in shops[2003].entries if e.item_key != key] == [e.item_key for e in base_shops[2003].entries]
    if ROOT + "itemgroupinfo.staticinfobody" in folded:
        groups = {row.key: row for row in parse_item_group_table(folded[ROOT + "itemgroupinfo.staticinfobody"],
                                                                  folded[ROOT + "itemgroupinfo.staticinfoheader"])}
        assert key in groups[17011].members


def test_a_shop_only_the_dlc_has_is_refused(tmp_path):
    service, snapshot = setup(tmp_path, dlc=True)
    plan = service.plan(_shop_spec("DmmFold"), snapshot, capture_independent=True)
    base = ROOT + "storeinfo.staticinfobody"

    def without_base_shop(path):
        if path in (base, ROOT + "storeinfo.staticinfoheader"):
            from tests.test_new_item_compact_dlc import TEMPLATE, store, table
            return table([(2004, store(2004, "Store_Other", [TEMPLATE]))], 2)[0 if path == base else 1]
        return _read(snapshot)(path)
    with pytest.raises(DmmTableError, match="only in the DLC"):
        fold_dlc_additions(plan.loose_files, without_base_shop)


def test_a_planned_item_reaches_dmm_as_operations_not_table_copies(tmp_path):
    from cdmw.services.dmm_dlc_tables import plan_for_dmm
    service, snapshot = setup(tmp_path, dlc=True)
    plan = service.plan(_shop_spec("DmmOps"), snapshot, capture_independent=True)
    dmm_plan, targets = plan_for_dmm(plan, _read(snapshot))
    assert not [path for path in dmm_plan.loose_files if "storeinfo" in path or "itemgroupinfo" in path]
    assert not [request for request in dmm_plan.patches if "storeinfo" in request.entry.path]
    shop = next(target for target in targets if target["file"] == "storeinfo.pabgb")
    assert [(intent["op"], intent["key"]) for intent in shop["intents"]] == [("array_append", 2003)]
    # Everything else the plan writes still goes to DMM as files.
    assert set(dmm_plan.loose_files) == {path for path in plan.loose_files
                                         if "storeinfo" not in path and "itemgroupinfo" not in path}


def test_adding_an_item_to_a_dmm_mod_keeps_the_earlier_items_operations(tmp_path):
    import json

    from cdmw.services.dmm_send import OPERATIONS_FILE, write_operations

    def group(key, item):
        return dict(file="itemgroupinfo.pabgb", intents=[dict(op="array_append", key=key, field="item_info_list", new=item)])

    def stock(item):
        return dict(file="storeinfo.pabgb", intents=[dict(op="array_append", key=2003, field="stock_data_list",
                                                          new={"lookup_a": 2003, "value": {"raw_q": item}})])

    folder = tmp_path / "mod"
    folder.mkdir()
    write_operations(folder, "Mod", [stock(1990000), group(17011, 1990000)], owned_items={1990000})
    write_operations(folder, "Mod", [stock(1990001), group(17011, 1990001)], owned_items={1990001})
    # Re-adding the first item to another group replaces only its own operations.
    write_operations(folder, "Mod", [stock(1990000), group(17010, 1990000)], owned_items={1990000})
    targets = json.loads((folder / OPERATIONS_FILE).read_text(encoding="utf-8"))["targets"]
    added = {(target["file"], intent["key"], intent["new"] if isinstance(intent["new"], int) else intent["new"]["value"]["raw_q"])
             for target in targets for intent in target["intents"]}
    assert added == {("storeinfo.pabgb", 2003, 1990000), ("storeinfo.pabgb", 2003, 1990001),
                     ("itemgroupinfo.pabgb", 17011, 1990001), ("itemgroupinfo.pabgb", 17010, 1990000)}
    assert sum(len(target["intents"]) for target in targets) == 4


def test_a_swap_placement_is_refused_for_dmm_with_its_reason(tmp_path):
    from cdmw.domain.new_item.rules import validate_spec
    from cdmw.services.dmm_dlc_tables import plan_for_dmm
    from tests.test_new_item_compact_dlc import TEMPLATE

    service, snapshot = setup(tmp_path, dlc=True)
    swap = replace(spec("DmmSwap"), placement=Placement(kind=PlacementKind.SWAP, store_name="Store_Pai_BlackMarket",
                                                         old_item_name=snapshot.rows[TEMPLATE].string_key))
    assert "placement.swap_not_for_dmm" in {issue.code for issue in validate_spec(swap)}
    plan = service.plan(swap, snapshot)  # A .cdmw package already refuses a swap.
    with pytest.raises(DmmTableError, match="Swap placement"):
        plan_for_dmm(plan, _read(snapshot))
