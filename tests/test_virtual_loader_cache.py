from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import threading
from uuid import uuid4

import pytest

from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.papgt_format import papgt_with_directory, serialize_papgt
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.compilation import compilation_record, compiler_stamp
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile
from cdmw.services.archive_overlay_install import _processed_payload
from cdmw.services.independent_item_package import canonical, digest, package_bytes, read_package
from cdmw.services import virtual_loader_cache as cache_owner
from cdmw.services import virtual_loader_composition as composition
from cdmw.services.virtual_loader_state import (
    FORMAT, PROFILE_PATH, generation_path, load_profile, publish_profile, validate_profile,
)
from tests.test_virtual_loader import game_bytes, packages


def _save_private(root, profile, output):
    """Write only this test's owned private generation and matching profile."""
    raw = canonical(profile)
    directory = generation_path(root, profile['generation'])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'profile.json').write_bytes(raw)
    (root / PROFILE_PATH).write_bytes(raw)
    for name, data in output.items():
        target = directory / 'files' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return raw


def _private_fixture(tmp_path, *, flags=0, extra_record=False, plain_asset=False):
    root = tmp_path / 'game'
    (root / 'meta').mkdir(parents=True)
    mount, pathc = serialize_papgt(()), b'unchanged texture registry fixture'
    (root / 'meta/0.papgt').write_bytes(mount)
    files = {'character/cache.txt': b'<resource>Current raw content</resource>' * 8}
    if extra_record:
        files['gamedata/changeable.txt'] = b'<record>Original value</record>'
    file_flags = {path: flags for path in files}
    if plain_asset:
        files['character/plain.dds'] = b'DDS plain immutable texture fixture' * 4096
        file_flags['character/plain.dds'] = 0
    entries = [OverlayFile(path, _processed_payload(raw, compression_type=file_flags[path] & 15,
                           encrypted=bool(file_flags[path] >> 4), basename=Path(path).name), len(raw), file_flags[path])
               for path, raw in files.items()]
    archive = build_overlay_archive(entries)
    output = {'9000/0.pamt': archive.pamt_bytes, '9000/0.paz': archive.paz_bytes,
              'meta/0.papgt': papgt_with_directory(mount, '9000', archive.pamt_checksum),
              'meta/0.pathc': pathc}
    source = str(root / 'meta/0.papgt')
    compiled = compilation_record(scope='virtual-profile', packages=[], sources={source: digest(mount)},
        allocations={}, order=[], runtime_abi='CDVFS3', outputs={p: digest(raw) for p, raw in output.items()},
        providers={'meta/0.papgt': digest(mount)})
    profile = {'format': FORMAT, 'generation': uuid4().hex, 'compiler': compiler_stamp(), 'items': {},
               'packages': [], 'mods': [], 'sources': [[source, digest(mount)]], 'catalogue': [],
               'inventories': [], 'observed': [['meta/0.papgt', digest(mount)]],
               'files': {p: digest(raw) for p, raw in output.items()}, 'compilation': compiled}
    profile['build_cache'] = cache_owner.make_cache_record(compiled, directory='9000', files=files,
        flags=file_flags, mount=mount, pathc=pathc)
    validate_profile(profile)
    raw = _save_private(root, profile, output)
    return root, profile, raw, output, files, file_flags, mount, pathc


@pytest.mark.parametrize('flags', [0, 1, 2, 0x30, 0x31, 0x32])
def test_reused_spans_match_the_real_processor_and_complete_private_output(tmp_path, flags):
    root, profile, raw_profile, output, files, file_flags, mount, pathc = _private_fixture(tmp_path, flags=flags)
    cached = cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache'])
    assert cached is not None
    record = profile['build_cache']
    assert cached.whole_output(record, mount=mount, pathc=pathc) == output
    for path, raw in files.items():
        assert cached.resource_payload(path, record['resources'][path]) == _processed_payload(
            raw, compression_type=file_flags[path] & 15, encrypted=bool(file_flags[path] >> 4), basename=Path(path).name)
    # Returned output is the immutable captured content, even if the previous
    # generation is subsequently damaged. It is never read a second time.
    (generation_path(root, profile['generation']) / 'files/9000/0.paz').write_bytes(b'changed')
    assert cached.whole_output(record, mount=mount, pathc=pathc) == output


