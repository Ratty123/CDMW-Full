"""Opaque semantic admission verifies required metadata, payloads and authored intent."""
from copy import deepcopy
import hashlib
import io
import json
import os
import warnings
import zipfile

import pytest

from cdmw.core.iteminfo_row import parse_iteminfo_row, set_max_stack_count
from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE, game_identity, read_semantic_export, write_semantic_export
from cdmw.domain.archives.iteminfo_composition import item_pair, replace_rows, rows_of
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from cdmw.services.independent_item_install import load_registry, prepare_install
from cdmw.services.independent_item_package import package_bytes, read_package
from cdmw.services.mod_merge_service import export_merged_mod
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_process import prepare_profile_in_subprocess
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import Backups
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game


@pytest.fixture(scope='module')
def original_export(tmp_path_factory):
    temporary = tmp_path_factory.mktemp('semantic-contract-source')
    _, snapshot, _ = setup_game(temporary)
    root = temporary / 'game'
    package = field_package(snapshot, value=1)
    Backups(temporary).apply(prepare_install([package_bytes(package)], root).preparation)
    exported = export_merged_mod(prepare_independent_mod_merge(root), temporary / 'exported')
    wrapper = exported.package_root / SEMANTIC_EXPORT_FILE
    assert read_semantic_export(exported.package_root) is not None
    return wrapper.read_bytes()


def decode(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = {item.filename: archive.read(item) for item in archive.infolist()}
    return members, json.loads(members['semantic.json'])


def write_modified(tmp_path, members, meta=None, *, duplicate=None, symlink=None):
    path = tmp_path / SEMANTIC_EXPORT_FILE
    members = dict(members)
    if meta is not None:
        members['semantic.json'] = json.dumps(meta, sort_keys=True, separators=(',', ':')).encode()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in members.items():
                if name == symlink:
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (0o120777 << 16)
                    archive.writestr(info, data)
                else:
                    archive.writestr(name, data)
            if duplicate is not None:
                archive.writestr(duplicate, members[duplicate])
    return path


@pytest.mark.parametrize('mutation', [
    'missing-manifest', 'unknown-format', 'unknown-version', 'boolean-version',
    'missing-required-capability', 'unknown-capability-version', 'boolean-capability-version',
    'missing-files', 'unknown-field', 'duplicate-json-key', 'duplicate-contributor',
    'changed-contributor-content', 'changed-contributor-size', 'changed-binding-content',
    'duplicate-output-path', 'case-output-path', 'traversal-output-path', 'backslash-output-path',
    'boolean-flags', 'payload-size', 'missing-payload', 'changed-payload',
    'changed-source-witness', 'duplicate-source-witness', 'unknown-compiler',
    'extra-member', 'undeclared-payload', 'case-member', 'duplicate-member', 'linked-member',
])
def test_required_semantic_contract_rejects_malformed_or_altered_disk_artifacts(tmp_path, original_export, mutation):
    members, meta = decode(original_export)
    duplicate, symlink = None, None
    payload_name = 'payloads/' + meta['files'][0]['sha256']
    if mutation == 'missing-manifest':
        del members['semantic.json']
        meta = None
    elif mutation == 'unknown-format':
        meta['format'] = 'unnegotiated'
    elif mutation == 'unknown-version':
        meta['version'] = 99
    elif mutation == 'boolean-version':
        meta['version'] = True
    elif mutation == 'missing-required-capability':
        meta['requires'] = {}
    elif mutation == 'unknown-capability-version':
        meta['requires']['export.semantic'] = 99
    elif mutation == 'boolean-capability-version':
        meta['requires']['export.semantic'] = True
    elif mutation == 'missing-files':
        del meta['files']
    elif mutation == 'unknown-field':
        meta['ignored_requirements'] = ['silently dropped']
    elif mutation == 'duplicate-json-key':
        members['semantic.json'] = b'{"version":1,' + members['semantic.json'][1:]
        meta = None
    elif mutation == 'duplicate-contributor':
        meta['packages'].append(deepcopy(meta['packages'][0]))
    elif mutation == 'changed-contributor-content':
        meta['packages'][0]['content'] = 'f' * 64
    elif mutation == 'changed-contributor-size':
        meta['packages'][0]['size'] += 1
    elif mutation == 'changed-binding-content':
        identity = meta['packages'][0]['identity']
        meta['bindings']['items'][identity]['digest'] = 'f' * 64
    elif mutation == 'duplicate-output-path':
        meta['files'].append(deepcopy(meta['files'][0]))
    elif mutation == 'case-output-path':
        meta['files'][0]['path'] = meta['files'][0]['path'].upper()
    elif mutation == 'traversal-output-path':
        meta['files'][0]['path'] = '../' + meta['files'][0]['path']
    elif mutation == 'backslash-output-path':
        meta['files'][0]['path'] = meta['files'][0]['path'].replace('/', chr(92))
    elif mutation == 'boolean-flags':
        meta['files'][0]['flags'] = True
    elif mutation == 'payload-size':
        meta['files'][0]['size'] += 1
    elif mutation == 'missing-payload':
        del members[payload_name]
    elif mutation == 'changed-payload':
        data = members[payload_name]
        members[payload_name] = data[:-1] + bytes([data[-1] ^ 1])
    elif mutation == 'changed-source-witness':
        required_path = meta['files'][0]['path']
        next(row for row in meta['witnesses']['payloads'] if row['path'] == required_path)['sha256'] = 'f' * 64
    elif mutation == 'duplicate-source-witness':
        meta['witnesses']['payloads'].append(deepcopy(meta['witnesses']['payloads'][0]))
    elif mutation == 'unknown-compiler':
        meta['compiler'] = {'unsupported': 99}
    elif mutation == 'extra-member':
        members['gamedata/unbound.bin'] = b'unbound game bytes'
    elif mutation == 'undeclared-payload':
        data = b'declared-by-nobody'
        members['payloads/' + hashlib.sha256(data).hexdigest()] = data
    elif mutation == 'case-member':
        members['Payloads/' + meta['files'][0]['sha256']] = members[payload_name]
    elif mutation == 'duplicate-member':
        duplicate = payload_name
    else:
        symlink = payload_name
    path = write_modified(tmp_path, members, meta, duplicate=duplicate, symlink=symlink)
    with pytest.raises((ValueError, IndependentItemError)):
        read_semantic_export(path)


def test_semantic_wrapper_cannot_downgrade_to_legacy_package_reader(tmp_path, original_export):
    wrapper = tmp_path / SEMANTIC_EXPORT_FILE
    wrapper.write_bytes(original_export)
    with pytest.raises((IndependentItemError, ValueError)):
        read_package(wrapper)
    members, _meta = decode(original_export)
    del members['semantic.json']
    path = write_modified(tmp_path, members)
    with pytest.raises(ValueError, match='required semantic'):
        read_semantic_export(path)
    renamed = tmp_path / 'renamed.cditem'
    renamed.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match='required semantic'):
        read_semantic_export(renamed)


