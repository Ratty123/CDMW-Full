"""Owned-file authoring and transactional publication for texture .cditem packages."""
from copy import deepcopy
import os
from pathlib import Path
import threading
import zipfile

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import independent_item_package as codec
from cdmw.services import independent_texture_authoring as authoring
from cdmw.services.independent_item_install import resolve_items
from cdmw.services.independent_item_package import read_package, write_package
from cdmw.services.independent_mod_package import read_v2
from tests.test_independent_item_regressions import files_in
from tests.test_independent_texture_packages import (
    SECOND_TEXTURE_PATH, TEXTURE_PATH, dds_payload, texture_game, texture_package,
)


def prepare_owned(tmp_path):
    root, _snapshot = texture_game(tmp_path)
    replacement = tmp_path / 'replacement.dds'
    replacement.write_bytes(dds_payload(fill=1))
    catalogue = authoring.find_existing_texture_targets(root, 'cdmw_existing_d.dds')
    review = authoring.prepare_texture_package(catalogue, TEXTURE_PATH, replacement)
    return root, catalogue, replacement, review


def prepare_update(tmp_path):
    root, catalogue, replacement, review = prepare_owned(tmp_path)
    destination = tmp_path / 'texture.cditem'
    authoring.write_texture_package(review, destination)
    original = destination.read_bytes()
    selected = authoring.load_texture_package_update(destination)
    replacement.write_bytes(dds_payload(fill=2))
    update = authoring.prepare_texture_package(catalogue, TEXTURE_PATH, replacement,
        title='Updated texture', release='2', update=selected)
    return root, catalogue, replacement, destination, original, selected, update


def change_same_size_and_timestamp(path):
    before = path.stat()
    data = bytearray(path.read_bytes())
    data[-1] ^= 1
    path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_reviewed_new_texture_package_has_actual_reader_and_compiler_roundtrip(tmp_path, target):
    root, catalogue, replacement, review = prepare_owned(tmp_path)
    before = files_in(root)
    assert catalogue.paths == (TEXTURE_PATH,)
    assert TEXTURE_PATH in '\n'.join(review.lines)
    destination = tmp_path / 'texture.cditem'
    exported = authoring.write_texture_package(review, destination)
    loaded = read_package(exported.path)
    assert loaded.identity == review.package.identity
    assert loaded.digest == exported.digest
    assert loaded.manifest['requires'] == {'texture.replace': 1}
    resolved = resolve_items([destination], root, target=target)
    changes = resolved.contributions[0][1]
    assert set(changes) == {TEXTURE_PATH}
    assert changes[TEXTURE_PATH]['after'] == replacement.read_bytes()
    assert resolved.rows[0][2] is None
    assert resolved.registry['items'][loaded.identity]['values'] == {}
    assert files_in(root) == before


def test_reviewed_update_keeps_uuid_module_identity_metadata_and_expected_digest(tmp_path):
    root, catalogue, replacement, initial = prepare_owned(tmp_path)
    manifest = deepcopy(initial.package.manifest)
    manifest['modules'][0]['id'] = 'custom_texture'
    manifest['metadata'] = {'author': 'Owned test author', 'notes': ['retain', {'tool': 7}]}
    previous = read_v2(manifest, initial.package.blobs)
    destination = tmp_path / 'texture.cditem'
    write_package(previous, destination)
    selected = authoring.load_texture_package_update(destination)
    assert selected.digest == previous.digest
    assert selected.artifact_digest == read_package(destination).artifact_digest
    replacement.write_bytes(dds_payload(fill=2))
    review = authoring.prepare_texture_package(catalogue, TEXTURE_PATH, replacement,
        title='Second release', release='2', update=selected)
    result = authoring.write_texture_package(review, destination)
    loaded = read_package(result.path)
    assert result.identity == selected.identity == previous.identity
    assert loaded.digest != previous.digest
    assert loaded.manifest['modules'][0]['id'] == 'custom_texture'
    assert loaded.manifest['metadata'] == manifest['metadata']
    assert loaded.manifest['provenance'] == previous.manifest['provenance']
    assert loaded.manifest['release'] == '2'
    assert loaded.title == 'Second release'
    for target in ('archive', 'virtual'):
        resolved = resolve_items([destination], root, target=target)
        assert resolved.contributions[0][1][TEXTURE_PATH]['after'] == replacement.read_bytes()


def test_new_write_cannot_implicitly_overwrite_a_package_and_update_path_is_fixed(tmp_path):
    _root, catalogue, replacement, destination, original, _selected, update = prepare_update(tmp_path)
    new = authoring.prepare_texture_package(catalogue, TEXTURE_PATH, replacement)
    with pytest.raises(IndependentItemError, match='Select the existing package explicitly'):
        authoring.write_texture_package(new, destination)
    with pytest.raises(IndependentItemError, match='explicitly selected package path'):
        authoring.write_texture_package(update, tmp_path / 'another.cditem')
    assert destination.read_bytes() == original
    assert not (tmp_path / 'another.cditem').exists()


