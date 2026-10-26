"""The native item composer reads and writes archive entries byte for byte like Python.

Covers stored payloads (archive_patching), the plain-text check that validates decrypted
XML, PAMT parsing and reading the effective file of each path through the mount list.
The native reader mounts exactly the groups meta/0.papgt lists, DMM's included, as the
game does; Python's catalogue skips DMM's folders by default, so the comparisons below
turn that skip off.
"""
from pathlib import Path
import random
import struct
import subprocess

import pytest

from cdmw.core.archive_format import parse_archive_pamt_bytes
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PapgtDirectory, serialize_papgt
from cdmw.services.archive_overlay_install import _processed_payload
from tests.test_native_overlay_merge import CLI, STATUS

pytestmark = pytest.mark.skipif(CLI is None, reason='Requires the explicitly built native item composer')
READ_STATUS = {0: 'ok', 1: 'absent', 2: 'error', 3: 'unsupported'}


@pytest.fixture
def cli(tmp_path):
    counter = iter(range(1_000_000))

    def run(command, data, *extra, response=True):
        index = next(counter)
        source, target = tmp_path / f'in-{index}.bin', tmp_path / f'out-{index}.bin'
        source.write_bytes(data)
        args = [str(CLI), command, str(source), *([str(target)] if response else []), *map(str, extra)]
        result = subprocess.run(args, check=True, capture_output=True, timeout=120)
        return target.read_bytes() if response else result.stdout
    return run


class Reader:
    def __init__(self, data):
        assert data[:8] == b'CDMWRES1'
        self.data, self.status = data, STATUS[data[8]]
        self.pos = 9
        self.message = self.take(4).decode('utf-8', 'replace')

    def number(self, width):
        value = int.from_bytes(self.data[self.pos:self.pos + width], 'little')
        self.pos += width
        return value

    def take(self, width):
        size = self.number(width)
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value


def _python(action):
    try:
        return 'ok', action()
    except Exception as exc:
        return 'error', f'{type(exc).__name__}: {exc}'


# ---- stored payloads ---------------------------------------------------------------------

@pytest.mark.parametrize('flags', [0x00, 0x01, 0x02, 0x30, 0x31, 0x32, 0x12, 0x03, 0x33])
@pytest.mark.parametrize('basename', ['storeinfo.pabgb', 'CD_Item_Icon.XML', 'localizationstring_eng.paloc'])
def test_stored_payloads(cli, flags, basename):
    rng = random.Random(flags * 31 + len(basename))
    for data in (b'', b'x', rng.randbytes(5000), b'<Texture Name="A"/>\r\n' * 900, bytes(70_000)):
        expected = _python(lambda: _processed_payload(data, compression_type=flags & 15, encrypted=bool(flags >> 4), basename=basename))
        reply = Reader(cli('store', data, flags, basename))
        actual = ('ok', reply.take(8)) if reply.status == 'ok' else ('error' if reply.status == 'error' else reply.status, reply.message)
        assert actual[0] == expected[0], (expected, actual)
        if expected[0] == 'ok':
            assert actual[1] == expected[1]


def test_chacha20_refuses_a_payload_past_its_block_counter(cli):
    # The seed is the starting block counter; the cryptography package refuses to wrap it.
    from cdmw.core.archive_format import CHACHA20_HASH_INITVAL, hashlittle
    name, seed = next((n, s) for n in (f'x{i}.xml' for i in range(2_000_000))
                      for s in (hashlittle(n.encode(), CHACHA20_HASH_INITVAL),) if s > 0xFFFF0000)
    room = 64 * (2 ** 32 - seed)
    for size in (room - 1, room, room + 1):
        data = random.Random(size).randbytes(size)
        expected = _python(lambda: _processed_payload(data, compression_type=0, encrypted=True, basename=name))
        reply = Reader(cli('store', data, 0x30, name))
        assert reply.status == expected[0], (size, room, expected[1] if expected[0] != 'ok' else '')
        if expected[0] == 'ok':
            assert reply.take(8) == expected[1]


# ---- the decrypted-text check ------------------------------------------------------------

