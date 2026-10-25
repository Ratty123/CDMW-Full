"""The native item composer reads .cditem packages as CDMW's Python does.

SHA-256 against hashlib, raw DEFLATE against zlib (accepting and refusing the same
streams), and ZIP reading against zipfile plus independent_item_package's size check,
on packages CDMW writes and on damaged archives.
"""
import hashlib
import io
import random
import struct
import subprocess
import zipfile
import zlib

import pytest

from cdmw.services import independent_item_package as owner
from tests.test_independent_item_streaming import package  # noqa: F401 - fixture
from tests.test_native_archive_reader import Reader
from tests.test_native_overlay_merge import CLI

pytestmark = pytest.mark.skipif(CLI is None, reason='Requires the explicitly built native item composer')


@pytest.fixture
def cli(tmp_path):
    counter = iter(range(1_000_000))

    def run(command, data, *extra, response=True):
        index = next(counter)
        source, target = tmp_path / f'in-{index}.bin', tmp_path / f'out-{index}.bin'
        source.write_bytes(data)
        args = [str(CLI), command, str(source), *([str(target)] if response else []), *map(str, extra)]
        result = subprocess.run(args, capture_output=True, timeout=120)
        if response:
            return result.returncode, target.read_bytes() if target.exists() else None
        return result.returncode, result.stdout
    return run


def test_sha256(cli):
    rng = random.Random(3)
    for size in (0, 1, 55, 56, 63, 64, 65, 119, 120, 128, 1000, 100_000):
        data = rng.randbytes(size)
        assert cli('sha256', data, response=False)[1].strip().decode() == hashlib.sha256(data).hexdigest()


# ---- DEFLATE -----------------------------------------------------------------------------

def _zlib(stream):
    decoder = zlib.decompressobj(-15)
    try:
        out = decoder.decompress(stream)
    except zlib.error:
        return None
    return out if decoder.eof else None


def _native_inflate(cli, stream, limit=1 << 24):
    code, out = cli('inflate', stream, limit)
    assert code in (0, 3)
    return out if code == 0 else None