@pytest.mark.parametrize('change', ['sources', 'allocations', 'order', 'providers', 'runtime_abi', 'packages', 'compiler', 'adapter'])
def test_whole_output_key_requires_all_compilation_inputs(tmp_path, change):
    root, profile, raw_profile, _output, files, flags, mount, pathc = _private_fixture(tmp_path)
    cached = cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache'])
    compiled = deepcopy(profile['compilation'])
    inputs = compiled['inputs']
    if change == 'sources':
        inputs['sources'][next(iter(inputs['sources']))] = 'a' * 64
    elif change == 'allocations':
        inputs['allocations'][uuid4().hex] = 'b' * 64
    elif change == 'order':
        inputs['policy']['order'] = ['changed-provider-order']
    elif change == 'providers':
        inputs['providers']['meta/0.pathc'] = 'c' * 64
    elif change == 'runtime_abi':
        inputs['runtime_abi'] = 'CDVFS2'
    elif change == 'packages':
        inputs['packages'] = [{'identity': uuid4().hex, 'content': 'd' * 64, 'artifact': 'e' * 64,
                              'retained_artifact': 'f' * 64, 'version': 1,
                              'features': {'item-v1': 1}, 'modules': [{'id': 'item', 'type': 'item-v1', 'version': 1}]}]
    elif change == 'compiler':
        inputs['compiler']['revision'] += 1
    else:
        inputs['compiler']['adapters']['item-v1'] += 1
    compiled['identity'] = digest(canonical(inputs))
    current = cache_owner.make_cache_record(compiled, directory='9000', files=files, flags=flags, mount=mount, pathc=pathc)
    assert cached.whole_output(current, mount=mount, pathc=pathc) is None


@pytest.mark.parametrize('change', ['directory', 'mount', 'pathc', 'catalogue', 'inventories', 'flags', 'resource'])
def test_whole_output_key_requires_metadata_processing_and_source_witnesses(tmp_path, change):
    root, profile, raw_profile, _output, files, flags, mount, pathc = _private_fixture(tmp_path)
    cached = cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache'])
    options = dict(directory='9000', files=files, flags=flags, mount=mount, pathc=pathc, catalogue=(), inventories=())
    if change == 'directory':
        options['directory'] = '9001'
    elif change == 'mount':
        options['mount'] = serialize_papgt((), header=b'ABCD' + bytes(8))
    elif change == 'pathc':
        options['pathc'] = b'new texture registry'
    elif change == 'catalogue':
        options['catalogue'] = [(str(root / '0009/1.paz'), (1, 2, 3))]
    elif change == 'inventories':
        options['inventories'] = [(str(tmp_path / 'mod'), [('files/example', 1, 2)])]
    elif change == 'flags':
        options['flags'] = {path: 2 for path in files}
    else:
        options['files'] = {path: raw + b'changed' for path, raw in files.items()}
    current = cache_owner.make_cache_record(profile['compilation'], **options)
    assert cached.whole_output(current, mount=options['mount'], pathc=options['pathc']) is None
    if change in ('flags', 'resource'):
        path = next(iter(files))
        assert cached.resource_payload(path, current['resources'][path]) is None


@pytest.mark.parametrize('corrupt', ['payload', 'index', 'manifest', 'missing'])
def test_corrupt_or_missing_private_output_is_a_cache_miss(tmp_path, corrupt):
    root, profile, raw_profile, _output, *_ = _private_fixture(tmp_path)
    generation = generation_path(root, profile['generation'])
    path = generation / ('profile.json' if corrupt == 'manifest' else 'files/9000/0.pamt' if corrupt == 'index' else 'files/9000/0.paz')
    if corrupt == 'missing':
        path.unlink()
    else:
        original = path.read_bytes()
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache']) is None


def test_self_consistent_descriptor_cannot_substitute_another_resource(tmp_path):
    root, profile, _raw_profile, output, files, flags, mount, pathc = _private_fixture(tmp_path, flags=0x32)
    path = next(iter(files))
    changed = {path: files[path].replace(b'Current', b'Changed')}
    forged = cache_owner.make_cache_record(profile['compilation'], directory='9000', files=changed,
        flags=flags, mount=mount, pathc=pathc)
    profile['build_cache'] = forged
    raw_profile = _save_private(root, profile, output)
    # Descriptor hashes, file hashes and compilation are individually valid.
    # Only decoding the retained processed span proves their claimed binding.
    validate_profile(profile)
    cached = cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache'])
    assert cached is not None
    assert cached.whole_output(forged, mount=mount, pathc=pathc) is None
    assert cached.resource_payload(path, forged['resources'][path]) is None


@pytest.mark.parametrize('field', ['key', 'inputs', 'guards', 'extra', 'path', 'size', 'flags', 'pathc'])
def test_cache_descriptor_is_strict_and_bound_to_its_profile(tmp_path, field):
    _root, profile, *_ = _private_fixture(tmp_path)
    record = profile['build_cache']
    resource = next(iter(record['resources'].values()))
    if field in ('key', 'inputs', 'guards'):
        record[field] = '0' * 64
    elif field == 'extra':
        record['unrecognized'] = True
    elif field == 'path':
        record['resources']['../escape'] = record['resources'].pop(next(iter(record['resources'])))
    elif field == 'size':
        resource['size'] = True
    elif field == 'flags':
        resource['flags'] = True
    else:
        record['metadata']['pathc'] = '0' * 64
    if field != 'key':
        record['key'] = digest(canonical({k: v for k, v in record.items() if k != 'key'}))
    with pytest.raises(VirtualLoaderError, match='cache'):
        validate_profile(profile)