def _text_cases():
    rng = random.Random(11)
    fixed = [b'', b'\xef\xbb\xbf', b'\xef\xbb\xbf \r\n', b'\xef\xbb\xbfx', b'\xff\xfe', b'\xff\xfe \x00', b'\xff\xfeA\x00',
             b'\xfe\xff\x00A', b'\xff\xfe\x00', b'<?xml version="1.0"?><a/>', b'{"a": 1}', b'\x00' * 10, b'abc\x00\x00\x00def',
             b'\xef\xbb\xbf\xef\xbb\xbf', b'\xed\xa0\x80' * 50, b'\xf0\x80\x80' + b'a' * 40, b'\x01\x02\x03' + b'a' * 30,
             b' \t\r\n' * 10, b'\x1c\x1d\x1e\x1f' * 10 + b'abc', '  text'.encode() * 20]
    yield from fixed
    alphabet = [b'a', b'<', b' ', b'\r\n', b'\x00', b'\x01', b'\x7f', b'\xc3\xa9', b'\xe2\x82', b'\xff', b'\xef\xbb\xbf', b'\x85']
    for _ in range(600):
        size = rng.choice([1, 3, 10, 50, 200, 2000, 5000])
        if rng.random() < 0.3:
            yield rng.randbytes(size)
        else:
            yield b''.join(rng.choice(alphabet) for _ in range(size))[:size * 2]


def test_plain_text_check(cli):
    from cdmw.domain.archives.format import try_decode_text_like_archive_data
    for data in _text_cases():
        expected = try_decode_text_like_archive_data(data) is not None
        assert cli('text-check', data, response=False).strip() == (b'1' if expected else b'0'), data[:60]


def test_structured_binary_check(cli):
    from cdmw.core.archive_format import _looks_like_structured_binary_payload
    rng = random.Random(21)
    words = [b'cd_phm_01_sword', b'character/bin__/prefab', b'ab::cd', b'Plain words here', b'x' * 170, b'abc', b'a1b2c3d4e5f6',
             b'CD_MainWeapon_Sword_R', b'\x00', b'\x01\x02', b'  padded_name  ', b'1234', b'!!!!????', b'ABCDEFGHIJKL']
    cases = [b'', b'PAR ', b'PARC', b'RIFF\0\0\0\0WAVE', b'\0\0\0\0TAG0\0\0\0\0SDKV', b'DDS ' + bytes(10)]
    cases += [b''.join(rng.choice(words) for _ in range(rng.randint(0, 40))) for _ in range(300)]
    cases += [rng.randbytes(rng.randint(0, 20_000)) for _ in range(20)]
    for data in cases:
        for extension in ('.pappt', '.dds'):
            expected = _looks_like_structured_binary_payload(extension, data)
            assert cli('structured-check', data, extension, response=False).strip() == (b'1' if expected else b'0'), data[:80]


# ---- PAMT parsing ------------------------------------------------------------------------

def _files(rng, count):
    folders = ['gamedata/binary__/client/bin', 'character/bin__', 'ui/xml/texture', '', 'a/b/c/d', 'é/ü']
    return [OverlayFile(f"{rng.choice(folders)}/{rng.choice(['x', 'item', 'storeinfo', 'n'])}{i}.{rng.choice(['pabgb', 'xml', 'paloc'])}".strip('/'),
                        rng.randbytes(rng.randint(0, 50)), rng.randint(0, 1000), rng.choice([0, 2, 0x32]))
            for i in range(count)]


def _listing(data):
    reply = Reader(data)
    if reply.status != 'ok':
        return reply.status, reply.message
    rows = []
    for _ in range(reply.number(4)):
        rows.append((reply.take(4).decode('utf-8'), reply.number(8), reply.number(8), reply.number(8), reply.number(4), reply.number(4)))
    return 'ok', rows


def _python_listing(data, path):
    def parse():
        return [(e.path, e.offset, e.comp_size, e.orig_size, e.flags, e.paz_index) for e in parse_archive_pamt_bytes(data, path)]
    return _python(parse)


@pytest.mark.parametrize('seed', range(40))
def test_pamt_parsing(cli, tmp_path, seed):
    rng = random.Random(seed)
    pamt = build_overlay_archive(_files(rng, rng.randint(1, 30))).pamt_bytes
    if seed % 2:
        damaged = bytearray(pamt)
        for _ in range(rng.randint(1, 4)):
            roll = rng.random()
            if roll < 0.6 and damaged:
                damaged[rng.randrange(len(damaged))] = rng.randrange(256)
            elif roll < 0.8 and damaged:
                del damaged[rng.randrange(len(damaged)):]
            else:
                damaged.insert(rng.randrange(len(damaged) + 1), rng.randrange(256))
        pamt = bytes(damaged)
    path = tmp_path / f'case{seed}' / '0.pamt'
    path.parent.mkdir()
    expected = _python_listing(pamt, path)
    actual = _listing(cli('pamt', pamt))
    assert actual[0] == expected[0], (expected, actual)
    if expected[0] == 'ok':
        assert actual[1] == expected[1]


