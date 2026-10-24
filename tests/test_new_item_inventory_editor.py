import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from cdmw.domain.new_item.item_inventory import ItemInventorySettings, MaterialGroup, ReserveSlotTarget
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.state import NewItemDraft
from cdmw.ui.new_item.rust_ui_document import PresentationDocument
from tests.test_independent_item_settings import extended_game
from tests.test_independent_item_inventory import inventory_game
from tests.test_independent_items import setup_game
from tests.test_new_item_settings_editor import native_edit


def controls(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(service=service, synchronous=True)
    controller.snapshot = snapshot
    controller.draft = NewItemDraft(template_key=1001295, internal_name='Inventory', display_names={'eng': 'Inventory'})
    panel = StatsPanel(controller)
    panel.rebuild()
    return controller, panel, panel.item_settings.inventory


def test_inventory_editor_retains_raw_ids_flags_pairs_clear_and_template_reset(tmp_path, inventory_game):
    app = QApplication.instance() or QApplication([])
    controller, panel, editor = controls(tmp_path)
    try:
        assert editor.isEnabled()
        assert editor.lists['material_groups'].text() == '17010:4294967295'
        editor.policies['use_immediately'].setCurrentIndex(editor.policies['use_immediately'].findData(False))
        editor.numbers['quick_slot_index'].setText('0'); editor.numbers['quick_slot_index'].editingFinished.emit()
        editor.overrides['tags'].setChecked(True)
        editor.lists['tags'].setText('0; 4,294,967,295'); editor.lists['tags'].editingFinished.emit()
        assert controller.current_spec().inventory_settings.tags == (0, 0xffffffff)
        editor.lists['tags'].setText('2; 2'); editor.lists['tags'].editingFinished.emit()
        assert editor.lists['tags'].text() == '0; 4294967295'
        assert 'Invalid' in editor.message.text()
        editor.numbers['quick_slot_index'].setText('256'); editor.numbers['quick_slot_index'].editingFinished.emit()
        assert controller.draft.inventory_settings.quick_slot_index == 0
        for name, text in (('material_groups', '17011:4,294,967,295'), ('reserve_slots', '800002:0')):
            editor.overrides[name].setChecked(True)
            editor.lists[name].setText(text); editor.lists[name].editingFinished.emit()
        choice = controller.current_spec().inventory_settings
        assert choice.material_groups == (MaterialGroup(17011, 0xffffffff),)
        assert choice.reserve_slots == (ReserveSlotTarget(800002, 0),)
        editor.lists['tags'].clear(); editor.lists['tags'].editingFinished.emit()
        assert controller.draft.inventory_settings.tags == ()
        editor.overrides['tags'].setChecked(False)
        assert controller.draft.inventory_settings.tags is None
        editor.reset.click()
        assert controller.draft.inventory_settings is None
        assert editor.lists['tags'].text() == '9876; 5432'
        editor.overrides['consumable_types'].setChecked(True)
        panel._reset()
        assert controller.draft.inventory_settings is None
        editor.overrides['tags'].setChecked(True)
        controller.set_template(1005300)
        assert controller.draft.inventory_settings is None
        controller.snapshot = None; panel.rebuild()
        assert not editor.isEnabled() and editor.lists['tags'].text() == ''
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()


def test_native_stack_edit_is_exact_to_u64_and_keeps_legacy_small_values(tmp_path, inventory_game):
    app = QApplication.instance() or QApplication([])
    controller, panel, editor = controls(tmp_path)
    try:
        assert panel.max_stack.text() == ''
        assert panel.max_stack.placeholderText() == str((1 << 40) + 19)
        document = PresentationDocument()
        def edit(value):
            native_edit(document, panel, panel.max_stack, 'text', value)
            native_edit(document, panel, panel.max_stack, 'finish_edit')
        for value in ('18,446,744,073,709,551,615', '9,007,199,254,740,993'):
            edit(value)
            assert controller.current_spec().inventory_settings.max_stack_count == int(value.replace(',', ''))
            assert controller.draft.max_stack_count is None
        editor.overrides['tags'].setChecked(True)
        editor.reset.click()
        assert controller.draft.inventory_settings == ItemInventorySettings(max_stack_count=9007199254740993)
        for invalid in ('18,446,744,073,709,551,616', '0', '3.5'):
            edit(invalid)
            assert controller.current_spec().inventory_settings.max_stack_count == 9007199254740993
        edit('4,294,967,295')
        assert controller.current_spec().max_stack_count == 0xffffffff
        assert controller.draft.inventory_settings is None
        edit(str((1 << 40) + 19))
        assert controller.draft.max_stack_count is None and controller.draft.inventory_settings is None
        edit('5')
        assert controller.current_spec().max_stack_count == 5 and controller.draft.inventory_settings is None
        # The actual panel specification still lowers to a frozen v1 package.
        from uuid import uuid4
        from cdmw.services.independent_item_package import from_plan, package_metadata
        plan = controller.service.plan(controller.current_spec(), controller.snapshot, capture_independent=True)
        package = from_plan(plan, uuid4().hex)
        assert package_metadata(package)['version'] == 1
        from cdmw.core.structured_binary_editor import parse_pabgh_table
        from cdmw.core.iteminfo_inventory import read_item_inventory
        pair = controller.snapshot.iteminfo
        body, header = plan.loose_files[pair.payload_entry.path], plan.loose_files[pair.header_entry.path]
        raw = next(body[start:end] for entry, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body))
                   if entry.row_id == plan.spec.item_key)
        assert read_item_inventory(raw).max_stack_count == 5
        edit('')
        assert controller.draft.max_stack_count is None
        edit(str((1 << 64) - 1))
        panel._reset()
        assert controller.draft.max_stack_count is None and controller.draft.inventory_settings is None
        controller.set_template(1005300)
        panel.rebuild()
        assert panel.max_stack.placeholderText() == str(controller.snapshot.rows[1005300].max_stack_count)
        edit(str((1 << 64) - 1))
        assert controller.current_spec().inventory_settings.max_stack_count == (1 << 64) - 1
        package = from_plan(controller.service.plan(controller.current_spec(), controller.snapshot,
                            capture_independent=True), uuid4().hex)
        assert package.manifest['requires'] == {'item.legacy': 1, 'item.properties': 2, 'item.inventory': 1}
    finally:
        panel.deleteLater(); controller.deleteLater(); app.processEvents()