def test_extra_game_files_cannot_share_the_semantic_folder_boundary(tmp_path, original_export):
    folder = tmp_path / 'selected'
    folder.mkdir()
    (folder / SEMANTIC_EXPORT_FILE).write_bytes(original_export)
    (folder / '0009').mkdir()
    (folder / '0009/0.pamt').write_bytes(b'unreviewed installable-looking archive')
    with pytest.raises(ValueError, match='single opaque'):
        read_semantic_export(folder)


@pytest.mark.parametrize('virtual', [False, True])
def test_checksum_consistent_compiled_payload_cannot_override_retained_requirement(tmp_path, original_export, virtual):
    members, meta = decode(original_export)
    output = {row['path']: members['payloads/' + row['sha256']] for row in meta['files']}
    body, header = item_pair(output)
    original = parse_iteminfo_row(rows_of(output[body], output[header])[1001295])
    assert original.max_stack_count == 1
    altered = replace_rows(output[body], output[header], {1001295: set_max_stack_count(original, 9)})
    checksum = hashlib.sha256(altered).hexdigest()
    members['payloads/' + checksum] = altered
    record = next(row for row in meta['files'] if row['path'] == body)
    record.update(size=len(altered), sha256=checksum)
    wrapper = write_modified(tmp_path, members, meta)
    decoded = read_semantic_export(wrapper)
    assert decoded is not None  # Integrity is valid; retained intent still has to match.
    retained = read_package(decoded.packages[0])
    assert retained.manifest['modules'][0]['data']['operations'][0]['value'] == 1

    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = files_in(root)
    with pytest.raises((IndependentItemError, ValueError), match='recompil|output|intent|payload|contribution'):
        if virtual:
            prepare_profile(VirtualProfile((wrapper,)), root)
        else:
            prepare_install([wrapper], root)
    assert files_in(root) == before


