"""Shared runtime registries retain only the active installs' identities."""
import pytest

from cdmw.core.item_icon_registry import add_icon_texture, registered_icon_names
from cdmw.core.pappt_format import parse_pappt, encode_pappt, insert_part_prefabs
from cdmw.core.pathc_format import parse_pathc, encode_pathc, register_dds, pathc_checksum
from cdmw.domain.archives.overlay_merge import merge_overlay_files, legacy_texture_baseline, OverlayConflict
from tests.test_pappt_format import _synthetic_bytes
from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS, BIG_HEADER


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
        table = register_dds(parse_pathc(values[key]), f'ui/texture/{name}.dds', header, tag=4)
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


def test_legacy_texture_baseline_restores_owned_rows_and_keeps_foreign_changes():
    from dataclasses import replace
    from cdmw.core.pathc_format import block_infos_for

    path = 'ui/texture/replaced.dds'
    base = build_table(headers=[ICON_HEADER], entries=[(path, 0, ICON_BLOCKS)])
    live = register_dds(base, 'ui/texture/foreign.dds', BIG_HEADER, tag=4)
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
    live = register_dds(base, path, BIG_HEADER, tag=4)
    if ambiguous == 'collision':
        live = replace(live, entries=tuple(replace(e, header_index=0xffff)
            if e.checksum == pathc_checksum(path) else e for e in live.entries))
    with pytest.raises(OverlayConflict, match='meta/0.pathc'):
        legacy_texture_baseline(encode_pathc(base), encode_pathc(live), {path: (None, ICON_HEADER)})
