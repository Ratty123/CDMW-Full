"""The native item composer writes overlay archives and mount lists byte for byte like Python."""
import random
import struct
import subprocess

import pytest

from cdmw.core import archive_overlay
from cdmw.core.archive_format import calculate_pa_checksum, hashlittle
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import PapgtDirectory, papgt_with_directory, parse_papgt, serialize_papgt
from tests.test_native_overlay_merge import CLI, STATUS

pytestmark = pytest.mark.skipif(CLI is None, reason='Requires the explicitly built native item composer')


@pytest.fixture
def cli(tmp_path):
    counter = iter(range(1_000_000))

    def run(command, data, *extra):
        index = next(counter)
        source, target = tmp_path / f'in-{index}.bin', tmp_path / f'out-{index}.bin'
        source.write_bytes(data)
        subprocess.run([str(CLI), command, str(source), str(target), *map(str, extra)], check=True, capture_output=True, timeout=120)
        return target.read_bytes()
    return run


def _status(data):
    assert data[:8] == b'CDMWRES1'
    size = struct.unpack_from('<I', data, 9)[0]
    return STATUS[data[8]], data[13:13 + size].decode('utf-8', 'replace'), 13 + size


def _native_overlay(cli, files):
    request = bytearray(b'CDMWOVL1' + struct.pack('<I', len(files)))
    for item in files:
        path = item.path.encode('utf-8')
        request += struct.pack('<I', len(path)) + path + struct.pack('<Q', len(item.payload)) + item.payload
        request += struct.pack('<QQ', item.orig_size, item.flags)
    data = cli('overlay', bytes(request))
    status, message, pos = _status(data)
    if status != 'ok':
        return status, message
    def take(width):
        nonlocal pos
        size = int.from_bytes(data[pos:pos + width], 'little')
        value = data[pos + width:pos + width + size]
        pos += width + size
        return value
    pamt, paz = take(8), take(8)
    checksum, count = struct.unpack_from('<II', data, pos)
    pos += 8
    entries = []
    for _ in range(count):
        path = take(4).decode('utf-8')
        entries.append((path, *struct.unpack_from('<QQQ', data, pos)))
        pos += 24
    assert pos == len(data)
    return 'ok', (pamt, paz, checksum, tuple(entries))


def _python_overlay(files):
    try:
        archive = build_overlay_archive(files)
    except Exception as exc:
        return 'error', f'{type(exc).__name__}: {exc}'
    return 'ok', (archive.pamt_bytes, archive.paz_bytes, archive.pamt_checksum, archive.entries)


@pytest.fixture
def overlay_parity(cli, monkeypatch):
    # The PAZ checksum is calculate_pa_checksum; large payloads otherwise need the native helper.
    monkeypatch.setattr(archive_overlay, '_payload_checksum', lambda payload, stop_event=None: calculate_pa_checksum(bytes(payload)))

    def check(files, *, allow_unsupported=False):
        expected, actual = _python_overlay(files), _native_overlay(cli, files)
        if actual[0] == 'unsupported' and allow_unsupported:
            return actual
        assert actual[0] == expected[0], (expected, actual)
        if expected[0] == 'ok':
            assert actual[1] == expected[1]
        return expected
    return check


def _file(path, payload=b'data', orig=None, flags=0):
    return OverlayFile(path=path, payload=payload, orig_size=len(payload) if orig is None else orig, flags=flags)


@pytest.mark.parametrize('files', [
    [_file('gamedata/binary__/client/bin/storeinfo.pabgb', b'x' * 37, 120, 2)],
    [_file('character/bin__/prefab/1_pc/a.prefab'), _file('character/bin__/prefab/1_pc/b.prefab', b'b' * 17),
     _file('character/bin__/partprefabtable.pappt', b'p' * 3), _file('character/texture/x.dds', b'd' * 64, 4096, 3),
     _file('ui/xml/texture/cd_item_icon.xml'), _file('ui/texture/icon/itemicon.dds', b'')],
    [_file('root.bin'), _file('zeta/one.bin'), _file('alpha/one.bin'), _file('alpha/beta/two.bin'), _file('alpha/b/three.bin')],
    [_file('a/same.bin', b'first'), _file('a/same.bin', b'second'), _file('a/Same.bin', b'third')],
    [_file('  \\leading\\back\\slashes.bin '), _file('/trailing/slash.bin/'), _file('\twhite / space .bin\n')],
    [_file('ünïcode/földer/naïve.bin'), _file('ünïcode/földer/zz.bin'), _file('ascii/after.bin')],
    [_file('a/' + 'n' * 255), _file('b/' + 'n' * 254)],
    [_file('x' * 200 + '/' + 'y' * 60 + '/file.bin')],
    [_file('dds/flags.bin', flags=0xFFFF)],
    [],
    [_file('')],
    [_file('   /  ')],
    [_file('a/' + 'n' * 256)],
    [_file('x' * 256 + '/file.bin')],
    [_file('flags/too.bin', flags=0x10000)],
    [_file('size/too.bin', orig=2 ** 32)],
    [_file('a/b/'), _file('a/b/c.bin')],
])
def test_overlay_archives(overlay_parity, files):
    overlay_parity(files)


