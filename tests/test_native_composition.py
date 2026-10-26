"""The native launch-time composition builds the private view CDMW's Python would build.

The reference below is virtual_loader_composition.prepare_profile's tail for packages
without field or texture operations, assembled from CDMW's own primitives: read what
the game reads (DMM's groups included), merge each package's changes in order, store
the changed files, build the group and mount it first, and carry the texture registry.
"""
from pathlib import Path
import struct
import subprocess

import pytest

from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PAPGT_DEFAULT_FLAGS, papgt_with_directory
from cdmw.domain.archives.overlay_merge import OverlayConflict, merge_overlay_files
from cdmw.services.archive_overlay_install import _processed_payload, overlay_directory_name
from tests.test_native_archive_reader import Reader, _install
from tests.test_native_overlay_merge import CLI

pytestmark = pytest.mark.skipif(CLI is None, reason='Requires the explicitly built native item composer')
STORE = ('gamedata/binary__/client/bin/storeinfo.pabgb', 'gamedata/binary__/client/bin/storeinfo.pabgh')
GROUP = ('gamedata/binary__/client/bin/itemgroupinfo.pabgb', 'gamedata/binary__/client/bin/itemgroupinfo.pabgh')
PALOC = 'gamedata/stringtable/binary__/localizationstring_eng.paloc'
PAPPT = 'character/bin__/partprefabtable.pappt'
ICONS = 'ui/xml/texture/cd_item_icon.xml'
PATHC = 'meta/0.pathc'
FLAGS = {STORE[0]: 0x02, STORE[1]: 0x00, GROUP[0]: 0x02, GROUP[1]: 0x00, PALOC: 0x30, PAPPT: 0x02, ICONS: 0x32}


def _effective(root, monkeypatch, *, entries=None):
    """What the game reads for a path: the first mounted entry, DMM's groups included."""
    from cdmw.core import archive_accelerator
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_scan_cache import discover_pamt_files
    monkeypatch.setattr(archive_accelerator, 'read_archive_entry_data_native', lambda *a, **k: None)
    first = {} if entries is None else entries
    for pamt in discover_pamt_files(root, use_default_ignored_folders=False):
        for entry in parse_archive_pamt(pamt):
            first.setdefault(entry.path.replace('\\', '/').strip().strip('/').lower(), entry)

    def read(path):
        if path == PATHC:
            disk = root / 'meta' / '0.pathc'
            return disk.read_bytes() if disk.is_file() else None
        entry = first.get(path.lower())
        return read_archive_entry_data(entry)[0] if entry else None
    return read


def python_compose(root, packages, group, read):
    """prepare_profile's composition tail for plain packages."""
    mount = (root / 'meta' / '0.papgt').read_bytes()
    flags, meta, paths = {}, set(), []
    for changes in packages:
        for path, change in changes.items():
            if path not in paths:
                paths.append(path)
            flags[path] = change['flags']
            if change['meta']:
                meta.add(path)
    underlay = {path: read(path) for path in paths}
    current = dict(underlay)
    for changes in packages:
        current = merge_overlay_files({p: c['before'] for p, c in changes.items()}, {p: c['after'] for p, c in changes.items()}, current)
    files = {p: data for p, data in current.items() if p not in meta and data is not None and data != underlay[p]}
    pathc = current.get(PATHC, read(PATHC))
    output = {'meta/0.papgt': mount}
    if files:
        entries = [OverlayFile(path, _processed_payload(raw, compression_type=flags.get(path, 0) & 15, encrypted=bool(flags.get(path, 0) >> 4),
                                                        basename=path.rsplit('/', 1)[-1]), len(raw), flags.get(path, 0))
                   for path, raw in sorted(files.items())]
        archive = build_overlay_archive(entries)
        output.update({group + '/0.pamt': archive.pamt_bytes, group + '/0.paz': archive.paz_bytes,
                       'meta/0.papgt': papgt_with_directory(mount, group, archive.pamt_checksum, flags=PAPGT_DEFAULT_FLAGS, first=True)})
    if pathc is not None:
        output[PATHC] = pathc
    return list(output.items()), len(files)


