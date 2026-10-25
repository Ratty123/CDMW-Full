"""The native item composer reproduces overlay_merge.py byte for byte.

Each case runs merge_overlay_files and native/cdmw_item_composer's CLI on the same
before/after/current files. Outputs must be identical, except that a rewritten .paloc
container may hold a different (valid) LZ4 block for the same payload. Failures must
agree on their kind: conflict or error. The native side may instead answer
"unsupported" only where a case says it may: inputs outside the subset it models.
"""
from dataclasses import replace
import os
from pathlib import Path
import random
import struct
import subprocess

import pytest

from cdmw.domain.archives.overlay_merge import OverlayConflict, merge_overlay_files

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'native/cdmw_item_composer/build'
CLI = next((path for path in (BUILD / 'Release/cdmw_compose_cli.exe', BUILD / 'cdmw_compose_cli') if path.is_file()), None)
pytestmark = pytest.mark.skipif(CLI is None, reason='Requires the explicitly built native item composer')

STATUS = {0: 'ok', 1: 'conflict', 2: 'error', 3: 'unsupported', 4: 'internal'}
STORE_BODY = 'gamedata/binary__/client/bin/storeinfo.pabgb'
STORE_HEAD = 'gamedata/binary__/client/bin/storeinfo.pabgh'
GROUP_BODY = 'gamedata/binary__/client/bin/itemgroupinfo.pabgb'
GROUP_HEAD = 'gamedata/binary__/client/bin/itemgroupinfo.pabgh'
PALOC = 'gamedata/stringtable/binary__/localizationstring_eng.paloc'
PAPPT = 'character/bin__/partprefabtable.pappt'
PATHC = 'meta/0.pathc'
ICONS = 'ui/xml/texture/cd_item_icon.xml'


def _encode_map(files):
    out = bytearray(struct.pack('<I', len(files)))
    for path, data in files.items():
        raw = path.encode('utf-8')
        out += struct.pack('<I', len(raw)) + raw
        out += b'\0' if data is None else b'\1' + struct.pack('<Q', len(data)) + data
    return bytes(out)


def _decode_response(data):
    assert data[:8] == b'CDMWRES1'
    status, size = data[8], struct.unpack_from('<I', data, 9)[0]
    message, pos = data[13:13 + size].decode('utf-8', 'replace'), 13 + size
    if status:
        return STATUS[status], message
    items = []
    count = struct.unpack_from('<I', data, pos)[0]
    pos += 4
    for _ in range(count):
        length = struct.unpack_from('<I', data, pos)[0]
        path = data[pos + 4:pos + 4 + length].decode('utf-8')
        pos += 4 + length
        value = None
        if data[pos]:
            size = struct.unpack_from('<Q', data, pos + 1)[0]
            value = data[pos + 9:pos + 9 + size]
            pos += 9 + size
        else:
            pos += 1
        items.append((path, value))
    assert pos == len(data)
    return 'ok', items


@pytest.fixture
def native(tmp_path):
    counter = iter(range(1_000_000))

    def run(before, after, current):
        index = next(counter)
        request, response = tmp_path / f'request-{index}.bin', tmp_path / f'response-{index}.bin'
        request.write_bytes(b'CDMWMRG1' + _encode_map(before) + _encode_map(after) + _encode_map(current))
        subprocess.run([str(CLI), 'merge', str(request), str(response)], check=True, capture_output=True, timeout=120)
        result = _decode_response(response.read_bytes())
        request.unlink()
        response.unlink()
        return result
    return run


def _python(before, after, current):
    try:
        return 'ok', list(merge_overlay_files(before, after, current).items())
    except OverlayConflict as exc:
        return 'conflict', str(exc)
    except Exception as exc:  # any other refusal: ValueError subclasses, IndexError, struct.error
        return 'error', f'{type(exc).__name__}: {exc}'


def _same_paloc_container(mine, theirs):
    """Equal containers apart from the LZ4 block: same header fields, same payload."""
    import lz4.block
    if not (mine.startswith(b'paloc') and theirs.startswith(b'paloc')):
        return False
    if mine[:9] != theirs[:9] or mine[13:512] != theirs[13:512]:
        return False
    if struct.unpack_from('<I', mine, 9)[0] != len(mine) - 512:
        return False
    size = struct.unpack_from('<I', theirs, 13)[0]
    decoded = lz4.block.decompress(mine[512:], uncompressed_size=size)
    return len(decoded) == size and decoded == lz4.block.decompress(theirs[512:], uncompressed_size=size)


@pytest.fixture
def parity(native):
    def check(before, after, current, *, allow_unsupported=False):
        expected, actual = _python(before, after, current), native(before, after, current)
        if actual[0] == 'unsupported' and allow_unsupported:
            return actual
        assert actual[0] == expected[0], (expected[0], expected[1] if expected[0] != 'ok' else '', actual[1] if actual[0] != 'ok' else '')
        if expected[0] == 'ok':
            assert [path for path, _ in actual[1]] == [path for path, _ in expected[1]]
            for (path, mine), (_, theirs) in zip(actual[1], expected[1]):
                if mine != theirs:
                    assert path.endswith('.paloc') and mine is not None and theirs is not None \
                        and _same_paloc_container(mine, theirs), f'{path} differs'
        return expected
    return check


