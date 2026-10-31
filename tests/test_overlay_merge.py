"""Shared runtime registries retain only the active installs' identities."""
import pytest

from cdmw.core.item_icon_registry import add_icon_texture, registered_icon_names
from cdmw.core.pappt_format import parse_pappt, encode_pappt, insert_part_prefabs
from cdmw.core.pathc_format import parse_pathc, encode_pathc, register_dds, pathc_checksum
from cdmw.domain.archives.overlay_merge import merge_overlay_files, legacy_texture_baseline, OverlayConflict
from tests.test_pappt_format import _synthetic_bytes
from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS, BIG_HEADER, dds_payload


@pytest.mark.parametrize('removed', ['alpha', 'beta'])
def test_removing_either_install_keeps_pappt_icons_and_texture_header_bindings(removed):
    pappt = parse_pappt(_synthetic_bytes(tag_prefix=b'\x01'))
    pathc = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    icon = b'\xef\xbb\xbf<Texture Name="Base" Filename="UI/texture/base.dds" Type="Image"/>\r\n'
    base = {'character/bin__/partprefabtable.pappt': encode_pappt(pappt),
            'meta/0.pathc': encode_pathc(pathc), 'ui/xml/texture/cd_item_icon.xml': icon}

    def append(values, name, header):
        result = dict(values)
        key = 'character/bin__/partprefabtable.pappt'
        table = parse_pappt(values[key])
        result[key] = encode_pappt(insert_part_prefabs(table, [pappt.records[0].cloned(name)], after_stem=table.records[-1].stem))
        key = 'meta/0.pathc'
        table = register_dds(parse_pathc(values[key]), f'ui/texture/{name}.dds', dds_payload(header), tag=4)
        result[key] = encode_pathc(table)
        key = 'ui/xml/texture/cd_item_icon.xml'
        result[key] = add_icon_texture(values[key], name, like='Base')
        return result

    alpha = append(base, 'alpha', BIG_HEADER)
    both = append(alpha, 'beta', ICON_HEADER)
    actual = merge_overlay_files(alpha, both, base) if removed == 'alpha' else merge_overlay_files(base, alpha, base)
    kept = 'beta' if removed == 'alpha' else 'alpha'
    table = parse_pappt(actual['character/bin__/partprefabtable.pappt'])
    assert kept in table.index() and removed not in table.index()
    assert table.head_records == pappt.head_records and table.tag_prefix == pappt.tag_prefix
    table = parse_pathc(actual['meta/0.pathc'])
    by_hash = {e.checksum: e for e in table.entries}
    assert pathc_checksum(f'ui/texture/{removed}.dds') not in by_hash
    entry = by_hash[pathc_checksum(f'ui/texture/{kept}.dds')]
    expected = ICON_HEADER if kept == 'beta' else BIG_HEADER
    assert table.headers[entry.header_index][:128] == expected
    assert table.entries == tuple(sorted(table.entries, key=lambda e: e.checksum))
    raw = actual['ui/xml/texture/cd_item_icon.xml']
    assert registered_icon_names(raw) == ('Base', kept)
    assert raw.startswith(b'\xef\xbb\xbf<Texture') and raw.endswith(b'\r\n')


def test_same_owned_file_with_different_bytes_is_a_conflict():
    path = 'character/model/owned.pac'
    with pytest.raises(OverlayConflict, match='conflict'):
        merge_overlay_files({path: None}, {path: b'new mesh'}, {path: b'other mesh'})


def test_icon_merge_preserves_bom_comments_and_unknown_content_without_claiming_them():
    from tests.test_item_icon_registry import registry
    path = 'ui/xml/texture/cd_item_icon.xml'
    base = registry('Base') + b'<Future Keep="yes"/>\r\n'
    alpha = add_icon_texture(base, 'Alpha', like='Base')
    beta = add_icon_texture(base, 'Beta', like='Base')
    merged = merge_overlay_files({path: base}, {path: alpha}, {path: beta})[path]
    assert set(registered_icon_names(merged)) == {'Base', 'Alpha', 'Beta'}
    assert merged.startswith(b'\xef\xbb\xbf<!-- icons -->')
    assert b'<Future Keep="yes"/>' in merged
    with pytest.raises(OverlayConflict, match='icon'):
        merge_overlay_files({path: base}, {path: alpha.replace(b'Keep="yes"', b'Keep="alpha"')},
                            {path: beta.replace(b'Keep="yes"', b'Keep="beta"')})