def native_compose(root, packages, group=None):
    request = bytearray(b'CDMWCMP1' + struct.pack('<I', len(packages)))
    for changes in packages:
        request += struct.pack('<I', len(changes))
        for path, change in changes.items():
            raw = path.encode()
            request += struct.pack('<I', len(raw)) + raw
            for value in (change['before'], change['after']):
                request += b'\0' if value is None else b'\1' + struct.pack('<Q', len(value)) + value
            request += struct.pack('<QB', change['flags'], int(change['meta']))
    source, target = root.parent / 'compose-request.bin', root.parent / 'compose-response.bin'
    source.write_bytes(bytes(request))
    subprocess.run([str(CLI), 'compose', str(source), str(target), str(root), *([group] if group else [])], check=True, capture_output=True, timeout=300)
    reply = Reader(target.read_bytes())
    if reply.status != 'ok':
        return reply.status, reply.message
    name, composed = reply.take(4).decode(), reply.number(4)
    files = [(reply.take(4).decode(), reply.take(8)) for _ in range(reply.number(4))]
    return 'ok', (name, composed, files)


# ---- a synthetic install with DMM mounted and two independent packages --------------------

def _game(tmp_path):
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
    from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
    from cdmw.core.pathc_format import encode_pathc
    from tests.test_native_overlay_merge import _groups, _stores
    from tests.test_pappt_format import _synthetic_bytes
    from tests.test_paloc_container import wrapped
    from tests.test_pathc_format import ICON_BLOCKS, ICON_HEADER, build_table
    root = tmp_path / 'game'
    store, group = _stores(), _groups()
    paloc = wrapped(encode_paloc([LocalizationEntry(7, '100', 'Sword'), LocalizationEntry(9, '300', 'Axe'), LocalizationEntry(5, 'named', 'x')]))
    icons = b'\xef\xbb\xbf<Texture Name="Base" Filename="UI/texture/base.dds" Type="Image"/>\r\n'
    base = [(STORE[0], store[0]), (STORE[1], store[1]), (GROUP[0], group[0]), (GROUP[1], group[1]),
            (PALOC, paloc), (PAPPT, _synthetic_bytes(tag_prefix=b'\x01')), (ICONS, icons)]
    # DMM's mounted group already edits one table; compositions must start from its version.
    rows = {row.key: row for row in parse_item_group_table(*group)}
    dmm = apply_item_group_row(*group, add_group_members(rows[17010], [777]))
    groups = {'0000': [(path, data, FLAGS[path], None) for path, data in base],
              'dmmsa': [(GROUP[0], dmm[0], FLAGS[GROUP[0]], None), (GROUP[1], dmm[1], FLAGS[GROUP[1]], None)]}
    _install(root, groups, ['dmmsa', '0000'])
    (root / 'meta' / '0.pathc').write_bytes(encode_pathc(build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])))
    (root / '0036').mkdir()  # an unmounted folder still reserves its name
    return root