def _install(parity, base, alpha, beta):
    """Install alpha then beta onto base, then remove each again; every step must agree."""
    first = parity(base, alpha, base)
    assert first[0] == 'ok', first[1]
    both = dict(first[1])
    second = parity(base, beta, both)
    if second[0] != 'ok':
        return second
    merged = dict(second[1])
    parity(alpha, base, merged)
    parity(beta, base, merged)
    return second


# ---- whole files -------------------------------------------------------------------------

@pytest.mark.parametrize(('before', 'after', 'current'), [
    ({'a.bin': None}, {'a.bin': b'new'}, {}),
    ({'a.bin': None}, {'a.bin': b'new'}, {'a.bin': b'new', 'z.bin': b'kept'}),
    ({'a.bin': None}, {'a.bin': b'new'}, {'a.bin': b'other'}),
    ({'a.bin': b'old'}, {'a.bin': None}, {'a.bin': b'old'}),
    ({'a.bin': b'old'}, {'a.bin': None}, {'a.bin': b'changed'}),
    ({'a.bin': b'old'}, {'a.bin': b'old'}, {'a.bin': b'changed'}),
    ({'b.bin': b'x', 'a.bin': None}, {'a.bin': b'new', 'c.bin': b'added'}, {'z.bin': None, 'b.bin': b'x'}),
    ({STORE_BODY: b'x'}, {STORE_BODY: b'y'}, {STORE_BODY: b'z'}),
    ({PATHC: b'x'}, {PATHC: b'y'}, {PATHC: b'z'}),
    ({ICONS: b'x'}, {ICONS: b'y'}, {ICONS: b'z'}),
    ({PALOC: b'x'}, {PALOC: b'y'}, {PALOC: b'z'}),
])
def test_whole_file_changes(parity, before, after, current):
    parity(before, after, current)


# ---- generic tables ----------------------------------------------------------------------

def _table(rows, *, key_width=4, count_width=2, order=None):
    """A .pabgh/.pabgb pair whose rows repeat their key inline, directory in `order`."""
    payload, entries = bytearray(), []
    for key, body in rows:
        raw = key.to_bytes(key_width, 'little')
        entries.append(raw + struct.pack('<I', len(payload)))
        payload += raw + body
    if order is not None:
        entries = [entries[index] for index in order]
    return bytes(payload), len(rows).to_bytes(count_width, 'little') + b''.join(entries)


def _tables(rows, path='gamedata/binary__/client/bin/testinfo', **layout):
    body, head = (path + '.pabgb', path + '.pabgh') if not path.endswith('static') else (path + 'infobody', path + 'infoheader')
    payload, header = _table(rows, **layout)
    return {body: payload, head: header}


LAYOUTS = [dict(key_width=w, count_width=c) for w in (1, 2, 4, 8, 12) for c in (1, 2, 4)]


@pytest.mark.parametrize('layout', LAYOUTS, ids=lambda l: f"key{l['key_width']}-count{l['count_width']}")
def test_table_rows_compose_in_every_directory_layout(parity, layout):
    base = [(1, b'one'), (2, b'two'), (3, b'three')]
    alpha = base + [(10, b'alpha row')]
    beta = [(1, b'one'), (2, b'two, changed by beta'), (3, b'three'), (11, b'beta row')]
    _install(parity, _tables(base, **layout), _tables(alpha, **layout), _tables(beta, **layout))
    clash = [(1, b'one'), (2, b'two, changed by alpha'), (3, b'three')]
    parity(_tables(base, **layout), _tables(clash, **layout), _tables(beta, **layout))
    parity(_tables(base, **layout), _tables([(1, b'one'), (3, b'three')], **layout), _tables(beta, **layout))


def test_table_directory_order_is_kept_apart_from_payload_order(parity):
    rows = [(5, b'e'), (1, b'aa'), (9, b'nine'), (3, b'c')]
    base = _tables(rows, order=[2, 0, 3, 1])
    alpha = _tables(rows + [(7, b'alpha')], order=[4, 2, 0, 3, 1])
    beta = _tables(rows[:2] + [(9, b'nine, beta')] + rows[3:] + [(8, b'beta')], order=[0, 1, 2, 3, 4])
    _install(parity, base, alpha, beta)


def test_table_static_info_paths_and_missing_halves(parity):
    base = _tables([(1, b'one')], path='gamedata/binary__/client/bin/testinfo.static')
    alpha = _tables([(1, b'one'), (2, b'two')], path='gamedata/binary__/client/bin/testinfo.static')
    beta = _tables([(1, b'one'), (3, b'three')], path='gamedata/binary__/client/bin/testinfo.static')
    _install(parity, base, alpha, beta)
    body = next(path for path in beta if path.endswith('body'))
    parity(base, beta, {**alpha, body.replace('body', 'header'): None})
    parity({body: base[body]}, {body: beta[body]}, alpha)


