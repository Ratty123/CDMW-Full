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