@pytest.mark.parametrize('writer', [False, True])
@pytest.mark.parametrize('kind', ['outputs', 'baselines'])
def test_shared_payload_bytes_cannot_bypass_logical_export_budgets(tmp_path, original_export, monkeypatch, writer, kind):
    members, meta = decode(original_export)
    selected = max(meta['files'], key=lambda row: row['size'])
    assert selected['size'] > 0 and selected['baseline'] is not None
    # Both the encoded artifact and its unique expanded members fit this tiny
    # budget. Only repeated logical ownership of the same bytes exceeds it.
    budget = max(4096, 2 * len(original_export), 2 * sum(map(len, members.values())))
    repeat = budget // selected['size'] + 2
    for index in range(repeat):
        duplicate = deepcopy(selected)
        duplicate['path'] = f'character/logical-budget-{index}.dat'
        if kind == 'outputs':
            duplicate['baseline'] = None
        else:
            meta['witnesses']['payloads'].append({
                'path': duplicate['path'], **duplicate['baseline']})
        meta['files'].append(duplicate)
    wrapper = write_modified(tmp_path, members, meta)
    export = read_semantic_export(wrapper)
    assert export is not None
    assert sum(len(data) for _, data, _ in export.files) > budget
    if kind == 'outputs':
        monkeypatch.setattr('cdmw.services.independent_item_package.MAX_TOTAL', budget)
    else:
        assert sum(len(data) for data in export.originals.values() if data is not None) > budget
        monkeypatch.setattr('cdmw.core.mod_compatibility.MAX_BASELINE_BYTES', budget)
    with pytest.raises(ValueError, match='logical|size|limit|budget'):
        write_semantic_export(tmp_path / 'copy', export) if writer else read_semantic_export(wrapper)
    assert not (tmp_path / 'copy' / SEMANTIC_EXPORT_FILE).exists()


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('kind', ['paver_sha256', 'executable_sha256', 'build'])
def test_known_game_identity_changes_refuse_semantic_import(tmp_path, original_export, virtual, kind):
    members, meta = decode(original_export)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    source = root / ('CrimsonDesert.exe' if kind == 'executable_sha256' else 'meta/0.paver')
    source.write_bytes(b'known-build-1')
    identity = game_identity(root)
    assert identity[kind]
    meta['target_game'] = {key: value if key in ('game', kind) else '' for key, value in identity.items()}
    wrapper = write_modified(tmp_path, members, meta)
    # The known identity is accepted before it changes.
    if virtual:
        prepare_profile(VirtualProfile((wrapper,)), root)
    else:
        prepare_install([wrapper], root)
    stamp = source.stat()
    source.write_bytes(b'known-build-2')
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    before = files_in(root)
    with pytest.raises(ValueError, match='game identity changed|game build changed'):
        if virtual:
            prepare_profile(VirtualProfile((wrapper,)), root)
        else:
            prepare_install([wrapper], root)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
def test_reviewed_game_identity_remains_pinned_until_publication(tmp_path, original_export, virtual):
    members, meta = decode(original_export)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    source = root / 'CrimsonDesert.exe'
    source.write_bytes(b'known-build-1')
    meta['target_game'] = game_identity(root)
    assert meta['target_game']['executable_sha256']
    wrapper = write_modified(tmp_path, members, meta)
    prepared = (prepare_profile(VirtualProfile((wrapper,)), root) if virtual
                else prepare_install([wrapper], root).preparation)
    assert prepared is not None
    stamp = source.stat()
    source.write_bytes(b'known-build-2')
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource|identity|changed'):
        publish_profile(prepared) if virtual else Backups(tmp_path).apply(prepared)
    assert files_in(root) == before


@pytest.mark.parametrize('virtual', [False, True])
def test_higher_priority_game_executable_cannot_appear_after_review(tmp_path, original_export, virtual):
    members, meta = decode(original_export)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    (root / 'CrimsonDesert.exe').write_bytes(b'known-build-1')
    meta['target_game'] = game_identity(root)
    wrapper = write_modified(tmp_path, members, meta)
    prepared = (prepare_profile(VirtualProfile((wrapper,)), root) if virtual
                else prepare_install([wrapper], root).preparation)
    assert prepared is not None
    (root / 'bin64').mkdir()
    (root / 'bin64/CrimsonDesert.exe').write_bytes(b'known-build-2')
    assert game_identity(root)['executable_sha256'] != meta['target_game']['executable_sha256']
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource|identity|changed'):
        publish_profile(prepared) if virtual else Backups(tmp_path).apply(prepared)
    assert files_in(root) == before