def _package(read, item, stem, *, model=True, store_count=None):
    from cdmw.core.item_icon_registry import add_icon_texture
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
    from cdmw.core.paloc_format import LocalizationEntry, add_localization_entries, encode_paloc, parse_paloc
    from cdmw.core.pappt_format import encode_pappt, insert_part_prefabs, parse_pappt
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from cdmw.core.storeinfo_table import apply_store_row, insert_stock_entry, parse_store_table, set_stock_count
    from tests.test_pathc_format import ICON_HEADER, dds_payload
    before = {path: read(path) for path in (*STORE, *GROUP, PALOC, PAPPT, ICONS, PATHC)}
    after = dict(before)
    rows = {row.key: row for row in parse_store_table(before[STORE[0]], before[STORE[1]])}
    edited = insert_stock_entry(rows[2003], item) if store_count is None else set_stock_count(rows[2003], 50001, store_count)
    after[STORE[0]], after[STORE[1]] = apply_store_row(before[STORE[0]], before[STORE[1]], edited)
    rows = {row.key: row for row in parse_item_group_table(before[GROUP[0]], before[GROUP[1]])}
    after[GROUP[0]], after[GROUP[1]] = apply_item_group_row(before[GROUP[0]], before[GROUP[1]], add_group_members(rows[17010], [item]))
    after[PALOC] = encode_paloc(add_localization_entries(parse_paloc(before[PALOC]), [LocalizationEntry(7, str((item << 32) | 0x70), stem)]))
    table = parse_pappt(before[PAPPT])
    after[PAPPT] = encode_pappt(insert_part_prefabs(table, [table.records[0].cloned(stem)]))
    after[PATHC] = encode_pathc(register_dds(parse_pathc(before[PATHC]), f'ui/texture/{stem}.dds', dds_payload(ICON_HEADER), tag=4))
    after[ICONS] = add_icon_texture(before[ICONS], stem, like='Base')
    changes = {path: {'before': before[path], 'after': after[path], 'flags': FLAGS.get(path, 0), 'meta': path.startswith('meta/')}
               for path in before}
    if model:
        changes[f'character/model/{stem}.pac'] = {'before': None, 'after': f'{stem} mesh'.encode() * 50, 'flags': 0x02, 'meta': False}
        changes[f'ui/texture/{stem}.dds'] = {'before': None, 'after': dds_payload(ICON_HEADER), 'flags': 0x00, 'meta': False}
    return changes


def _compare(root, packages, read, group='0037'):
    try:
        expected = ('ok', python_compose(root, packages, group, read))
    except OverlayConflict:
        expected = ('conflict',)
    except Exception as exc:
        expected = ('error', str(exc))
    actual = native_compose(root, packages, group)
    assert actual[0] == expected[0], (expected, actual)
    if expected[0] == 'ok':
        files, composed = expected[1]
        assert actual[1][0] == group and actual[1][1] == composed
        assert [path for path, _ in actual[1][2]] == [path for path, _ in files]
        for (path, mine), (_, theirs) in zip(actual[1][2], files):
            assert mine == theirs, path
    return actual