def test_unusual_table_directories(parity):
    path = 'gamedata/binary__/client/bin/testinfo'
    cases = [
        ({path + '.pabgb': b'', path + '.pabgh': b'\0'}, 'empty'),
        ({path + '.pabgb': b'\x01\0\0\0x', path + '.pabgh': b'\x01\0\x01\0\0\0\0\0\0\0'}, 'trailing directory bytes'),
        ({path + '.pabgb': b'\x01\0\0\0x\x01\0\0\0y', path + '.pabgh': b'\x02\0\x01\0\0\0\0\0\0\0\x01\0\0\0\x05\0\0\0'}, 'duplicate keys'),
        ({path + '.pabgb': b'\x01\0\0\0x', path + '.pabgh': b'\x01\0\x01\0\0\0\x09\0\0\0'}, 'offset past the payload'),
    ]
    good = _tables([(1, b'x'), (2, b'y')])
    for files, _why in cases:
        parity(good, files, _tables([(1, b'x'), (2, b'y'), (3, b'z')]))
        parity(files, good, files)
        parity(files, _tables([(4, b'w')]), files)


def _random_rows(rng, count, key_width):
    keys = rng.sample(range(1, min(2 ** (8 * key_width) - 1, 10 ** 9)), count)
    return [(key, rng.randbytes(rng.randint(0, 12))) for key in keys]


def _edit(rng, rows, key_width):
    rows = list(rows)
    for _ in range(rng.randint(1, 4)):
        roll = rng.random()
        if roll < 0.4 or not rows:
            rows.insert(rng.randint(0, len(rows)), _random_rows(rng, 1, key_width)[0])
        elif roll < 0.7:
            index = rng.randrange(len(rows))
            rows[index] = (rows[index][0], rng.randbytes(rng.randint(0, 12)))
        else:
            rows.pop(rng.randrange(len(rows)))
    seen, unique = set(), []
    for key, body in rows:
        if key not in seen:
            seen.add(key)
            unique.append((key, body))
    return unique


@pytest.mark.parametrize('seed', range(40))
def test_random_table_edits(parity, seed):
    rng = random.Random(seed)
    layout = rng.choice(LAYOUTS)
    base = _random_rows(rng, rng.randint(1, 6), layout['key_width'])
    alpha, beta = (_edit(rng, base, layout['key_width']) for _ in range(2))
    if not alpha or not beta:
        return
    _install(parity, _tables(base, **layout), _tables(alpha, **layout), _tables(beta, **layout))


# ---- storeinfo and itemgroupinfo ---------------------------------------------------------

def _stores(layout='legacy'):
    from tests.test_storeinfo_table import ZIANE, _entry, _row, _table as store_table
    option = struct.pack('<I', 1001479) + b'\x01' + bytes(range(8))
    def entries(key):
        rows = (_entry(50001, 0, count=60), _entry(ZIANE, 1, option=option, order=7),
                _entry(1000372, 2, records=(bytes(4) + struct.pack('<I', 1) + bytes(4),)),
                _entry(1000692, 3, buyable=False, sellable=True))
        return tuple(replace(e, condition_data=bytes(range(8))) for e in rows) if layout == 'current' else rows
    payload, header = store_table([_row(entries(2003)), _row(entries(61), name='Store_Pai_Equipment', key=61)])
    return payload, header


def _store_files(payload, header, layout):
    if layout == 'current':
        return {STORE_BODY.replace('.pabgb', '.staticinfobody'): payload, STORE_HEAD.replace('.pabgh', '.staticinfoheader'): header}
    return {STORE_BODY: payload, STORE_HEAD: header}


def _store_edit(payload, header, layout, store, edit):
    from cdmw.core.storeinfo_table import apply_store_row, parse_store_table
    rows = {row.key: row for row in parse_store_table(payload, header, layout=layout)}
    return apply_store_row(payload, header, edit(rows[store]))


@pytest.mark.parametrize('layout', ['legacy', 'current'])
def test_shop_stock_from_two_installs(parity, layout):
    from cdmw.core.storeinfo_table import insert_stock_entry, remove_stock_entry, set_stock_count, swap_stock_item
    base = _stores(layout)
    def files(edit, store=2003, pair=base):
        return _store_files(*_store_edit(*pair, layout, store, edit), layout)
    plain = _store_files(*base, layout)
    alpha = files(lambda row: insert_stock_entry(row, 1990001))
    beta = files(lambda row: insert_stock_entry(row, 1990002, keep_requirement=False, count=0xFFFFFFFF))
    _install(parity, plain, alpha, beta)
    # The same new item from both installs pairs by item identity.
    _install(parity, plain, alpha, files(lambda row: insert_stock_entry(row, 1990001)))
    # Edits to different entries compose; the same entry edited twice conflicts.
    _install(parity, plain, files(lambda row: set_stock_count(row, 50001, 5)), files(lambda row: remove_stock_entry(row, 1000692)))
    parity(plain, files(lambda row: set_stock_count(row, 50001, 5)), files(lambda row: set_stock_count(row, 50001, 6)))
    _install(parity, plain, files(lambda row: swap_stock_item(row, 1000372, 1990003)), files(lambda row: insert_stock_entry(row, 1990004, position=0)))
    # Rows of different stores compose as rows.
    _install(parity, plain, alpha, files(lambda row: insert_stock_entry(row, 1990005), store=61))
    sellable = files(lambda row: insert_stock_entry(row, 1990006, template=row.entries[3], position=len(row.entries)))
    _install(parity, plain, sellable, beta)