def test_old_compiler_processing_and_large_generation_disable_resource_reuse(tmp_path, monkeypatch):
    root, profile, raw_profile, output, *_ = _private_fixture(tmp_path)
    with monkeypatch.context() as patch:
        stamp = compiler_stamp()
        stamp['revision'] += 1
        patch.setattr(cache_owner, 'compiler_stamp', lambda: stamp)
        assert cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache']) is None
    with monkeypatch.context() as patch:
        stamp = cache_owner.processing_stamp()
        stamp['payload'] += 1
        patch.setattr(cache_owner, 'processing_stamp', lambda: stamp)
        assert cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache']) is None
    monkeypatch.setattr(cache_owner, 'MAX_CACHE_BYTES', sum(map(len, output.values())) - 1)
    assert cache_owner.load_previous_cache(root, raw_profile, current_record=profile['build_cache']) is None
    old = deepcopy(profile)
    del old['build_cache']
    assert cache_owner.load_previous_cache(root, _save_private(root, old, output), current_record=profile['build_cache']) is None


def test_tiny_transformed_match_does_not_capture_large_plain_generation(tmp_path, monkeypatch):
    root, profile, raw_profile, _output, files, flags, mount, pathc = _private_fixture(
        tmp_path, flags=0x32, extra_record=True, plain_asset=True)
    files['gamedata/changeable.txt'] = b'<record>Changed value</record>'
    current = cache_owner.make_cache_record(profile['compilation'], directory='9000', files=files,
        flags=flags, mount=mount, pathc=pathc)
    def captured(*args, **kwargs):
        pytest.fail('A tiny reusable transform must not capture a large plain payload archive.')
    monkeypatch.setattr(cache_owner, '_captured_file', captured)
    assert cache_owner.load_previous_cache(root, raw_profile, current_record=current) is None


def test_unchanged_apply_reuses_outputs_after_fresh_source_hashing(tmp_path, monkeypatch):
    root, selected = packages(tmp_path, 1)
    profile = VirtualProfile(selected)
    before = game_bytes(root)
    first = composition.prepare_profile(profile, root)
    publish_profile(first)
    prior_profile = (root / PROFILE_PATH).read_bytes()
    calls = []
    hash_sources = composition._hash_sources
    def fresh_hash(paths, *args, **kwargs):
        calls.append(tuple(paths))
        return hash_sources(paths, *args, **kwargs)
    def rebuilt(*args, **kwargs):
        pytest.fail('An unchanged verified output must not be processed or repacked.')
    monkeypatch.setattr(composition, '_hash_sources', fresh_hash)
    monkeypatch.setattr(composition, '_processed_payload', rebuilt)
    monkeypatch.setattr(composition, 'build_overlay_archive', rebuilt)
    second = composition.prepare_profile(profile, root)
    assert calls and calls[0]
    assert dict(second.files) == dict(first.files) and second.generation != first.generation
    assert json.loads(second.profile)['compilation'] == json.loads(first.profile)['compilation']
    assert any('Reused verified private archives' in line for line in second.summary)
    assert (root / PROFILE_PATH).read_bytes() == prior_profile
    assert game_bytes(root) == before
    publish_profile(second)
    assert load_profile(root)['generation'] == second.generation and game_bytes(root) == before


def test_changed_records_skip_raw_only_cache_and_match_uncached_output(tmp_path, monkeypatch):
    root, selected = packages(tmp_path, 1)
    mod = tmp_path / 'mod'
    asset = mod / 'files/character/cache_shared.txt'
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b'unchanged large model or texture resource' * 128)
    profile = VirtualProfile(selected, (mod,))
    before = game_bytes(root)
    first = composition.prepare_profile(profile, root)
    publish_profile(first)
    item = read_package(selected[0])
    recipe = deepcopy(item.recipe)
    recipe['spec']['fields']['display_names']['map']['eng'] = 'Updated display name'
    selected[0].write_bytes(package_bytes(replace(item, recipe=recipe)))
    processed, packed = [], []
    process, pack = composition._processed_payload, composition.build_overlay_archive
    def processing(raw, **kwargs):
        processed.append(kwargs['basename'])
        return process(raw, **kwargs)
    def packing(entries, **kwargs):
        packed.append(len(entries))
        return pack(entries, **kwargs)
    monkeypatch.setattr(composition, '_processed_payload', processing)
    monkeypatch.setattr(composition, 'build_overlay_archive', packing)
    def captured(*args, **kwargs):
        pytest.fail('Raw-only partial reuse must not read previous generation output.')
    monkeypatch.setattr(cache_owner, '_captured_file', captured)
    second = composition.prepare_profile(profile, root)
    assert packed and processed and 'cache_shared.txt' in processed
    assert not any('Reused verified processed data' in line for line in second.summary)
    monkeypatch.setattr(cache_owner, 'load_previous_cache', lambda *args, **kwargs: None)
    uncached = composition.prepare_profile(profile, root)
    assert 'cache_shared.txt' in processed
    assert dict(second.files) == dict(uncached.files)
    assert game_bytes(root) == before


