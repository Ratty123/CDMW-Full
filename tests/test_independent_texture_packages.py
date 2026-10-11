"""Owned archive fixtures and strict admission for existing-texture packages."""
from copy import deepcopy
from dataclasses import replace
import struct
from uuid import uuid4

import pytest

from cdmw.core.pathc_format import PathcTable, encode_pathc, register_dds
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.new_item.mod_package import capability_result
from cdmw.services import independent_item_install as install
from cdmw.services.independent_item_package import (
    FORMAT, canonical, digest, package_bytes, package_metadata, read_package, stock_snapshot,
)
from cdmw.services.independent_mod_package import has_legacy_item, read_v2
from tests.test_independent_item_regressions import files_in
from tests.test_independent_item_v2 import packed

TEXTURE_PATH = 'character/texture/1_pc/cdmw_existing_d.dds'
SECOND_TEXTURE_PATH = 'character/texture/1_pc/cdmw_existing_second_d.dds'


def dds_payload(*, width=8, height=8, mips=4, fourcc=b'DXT1', fill=0, dxgi=71):
    """Small complete raw 2D BC payload; each mip has its actual block size."""
    data = bytearray(148 if fourcc == b'DX10' else 128)
    data[:4] = b'DDS '
    struct.pack_into('<I', data, 4, 124)
    struct.pack_into('<I', data, 8, 0x000A1007)
    struct.pack_into('<II', data, 12, height, width)
    block = 8 if fourcc in (b'DXT1', b'BC4U', b'ATI1', b'BC4S') or (
        fourcc == b'DX10' and dxgi in (71, 72, 80, 81)) else 16
    struct.pack_into('<I', data, 20, max(1, (width + 3) // 4) * max(1, (height + 3) // 4) * block)
    struct.pack_into('<I', data, 28, mips)
    struct.pack_into('<II', data, 76, 32, 4)
    data[84:88] = fourcc
    struct.pack_into('<I', data, 108, 0x401008 if mips > 1 else 0x1000)
    if fourcc == b'DX10':
        struct.pack_into('<5I', data, 128, dxgi, 3, 0, 1, 0)
    w, h = width, height
    for _ in range(mips):
        data.extend(bytes([fill]) * (max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * block))
        w, h = max(1, w // 2), max(1, h // 2)
    return bytes(data)


def texture_game(tmp_path, *, source=None, registered=True):
    """Build a current owned catalogue whose legacy material uses TEXTURE_PATH."""
    from cdmw.core.pappt_format import encode_pappt, parse_pappt
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import PAC_XML, STEM, build_package
    from tests.test_pac_xml_standard_material import HEAD, TAIL, wrapper, texture, STANDARD_SHADER

    source = dds_payload() if source is None else source
    files = current_files()
    files[TEXTURE_PATH] = source
    files[SECOND_TEXTURE_PATH] = source
    files[PAC_XML] = (HEAD + wrapper(STEM, STANDARD_SHADER,
        texture('_baseColorTexture', '0', TEXTURE_PATH, 0)) + TAIL).encode()
    pappt_path = 'character/bin__/partprefabtable.pappt'
    pappt = parse_pappt(files[pappt_path])
    sockets = 'character/sockets/independent_texture_test.sockets.xml'
    files[pappt_path] = encode_pappt(replace(pappt, records=tuple(
        replace(record, sockets_path=sockets) for record in pappt.records)))
    files[sockets] = b'<Sockets/>'
    root = tmp_path / 'game'
    build_package(root, files)
    table = PathcTable(0, 148, (), (), (), b'')
    for path, data in sorted(files.items()):
        if path.endswith('.dds') and (registered or path not in (TEXTURE_PATH, SECOND_TEXTURE_PATH)):
            table = register_dds(table, path, data)
    (root / 'meta/0.pathc').write_bytes(encode_pathc(table))
    return root, stock_snapshot(root)


def texture_manifest(snapshot, replacements=None, identity=None, title='Existing texture', release='1'):
    replacements = {TEXTURE_PATH: dds_payload(fill=1)} if replacements is None else replacements
    blobs, dependencies, rows = {}, {}, []
    for path, data in replacements.items():
        source = snapshot.payload(path)
        header_size = 148 if source[84:88] == b'DX10' else 128
        key = digest(data)
        blobs[key] = data
        dependencies[path] = digest(source)
        rows.append({'path': path, 'source_sha256': digest(source), 'source_size': len(source),
                     'replacement': key, 'descriptor_sha256': digest(source[:header_size])})
    manifest = {'format': FORMAT, 'version': 2, 'identity': identity or uuid4().hex,
        'title': title, 'release': release, 'requires': {'texture.replace': 1},
        'modules': [{'id': 'textures', 'type': 'texture.replace', 'version': 1, 'required': True,
            'data': {'registry_sha256': digest(encode_pathc(snapshot.pathc)), 'replacements': rows}}],
        'dependencies': dependencies, 'blobs': {key: len(data) for key, data in blobs.items()},
        'provenance': None, 'metadata': {}}
    return manifest, blobs


def texture_package(snapshot, replacements=None, identity=None, title='Existing texture', release='1'):
    from cdmw.services.independent_texture_package import from_texture_replacements
    replacements = {TEXTURE_PATH: dds_payload(fill=1)} if replacements is None else replacements
    return from_texture_replacements(snapshot, identity or uuid4().hex, replacements,
                                     title=title, release=release)


def _changed_replacement(manifest, blobs, data, *, descriptor=False):
    manifest = deepcopy(manifest)
    row = manifest['modules'][0]['data']['replacements'][0]
    old, new = row['replacement'], digest(data)
    blobs = {key: value for key, value in blobs.items() if key != old}
    blobs[new] = data
    manifest['blobs'] = {key: len(value) for key, value in blobs.items()}
    row['replacement'] = new
    if descriptor:
        row['descriptor_sha256'] = digest(data[:148 if data[84:88] == b'DX10' else 128])
    return manifest, blobs


@pytest.mark.parametrize('fourcc', [b'DXT1', b'DXT5'])
@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_standalone_texture_roundtrip_resolves_without_allocating_item_ids(tmp_path, monkeypatch, fourcc, target):
    original, replacement = dds_payload(fourcc=fourcc), dds_payload(fourcc=fourcc, fill=1)
    root, snapshot = texture_game(tmp_path, source=original)
    package = texture_package(snapshot, {TEXTURE_PATH: replacement})
    decoded = read_package(package_bytes(package))
    assert decoded == package and not has_legacy_item(decoded)
    assert decoded.dependencies == {TEXTURE_PATH: digest(original)}
    assert decoded.blobs == {digest(replacement): replacement}
    assert decoded.manifest['modules'][0]['data']['registry_sha256'] == digest((root / 'meta/0.pathc').read_bytes())
    monkeypatch.setattr(install.IdentityBindings, 'allocate',
                        lambda *args: pytest.fail('Existing texture replacement must not allocate item IDs'))
    before = files_in(root)
    resolved = install.resolve_items([package_bytes(package)], root, target=target)
    assert files_in(root) == before
    assert resolved.registry['format'] == install.MOD_PROFILE_FORMAT
    reservation = resolved.registry['items'][package.identity]
    assert reservation['values'] == {} and reservation['paths'] == [] and reservation['stem'] == ''
    assert resolved.rows[0][2] is None
    assert len(resolved.contributions) == 1
    retained, changes = resolved.contributions[0]
    assert retained.identity == package.identity and set(changes) == {TEXTURE_PATH}
    assert changes[TEXTURE_PATH]['before'] == original and changes[TEXTURE_PATH]['after'] == replacement
    assert changes[TEXTURE_PATH]['flags'] == snapshot.entries[TEXTURE_PATH].flags
    assert not changes[TEXTURE_PATH]['meta']


def test_texture_capability_claims_adapter_and_synthetic_evidence_only():
    result = capability_result('texture.replace', 1)
    assert result.supported
    assert {claim.stage for claim in result.evidence} == {'adapter', 'synthetic'}
    assert not capability_result('texture.replace', 2).supported


@pytest.mark.parametrize('mutation', [
    'unknown-data-field', 'missing-registry', 'bad-registry', 'empty-replacements',
    'unknown-row-field', 'missing-row-field', 'uppercase', 'backslash', 'parent',
    'absolute', 'non-dds', 'unsupported-root', 'boolean-size', 'negative-size',
    'bad-source-hash', 'bad-descriptor-hash', 'missing-blob', 'missing-dependency',
    'mismatched-dependency', 'duplicate-path',
])
def test_malformed_texture_contract_refuses_before_game_access(tmp_path, monkeypatch, mutation):
    _, snapshot = texture_game(tmp_path / 'author')
    manifest, blobs = texture_manifest(snapshot)
    data = manifest['modules'][0]['data']
    row = data['replacements'][0]
    if mutation == 'unknown-data-field':
        data['fallback'] = 'raw'
    elif mutation == 'missing-registry':
        del data['registry_sha256']
    elif mutation == 'bad-registry':
        data['registry_sha256'] = True
    elif mutation == 'empty-replacements':
        data['replacements'] = []
    elif mutation == 'unknown-row-field':
        row['allow_layout_change'] = True
    elif mutation == 'missing-row-field':
        del row['source_size']
    elif mutation in ('uppercase', 'backslash', 'parent', 'absolute', 'non-dds', 'unsupported-root'):
        row['path'] = {
            'uppercase': TEXTURE_PATH.upper(), 'backslash': TEXTURE_PATH.replace('/', '\\'),
            'parent': 'character/texture/../bad.dds', 'absolute': '/' + TEXTURE_PATH,
            'non-dds': TEXTURE_PATH[:-4] + '.png', 'unsupported-root': 'mods/replacement.dds',
        }[mutation]
    elif mutation == 'boolean-size':
        row['source_size'] = True
    elif mutation == 'negative-size':
        row['source_size'] = -1
    elif mutation == 'bad-source-hash':
        row['source_sha256'] = 'G' * 64
    elif mutation == 'bad-descriptor-hash':
        row['descriptor_sha256'] = '0' * 63
    elif mutation == 'missing-blob':
        row['replacement'] = '0' * 64
    elif mutation == 'missing-dependency':
        manifest['dependencies'] = {SECOND_TEXTURE_PATH: row['source_sha256']}
    elif mutation == 'mismatched-dependency':
        manifest['dependencies'][TEXTURE_PATH] = '0' * 64
    elif mutation == 'duplicate-path':
        data['replacements'].append(deepcopy(row))
    monkeypatch.setattr(install, 'load_registry',
                        lambda *args: pytest.fail('Malformed texture behavior reached identity preparation'))
    before = files_in(tmp_path)
    with pytest.raises(IndependentItemError):
        install.resolve_items([packed(manifest, blobs)], tmp_path / 'recipient')
    assert files_in(tmp_path) == before


@pytest.mark.parametrize('mutation', [
    'truncated-header', 'truncated-last-mip', 'trailing-data', 'wrong-magic',
    'wrong-header-size', 'unknown-format', 'volume', 'cube', 'excessive-mips', 'oversized-dimensions',
])
def test_checksum_consistent_invalid_dds_refuses_without_raw_fallback(tmp_path, mutation):
    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    payload = bytearray(next(iter(blobs.values())))
    if mutation == 'truncated-header':
        payload = payload[:127]
    elif mutation == 'truncated-last-mip':
        payload = payload[:-1]
    elif mutation == 'trailing-data':
        payload += b'x'
    elif mutation == 'wrong-magic':
        payload[:4] = b'PNG '
    elif mutation == 'wrong-header-size':
        struct.pack_into('<I', payload, 4, 120)
    elif mutation == 'unknown-format':
        payload[84:88] = b'ZZZZ'
    elif mutation == 'volume':
        struct.pack_into('<I', payload, 24, 2)
    elif mutation == 'cube':
        struct.pack_into('<I', payload, 112, 0x200)
    elif mutation == 'excessive-mips':
        struct.pack_into('<I', payload, 28, 32)
    elif mutation == 'oversized-dimensions':
        struct.pack_into('<II', payload, 12, 65536, 65536)
    manifest, blobs = _changed_replacement(manifest, blobs, bytes(payload), descriptor=True)
    with pytest.raises(IndependentItemError):
        read_package(packed(manifest, blobs))


@pytest.mark.parametrize('mutation', ['array', 'dimension', 'cube', 'alpha', 'incomplete-extension'])
def test_dx10_surface_ambiguities_refuse(tmp_path, mutation):
    original = dds_payload(fourcc=b'DX10')
    _, snapshot = texture_game(tmp_path, source=original)
    manifest, blobs = texture_manifest(snapshot, {TEXTURE_PATH: dds_payload(fourcc=b'DX10', fill=1)})
    payload = bytearray(next(iter(blobs.values())))
    if mutation == 'array':
        struct.pack_into('<I', payload, 140, 2)
    elif mutation == 'dimension':
        struct.pack_into('<I', payload, 132, 4)
    elif mutation == 'cube':
        struct.pack_into('<I', payload, 136, 4)
    elif mutation == 'alpha':
        struct.pack_into('<I', payload, 144, 5)
    elif mutation == 'incomplete-extension':
        payload = payload[:147]
    manifest, blobs = _changed_replacement(manifest, blobs, bytes(payload), descriptor=True)
    with pytest.raises(IndependentItemError):
        read_package(packed(manifest, blobs))


def test_unused_and_checksum_corrupt_resources_are_not_admitted(tmp_path):
    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    extra = b'not a declared replacement'
    manifest['blobs'][digest(extra)] = len(extra)
    with pytest.raises(IndependentItemError, match='unreferenced|unused'):
        read_package(packed(manifest, dict(blobs, **{digest(extra): extra})))
    manifest, blobs = texture_manifest(snapshot)
    key = next(iter(blobs))
    blobs[key] = blobs[key][:-1] + b'\x02'
    with pytest.raises(IndependentItemError, match='checksum'):
        read_package(packed(manifest, blobs))


def test_replacement_count_budget_spans_all_texture_modules(tmp_path):
    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    original = manifest['modules'][0]
    row = original['data']['replacements'][0]
    manifest['modules'] = []
    manifest['dependencies'] = {}
    for index in range(2):
        module = deepcopy(original)
        module['id'] = f'textures_{index}'
        module['data']['replacements'] = []
        for number in range(65 if index == 0 else 64):
            replacement = dict(row, path=f'character/texture/1_pc/budget_{index}_{number}.dds')
            module['data']['replacements'].append(replacement)
            manifest['dependencies'][replacement['path']] = replacement['source_sha256']
        manifest['modules'].append(module)
    with pytest.raises(IndependentItemError, match='budget|128|limit|many'):
        read_package(packed(manifest, blobs))


def test_shared_blob_cannot_bypass_logical_replacement_byte_budget(tmp_path, monkeypatch):
    from cdmw.services import independent_item_package as codec

    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot, {
        TEXTURE_PATH: dds_payload(fill=1), SECOND_TEXTURE_PATH: dds_payload(fill=1)})
    assert len(blobs) == 1
    # The complete manifest and a single deduplicated blob fit; both outputs do not.
    blob_size = len(next(iter(blobs.values())))
    budget = len(canonical(manifest)) + 2 * blob_size - 1
    assert len(canonical(manifest)) + blob_size < budget
    monkeypatch.setattr(codec, 'MAX_TOTAL', budget)
    with pytest.raises(IndependentItemError, match='size|budget|limit'):
        read_v2(manifest, blobs)


def test_same_target_cannot_be_declared_by_two_modules_in_one_package(tmp_path):
    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    duplicate = deepcopy(manifest['modules'][0])
    duplicate['id'] = 'second_texture_module'
    manifest['modules'].append(duplicate)
    with pytest.raises(IndependentItemError, match='duplicate|same|already'):
        read_package(packed(manifest, blobs))


@pytest.mark.parametrize('mutation', ['dimensions', 'mips', 'format', 'reserved-header', 'dx10-srgb'])
def test_replacement_cannot_change_any_original_descriptor_field(tmp_path, mutation):
    source = dds_payload(fourcc=b'DX10') if mutation == 'dx10-srgb' else dds_payload()
    _, snapshot = texture_game(tmp_path, source=source)
    replacement = {
        'dimensions': dds_payload(width=16, height=4, fill=1),
        'mips': dds_payload(mips=1, fill=1),
        'format': dds_payload(fourcc=b'DXT5', fill=1),
        'reserved-header': dds_payload(fill=1),
        'dx10-srgb': dds_payload(fourcc=b'DX10', dxgi=72, fill=1),
    }[mutation]
    if mutation == 'reserved-header':
        payload = bytearray(replacement)
        payload[32] = 1
        replacement = bytes(payload)
    manifest, blobs = texture_manifest(snapshot, {TEXTURE_PATH: replacement})
    with pytest.raises(IndependentItemError, match='descriptor|header|layout|size'):
        read_package(packed(manifest, blobs))


def test_actual_decode_is_required_for_every_declared_mip(tmp_path, monkeypatch):
    from PIL import Image

    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    original_load = Image.Image.load
    decoded_sizes = []

    def fail_lower_mip(image, *args, **kwargs):
        decoded_sizes.append(image.size)
        if image.size == (2, 2):
            raise OSError('owned lower-mip decoder refusal')
        return original_load(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'load', fail_lower_mip)
    with pytest.raises(IndependentItemError, match='decode|DDS|texture'):
        read_package(packed(manifest, blobs))
    assert (8, 8) in decoded_sizes and (4, 4) in decoded_sizes and (2, 2) in decoded_sizes


def test_known_layout_with_unavailable_decoder_refuses(tmp_path):
    payload = dds_payload(fourcc=b'BC4S')
    _, snapshot = texture_game(tmp_path, source=payload)
    manifest, blobs = texture_manifest(snapshot, {TEXTURE_PATH: dds_payload(fourcc=b'BC4S', fill=1)})
    with pytest.raises(IndependentItemError, match='decode|format|DDS|texture'):
        read_package(packed(manifest, blobs))


@pytest.mark.parametrize('mutation', ['source', 'registry', 'missing-registry', 'missing-target'])
def test_import_requires_exact_source_and_texture_registry(tmp_path, mutation):
    from tests.test_new_item_service import build_package

    _, authored_snapshot = texture_game(tmp_path / 'author')
    package = texture_package(authored_snapshot)
    root, snapshot = texture_game(tmp_path / 'recipient',
        source=dds_payload(fill=2) if mutation == 'source' else None)
    if mutation == 'registry':
        table = register_dds(snapshot.pathc, 'character/texture/1_pc/extra_registry_entry_d.dds', dds_payload())
        (root / 'meta/0.pathc').write_bytes(encode_pathc(table))
    elif mutation == 'missing-registry':
        (root / 'meta/0.pathc').unlink()
    elif mutation == 'missing-target':
        files = {path: snapshot.payload(path) for path in snapshot.entries if path != TEXTURE_PATH}
        build_package(root, files)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='source|depend|registry|texture|missing|changed',):
        install.resolve_items([package_bytes(package)], root)
    assert files_in(root) == before


@pytest.mark.parametrize('mutation', ['unregistered', 'descriptor'])
def test_checksum_correct_registry_must_identify_the_original_texture(tmp_path, mutation):
    from cdmw.core.pathc_format import registry_header_for

    root, snapshot = texture_game(tmp_path, registered=mutation != 'unregistered')
    if mutation == 'descriptor':
        headers = list(snapshot.pathc.headers)
        headers[snapshot.pathc.find(TEXTURE_PATH).header_index] = registry_header_for(dds_payload(fourcc=b'DXT5'))
        (root / 'meta/0.pathc').write_bytes(encode_pathc(replace(snapshot.pathc, headers=tuple(headers))))
        snapshot = stock_snapshot(root)
    manifest, blobs = texture_manifest(snapshot)
    source = packed(manifest, blobs)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='registry|registered|descriptor|texture'):
        install.resolve_items([source], root)
    assert files_in(root) == before