def test_large_payloads_and_alignment(overlay_parity):
    rng = random.Random(7)
    overlay_parity([_file(f'big/file_{i:02}.bin', rng.randbytes(rng.choice([1, 15, 16, 17, 70_000, 200_001]))) for i in range(8)])


@pytest.mark.parametrize('seed', range(40))
def test_random_overlay_archives(overlay_parity, seed):
    rng = random.Random(seed)
    parts = ['gamedata', 'binary__', 'client', 'bin', 'character', 'prefab', 'texture', 'ui', 'a', 'ab', 'abc', 'é']
    files = []
    for _ in range(rng.randint(1, 25)):
        depth = rng.randint(0, 4)
        folder = '/'.join(rng.choice(parts) for _ in range(depth))
        name = rng.choice(['x', 'xy', 'xyz', 'file', 'file2', 'ä.bin']) + rng.choice(['', '.pabgb', '.dds', '_' + str(rng.randint(0, 9))])
        path = f'{folder}/{name}' if folder else name
        if rng.random() < 0.1:
            path = path.replace('/', '\\')
        files.append(_file(path, rng.randbytes(rng.randint(0, 40)), rng.randint(0, 2 ** 20), rng.randint(0, 4)))
    overlay_parity(files)


@pytest.mark.parametrize('path', ['a/b ', '　a/b.bin', ' /a /b.bin\x1c', 'é/ä', 'a/​zero-width.bin'])
def test_unicode_white_space_is_stripped_like_python(overlay_parity, path):
    overlay_parity([_file(path)])


# ---- PAPGT -------------------------------------------------------------------------------

def _papgt(names, header=b'\x01\x02\x03\x04\0\0\0\0\x00\x09\x08\x07'):
    return serialize_papgt([PapgtDirectory(name, 0x007FFF00 + i, 0x1000 + i) for i, name in enumerate(names)], header=header)


def _native_bytes(data):
    status, message, pos = _status(data)
    if status != 'ok':
        return status, message
    size = struct.unpack_from('<Q', data, pos)[0]
    return 'ok', data[pos + 8:pos + 8 + size]


def _python_bytes(action):
    try:
        return 'ok', action()
    except Exception as exc:
        return 'error', f'{type(exc).__name__}: {exc}'


def _same(expected, actual):
    assert actual[0] == expected[0], (expected, actual)
    if expected[0] == 'ok':
        assert actual[1] == expected[1]


SOURCES = {
    'shipped shape': _papgt([f'{i:04}' for i in range(20)] + ['0035']),
    'repeated names': _papgt(['0000', '0001', '0000']),
    'no directories': _papgt([]),
    'zero header': _papgt(['0000'], header=b''),
}


@pytest.mark.parametrize('name', sorted(SOURCES))
def test_mount_lists_round_trip_and_mount(cli, name):
    data = SOURCES[name]
    _same(_python_bytes(lambda: serialize_papgt(parse_papgt(data), header=data[:12])), _native_bytes(cli('papgt-roundtrip', data)))
    for directory, checksum, flags, first in (('0100', 0xDEADBEEF, 0x007FFF00, True), ('0100', 7, 5, False),
                                               ('0001', 0x12345678, 0, True), ('café', 1, 0, True)):
        expected = _python_bytes(lambda: papgt_with_directory(data, directory, checksum, flags=flags, first=first))
        actual = _native_bytes(cli('papgt-add', data, directory, checksum, flags, int(first)))
        _same(expected, actual)


@pytest.mark.parametrize('damage', ['checksum', 'count', 'table size', 'offset', 'unterminated', 'non-ascii', 'short'])
def test_damaged_mount_lists_are_refused_alike(cli, damage):
    data = bytearray(_papgt(['0000', '0001']))
    if damage == 'checksum':
        data[4] ^= 1
    elif damage == 'count':
        data[8] = 9
    elif damage == 'table size':
        data[12 + 2 * 12] += 1
    elif damage == 'offset':
        data[12 + 4] = 200
    elif damage == 'unterminated':
        data[-1] = ord('x')
    elif damage == 'non-ascii':
        data[-2] = 0xE9
    else:
        data = data[:15]
    if damage not in ('checksum', 'short'):
        struct.pack_into('<I', data, 4, calculate_pa_checksum(bytes(data[12:])))
    data = bytes(data)
    _same(_python_bytes(lambda: serialize_papgt(parse_papgt(data), header=data[:12])), _native_bytes(cli('papgt-roundtrip', data)))


def test_more_than_255_directories_are_refused(cli):
    data = _papgt([f'{i:04}' for i in range(255)])
    _same(_python_bytes(lambda: papgt_with_directory(data, '9999', 1)), _native_bytes(cli('papgt-add', data, '9999', 1, 0x007FFF00, 1)))


@pytest.mark.parametrize('size', [0, 1, 3, 4, 5, 11, 12, 13, 24, 25, 100, 4097])
def test_checksums(cli, size):
    data = random.Random(size).randbytes(size)
    assert cli('checksum', data) == struct.pack('<II', calculate_pa_checksum(data), hashlittle(data, 0xC5EDE))