def test_stock_added_to_a_shop_with_no_stock(parity):
    from tests.test_storeinfo_table import _entry, _row, _table as store_table
    from cdmw.core.storeinfo_table import insert_stock_entry
    template = _entry(50001, 0, count=60)
    pair = store_table([_row((), name='Store_Empty', key=77), _row((template,), name='Store_Other', key=78)])
    def files(item):
        return _store_files(*_store_edit(*pair, 'legacy', 77, lambda row: insert_stock_entry(row, item, template=replace(template, store_key=77))), 'legacy')
    _install(parity, _store_files(*pair, 'legacy'), files(1990001), files(1990002))


@pytest.mark.parametrize('seed', range(30))
def test_random_shop_stock_edits(parity, seed):
    from cdmw.core.storeinfo_table import insert_stock_entry, remove_stock_entry, set_stock_count
    rng = random.Random(seed)
    layout = rng.choice(['legacy', 'current'])
    base = _stores(layout)

    def edits():
        pair = base
        for _ in range(rng.randint(1, 3)):
            store = rng.choice([2003, 61])
            roll = rng.random()
            if roll < 0.5:
                item = rng.choice([1990001, 1990002, 1990003])
                edit = lambda row, item=item: insert_stock_entry(row, item, position=rng.randint(0, len(row.entries))) if not row.entries_for(item) else row
            elif roll < 0.8:
                edit = lambda row: set_stock_count(row, 50001, rng.randint(0, 99))
            else:
                edit = lambda row: remove_stock_entry(row, 1000692) if row.entries_for(1000692) else row
            pair = _store_edit(*pair, layout, store, edit)
        return _store_files(*pair, layout)
    _install(parity, _store_files(*base, layout), edits(), edits())


def _groups():
    from tests.test_itemgroupinfo_table import _row, _table as group_table
    return group_table([_row(17010, 'ItemGroup_Equip_Weapon_OneHandSword', (240018, 1001295, 13800), subgroups=(17011, 17012)),
                        _row(17011, 'ItemGroup_Equip_Weapon_Other', (240018,), tail_extra=b'\x05\x06')])


def _group_files(edit=None, group=17010, pair=None):
    from cdmw.core.itemgroupinfo_table import apply_item_group_row, parse_item_group_table
    payload, header = pair or _groups()
    if edit:
        rows = {row.key: row for row in parse_item_group_table(payload, header)}
        payload, header = apply_item_group_row(payload, header, edit(rows[group]))
    return {GROUP_BODY: payload, GROUP_HEAD: header}


def test_item_group_members_from_two_installs(parity):
    from cdmw.core.itemgroupinfo_table import add_group_members
    plain = _group_files()
    alpha = _group_files(lambda row: add_group_members(row, [1990001]))
    beta = _group_files(lambda row: add_group_members(row, [1990002], after=240018))
    _install(parity, plain, alpha, beta)
    _install(parity, plain, alpha, _group_files(lambda row: add_group_members(row, [1990001])))
    _install(parity, plain, alpha, _group_files(lambda row: add_group_members(row, [1990003]), group=17011))
    parity(plain, alpha, _group_files(lambda row: replace(row, subgroups=(17011,))))
    parity(plain, _group_files(lambda row: replace(row, subgroups=())), _group_files(lambda row: replace(row, subgroups=(17011,))))


# ---- paloc -------------------------------------------------------------------------------

def _paloc(entries, *, container=False):
    from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
    data = encode_paloc([LocalizationEntry(category, key, text) for category, key, text in entries])
    if container:
        from tests.test_paloc_container import wrapped
        data = wrapped(data)
    return data


PALOC_BASE = [(7, '100', 'Sword'), (8, '101', 'A sword.'), (38, 'questdialog_main_00001', 'Hello.'),
              (7, '300', 'Axe'), (9, '0400', 'Leading zero'), (7, '250', 'Out of order tail')]