def test_shared_texture_outputs_cannot_bypass_selected_batch_budget(tmp_path, monkeypatch):
    root, snapshot = texture_game(tmp_path)
    replacements = {TEXTURE_PATH: dds_payload(fill=1), SECOND_TEXTURE_PATH: dds_payload(fill=1)}
    packages = [texture_package(snapshot, replacements) for _ in range(2)]
    logical_size = sum(len(canonical(package_metadata(package))) + sum(len(data) for data in replacements.values())
                       for package in packages)
    monkeypatch.setattr(install, 'MAX_TOTAL', logical_size - 1)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='batch size|budget|limit'):
        install.resolve_items([package_bytes(package) for package in packages], root)
    assert files_in(root) == before


@pytest.mark.parametrize('changed', ['source', 'registry'])
def test_authoring_refuses_changed_observed_bytes_even_with_preserved_stat(tmp_path, changed):
    import os
    from pathlib import Path
    from cdmw.services.independent_texture_package import from_texture_replacements
    from cdmw.services.new_item_provenance import StaleNewItemSource

    root, snapshot = texture_game(tmp_path)
    snapshot.payload(TEXTURE_PATH)
    if changed == 'source':
        entry = snapshot.entries[TEXTURE_PATH]
        target = Path(entry.paz_file)
        offset = entry.offset + entry.orig_size - 1
    else:
        target = root / 'meta/0.pathc'
        # A header's engine tag may change without affecting DDS dimensions.
        offset = 28 + 124
    previous = target.stat()
    data = bytearray(target.read_bytes())
    data[offset] ^= 1
    target.write_bytes(bytes(data))
    os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    before = files_in(root)
    with pytest.raises((IndependentItemError, StaleNewItemSource), match='changed|registry|source|Source'):
        from_texture_replacements(snapshot, uuid4().hex, {TEXTURE_PATH: dds_payload(fill=1)})
    assert files_in(root) == before


