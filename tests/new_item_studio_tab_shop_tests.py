"""Shop selection in the New Item Studio: stability under rapid use, and the picker."""

from __future__ import annotations

from test_new_item_service import TEMPLATE

from cdmw.domain.new_item.spec import PlacementKind

CAMP = "Store_Camp_Equipment"
MARKET = "Store_Pai_BlackMarket"


class _TabShopPickerMixin:
    def _shop_tab(self):
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        return tab, tab.placement_panel

    def _count_invalidations(self, tab):
        counter = {"n": 0}
        tab.controller.plan_invalidated.connect(lambda: counter.__setitem__("n", counter["n"] + 1))
        return counter

    def test_one_shop_change_invalidates_the_plan_once(self) -> None:
        tab, placement = self._shop_tab()
        placement.swap.setChecked(True)
        self.assertTrue(placement.choose_store(MARKET))
        counter = self._count_invalidations(tab)
        self.assertTrue(placement.choose_store(CAMP))
        self.assertEqual(counter["n"], 1, "the stock line follows the shop in the same change")
        self.assertEqual(tab.controller.draft.store_name, CAMP)
        self.assertIn(CAMP, placement.store_summary.text())
        self.assertIn("Tranan", placement.store_summary.text(), "the confirmed merchant is named")

    def test_unknown_or_stale_shop_is_handled_without_exceptions(self) -> None:
        tab, placement = self._shop_tab()
        placement.swap.setChecked(True)
        self.assertTrue(placement.choose_store(CAMP))
        draft = tab.controller.draft
        self.assertIsNotNone(draft.stock_index)
        # a restored draft from another snapshot names a shop these tables lack
        placement._store_changed("Store_Gone")
        self.assertEqual(placement.old_item.count(), 0, "no stock lines of the previous shop remain selectable")
        self.assertIsNone(draft.stock_index)
        draft.stock_index = 0
        placement._refresh_requirement_note()
        placement._refresh_store_summary()
        self.assertEqual(placement.apply_shop_selection(["Store_Gone"]), "")

    def test_rapid_shop_changes_and_step_switches_stay_consistent(self) -> None:
        tab, placement = self._shop_tab()
        placement.swap.setChecked(True)
        for round_index in range(60):
            placement.choose_store(CAMP if round_index % 2 else MARKET)
            if round_index % 3 == 0:
                placement.old_item.showPopup()
            tab.show_step(4 if round_index % 2 else 6)
            tab.show_step(5)
            self.app.processEvents()
        draft = tab.controller.draft
        snapshot = tab.controller.snapshot
        lines = {entry.stock_index for entry in snapshot.store(draft.store_name).buyable_entries}
        self.assertIn(draft.stock_index, lines, "the stock line always belongs to the chosen shop")
        self.assertFalse(placement.old_item.view().isVisible(), "leaving the step closes the list")

    def test_picker_searches_names_and_ids_and_keeps_ticks_across_filters(self) -> None:
        from cdmw.ui.new_item.shop_picker import ShopPickerDialog

        tab, _placement = self._shop_tab()
        dialog = ShopPickerDialog(tab.controller.shop_choices(), multi=True)
        try:
            dialog.search.setText("tranan")
            self.assertEqual(dialog.proxy.rowCount(), 1, "the confirmed merchant name is searchable")
            dialog.set_checked(CAMP, True)
            dialog.search.setText("pai_blackmarket")
            self.assertEqual(dialog.proxy.rowCount(), 1, "internal IDs are searchable")
            dialog.set_checked(MARKET, True)
            dialog.search.setText("")
            self.assertEqual(dialog.selected_keys(), (CAMP, MARKET), "ticks survive filtering")
            self.assertIn("Selected (2)", dialog.selected_label.text())
            self.assertTrue(dialog.accept_button.isEnabled())
            market_row = next(
                row for row in range(dialog.model.rowCount())
                if dialog.model.item(row, 4).text() == MARKET
            )
            self.assertTrue(dialog.model.item(market_row, 0).text().endswith("*"), "a derived name is marked")
            self.assertIn("not confirmed", dialog.model.item(market_row, 0).toolTip())
        finally:
            dialog.deleteLater()

    def test_several_picked_shops_become_insert_routes_without_duplicates(self) -> None:
        tab, placement = self._shop_tab()
        placement.insert.setChecked(True)
        message = placement.apply_shop_selection([CAMP, MARKET])
        routes = tab.controller.draft.shop_placements
        self.assertEqual([(route.kind, route.store_name) for route in routes],
                         [(PlacementKind.INSERT, CAMP), (PlacementKind.INSERT, MARKET)])
        self.assertIn("Added 2", message)
        again = placement.apply_shop_selection([MARKET])
        self.assertEqual(len(tab.controller.draft.shop_placements), 2)
        self.assertIn("Shop:", again)
        again = placement.apply_shop_selection([CAMP, MARKET])
        self.assertIn("Skipped 2", again)
        self.assertEqual(len(tab.controller.draft.shop_placements), 2)
        self.assertEqual(len(tab.controller.current_spec().shop_placements), 2, "the routes reach the spec")

    def test_replace_mode_picker_chooses_one_shop(self) -> None:
        tab, placement = self._shop_tab()
        placement.swap.setChecked(True)
        placement.apply_shop_selection([MARKET, CAMP])
        self.assertEqual(tab.controller.draft.store_name, MARKET)
        self.assertIsNone(tab.controller.draft.shop_placements, "replacing never creates routes automatically")
        self.assertEqual(placement.choose_store_button.text(), "Choose shop...")