def _sample(rng):
    kind = rng.randrange(4)
    size = rng.choice([0, 1, 10, 300, 5000, 70_000, 200_000])
    if kind == 0:
        return rng.randbytes(size)
    if kind == 1:
        return bytes(size)
    words = [rng.randbytes(rng.randint(1, 8)) for _ in range(rng.randint(1, 30))]
    return b''.join(rng.choice(words) for _ in range(size // 4 + 1))[:size]


@pytest.mark.parametrize('seed', range(40))
def test_inflate_decodes_every_zlib_strategy(cli, seed):
    rng = random.Random(seed)
    data = _sample(rng)
    strategy = rng.choice([zlib.Z_DEFAULT_STRATEGY, zlib.Z_FILTERED, zlib.Z_HUFFMAN_ONLY, zlib.Z_RLE, zlib.Z_FIXED])
    encoder = zlib.compressobj(rng.randint(0, 9), zlib.DEFLATED, -15, rng.randint(1, 9), strategy)
    stream = encoder.compress(data) + encoder.flush()
    assert _native_inflate(cli, stream) == data


@pytest.mark.parametrize('seed', range(60))
def test_inflate_refuses_what_zlib_refuses(cli, seed):
    rng = random.Random(1000 + seed)
    data = _sample(rng)[:3000]
    encoder = zlib.compressobj(rng.randint(0, 9), zlib.DEFLATED, -15, 8, rng.choice([zlib.Z_DEFAULT_STRATEGY, zlib.Z_FIXED]))
    stream = bytearray(encoder.compress(data) + encoder.flush())
    for _ in range(rng.randint(1, 3)):
        roll = rng.random()
        if roll < 0.6 and stream:
            stream[rng.randrange(len(stream))] ^= 1 << rng.randrange(8)
        elif roll < 0.8 and stream:
            del stream[rng.randrange(len(stream)):]
        else:
            stream[rng.randrange(len(stream) + 1):rng.randrange(len(stream) + 1)] = rng.randbytes(rng.randint(1, 4))
    assert _native_inflate(cli, bytes(stream)) == _zlib(bytes(stream))


def test_inflate_limits_its_output(cli):
    encoder = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = encoder.compress(bytes(10_000)) + encoder.flush()
    assert _native_inflate(cli, stream, 10_000) == bytes(10_000)
    assert _native_inflate(cli, stream, 9_999) is None


# ---- ZIP ---------------------------------------------------------------------------------

def _python_zip(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows = []
            for info in archive.infolist():
                try:
                    content = ('ok', owner._read_member(archive, info, None))
                except Exception as exc:  # BadZipFile, IndependentItemError, NotImplementedError, EOFError
                    content = ('error', type(exc).__name__)
                rows.append((info.filename, info.orig_filename, info.flag_bits, info.compress_type, info.CRC,
                             info.compress_size, info.file_size, info.external_attr, info.header_offset, content))
            return 'ok', rows
    except Exception as exc:
        return 'error', f'{type(exc).__name__}: {exc}'


def _native_zip(cli, data):
    _code, reply_bytes = cli('zip', data)
    reply = Reader(reply_bytes)
    if reply.status != 'ok':
        return reply.status, reply.message
    rows = []
    for _ in range(reply.number(4)):
        meta = (reply.take(4).decode('utf-8'), reply.take(4).decode('utf-8'), reply.number(4), reply.number(4), reply.number(4),
                reply.number(8), reply.number(8), reply.number(4), int.from_bytes(reply.number(8).to_bytes(8, 'little'), 'little', signed=True))
        status = {0: 'ok', 2: 'error', 3: 'unsupported'}[reply.data[reply.pos]]
        reply.pos += 1
        message, content = reply.take(4), reply.take(8)
        rows.append((*meta, (status, content if status == 'ok' else message.decode('utf-8', 'replace'))))
    return 'ok', rows


def _zip_parity(cli, data, *, allow_unsupported=True):
    expected, actual = _python_zip(data), _native_zip(cli, data)
    if allow_unsupported and actual[0] == 'unsupported':
        return actual
    assert actual[0] == expected[0], (expected, actual)
    if expected[0] != 'ok':
        return actual
    assert len(actual[1]) == len(expected[1])
    for mine, theirs in zip(actual[1], expected[1]):
        assert mine[:9] == theirs[:9]
        if allow_unsupported and mine[9][0] == 'unsupported':
            continue
        assert mine[9][0] == theirs[9][0], (mine[0], mine[9], theirs[9])
        if theirs[9][0] == 'ok':
            assert mine[9][1] == theirs[9][1]
    return actual


def test_packages_cdmw_writes(cli, package):  # noqa: F811 - pytest fixture
    data = owner.package_bytes(package)
    actual = _zip_parity(cli, data, allow_unsupported=False)
    assert actual[0] == 'ok' and all(row[9][0] == 'ok' for row in actual[1])
    assert {row[0] for row in actual[1]} == {'item.json', *('assets/' + key for key in package.blobs)}
    for row in actual[1]:
        if row[0].startswith('assets/'):
            assert hashlib.sha256(row[9][1]).hexdigest() == row[0][7:]


def _archive(rng, *, method, comment=b'', names=None, level=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=method, compresslevel=level) as archive:
        archive.comment = comment
        for name in names or ['item.json', 'assets/' + 'a' * 64, 'dir/nested.bin', 'naïve.txt']:
            archive.writestr(name, _sample(rng)[:20_000])
    return stream.getvalue()


@pytest.mark.parametrize('seed', range(24))
def test_zip_variants(cli, seed):
    rng = random.Random(seed)
    method = rng.choice([zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
    # A comment holding the end-record signature hides the real record from zipfile's
    # backwards search; both readers must then refuse the archive.
    comment = rng.choice([b'', b'note', b'PK\x05\x06 inside', bytes(300)])
    data = _archive(rng, method=method, comment=comment, level=rng.choice([None, 0, 1, 9]) if method == zipfile.ZIP_DEFLATED else None)
    if seed % 3 == 0:
        data = rng.randbytes(rng.randint(1, 500)) + data  # prepended data, as a self-extractor has
    actual = _zip_parity(cli, data, allow_unsupported=False)
    assert actual[0] == ('error' if b'PK\x05\x06' in comment else 'ok')


def test_zip_names_extra_fields_and_duplicates(cli):
    rng = random.Random(9)
    base = _archive(rng, method=zipfile.ZIP_DEFLATED, names=['item.json', 'b.bin', 'item.json'])
    _zip_parity(cli, base, allow_unsupported=False)
    # A backslash and a NUL in a stored name, written in both headers.
    raw = bytearray(_archive(rng, method=zipfile.ZIP_STORED, names=['dir/a_b.bin']))
    for at in [i for i in range(len(raw)) if raw[i:i + 11] == b'dir/a_b.bin']:
        raw[at + 3] = ord('\\')
        raw[at + 5] = 0
    _zip_parity(cli, bytes(raw), allow_unsupported=False)
    # Info-ZIP's Unicode path field renames a member whose name CRC it matches.
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        info = zipfile.ZipInfo('plain.bin')
        unicode_name = 'unicodé.bin'.encode()
        info.extra = struct.pack('<HHBL', 0x7075, 5 + len(unicode_name), 1, zlib.crc32(b'plain.bin')) + unicode_name
        archive.writestr(info, b'renamed')
        other = zipfile.ZipInfo('kept.bin')
        other.extra = struct.pack('<HHBL', 0x7075, 5 + 3, 1, 1234) + b'xyz'
        archive.writestr(other, b'kept')
    _zip_parity(cli, stream.getvalue(), allow_unsupported=False)


@pytest.mark.parametrize('seed', [*range(80), 183, 185, 236])  # the last three shift offsets negative
def test_damaged_zips_fail_the_same_way(cli, seed):
    rng = random.Random(500 + seed)
    data = bytearray(_archive(rng, method=rng.choice([zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]), names=['item.json', 'assets/' + 'b' * 64]))
    for _ in range(rng.randint(1, 3)):
        roll = rng.random()
        if roll < 0.7 and data:
            data[rng.randrange(len(data))] = rng.randrange(256)
        elif roll < 0.85 and data:
            del data[rng.randrange(len(data)):]
        else:
            at = rng.randrange(len(data) + 1)
            data[at:at] = rng.randbytes(rng.randint(1, 6))
    _zip_parity(cli, bytes(data))


def test_overlapping_members_are_refused(cli):
    rng = random.Random(4)
    data = bytearray(_archive(rng, method=zipfile.ZIP_STORED, names=['a.bin', 'b.bin']))
    # Point the second member's directory entry at the first member's local header.
    first = data.find(b'PK\x01\x02')
    second = data.find(b'PK\x01\x02', first + 4)
    struct.pack_into('<I', data, second + 42, 0)
    _zip_parity(cli, bytes(data), allow_unsupported=False)
