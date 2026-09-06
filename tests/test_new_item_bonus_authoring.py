import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import struct
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from cdmw.core.buffinfo_table import BuffInfoError, parse_equipment_buff, encode_equipment_buff
from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.new_item.authoring import EquipmentBonus, LevelBonuses
from cdmw.services.new_item_equipment_bonuses import load_equipment_bonuses
from cdmw.ui.new_item.bonus_editor import BonusEditor
from cdmw.ui.new_item.controller import NewItemStudioController
from tests.test_new_item_provenance import setup_game, current_files, spec
from tests.test_new_item_service import build_package, _read, TEMPLATE
from tests.test_new_item_socket_authoring import planned_row
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.services.new_item_service import NewItemService

BUFF = 1000280


def buff_row():
    name = b"Synthetic_Equipment_Bonus"
    raw = struct.pack("<II", BUFF, len(name)) + name + b"\0" + struct.pack("<I", 2)
    for level in (1, 2):
        record = bytearray(116)
        struct.pack_into("<i", record, 0, level)
        struct.pack_into("<I", record, 5, 79)
        raw += record
    return raw + struct.pack("<iiI", 0, 2, 0) + b"\1" + bytes(14)


def game_with_bonus(root):
    files = current_files()
    path = "gamedata/binarystaticinfo__/bin/"
    body, header = files[path + "iteminfo.staticinfobody"], files[path + "iteminfo.staticinfoheader"]
    from cdmw.core.structured_binary_editor import replace_table_row
    template = next(parse_iteminfo_row(body[s:e]) for row, s, e in parse_pabgh_table(header, payload=body).row_spans(len(body)) if row.row_id == TEMPLATE)
    changed = rebuild_stat_block(template, levels=[replace(level, equip_buffs=(BUFF,), equip_buff_extras=(1,)) for level in template.enchant_levels])
    new_body, new_head = replace_table_row(body, header, TEMPLATE, changed)
    files[path + "iteminfo.staticinfobody"], files[path + "iteminfo.staticinfoheader"] = new_body, new_head
    files[path + "buffinfo.staticinfobody"] = buff_row()
    files[path + "buffinfo.staticinfoheader"] = struct.pack("<HII", 1, BUFF, 0)
    service = NewItemService()
    pamt = build_package(root / "game", files)
    return service, service.build_snapshot(parse_archive_pamt(pamt), read_entry=_read)


def test_buff_level_map_roundtrip_and_unknown_kind_refused():
    raw = buff_row()
    buff = parse_equipment_buff(raw)
    assert encode_equipment_buff(buff) == raw
    assert buff.supports(0) and buff.supports(2) and not buff.supports(3)
    data = bytearray(raw)
    p = 8 + len(buff.name.encode()) + 5
    struct.pack_into("<I", data, p + 5, 999)
    with pytest.raises(BuffInfoError, match="Unsupported"):
        parse_equipment_buff(data)


def test_bonus_inheritance_partial_overrides_and_explicit_clearing(tmp_path):
    service, snapshot = game_with_bonus(tmp_path)
    index = load_equipment_bonuses(snapshot)
    assert index.buffs[BUFF].maximum == 2
    plan = service.plan(replace(spec(), equipment_bonuses=(LevelBonuses(1, (EquipmentBonus(BUFF, 2),)),)), snapshot)
    row = planned_row(snapshot, plan)
    assert row.enchant_levels[0].equip_buff_extras == (1,)
    assert row.enchant_levels[1].equip_buff_extras == (2,)
    empty = service.plan(replace(spec(), equipment_bonuses=()), snapshot)
    assert all(not level.equip_buffs for level in planned_row(snapshot, empty).enchant_levels)
    with pytest.raises(ValueError, match="Unsupported equipment bonus"):
        service.plan(replace(spec(), equipment_bonuses=(LevelBonuses(0, (EquipmentBonus(BUFF, 3),)),)), snapshot)


def test_bonus_widget_loads_presets_applies_all_and_restores_inheritance(tmp_path):
    app = QApplication.instance() or QApplication([])
    service, snapshot = game_with_bonus(tmp_path)
    controller = NewItemStudioController(synchronous=True)
    controller.snapshot = snapshot
    controller.set_template(TEMPLATE)
    widget = BonusEditor(controller)
    widget.load.click()
    assert widget.index is not None
    widget.customize.setChecked(True)
    widget.values.cellWidget(0, 1).setValue(2)
    widget.apply_all.click()
    assert all(level.bonuses[0].parameter == 2 for level in controller.draft.equipment_bonuses)
    widget.values.setCurrentCell(0, 0)
    widget.remove.click()
    assert controller.draft.equipment_bonuses[0].bonuses == ()
    widget.customize.setChecked(False)
    assert controller.draft.equipment_bonuses is None
    widget.close()
    controller.shutdown()