@pytest.mark.parametrize('chain', [False, True])
def test_decoded_mip_budget_is_checked_before_decoder_allocation(tmp_path, monkeypatch, chain):
    from PIL import Image
    from cdmw.services import independent_texture_package as textures

    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    # Top mip needs 256 decoded bytes, followed by 64, 16 and 4 bytes.
    monkeypatch.setattr(textures, 'DDS_MAX_DECODED_BYTES', 280 if chain else 255)
    opened = []

    def bounded_open(*args, **kwargs):
        opened.append(True)
        pytest.fail('A texture over the decoded byte budget reached the decoder')

    monkeypatch.setattr(Image, 'open', bounded_open)
    with pytest.raises(IndependentItemError, match='resource limit'):
        read_package(packed(manifest, blobs))
    assert opened == []


@pytest.mark.parametrize('stage', ['before', 'after-top', 'after-last'])
def test_texture_decode_cancellation_cannot_return_an_admitted_package(tmp_path, monkeypatch, stage):
    import threading
    from PIL import Image
    from cdmw.domain.cancellation import RunCancelled

    _, snapshot = texture_game(tmp_path)
    manifest, blobs = texture_manifest(snapshot)
    source = packed(manifest, blobs)
    stop = threading.Event()
    opened = []
    open_image = Image.open

    def cancelling_open(*args, **kwargs):
        image = open_image(*args, **kwargs)
        opened.append(image.size)
        load_image = image.load

        def load_then_cancel(*load_args, **load_kwargs):
            result = load_image(*load_args, **load_kwargs)
            if image.size == ((8, 8) if stage == 'after-top' else (1, 1)):
                stop.set()
            return result

        image.load = load_then_cancel
        return image

    monkeypatch.setattr(Image, 'open', cancelling_open)
    if stage == 'before':
        stop.set()
    with pytest.raises(RunCancelled):
        read_package(source, stop_event=stop)
    assert opened == {
        'before': [], 'after-top': [(8, 8)], 'after-last': [(8, 8), (4, 4), (2, 2), (1, 1)],
    }[stage]