def test_pamt_name_tries_with_cycles_and_shared_prefixes(cli, tmp_path):
    def record(parent, text):
        return struct.pack('<IB', parent, len(text)) + text
    names = record(0xFFFFFFFF, b'item') + record(0, b'_a.pabgb') + record(26, b'loop') + record(13, b'_b.xml') + record(9, b'_c')
    directories = record(0xFFFFFFFF, b'gamedata') + record(0, b'/bin\\') + record(0xFFFFFFFF, b'\xff\xfebad')
    out = struct.pack('<III', 0, 1, 0x610E0232) + struct.pack('<III', 0, 0, 0)
    out += struct.pack('<I', len(directories)) + directories + struct.pack('<I', len(names)) + names
    folders = [(0, 0, 0, 2), (0, 13, 2, 2), (0, 22, 4, 1)]
    out += struct.pack('<I', len(folders)) + b''.join(struct.pack('<IIII', *f) for f in folders)
    files = [(0, 0, 1, 1), (5, 0, 1, 1), (13, 0, 1, 1), (26, 0, 1, 1), (37, 0, 1, 1)]
    out += struct.pack('<I', len(files)) + b''.join(struct.pack('<IIIIHH', o, a, b, c, 0, 0) for o, a, b, c in files)
    path = tmp_path / '0.pamt'
    assert _listing(cli('pamt', out)) == _python_listing(out, path)


# ---- the effective file of each path -----------------------------------------------------

ICON_XML = b'\xef\xbb\xbf<Texture Name="Base" Filename="UI/texture/base.dds" Type="Image"/>\r\n' * 40


def _paloc_container():
    from cdmw.core.paloc_format import LocalizationEntry, encode_paloc
    from tests.test_paloc_container import wrapped
    return wrapped(encode_paloc([LocalizationEntry(7, '100', 'Sword ' * 50), LocalizationEntry(8, '101', 'Text')]))


def _install(root, groups, order):
    """Archive groups written as the game ships them, and a mount list in `order`."""
    for name, files in groups.items():
        entries = []
        for path, raw, flags, stored in files:
            payload = stored if stored is not None else _processed_payload(raw, compression_type=flags & 15,
                                                                          encrypted=bool(flags >> 4), basename=path.rsplit('/', 1)[-1])
            entries.append(OverlayFile(path, payload, len(raw), flags))
        archive = build_overlay_archive(entries)
        (root / name).mkdir(parents=True)
        (root / name / '0.pamt').write_bytes(archive.pamt_bytes)
        (root / name / '0.paz').write_bytes(archive.paz_bytes)
    papgt = serialize_papgt([PapgtDirectory(name, 0x007FFF00, 0) for name in order])
    (root / 'meta').mkdir()
    (root / 'meta' / '0.papgt').write_bytes(papgt)
    return papgt


def _python_effective(root, paths, monkeypatch):
    from cdmw.core import archive_accelerator
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_scan_cache import discover_pamt_files
    # The in-process decode alone is the contract; the helper fallback is out of scope.
    monkeypatch.setattr(archive_accelerator, 'read_archive_entry_data_native', lambda *a, **k: None)
    first = {}
    for pamt in discover_pamt_files(root, use_default_ignored_folders=False):
        for entry in parse_archive_pamt(pamt):
            first.setdefault(entry.path.replace('\\', '/').strip().strip('/').lower(), entry)
    results = []
    for path in paths:
        entry = first.get(path.lower())
        if entry is None:
            results.append(('absent',))
            continue
        outcome = _python(lambda: read_archive_entry_data(entry)[0])
        results.append((outcome[0], outcome[1], Path(entry.pamt_path).resolve(), entry.flags) if outcome[0] == 'ok' else (outcome[0],))
    return results


def _native_effective(cli_path, root, papgt_path, paths):
    target = root.parent / 'read-response.bin'
    subprocess.run([str(CLI), 'read-archives', str(root), str(papgt_path), str(target), *paths], check=True, capture_output=True, timeout=120)
    reply = Reader(target.read_bytes())
    assert reply.status == 'ok', reply.message
    results = []
    for _ in range(reply.number(4)):
        status = READ_STATUS[reply.data[reply.pos]]
        reply.pos += 1
        message = reply.take(4).decode('utf-8', 'replace')
        if status == 'ok':
            pamt = Path(reply.take(4).decode('utf-8')).resolve()
            flags = reply.number(4)
            results.append((status, reply.take(8), pamt, flags))
        else:
            results.append((status, message) if status == 'unsupported' else (status,))
    return results


