from dataclasses import replace

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
from cdmw.core.paloc_format import parse_paloc, encode_paloc, add_localization_entries, LocalizationEntry
from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row
from cdmw.domain.new_item.spec import PriceEdit
from cdmw.services.new_item_service import NewItemService
from tests.test_new_item_provenance import current_files, spec
from tests.test_new_item_service import build_package, _read
from tests.test_iteminfo_row import build_row


def test_one_copper_owns_zero_price_perks_and_preserves_their_bonuses_and_names(tmp_path):
    files = current_files()
    body_path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    head_path = body_path.replace('body', 'header')
    body, head = files[body_path], files[head_path]
    rows = {r.row_id: parse_iteminfo_row(body[s:e]) for r, s, e in parse_pabgh_table(head, payload=body).row_spans(len(body))}
    perk = rows[1002791]
    raw = build_row(key=perk.key, string_key=perk.string_key, name_key=str((perk.key << 32) | 0x70),
                    desc_key=str((perk.key << 32) | 0x71), equip='', item_type=2501, stems=(),
                    levels=[([(1000007, 50000)], [])], prices=((1, 560),), socket_items=(), adds=())
    perk = parse_iteminfo_row(raw)
    raw = rebuild_stat_block(replace(perk, stat_block_marker=0x12))
    files[body_path], files[head_path] = replace_table_row(body, head, perk.key, raw)
    for path in list(files):
        if path.endswith('.paloc'):
            table = parse_paloc(files[path])
            files[path] = encode_paloc(add_localization_entries(table, (
                LocalizationEntry(7, perk.name_key, 'Critical bonus'), LocalizationEntry(8, perk.desc_key, 'Bonus description'),
            )))
    service = NewItemService()
    snapshot = service.build_snapshot(parse_archive_pamt(build_package(tmp_path / 'game', files)), read_entry=_read)
    plan = service.plan(replace(spec(), include_perk_prices=False, price_edits=(PriceEdit(1, 1),)), snapshot,
                        reserved_keys=(key for key in (1990001,)))
    body, head = plan.loose_files[body_path], plan.loose_files[head_path]
    rows = {r.row_id: parse_iteminfo_row(body[s:e]) for r, s, e in parse_pabgh_table(head, payload=body).row_spans(len(body))}
    item = rows[plan.spec.item_key]
    owned = rows[item.socket_items[0]]
    assert owned.key not in (perk.key, 1990001, item.key)
    assert rows[perk.key].raw == raw
    assert sum(p.price for p in item.price_list if p.item_key == 1) == 1
    assert all(p.price == 0 for p in owned.price_list)
    assert [[(s.status_key, s.value, s.extra) for s in level.stats] for level in owned.enchant_levels] == [[(1000007, 50000, 0)]]
    assert [level.equip_buffs for level in owned.enchant_levels] == [level.equip_buffs for level in snapshot.rows[perk.key].enchant_levels]
    assert owned.item_type == perk.item_type
    for path in files:
        if path.endswith('.paloc'):
            table = parse_paloc(plan.loose_files[path]).index()
            assert table[owned.name_key].text == 'Critical bonus'
            assert table[owned.desc_key].text == 'Bonus description'
    ordinary = service.plan(spec('Ordinary'), snapshot)
    assert 'owned_price_perks' not in ordinary.manifest