def test_unavailable_texture_decoder_cannot_prepare_a_physical_install(tmp_path, monkeypatch):
    from PIL import Image

    root, snapshot = texture_game(tmp_path)
    source = package_bytes(texture_package(snapshot))

    def unavailable(*args, **kwargs):
        raise OSError('owned texture decoder unavailable')

    monkeypatch.setattr(Image, 'open', unavailable)
    monkeypatch.setattr(install, 'load_registry',
                        lambda *args: pytest.fail('Decoder refusal reached identity preparation'))
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='owned texture decoder unavailable'):
        install.prepare_install([source], root)
    assert files_in(root) == before


def test_texture_update_publication_failure_restores_previous_owned_state(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_manager as overlays
    from tests.test_archive_overlay_manager import Backups, snapshot_of

    root, snapshot = texture_game(tmp_path)
    original = texture_package(snapshot)
    update = texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=2)},
                             identity=original.identity, release='2')
    backups = Backups(tmp_path)
    backups.apply(install.prepare_install([package_bytes(original)], root).preparation)
    previous = install.load_registry(root)
    before = files_in(root)
    prepared = install.prepare_install([package_bytes(update)], root).preparation
    write = overlays.atomic_write_bytes

    def fail_after_identity_write(path, data):
        write(path, data)
        if path.name == 'independent-items.json':
            raise OSError('owned texture identity publication failure')

    monkeypatch.setattr(overlays, 'atomic_write_bytes', fail_after_identity_write)
    with pytest.raises(OSError, match='owned texture identity publication failure'):
        backups.apply(prepared)
    assert files_in(root) == before
    assert install.load_registry(root) == previous
    assert snapshot_of(root).payload(TEXTURE_PATH) == dds_payload(fill=1)