@pytest.mark.parametrize('container', [False, True])
def test_localization_from_two_installs(parity, container):
    def table(extra=(), drop=(), change=None):
        rows = [row for row in PALOC_BASE if row[1] not in drop]
        if change:
            rows = [(c, k, change.get(k, t)) for c, k, t in rows]
        return {PALOC: _paloc(rows + list(extra), container=container)}
    base = table()
    alpha = table([(7, '200', 'Alpha name'), (7, '1990000', 'Alpha'), (5, 'cdmw_alpha', 'named')])
    beta = table([(7, '150', 'Beta name'), (7, '0200', 'Leading zeros'), (7, '99999999999999999999999', 'Huge'), (5, 'cdmw_beta', 'b')])
    _install(parity, base, alpha, beta)
    _install(parity, base, table(change={'101': 'Alpha text'}), table(drop=('300',)))
    parity(base, table(change={'101': 'Alpha text'}), table(change={'101': 'Beta text'}))
    parity(base, alpha, table([(7, '200', 'Different alpha name')]))
    parity(base, table([(7, '', 'empty key')]), base)
    parity(base, table([(7, '٣', 'Arabic-Indic digit')]), base, allow_unsupported=True)
    unchanged = parity(base, base, base)
    assert dict(unchanged[1])[PALOC] == base[PALOC]


@pytest.mark.parametrize('seed', range(30))
def test_random_localization_edits(parity, seed):
    rng = random.Random(seed)
    container = rng.random() < 0.5
    base = [(rng.randint(0, 40), str(key), rng.choice(['', 'text ', 'ü ', '日本語 ']) * rng.randint(0, 30))
            for key in sorted(rng.sample(range(1, 5000), rng.randint(1, 12)))]
    base += [(5, f'named_{i}', 'x' * i) for i in range(rng.randint(0, 3))]

    def edit():
        rows = list(base)
        for _ in range(rng.randint(1, 4)):
            roll = rng.random()
            if roll < 0.5:
                key = rng.choice([str(rng.randint(1, 6000)), f'mod_{rng.randint(0, 9)}', '0' + str(rng.randint(1, 99))])
                if key not in {row[1] for row in rows}:
                    rows.insert(rng.randint(0, len(rows)), (7, key, 'added ' * rng.randint(0, 40)))
            elif roll < 0.8 and rows:
                index = rng.randrange(len(rows))
                rows[index] = (rows[index][0], rows[index][1], 'edited')
            elif rows:
                rows.pop(rng.randrange(len(rows)))
        return {PALOC: _paloc(rows, container=container)}
    _install(parity, {PALOC: _paloc(base, container=container)}, edit(), edit())


# ---- pappt, pathc, icon registry ---------------------------------------------------------

def _registries():
    from cdmw.core.pappt_format import parse_pappt, encode_pappt
    from cdmw.core.pathc_format import encode_pathc
    from tests.test_pappt_format import _synthetic_bytes
    from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS
    pappt = parse_pappt(_synthetic_bytes(tag_prefix=b'\x01'))
    pathc = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    icon = b'\xef\xbb\xbf<Texture Name="Base" Filename="UI/texture/base.dds" Type="Image"/>\r\n'
    return {PAPPT: encode_pappt(pappt), PATHC: encode_pathc(pathc), ICONS: icon}


def _add_item(values, name, header):
    from cdmw.core.item_icon_registry import add_icon_texture
    from cdmw.core.pappt_format import parse_pappt, encode_pappt, insert_part_prefabs
    from cdmw.core.pathc_format import parse_pathc, encode_pathc, register_dds
    from tests.test_pathc_format import dds_payload
    result = dict(values)
    table = parse_pappt(values[PAPPT])
    result[PAPPT] = encode_pappt(insert_part_prefabs(table, [table.records[0].cloned(name)], after_stem=table.records[-1].stem))
    result[PATHC] = encode_pathc(register_dds(parse_pathc(values[PATHC]), f'ui/texture/{name}.dds', dds_payload(header), tag=4))
    result[ICONS] = add_icon_texture(values[ICONS], name, like='Base')
    return result


def test_registries_from_two_installs(parity):
    from tests.test_pathc_format import BIG_HEADER, ICON_HEADER
    base = _registries()
    _install(parity, base, _add_item(base, 'alpha', BIG_HEADER), _add_item(base, 'beta', ICON_HEADER))
    _install(parity, base, _add_item(base, 'alpha', BIG_HEADER), _add_item(base, 'alpha', BIG_HEADER))
    parity(base, _add_item(base, 'alpha', BIG_HEADER), _add_item(base, 'alpha', ICON_HEADER))
    for tag_prefix in (b'', b'\x01'):
        from tests.test_pappt_format import _synthetic_bytes
        plain = {**base, PAPPT: _synthetic_bytes(tag_prefix=tag_prefix)}
        _install(parity, plain, _add_item(plain, 'alpha', BIG_HEADER), _add_item(plain, 'beta', BIG_HEADER))