def test_two_mods_claiming_the_same_icon_must_agree_on_its_bytes():
    from tests.test_item_icon_registry import registry
    path = 'ui/xml/texture/cd_item_icon.xml'
    base = registry('Base')
    first = add_icon_texture(base, 'Shared', like='Base', filename='UI/first.dds')
    second = add_icon_texture(base, 'Shared', like='Base', filename='UI/second.dds')
    assert merge_overlay_files({path: base}, {path: first}, {path: first})[path] == first
    with pytest.raises(OverlayConflict, match='same record'):
        merge_overlay_files({path: base}, {path: first}, {path: second})


def test_icon_merge_and_removal_preserve_equivalent_repeated_base_rows():
    from cdmw.core.item_icon_registry import parse_icon_registry
    from tests.test_item_icon_registry import registry
    path = 'ui/xml/texture/cd_item_icon.xml'
    base = registry('Base', 'BASE').replace(b'Filename="UI/texture/icon/BASE.dds"',
        b'FileName="UI/texture/icon/BASE.dds"') + b'<Future Keep="yes"/>\r\n'
    original = parse_icon_registry(base).textures
    alpha = add_icon_texture(base, 'Alpha', like='Base')
    beta = add_icon_texture(base, 'Beta', like='Base')
    merged = merge_overlay_files({path: base}, {path: alpha}, {path: beta})[path]
    for source, kept in ((alpha, 'Beta'), (beta, 'Alpha')):
        removed = merge_overlay_files({path: source}, {path: base}, {path: merged})[path]
        rows = parse_icon_registry(removed).textures
        assert rows[:2] == original
        assert registered_icon_names(removed) == ('Base', 'BASE', kept)
        assert b'<Future Keep="yes"/>' in removed


def test_legacy_texture_baseline_restores_owned_rows_and_keeps_foreign_changes():
    from dataclasses import replace
    from cdmw.core.pathc_format import block_infos_for

    path = 'ui/texture/replaced.dds'
    base = build_table(headers=[ICON_HEADER], entries=[(path, 0, ICON_BLOCKS)])
    live = register_dds(base, 'ui/texture/foreign.dds', dds_payload(BIG_HEADER), tag=4)
    live = replace(live, entries=tuple(replace(e, header_index=1, block_infos=block_infos_for(BIG_HEADER))
        if e.checksum == pathc_checksum(path) else e for e in live.entries))
    restored = parse_pathc(legacy_texture_baseline(encode_pathc(base), encode_pathc(live), {path: (ICON_HEADER, BIG_HEADER)}))
    assert restored.find(path) == base.find(path)
    assert restored.find('ui/texture/foreign.dds') == live.find('ui/texture/foreign.dds')
    assert restored.headers == live.headers


@pytest.mark.parametrize('ambiguous', ['changed_header', 'collision'])
def test_legacy_texture_baseline_refuses_unproven_registration_ownership(ambiguous):
    from dataclasses import replace

    path = 'ui/texture/legacy.dds'
    base = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    live = register_dds(base, path, dds_payload(BIG_HEADER), tag=4)
    if ambiguous == 'collision':
        live = replace(live, entries=tuple(replace(e, header_index=0xffff)
            if e.checksum == pathc_checksum(path) else e for e in live.entries))
    with pytest.raises(OverlayConflict, match='meta/0.pathc'):
        legacy_texture_baseline(encode_pathc(base), encode_pathc(live), {path: (None, ICON_HEADER)})


COMPACT = 'gamedata/binarystaticinfo__/bin/'


def _compact_game(stores, groups):
    from tests.compact_item_fixtures import table, store, group
    files = {}
    for kind, rows in (('storeinfo', [(key, store(key, name, items, order=0xFFFFFFFF)) for key, name, items in stores]),
                       ('itemgroupinfo', [(key, group(key, name, items)) for key, name, items in groups])):
        files[COMPACT + kind + '.staticinfobody'], files[COMPACT + kind + '.staticinfoheader'] = table(rows, 2)
    return files


