"""Multiple shop edits must preserve exact duplicate-entry identity and quantities."""
from dataclasses import replace
from PySide6.QtWidgets import QApplication

from cdmw.domain.new_item.spec import Placement, PlacementKind
from cdmw.services.new_item_shops import plan_shops
from cdmw.core.storeinfo_table import parse_store_table, apply_store_row
from cdmw.ui.new_item.panels_placement import PlacementPanel
from cdmw.ui.new_item.controller import NewItemStudioController
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import TEMPLATE


def test_multiple_operations_on_one_store_preserve_other_duplicates(tmp_path):
    service,snapshot,_=setup_game(tmp_path)
    store=snapshot.stores[0]
    first=store.buyable_entries[0]
    duplicate=replace(first,stock_index=1,order_index=1,count=9)
    third=replace(first,stock_index=2,order_index=2,count=11)
    store=replace(store,entries=(first,duplicate,third),buyable_count=3,sellable_count=0)
    snapshot.stores=(store,*snapshot.stores[1:])
    pair=snapshot.storeinfo
    body,header=apply_store_row(pair.payload,pair.header,store)
    name=snapshot.rows[first.item_key].string_key
    choice=replace(spec(),item_key=1990000,shop_placements=(
        Placement(PlacementKind.SWAP,store.name,name,stock_index=duplicate.stock_index,stock_count=4),
        Placement(PlacementKind.SWAP,store.name,name,stock_index=third.stock_index,stock_count=7),))
    body,header,*_=plan_shops(choice,snapshot,body,header)
    edited=next(s for s in parse_store_table(body,header,layout="current") if s.key==store.key)
    assert edited.entries[0].item_key==first.item_key
    assert sorted(e.count for e in edited.entries if e.item_key==1990000)==[4,7]
    assert all(e.condition_data==bytes(8) for e in edited.entries)


def test_shop_widget_captures_exact_entry_and_count(tmp_path):
    app=QApplication.instance() or QApplication([])
    _,snapshot,_=setup_game(tmp_path)
    controller=NewItemStudioController(synchronous=True)
    controller.snapshot=snapshot
    controller.set_template(TEMPLATE)
    panel=PlacementPanel(controller)
    panel._refresh_stores()
    panel.swap.setChecked(True)
    panel.old_item.setCurrentIndex(1)
    panel.unlimited_stock.setChecked(False)
    panel.stock_count.setValue(12)
    route=controller.current_spec().placement
    assert route.stock_index==snapshot.store(route.store_name).buyable_entries[1].stock_index
    assert route.stock_count==12
    panel.shop_routes.add.click()
    assert controller.current_spec().shop_placements==(route,)
    controller.shutdown()