def test_texture_registry_collision_rows_and_repeated_headers(parity):
    from cdmw.core.pathc_format import PathcEntry, PathcTable, encode_pathc, pathc_checksum
    from tests.test_pathc_format import BIG_HEADER, ICON_BLOCKS, ICON_HEADER
    header = ICON_HEADER.ljust(148, b'\0')
    entries = sorted([PathcEntry(pathc_checksum('ui/texture/a.dds'), 0, 255, 255, ICON_BLOCKS),
                      PathcEntry(pathc_checksum('ui/texture/b.dds'), 1, 255, 255, ICON_BLOCKS),
                      PathcEntry(pathc_checksum('ui/texture/collided.dds'), 0xFFFF, 0, 1, bytes(16))], key=lambda e: e.checksum)
    table = PathcTable(reserved=0, header_size=148, headers=(header, header), entries=tuple(entries),
                       collisions=(struct.pack('<IHH16s', 0, 0, 0, bytes(16)),), filenames=b'ui/texture/collided.dds\0')
    base = {**_registries(), PATHC: encode_pathc(table)}
    _install(parity, base, _add_item(base, 'alpha', BIG_HEADER), _add_item(base, 'beta', ICON_HEADER))
    other = replace(table, filenames=b'ui/texture/collided.dds\0extra\0')
    parity(base, _add_item(base, 'alpha', BIG_HEADER), {**base, PATHC: encode_pathc(other)})
    broken = replace(table, entries=tuple(replace(e, header_index=7) if e.header_index == 1 else e for e in entries))
    parity(base, _add_item(base, 'alpha', BIG_HEADER), {**base, PATHC: encode_pathc(broken)})


def _icon_registry(*names, crlf=True, bom=True, extra=b''):
    from tests.test_item_icon_registry import registry
    return registry(*names, crlf=crlf, bom=bom) + extra


@pytest.mark.parametrize(('crlf', 'bom'), [(True, True), (False, False), (True, False)])
def test_icon_registry_compositions(parity, crlf, bom):
    from cdmw.core.item_icon_registry import add_icon_texture
    base = _icon_registry('Base', 'BASE', crlf=crlf, bom=bom, extra=b'<Future Keep="yes"/>\r\n<!-- note -->\n')
    alpha, beta = add_icon_texture(base, 'Alpha', like='Base'), add_icon_texture(base, 'Beta', like='Base')
    _install(parity, {ICONS: base}, {ICONS: alpha}, {ICONS: beta})
    parity({ICONS: base}, {ICONS: alpha.replace(b'Keep="yes"', b'Keep="a"')}, {ICONS: beta.replace(b'Keep="yes"', b'Keep="b"')})
    first = add_icon_texture(base, 'Shared', like='Base', filename='UI/first.dds')
    parity({ICONS: base}, {ICONS: first}, {ICONS: add_icon_texture(base, 'Shared', like='Base', filename='UI/second.dds')})


@pytest.mark.parametrize('text', [
    b'<Texture Name="A" Filename="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds" FileName="A.DDS"/>\n<Texture Name="a" FileName="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds" FileName="b.dds"/>',
    b"<Texture Name='A'\r\n Filename = 'a.dds'\tGetRect=\"0,0\tx\"/>",
    b'<Texture Name="A" Filename="a.dds"></Texture>',
    b'<Other><Texture Name="A" Filename="a.dds"/></Other>',
    b'<Other x="1"><Inner/>text</Other><Texture Name="A" Filename="a.dds"/>',
    b'<Texture Name=" " Filename="a.dds"/>',
    b'<Texture Filename="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds"/><Texture Name="a" Filename="other.dds"/>',
    b'<Texture Name="A" Filename="a.dds"/><Texture Name="a" Filename="A.dds"/>',
    b'<Texture Name="A" Filename="a.dds" Type="x"/><Texture Name="a" Filename="a.dds"/>',
    b'no textures at all',
    b'<Texture Name="A" Filename="a.dds"/><Unclosed>',
    b'<Texture Name="A" Filename="a.dds"/></Stray>',
    b'<Texture Name="A" Filename="a.dds"/><!-- a -- b -->',
    b'<Texture Name="A&amp;B" Filename="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds"/>&#65;',
    b'<?xml version="1.0"?><Texture Name="A" Filename="a.dds"/>',
    b'<Texture Name="\xc3\xa9" Filename="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds" Note="caf\xc3\xa9"/>',
    b'<Texture Name="A" Filename="a.dds"/>\xff',
    b'<Texture Name="A" Filename="a.dds"/><![CDATA[x]]>',
    b'<Texture Name="A" Filename="a.dds"/>]]>',
    b'<Texture Name="A" Filename="a.dds"/></CDMWIconRegistry><Texture Name="B" Filename="b.dds"/>',
    b'<Texture Name="A"Filename="a.dds"/>',
    b'<Texture Name="A" Name="B" Filename="a.dds"/>',
    b'<Texture Name="A" Filename="a.dds"',
])
def test_icon_registry_grammar(parity, text):
    good = _icon_registry('Base')
    for files in (({ICONS: good}, {ICONS: text}, {ICONS: good + b'\r\n'}), ({ICONS: text}, {ICONS: good}, {ICONS: text + b'\n'}),
                  ({ICONS: text}, {ICONS: text + b'<Texture Name="Z" Filename="z.dds"/>'}, {ICONS: text + b' '})):
        parity(*files, allow_unsupported=True)