def test_same_content_repacked_update_must_be_loaded_again(tmp_path):
    _root, _catalogue, _replacement, destination, _original, selected, update = prepare_update(tmp_path)
    with zipfile.ZipFile(destination, 'a') as archive:
        archive.comment = b'An independently repacked artifact'
    current = destination.read_bytes()
    assert read_package(destination).digest == selected.digest
    assert read_package(destination).artifact_digest != selected.artifact_digest
    with pytest.raises(IndependentItemError, match='selected for update changed'):
        authoring.write_texture_package(update, destination)
    assert destination.read_bytes() == current
    assert not tuple(tmp_path.glob('.cditem-*.tmp'))


@pytest.mark.parametrize('changed_input', ['replacement', 'registry'])
def test_final_source_guard_rejects_drift_after_staging_and_preserves_previous_package(tmp_path, monkeypatch, changed_input):
    root, _catalogue, replacement, destination, original, _selected, update = prepare_update(tmp_path)
    serialize = codec._write_package_archive
    checked = []
    actual_read = codec.read_package
    def record_read(source, **kwargs):
        result = actual_read(source, **kwargs)
        if isinstance(source, Path) and source.name.startswith('.cditem-'):
            checked.append(result.digest)
        return result
    def drift(package, stream, stop_event):
        serialize(package, stream, stop_event)
        change_same_size_and_timestamp(replacement if changed_input == 'replacement' else root / 'meta/0.pathc')
    monkeypatch.setattr(codec, 'read_package', record_read)
    monkeypatch.setattr(codec, '_write_package_archive', drift)
    with pytest.raises((IndependentItemError, ValueError, RuntimeError)):
        authoring.write_texture_package(update, destination)
    assert checked == [update.package.digest], 'The staged artifact must pass the actual reader before the final source guard.'
    assert destination.read_bytes() == original
    assert not tuple(tmp_path.glob('.cditem-*.tmp'))


@pytest.mark.parametrize('failure', ['cancel', 'invalid-archive', 'replace-error'])
def test_failed_or_cancelled_publication_keeps_previous_package(tmp_path, monkeypatch, failure):
    _root, _catalogue, _replacement, destination, original, _selected, update = prepare_update(tmp_path)
    stop = threading.Event()
    serialize, replace = codec._write_package_archive, codec.os.replace
    def fail_stage(package, stream, stop_event):
        if failure == 'invalid-archive':
            stream.write(b'not a package archive')
        else:
            serialize(package, stream, stop_event)
            stop.set()
    def fail_replace(source, target):
        if Path(target) == destination:
            raise OSError('Owned publication failure')
        return replace(source, target)
    if failure == 'replace-error':
        monkeypatch.setattr(codec.os, 'replace', fail_replace)
    else:
        monkeypatch.setattr(codec, '_write_package_archive', fail_stage)
    expected = RunCancelled if failure == 'cancel' else (IndependentItemError, OSError)
    with pytest.raises(expected):
        authoring.write_texture_package(update, destination, stop_event=stop)
    assert destination.read_bytes() == original
    assert not tuple(tmp_path.glob('.cditem-*.tmp'))


def test_late_cancel_after_atomic_replace_returns_committed_package(tmp_path, monkeypatch):
    _root, _catalogue, _replacement, destination, original, selected, update = prepare_update(tmp_path)
    stop = threading.Event()
    replace = codec.os.replace
    def commit_then_cancel(source, target):
        replace(source, target)
        if Path(target) == destination:
            stop.set()
    monkeypatch.setattr(codec.os, 'replace', commit_then_cancel)
    exported = authoring.write_texture_package(update, destination, stop_event=stop)
    assert stop.is_set()
    assert exported.identity == selected.identity
    assert destination.read_bytes() != original
    assert read_package(destination).digest == exported.digest
    assert not tuple(tmp_path.glob('.cditem-*.tmp'))


def test_editor_refuses_combined_texture_package_without_rewriting_it(tmp_path):
    _root, snapshot = texture_game(tmp_path)
    package = texture_package(snapshot, {TEXTURE_PATH: dds_payload(fill=1),
                                         SECOND_TEXTURE_PATH: dds_payload(fill=2)})
    destination = tmp_path / 'combined.cditem'
    write_package(package, destination)
    before = destination.read_bytes()
    with pytest.raises(IndependentItemError, match='one texture replacement at a time'):
        authoring.load_texture_package_update(destination)
    assert destination.read_bytes() == before


def test_find_returns_bounded_registered_paths_and_reports_total(tmp_path, monkeypatch):
    root, _snapshot = texture_game(tmp_path)
    monkeypatch.setattr(authoring, 'MAX_TEXTURE_SEARCH_RESULTS', 1)
    catalogue = authoring.find_existing_texture_targets(root, 'cdmw_existing')
    assert len(catalogue.paths) == 1 and catalogue.total_matches == 2
    assert catalogue.paths[0] in (TEXTURE_PATH, SECOND_TEXTURE_PATH)


def test_portable_writer_refuses_game_archive_destination(tmp_path):
    root, _catalogue, _replacement, review = prepare_owned(tmp_path)
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='outside the game archive folder'):
        authoring.write_texture_package(review, root / 'managed/texture.cditem')
    assert files_in(root) == before