def test_texture_virtual_update_failure_restores_active_ledgers_and_previous_generation(tmp_path, monkeypatch):
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services import virtual_loader_state as state
    from cdmw.services.virtual_loader_composition import prepare_profile
    from tests.test_virtual_loader import game_bytes

    root, snapshot = texture_game(tmp_path)
    original = texture_package(snapshot)
    update = texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=2)},
                             identity=original.identity, release='2')
    original_path, update_path = tmp_path / 'original.cditem', tmp_path / 'update.cditem'
    original_path.write_bytes(package_bytes(original))
    update_path.write_bytes(package_bytes(update))
    stock = game_bytes(root)
    state.publish_profile(prepare_profile(VirtualProfile((original_path,)), root))
    previous = state.load_profile(root)
    original_generation = state.generation_path(root, previous['generation'])
    generation_bytes = files_in(original_generation)
    ledgers = {path: (root / path).read_bytes() for path in (state.PROFILE_PATH, state.REGISTRY)}
    prepared = prepare_profile(VirtualProfile((update_path,)), root)
    write = state.atomic_write_bytes

    def fail_active_profile(path, data):
        if path == root / state.PROFILE_PATH:
            raise OSError('owned texture virtual profile failure')
        write(path, data)

    monkeypatch.setattr(state, 'atomic_write_bytes', fail_active_profile)
    with pytest.raises(OSError, match='owned texture virtual profile failure'):
        state.publish_profile(prepared)
    assert all((root / path).read_bytes() == data for path, data in ledgers.items())
    assert not (root / state.JOURNAL_PATH).exists()
    assert state.load_profile(root) == previous
    assert install.load_registry(root)['items'][original.identity]['digest'] == original.digest
    assert files_in(original_generation) == generation_bytes
    assert game_bytes(root) == stock


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('changed', ['source', 'registry'])
def test_texture_source_witness_survives_preparation_until_publication(tmp_path, virtual, changed):
    import os
    from pathlib import Path
    from cdmw.domain.virtual_loader import VirtualProfile
    from cdmw.services.virtual_loader_composition import prepare_profile
    from cdmw.services.virtual_loader_state import publish_profile
    from tests.test_archive_overlay_manager import Backups

    root, snapshot = texture_game(tmp_path)
    package = texture_package(snapshot)
    path = tmp_path / 'texture.cditem'
    path.write_bytes(package_bytes(package))
    prepared = (prepare_profile(VirtualProfile((path,)), root) if virtual
                else install.prepare_install([path], root).preparation)
    if changed == 'source':
        entry = snapshot.entries[TEXTURE_PATH]
        target = Path(entry.paz_file)
        offset = entry.offset + entry.orig_size - 1
    else:
        target = root / 'meta/0.pathc'
        offset = 28 + 124
    previous = target.stat()
    data = bytearray(target.read_bytes())
    data[offset] ^= 1
    target.write_bytes(bytes(data))
    os.utime(target, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource|registry|changed'):
        publish_profile(prepared) if virtual else Backups(tmp_path).apply(prepared)
    assert files_in(root) == before


@pytest.mark.parametrize('mutation', ['integer', 'iterable', 'oversized-bytearray', 'shared-output-budget'])
def test_authoring_resource_admission_precedes_conversion_and_game_reads(tmp_path, monkeypatch, mutation):
    from cdmw.services import independent_item_package as codec
    from cdmw.services import independent_texture_package as textures

    class RefusedIterable:
        def __iter__(self):
            pytest.fail('An unadmitted replacement iterable was converted to bytes')

    class RefusedBytearrayCopy(bytearray):
        def __bytes__(self):
            pytest.fail('An oversized replacement bytearray was copied before admission')

    _, snapshot = texture_game(tmp_path)
    replacement = dds_payload(fill=1)
    if mutation == 'integer':
        # Keep a regressed conversion harmless while still rejecting non-byte input.
        selected = {TEXTURE_PATH: 1}
    elif mutation == 'iterable':
        selected = {TEXTURE_PATH: RefusedIterable()}
    elif mutation == 'oversized-bytearray':
        monkeypatch.setattr(codec, 'MAX_BLOB', len(replacement) - 1)
        selected = {TEXTURE_PATH: RefusedBytearrayCopy(replacement)}
    else:
        monkeypatch.setattr(codec, 'MAX_TOTAL', 2 * len(replacement) - 1)
        selected = {TEXTURE_PATH: replacement, SECOND_TEXTURE_PATH: replacement}
        assert selected[TEXTURE_PATH] is selected[SECOND_TEXTURE_PATH]

    def refuse_game_access(*args, **kwargs):
        pytest.fail('An inadmissible replacement batch reached game source access')

    monkeypatch.setattr(textures, '_registry_witness', refuse_game_access)
    monkeypatch.setattr(textures, '_source_texture', refuse_game_access)
    monkeypatch.setattr(textures, 'validated_texture', refuse_game_access)
    with pytest.raises(IndependentItemError, match='bounded DDS bytes|logical.*size|size limit'):
        textures.from_texture_replacements(snapshot, uuid4().hex, selected)


@pytest.mark.parametrize('owner_state', ['active', 'disabled', 'removed'])
def test_registry_baseline_follows_the_legacy_texture_owners_lifecycle(tmp_path, owner_state):
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.pathc_format import parse_pathc
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.domain.new_item.spec import IconSource
    from cdmw.services import archive_overlay_manager as overlays
    from cdmw.services.independent_item_package import from_plan
    from cdmw.services.new_item_service import NewItemService
    from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
    from tests.test_new_item_service import _fake_dds

    root, snapshot = texture_game(tmp_path)
    registry_path = root / 'meta/0.pathc'
    original_registry = registry_path.read_bytes()
    service = NewItemService()
    choice = replace(shop_spec('RegistryOwner'), icon=IconSource.GENERATED)
    name = icon_string_for_stem(service.allocate(choice, snapshot).stem)
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
    legacy = from_plan(service.plan(choice, snapshot, icon=icon, capture_independent=True), uuid4().hex)
    backups = Backups(tmp_path)
    backups.apply(install.prepare_install([package_bytes(legacy)], root).preparation)
    retained_identity = deepcopy(install.load_registry(root)['items'][legacy.identity])
    assert registry_path.read_bytes() != original_registry
    if owner_state == 'disabled':
        backups.apply(overlays.prepare_overlay_enabled(root, retained_identity['layer'], False))
    elif owner_state == 'removed':
        backups.apply(install.prepare_remove(legacy.identity, root))
        assert registry_path.read_bytes() == original_registry
        # Simulate a new original registry only after CDMW has removed its owner.
        updated_registry = register_dds(parse_pathc(original_registry),
            'character/texture/1_pc/cdmw_current_stock_registry_d.dds', dds_payload())
        registry_path.write_bytes(encode_pathc(updated_registry))
    observed_registry = registry_path.read_bytes()
    expected_baseline = observed_registry if owner_state == 'removed' else original_registry
    fresh = stock_snapshot(root)
    assert encode_pathc(fresh.pathc) == expected_baseline
    assert fresh.pathc_source_digest == digest(observed_registry)
    replacement = dds_payload(fill=1)
    package = texture_package(fresh, {SECOND_TEXTURE_PATH: replacement})
    assert package.manifest['modules'][0]['data']['registry_sha256'] == digest(expected_baseline)
    before = files_in(root)
    prepared = install.prepare_install([package_bytes(package)], root).preparation
    assert files_in(root) == before
    backups.apply(prepared)
    assert snapshot_of(root).payload(SECOND_TEXTURE_PATH) == replacement
    assert registry_path.read_bytes() == observed_registry
    assert install.load_registry(root)['items'][legacy.identity] == retained_identity
    if owner_state != 'removed':
        layer = next(layer for layer in overlays._load_index(root)['layers']
                     if layer['id'] == retained_identity['layer'])
        assert layer['active'] is (owner_state == 'active')
        assert bool(layer.get('disabled')) is (owner_state == 'disabled')