def _package_adds(base, item, *, count=None):
    """What one independent install changes: a new shop line and group member for `item`."""
    from dataclasses import replace
    from cdmw.core.itemgroupinfo_table import add_group_members, parse_item_group_table, encode_item_group_row
    from cdmw.core.storeinfo_table import insert_stock_entry, parse_store_table, set_stock_count
    from tests.compact_item_fixtures import table
    stores = parse_store_table(base[COMPACT + 'storeinfo.staticinfobody'], base[COMPACT + 'storeinfo.staticinfoheader'])
    groups = parse_item_group_table(base[COMPACT + 'itemgroupinfo.staticinfobody'], base[COMPACT + 'itemgroupinfo.staticinfoheader'])
    edited_stores = [(row.key, insert_stock_entry(row, item, count=count).raw if row.key == 6600 else row.raw) for row in stores]
    edited_groups = [(row.key, add_group_members(row, [item]).raw) for row in groups]
    after = dict(base)
    after[COMPACT + 'storeinfo.staticinfobody'], after[COMPACT + 'storeinfo.staticinfoheader'] = table(edited_stores, 2)
    after[COMPACT + 'itemgroupinfo.staticinfobody'], after[COMPACT + 'itemgroupinfo.staticinfoheader'] = table(edited_groups, 2)
    return after


def test_independent_compact_shop_lines_and_group_members_compose_together():
    from cdmw.core.itemgroupinfo_table import parse_item_group_table
    from cdmw.core.storeinfo_table import parse_store_table
    # Every line of a shipped 1.0.0.3446 store has order index 0xFFFFFFFF, so two
    # installs' new lines cannot be told apart by order; the stocked item tells them apart.
    base = _compact_game([(6600, 'Store_Camp_Equipment', [101, 102]), (6700, 'Store_Camp_Costume', [103])],
                         [(17011, 'ItemGroup_Equip', [101])])
    current = dict(base)
    for item in (1990000, 1990001, 1990002):
        current = merge_overlay_files(base, _package_adds(base, item), current)
    stores = {row.key: row for row in parse_store_table(current[COMPACT + 'storeinfo.staticinfobody'], current[COMPACT + 'storeinfo.staticinfoheader'])}
    camp = stores[6600]
    assert [e.item_key for e in camp.entries] == [101, 102, 1990000, 1990001, 1990002]
    assert [e.stock_index for e in camp.entries] == [0, 1, 2, 3, 4]
    assert {e.order_index for e in camp.entries} == {0xFFFFFFFF}
    assert (camp.buyable_count, camp.sellable_count) == (5, 5)
    assert [e.item_key for e in stores[6700].entries] == [103]
    group, = parse_item_group_table(current[COMPACT + 'itemgroupinfo.staticinfobody'], current[COMPACT + 'itemgroupinfo.staticinfoheader'])
    assert group.members == (101, 1990000, 1990001, 1990002)


def test_compact_installs_changing_the_same_shop_line_still_conflict():
    from dataclasses import replace
    from cdmw.core.storeinfo_table import parse_store_table, set_stock_count
    from tests.compact_item_fixtures import table
    base = _compact_game([(6600, 'Store_Camp_Equipment', [101, 102])], [(17011, 'ItemGroup_Equip', [101])])
    def restocked(count):
        rows = parse_store_table(base[COMPACT + 'storeinfo.staticinfobody'], base[COMPACT + 'storeinfo.staticinfoheader'])
        after = dict(base)
        after[COMPACT + 'storeinfo.staticinfobody'], after[COMPACT + 'storeinfo.staticinfoheader'] = table(
            [(row.key, set_stock_count(row, 101, count).raw) for row in rows], 2)
        return after
    current = merge_overlay_files(base, restocked(5), dict(base))
    with pytest.raises(OverlayConflict, match='storeinfo'):
        merge_overlay_files(base, restocked(7), current)