@pytest.mark.parametrize('text', [
    b'<Texture Name="A" Filename="a.dds"/>',
    b'\xef\xbb\xbf<!-- head -->\r\n<Texture Name="A"\tFilename="a.dds" Type="Image" GetRect="0,0,256,256"/>\r\n<Future/>',
    b"<Texture Name='A'\r\n Filename = 'a.dds'\tGetRect=\"0,0\tx\"/>",
    b'<Texture Name="A" Filename="a.dds" Note="caf\xc3\xa9"/>',
    b'<Other x="1"><Inner/>text</Other><Texture Name="A" Filename="a.dds"/>',
])
def test_supported_icon_grammar_is_never_refused(native, text):
    for files in (({ICONS: text}, {ICONS: text + b'\n<Texture Name="Z" Filename="z.dds"/>'}, {ICONS: text + b'\n<Texture Name="Y" Filename="y.dds"/>'}),):
        assert native(*files)[0] == 'ok'


# ---- shipped tables ----------------------------------------------------------------------

def _append_row(payload, header, source_key, new_key):
    """The table with a copy of row `source_key` under `new_key`, appended."""
    from cdmw.core.structured_binary_editor import parse_pabgh_table
    table = parse_pabgh_table(header, payload=payload)
    spans = {row.key: (start, end) for row, start, end in table.row_spans(len(payload))}
    start, end = spans[source_key]
    key = new_key.to_bytes(table.key_width, 'little')
    count = int.from_bytes(header[:table.header_size], 'little') + 1
    grown = header[table.header_size:] + key + struct.pack('<I', len(payload))
    return payload + key + payload[start + table.key_width:end], count.to_bytes(table.header_size, 'little') + grown


@pytest.mark.real_game
def test_shipped_tables_compose_like_python(parity):
    import time
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.item_icon_registry import add_icon_texture, parse_icon_registry
    from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, parse_item_group_table
    from cdmw.core.paloc_format import LocalizationEntry, add_localization_entries, encode_paloc, parse_paloc
    from cdmw.core.pappt_format import encode_pappt, insert_part_prefabs, parse_pappt
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from cdmw.core.storeinfo_table import apply_store_row, insert_stock_entry, parse_store_table, store_index
    from tests.test_pathc_format import ICON_HEADER, dds_payload
    from tools.new_item_corpus import read_table
    from tools.placement_studio import corpus

    root = corpus.game_root()
    base, layout = {}, {}
    for stem in ('storeinfo', 'itemgroupinfo', 'iteminfo'):
        pair = read_table(stem)
        layout[stem] = pair.descriptor['layout']
        body, head = (corpus.normalize_game_path(entry.path) for entry in (pair.payload_entry, pair.header_entry))
        base[body], base[head], layout[stem + '_paths'] = pair.payload, pair.header, (body, head)
    for _package, entry in corpus._iter_archive_entries(root):
        path = corpus.normalize_game_path(entry.path)
        if (path in (PAPPT, ICONS) or path.endswith('localizationstring_eng.paloc')) and path not in base:
            base[path] = bytes(read_archive_entry_data(entry)[0])
    base[PATHC] = (root / 'meta/0.pathc').read_bytes()
    paloc = next(path for path in base if path.endswith('.paloc'))

    def install(item, stem):
        files = dict(base)
        body, head = layout['storeinfo_paths']
        rows = store_index(parse_store_table(files[body], files[head], layout=layout['storeinfo']))
        files[body], files[head] = apply_store_row(files[body], files[head], insert_stock_entry(rows['Store_Camp_Equipment'], item))
        body, head = layout['itemgroupinfo_paths']
        group = parse_item_group_table(files[body], files[head])[0]
        files[body], files[head] = apply_item_group_row(files[body], files[head], add_group_members(group, [item]))
        body, head = layout['iteminfo_paths']
        from cdmw.core.structured_binary_editor import parse_pabgh_table
        donor = parse_pabgh_table(files[head], payload=files[body]).rows[0].key
        files[body], files[head] = _append_row(files[body], files[head], donor, item)
        table = parse_paloc(files[paloc])
        files[paloc] = encode_paloc(add_localization_entries(table, [LocalizationEntry(7, str((item << 32) | 0x70), f'Item {item}')]))
        prefabs = parse_pappt(files[PAPPT])
        files[PAPPT] = encode_pappt(insert_part_prefabs(prefabs, [prefabs.records[0].cloned(stem)]))
        files[PATHC] = encode_pathc(register_dds(parse_pathc(files[PATHC]), f'ui/texture/icon/{stem}.dds', dds_payload(ICON_HEADER), tag=15))
        icons = parse_icon_registry(files[ICONS])
        files[ICONS] = add_icon_texture(files[ICONS], stem, like=icons.textures[0].name)
        return files

    alpha, beta = install(1990001, 'cdmw_parity_alpha'), install(1990002, 'cdmw_parity_beta')
    started = time.perf_counter()
    result = _install(parity, base, alpha, beta)
    assert result[0] == 'ok', result[1]
    print(f'shipped-table parity: {len(base)} files, {sum(map(len, base.values())):,} bytes, '
          f'{time.perf_counter() - started:.1f} s for four Python and four native merges')