def test_two_packages_compose_onto_dmms_tables(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    alpha, beta = _package(read, 1990001, 'alpha'), _package(read, 1990002, 'beta')
    actual = _compare(root, [alpha, beta], read)
    files = dict(actual[1][2])
    assert set(files) == {'meta/0.papgt', '0037/0.pamt', '0037/0.paz', PATHC}
    from cdmw.core.archive_format import parse_archive_pamt_bytes
    from cdmw.core.itemgroupinfo_table import parse_item_group_table
    (tmp_path / 'view' / '0037').mkdir(parents=True)
    for name in ('0.pamt', '0.paz'):
        (tmp_path / 'view' / '0037' / name).write_bytes(files['0037/' + name])
    entries = {entry.path: entry for entry in parse_archive_pamt_bytes(files['0037/0.pamt'], tmp_path / 'view' / '0037' / '0.pamt')}
    assert {GROUP[0], 'character/model/alpha.pac', 'character/model/beta.pac'} <= set(entries)
    from cdmw.core.archive_extraction import read_archive_entry_data
    composed = parse_item_group_table(read_archive_entry_data(entries[GROUP[0]])[0], read_archive_entry_data(entries[GROUP[1]])[0])
    assert {777, 1990001, 1990002} <= set(next(row for row in composed if row.key == 17010).members)  # DMM's edit kept
    _compare(root, [beta, alpha], read)
    _compare(root, [alpha], read)


def test_composition_refuses_two_edits_of_one_record(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    first, second = _package(read, 1990001, 'alpha', store_count=5), _package(read, 1990002, 'beta', store_count=6)
    assert _compare(root, [first, second], read)[0] == 'conflict'


def test_a_package_with_no_effect_publishes_only_the_mount_list(tmp_path, monkeypatch):
    root = _game(tmp_path)
    read = _effective(root, monkeypatch)
    unchanged = {path: {'before': read(path), 'after': read(path), 'flags': FLAGS.get(path, 0), 'meta': path.startswith('meta/')}
                 for path in (*STORE, PATHC)}
    actual = _compare(root, [unchanged], read)
    assert [path for path, _ in actual[1][2]] == ['meta/0.papgt', PATHC] and actual[1][1] == 0


@pytest.mark.real_game
def test_shipped_install_composes_like_python(monkeypatch):
    """Two packages over the installed game, read-only: native and Python views agree."""
    import time
    from cdmw.core.item_icon_registry import add_icon_texture, parse_icon_registry
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
    from cdmw.core.paloc_format import LocalizationEntry, add_localization_entries, encode_paloc, parse_paloc
    from cdmw.core.pappt_format import encode_pappt, insert_part_prefabs, parse_pappt
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from cdmw.core.storeinfo_table import apply_store_row, insert_stock_entry, parse_store_table, store_index
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    from tests.test_native_overlay_merge import _append_row
    from tests.test_pathc_format import ICON_HEADER, dds_payload
    from tools.new_item_corpus import read_table
    from tools.placement_studio import corpus

    root = corpus.game_root()
    entries = {}
    read = _effective(root, monkeypatch, entries=entries)
    tables, layout = {}, {}
    for stem in ('storeinfo', 'itemgroupinfo', 'iteminfo'):
        pair = read_table(stem)
        tables[stem] = tuple(corpus.normalize_game_path(entry.path) for entry in (pair.payload_entry, pair.header_entry))
        layout[stem] = pair.descriptor['layout']
    paloc = 'gamedata/stringtable/binary__/eng/item.paloc'  # item names in the current per-language layout
    shared = (*tables['storeinfo'], *tables['itemgroupinfo'], *tables['iteminfo'], paloc, PAPPT, ICONS, PATHC)
    before = {path: read(path) for path in shared}
    assert all(value is not None for value in before.values())

    def package(item, stem):
        after = dict(before)
        body, head = tables['storeinfo']
        rows = store_index(parse_store_table(before[body], before[head], layout=layout['storeinfo']))
        after[body], after[head] = apply_store_row(before[body], before[head], insert_stock_entry(rows['Store_Camp_Equipment'], item))
        body, head = tables['itemgroupinfo']
        group = parse_item_group_table(before[body], before[head])[0]
        after[body], after[head] = apply_item_group_row(before[body], before[head], add_group_members(group, [item]))
        body, head = tables['iteminfo']
        donor = parse_pabgh_table(before[head], payload=before[body]).rows[0].key
        after[body], after[head] = _append_row(before[body], before[head], donor, item)
        after[paloc] = encode_paloc(add_localization_entries(parse_paloc(before[paloc]), [LocalizationEntry(7, str((item << 32) | 0x70), f'Item {item}')]))
        prefabs = parse_pappt(before[PAPPT])
        after[PAPPT] = encode_pappt(insert_part_prefabs(prefabs, [prefabs.records[0].cloned(stem)]))
        after[PATHC] = encode_pathc(register_dds(parse_pathc(before[PATHC]), f'ui/texture/icon/{stem}.dds', dds_payload(ICON_HEADER), tag=15))
        after[ICONS] = add_icon_texture(before[ICONS], stem, like=parse_icon_registry(before[ICONS]).textures[0].name)
        changes = {path: {'before': before[path], 'after': after[path], 'flags': entries[path].flags if path in entries else 0,
                          'meta': path.startswith('meta/')} for path in shared}
        changes[f'character/model/{stem}.pac'] = {'before': None, 'after': f'{stem} mesh'.encode() * 500, 'flags': 0x02, 'meta': False}
        return changes

    alpha, beta = package(1990001, 'cdmw_parity_alpha'), package(1990002, 'cdmw_parity_beta')
    started = time.perf_counter()
    actual = _compare(root, [alpha, beta], read, group=overlay_directory_name(root))
    print(f'shipped composition parity: {actual[1][1]} composed files, {sum(len(data) for _, data in actual[1][2]):,} published bytes, '
          f'{time.perf_counter() - started:.1f} s for one Python and one native composition')


def test_the_free_group_name_matches_cdmws_choice(tmp_path):
    root = _game(tmp_path)
    result = subprocess.run([str(CLI), 'group-name', str(root)], check=True, capture_output=True, timeout=60)
    assert result.stdout.decode().strip() == overlay_directory_name(root) == '0037'