def test_known_game_identity_is_pinned_between_export_plan_and_writer(tmp_path):
    _, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = field_package(snapshot, value=1)
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    executable = root / 'CrimsonDesert.exe'
    executable.write_bytes(b'known-build-1')
    plan = prepare_independent_mod_merge(root)
    assert plan.semantic_export.target_game['executable_sha256'] == hashlib.sha256(b'known-build-1').hexdigest()
    stamp = executable.stat()
    executable.write_bytes(b'known-build-2')
    os.utime(executable, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource|identity|changed'):
        export_merged_mod(plan, tmp_path / 'not-published')
    assert files_in(root) == before
    assert not (tmp_path / 'not-published').exists()


def nested_identity_selection(tmp_path, original_export):
    members, meta = decode(original_export)
    setup_game(tmp_path / 'installation')
    root = tmp_path / 'installation/game'
    # The fixture game folder is the selected archive root. The established
    # resolver also admits an executable in its parent installation directory.
    executable = root.parent / 'CrimsonDesert.exe'
    executable.write_bytes(b'known-build-1')
    meta['target_game'] = game_identity(root)
    assert meta['target_game']['executable_sha256'] == hashlib.sha256(b'known-build-1').hexdigest()
    return root, executable, write_modified(tmp_path, members, meta)


@pytest.mark.parametrize('virtual', [False, True])
def test_nested_archive_root_accepts_witnessed_ancestor_executable(tmp_path, original_export, virtual):
    root, executable, wrapper = nested_identity_selection(tmp_path, original_export)
    prepared = (prepare_profile_in_subprocess(VirtualProfile((wrapper,)), root) if virtual
                else prepare_install([wrapper], root).preparation)
    assert prepared is not None
    publish_profile(prepared) if virtual else Backups(tmp_path).apply(prepared)
    package = read_package(read_semantic_export(wrapper).packages[0])
    assert load_registry(root)['items'][package.identity]['digest'] == package.digest
    assert executable.read_bytes() == b'known-build-1'


@pytest.mark.parametrize('virtual', [False, True])
def test_nested_archive_root_pins_earlier_ancestor_executable_candidates(tmp_path, original_export, virtual):
    root, executable, wrapper = nested_identity_selection(tmp_path, original_export)
    prepared = (prepare_profile_in_subprocess(VirtualProfile((wrapper,)), root) if virtual
                else prepare_install([wrapper], root).preparation)
    assert prepared is not None
    earlier = root.parent / 'bin64/CrimsonDesert.exe'
    earlier.parent.mkdir()
    earlier.write_bytes(b'known-build-2')
    assert game_identity(root)['executable_sha256'] == hashlib.sha256(b'known-build-2').hexdigest()
    assert executable.read_bytes() == b'known-build-1'
    before = files_in(root)
    with pytest.raises(ValueError, match='[Ss]ource|identity|changed'):
        publish_profile(prepared) if virtual else Backups(tmp_path).apply(prepared)
    assert files_in(root) == before


def test_earlier_executable_created_while_pinning_cannot_validate_old_selection(tmp_path, original_export, monkeypatch):
    from cdmw.services.new_item_provenance import SourceTracker

    root, executable, wrapper = nested_identity_selection(tmp_path, original_export)
    earlier = root.parent / 'bin64/CrimsonDesert.exe'
    original_pin = SourceTracker.pin_file
    created = False

    def create_before_pin(tracker, path):
        nonlocal created
        if path.resolve() == earlier.resolve() and not created:
            created = True
            earlier.parent.mkdir()
            earlier.write_bytes(b'known-build-2')
        return original_pin(tracker, path)

    monkeypatch.setattr(SourceTracker, 'pin_file', create_before_pin)
    before = files_in(root)
    with pytest.raises(ValueError, match='game identity changed'):
        prepare_install([wrapper], root)
    assert created
    assert executable.read_bytes() == b'known-build-1'
    assert game_identity(root)['executable_sha256'] == hashlib.sha256(b'known-build-2').hexdigest()
    assert files_in(root) == before