# ---- damaged inputs ----------------------------------------------------------------------

def _damage_cases():
    from tests.test_pathc_format import BIG_HEADER
    base = _registries()
    yield 'registries', base, _add_item(base, 'alpha', BIG_HEADER), _add_item(base, 'beta', BIG_HEADER)
    plain = _store_files(*_stores(), 'legacy')
    from cdmw.core.storeinfo_table import insert_stock_entry
    yield 'stores', plain, _store_files(*_store_edit(*_stores(), 'legacy', 2003, lambda r: insert_stock_entry(r, 1990001)), 'legacy'), \
        _store_files(*_store_edit(*_stores(), 'legacy', 2003, lambda r: insert_stock_entry(r, 1990002)), 'legacy')
    from cdmw.core.itemgroupinfo_table import add_group_members
    yield 'groups', _group_files(), _group_files(lambda r: add_group_members(r, [1])), _group_files(lambda r: add_group_members(r, [2]))
    for container in (False, True):
        yield 'paloc', {PALOC: _paloc(PALOC_BASE, container=container)}, \
            {PALOC: _paloc(PALOC_BASE + [(7, '120', 'a')], container=container)}, \
            {PALOC: _paloc(PALOC_BASE + [(7, '130', 'b')], container=container)}


@pytest.mark.parametrize('seed', range(60))
def test_damaged_inputs_fail_the_same_way(parity, seed):
    rng = random.Random(seed)
    cases = list(_damage_cases())
    _name, base, alpha, beta = cases[seed % len(cases)]
    merged = merge_overlay_files(base, alpha, base)
    victim = rng.choice(['before', 'after', 'current'])
    files = {'before': dict(base), 'after': dict(beta), 'current': dict(merged)}
    path = rng.choice(sorted(files[victim]))
    data = bytearray(files[victim][path])
    for _ in range(rng.randint(1, 3)):
        roll = rng.random()
        if roll < 0.5 and data:
            data[rng.randrange(len(data))] = rng.randrange(256)
        elif roll < 0.75 and data:
            cut = rng.randrange(len(data))
            del data[cut:cut + rng.randint(1, 8)]
        else:
            at = rng.randrange(len(data) + 1)
            data[at:at] = rng.randbytes(rng.randint(1, 8))
    files[victim][path] = bytes(data)
    parity(files['before'], files['after'], files['current'], allow_unsupported=True)


# ---- LZ4 blocks --------------------------------------------------------------------------

def _lz4(tmp_path, command, data, *extra):
    source, target = tmp_path / 'lz4-in.bin', tmp_path / 'lz4-out.bin'
    source.write_bytes(data)
    target.unlink(missing_ok=True)
    result = subprocess.run([str(CLI), command, str(source), str(target), *map(str, extra)], capture_output=True, timeout=60)
    assert result.returncode in (0, 3), result.stderr
    return target.read_bytes() if result.returncode == 0 else None


@pytest.mark.parametrize('seed', range(12))
def test_native_lz4_blocks_decode_with_python_lz4(tmp_path, seed):
    import lz4.block
    rng = random.Random(seed)
    words = [rng.randbytes(rng.randint(1, 9)) for _ in range(rng.randint(1, 20))]
    for size in (0, 1, 5, 12, 13, 17, 64, 300, 70_000):
        data = b''.join(rng.choice(words) for _ in range(size))[:size] if seed % 3 else rng.randbytes(size)
        block = _lz4(tmp_path, 'lz4-compress', data)
        assert lz4.block.decompress(block, uncompressed_size=len(data)) == data


@pytest.mark.parametrize('seed', range(40))
def test_native_lz4_decoder_accepts_what_python_lz4_accepts(tmp_path, seed):
    import lz4.block
    rng = random.Random(seed)
    data = b''.join(rng.choice([b'ab', b'abcabcab', rng.randbytes(3)]) for _ in range(rng.randint(1, 80)))
    block = bytearray(lz4.block.compress(data, store_size=False))
    size = len(data)
    if seed % 4:
        for _ in range(rng.randint(1, 2)):
            if rng.random() < 0.6 and block:
                block[rng.randrange(len(block))] = rng.randrange(256)
            elif rng.random() < 0.5 and block:
                del block[rng.randrange(len(block)):]
            else:
                size += rng.choice([-1, 1])
    try:
        expected = lz4.block.decompress(bytes(block), uncompressed_size=max(size, 0))
        expected = expected if len(expected) == size else None
    except lz4.block.LZ4BlockError:
        expected = None
    assert _lz4(tmp_path, 'lz4-decompress', bytes(block), max(size, 0)) == expected
