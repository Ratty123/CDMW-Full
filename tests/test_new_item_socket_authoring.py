import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.domain.new_item.authoring import SocketSlot
from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.socket_editor import SocketEditor
from tests.test_new_item_provenance import setup_game, spec


def planned_row(snapshot, plan):
    body = plan.loose_files[snapshot.iteminfo.payload_entry.path]
    header = plan.loose_files[snapshot.iteminfo.header_entry.path]
    return next(parse_iteminfo_row(body[s:e]) for row, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body)) if row.row_id == plan.spec.item_key)


def test_empty_slots_and_perks_and_unlock_costs_are_independent(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    slots = (SocketSlot(1, 17), SocketSlot(1, 31))
    plan = service.plan(replace(spec(), socket_items=(), socket_slots=slots), snapshot)
    row = planned_row(snapshot, plan)
    assert row.socket_items == ()
    assert row.add_socket_materials == ((1, 17, 0), (1, 31, 0))
    plan = service.plan(replace(spec(), socket_items=(), socket_slots=()), snapshot)
    assert planned_row(snapshot, plan).add_socket_materials == ()
    with pytest.raises(ValueError, match="need more slots"):
        service.plan(replace(spec(), socket_slots=()), snapshot)


def test_socket_widget_invalidates_plan_and_never_deletes_perks(tmp_path):
    app = QApplication.instance() or QApplication([])
    service, snapshot, _ = setup_game(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(spec().template_key)
    widget = SocketEditor(controller)
    revision = controller._draft_revision
    inherited_perks = controller.template_socket_items()
    widget.customize.setChecked(True)
    widget.count.setValue(0)
    assert controller._draft_revision > revision
    assert controller.draft.socket_items is None
    assert controller.template_socket_items() == inherited_perks
    assert "need more" in widget.state.text()
    widget.count.setValue(2)
    widget.costs.cellWidget(1, 2).setText("123")
    assert controller.draft.socket_slots[1].amount == 123
    widget.customize.setChecked(False)
    assert controller.draft.socket_slots is None
    widget.close()
    controller.shutdown()