@pytest.mark.parametrize('flags', [0, 1])
def test_raw_only_partial_miss_reads_no_previous_generation_files(tmp_path, monkeypatch, flags):
    root, profile, raw_profile, _output, files, file_flags, mount, pathc = _private_fixture(tmp_path, flags=flags)
    current = cache_owner.make_cache_record(profile['compilation'], directory='9000', files=files,
        flags=file_flags, mount=mount, pathc=pathc + b'changed')
    def captured(*args, **kwargs):
        pytest.fail('An identity transform cannot justify any previous-generation capture.')
    monkeypatch.setattr(cache_owner, '_captured_file', captured)
    assert cache_owner.load_previous_cache(root, raw_profile, current_record=current) is None


@pytest.mark.parametrize('flags', [2, 0x30, 0x31, 0x32])
def test_changed_records_reuse_matching_transformed_resources(tmp_path, flags):
    root, profile, raw_profile, _output, files, file_flags, mount, pathc = _private_fixture(tmp_path, flags=flags, extra_record=True)
    changed = dict(files)
    changed['gamedata/changeable.txt'] = b'<record>Modified value</record>'
    current = cache_owner.make_cache_record(profile['compilation'], directory='9000', files=changed,
        flags=file_flags, mount=mount, pathc=pathc)
    cached = cache_owner.load_previous_cache(root, raw_profile, current_record=current)
    assert cached is not None and cached.whole_output(current, mount=mount, pathc=pathc) is None
    assert cached.resource_payload('gamedata/changeable.txt', current['resources']['gamedata/changeable.txt']) is None
    retained = cached.resource_payload('character/cache.txt', current['resources']['character/cache.txt'])
    assert retained is not None
    fresh_entries, reused_entries = [], []
    for path, raw in sorted(changed.items()):
        processed = _processed_payload(raw, compression_type=flags & 15, encrypted=bool(flags >> 4), basename=Path(path).name)
        fresh_entries.append(OverlayFile(path, processed, len(raw), flags))
        reused_entries.append(OverlayFile(path, retained if path == 'character/cache.txt' else processed, len(raw), flags))
    assert build_overlay_archive(reused_entries) == build_overlay_archive(fresh_entries)


def test_corrupt_private_generation_rebuilds_complete_unchanged_output(tmp_path, monkeypatch):
    root, selected = packages(tmp_path, 1)
    first = composition.prepare_profile(VirtualProfile(selected), root)
    publish_profile(first)
    generation = generation_path(root, first.generation)
    paz = next((generation / 'files').glob('*/0.paz'))
    raw = paz.read_bytes()
    paz.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    called = []
    pack = composition.build_overlay_archive
    def packing(*args, **kwargs):
        called.append(True)
        return pack(*args, **kwargs)
    monkeypatch.setattr(composition, 'build_overlay_archive', packing)
    rebuilt = composition.prepare_profile(VirtualProfile(selected), root)
    assert called and dict(rebuilt.files) == dict(first.files)


def test_cancellation_during_verified_resource_reuse_preserves_active_generation(tmp_path, monkeypatch):
    root, selected = packages(tmp_path, 1)
    first = composition.prepare_profile(VirtualProfile(selected), root)
    publish_profile(first)
    before = {path: path.read_bytes() for path in (root / PROFILE_PATH, root / '.cdmw/independent-items.json')}
    stop = threading.Event()
    verify = cache_owner.VerifiedBuildCache._verify_resource
    def cancelling(self, *args, **kwargs):
        result = verify(self, *args, **kwargs)
        stop.set()
        return result
    monkeypatch.setattr(cache_owner.VerifiedBuildCache, '_verify_resource', cancelling)
    with pytest.raises(RunCancelled):
        composition.prepare_profile(VirtualProfile(selected), root, stop_event=stop)
    assert stop.is_set() and all(path.read_bytes() == raw for path, raw in before.items())
    assert load_profile(root)['generation'] == first.generation