def test_effective_files_follow_the_mount_order(tmp_path, monkeypatch):
    root = tmp_path / 'game'
    store = b'\x01\x00' + b'store row ' * 300
    groups = {
        '0000': [('gamedata/binary__/client/bin/storeinfo.pabgb', store, 0x02, None),
                 ('gamedata/binary__/client/bin/storeinfo.pabgh', b'\x01\x00\x01\x00\x00\x00\x00\x00', 0x00, None),
                 ('ui/xml/texture/cd_item_icon.xml', ICON_XML, 0x32, None),
                 ('gamedata/stringtable/binary__/localizationstring_eng.paloc', _paloc_container(), 0x30, None),
                 ('character/bin__/partprefabtable.pappt', b'\x00' * 12 + b'\x00' * 4, 0x02, None),
                 ('only/in/base.bin', b'base', 0x00, None)],
        '0001': [('gamedata/binary__/client/bin/storeinfo.pabgb', store + b'from 0001', 0x02, None),
                 ('ui/xml/texture/flagged_plain.xml', ICON_XML, 0x32, _processed_payload(ICON_XML, compression_type=2, encrypted=False, basename='x')),
                 ('ui/xml/texture/garbage.xml', b'x' * 64, 0x30, random.Random(1).randbytes(64)),
                 ('gamedata/binary__/client/bin/bad_lz4.pabgb', b'y' * 200, 0x02, b'\xf0' + b'\x00' * 10)],
        'dmmsa': [('gamedata/binary__/client/bin/storeinfo.pabgb', store + b'from DMM', 0x02, None),
                  ('ui/xml/texture/cd_item_icon.xml', ICON_XML.replace(b'Base', b'Dmmm'), 0x32, None)],
    }
    papgt = _install(root, groups, ['dmmsa', '0001', '0000'])
    paths = ['gamedata/binary__/client/bin/storeinfo.pabgb', 'GameData/Binary__/Client/Bin/StoreInfo.PABGH', 'ui/xml/texture/cd_item_icon.xml',
             'gamedata/stringtable/binary__/localizationstring_eng.paloc', 'character/bin__/partprefabtable.pappt',
             'only/in/base.bin', 'ui/xml/texture/flagged_plain.xml', 'ui/xml/texture/garbage.xml',
             'gamedata/binary__/client/bin/bad_lz4.pabgb', 'not/there.bin']
    expected = _python_effective(root, paths, monkeypatch)
    actual = _native_effective(CLI, root, root / 'meta' / '0.papgt', paths)
    for path, mine, theirs in zip(paths, actual, expected):
        assert mine[:1] == theirs[:1], (path, mine, theirs)
        if theirs[0] == 'ok':
            assert mine == theirs, path
    assert actual[0][1].endswith(b'from DMM')


def test_unlisted_directories_are_not_mounted(tmp_path):
    root = tmp_path / 'game'
    papgt = _install(root, {'0000': [('a/listed.bin', b'listed', 0, None)], '0041': [('a/unlisted.bin', b'stale', 0, None)]}, ['0000'])
    actual = _native_effective(CLI, root, root / 'meta' / '0.papgt', ['a/listed.bin', 'a/unlisted.bin'])
    assert [row[0] for row in actual] == ['ok', 'absent']


@pytest.mark.real_game
def test_shipped_tables_read_like_python(monkeypatch):
    from tools.placement_studio import corpus
    root = corpus.game_root()
    tables = 'gamedata/binarystaticinfo__/bin/'
    paths = [tables + name for stem in ('storeinfo', 'itemgroupinfo', 'iteminfo', 'multichangeinfo', 'dropsetinfo')
             for name in (stem + '.staticinfobody', stem + '.staticinfoheader')]
    paths += ['character/bin__/partprefabtable.pappt', 'ui/xml/texture/cd_item_icon.xml']
    paths += [f'gamedata/stringtable/binary__/{language}/item.paloc' for language in ('eng', 'kor', 'jpn', 'ara')]
    expected = _python_effective(root, paths, monkeypatch)
    actual = _native_effective(CLI, root, root / 'meta' / '0.papgt', paths)
    for path, mine, theirs in zip(paths, actual, expected):
        assert mine == theirs, path
