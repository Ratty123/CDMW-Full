"""Owned exported-folder fixtures exercise metadata admission through real consumers."""
import os
from uuid import uuid4

import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.domain.archives.overlay_merge import OverlayConflict
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from cdmw.services.independent_item_compatibility import scan_independent_conflicts
from cdmw.services.independent_item_install import prepare_install, resolve_items
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_new_item_service import _fake_dds


TEXTURE = 'character/texture/exported-look.dds'
CHARACTER = 'character/exported-look.dat'


def exported_folder(tmp_path, *, texture=False, registry='absent'):
    service, snapshot, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    package = from_plan(service.plan(shop_spec('FolderCompanion'), snapshot, capture_independent=True), uuid4().hex)
    selected = tmp_path / 'companion.cditem'
    selected.write_bytes(package_bytes(package))
    path, data = (TEXTURE, _fake_dds(4, 4)) if texture else (CHARACTER, b'owned synthetic character resource')
    metadata = []
    if registry != 'absent':
        original = (root / 'meta/0.pathc').read_bytes()
        if registry == 'changed':
            original = encode_pathc(register_dds(parse_pathc(original), TEXTURE, _fake_dds(4, 4)))
        metadata.append(('meta/0.pathc', original))
    folder = tmp_path / 'exported'
    export_archive_overlay_package((), (ArchiveAddRequest(root / '0009/0.pamt', path, data, 0),),
        package_root=folder, game_root=root, metadata_files=metadata)
    assert (folder / 'meta/0.papgt').is_file()
    return root, selected, folder, path, data


@pytest.mark.parametrize('route', ['scan', 'physical', 'virtual'])
@pytest.mark.parametrize('texture', [False, True])
def test_exported_mount_metadata_is_consumed_without_becoming_a_payload(tmp_path, route, texture):
    root, selected, folder, path, data = exported_folder(tmp_path, texture=texture)
    if route == 'scan':
        Backups(tmp_path).apply(prepare_install([selected], root).preparation)
    before, source_before = files_in(root), files_in(folder)
    if route == 'scan':
        report = scan_independent_conflicts(root, folders=(folder,))
        assert report.compatible, report.text()
    elif route == 'physical':
        # The shared archive resolver admits selected folders before publication.
        resolved = resolve_items([selected], root, target='archive', folders=(folder,))
        assert path in resolved.external.paths
        assert 'meta/0.papgt' not in resolved.external.paths
    else:
        prepared = prepare_profile(VirtualProfile((selected,), (folder,)), root)
        view = tmp_path / 'view'
        for relative, payload in prepared.files:
            output = view / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(payload)
        pamt = next(view.glob('*/0.pamt'))
        entries = {entry.path: entry for entry in parse_archive_pamt(pamt)}
        assert read_archive_entry_data(entries[path])[0] == data
        assert not any(name.startswith('meta/') for name in entries)
        if texture:
            assert parse_pathc(dict(prepared.files)['meta/0.pathc']).find(path) is not None
    assert files_in(root) == before
    assert files_in(folder) == source_before


def test_unchanged_exported_texture_registry_is_verified_as_metadata(tmp_path):
    root, selected, folder, _path, _data = exported_folder(tmp_path, registry='unchanged')
    before, source_before = files_in(root), files_in(folder)
    prepared = prepare_profile(VirtualProfile((selected,), (folder,)), root)
    assert dict(prepared.files)['meta/0.pathc'] == (root / 'meta/0.pathc').read_bytes()
    assert files_in(root) == before
    assert files_in(folder) == source_before


def test_changed_exported_texture_registry_requires_recorded_merge_ownership(tmp_path):
    root, selected, folder, _path, _data = exported_folder(tmp_path, texture=True, registry='changed')
    before, source_before = files_in(root), files_in(folder)
    with pytest.raises(OverlayConflict, match='texture registry.*recorded.*ownership'):
        prepare_profile(VirtualProfile((selected,), (folder,)), root)
    assert files_in(root) == before
    assert files_in(folder) == source_before


def test_unknown_external_metadata_refuses_instead_of_being_archived(tmp_path):
    root, selected, folder, _path, _data = exported_folder(tmp_path)
    (folder / 'meta/unknown.bin').write_bytes(b'unrecognized metadata')
    before = files_in(root)
    with pytest.raises(OverlayConflict, match='Unsupported external package metadata.*meta/unknown.bin'):
        prepare_profile(VirtualProfile((selected,), (folder,)), root)
    assert files_in(root) == before


def test_invalid_exported_mount_index_refuses_before_discovery_fallback(tmp_path):
    root, selected, folder, _path, _data = exported_folder(tmp_path)
    (folder / 'meta/0.papgt').write_bytes(b'invalid mount index')
    before = files_in(root)
    with pytest.raises(OverlayConflict, match='Invalid external package metadata.*0.papgt'):
        prepare_profile(VirtualProfile((selected,), (folder,)), root)
    assert files_in(root) == before


@pytest.mark.parametrize('index', ['0.papgt', '0.pathc'])
def test_consumed_metadata_retains_original_digest_after_discovery(tmp_path, monkeypatch, index):
    from cdmw.services import new_item_mod_base, new_item_provenance as provenance

    root, selected, folder, _path, _data = exported_folder(tmp_path, registry='unchanged')
    source = (folder / 'meta' / index).resolve()
    stamp = provenance._stamp
    original_stamp = stamp(source)
    # Hold the whole stamp equal, including ctime, to isolate digest enforcement.
    monkeypatch.setattr(provenance, '_stamp', lambda path: original_stamp if path == source else stamp(path))
    original = new_item_mod_base.mod_folder_payloads
    changed = False

    def drift(*args, **kwargs):
        nonlocal changed
        result = original(*args, **kwargs)
        if not changed:
            changed = True
            stamp, raw = source.stat(), bytearray(source.read_bytes())
            raw[-1] ^= 1
            source.write_bytes(raw)
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return result

    monkeypatch.setattr(new_item_mod_base, 'mod_folder_payloads', drift)
    before = files_in(root)
    with pytest.raises(provenance.StaleNewItemSource, match='Source index changed since parsing'):
        prepare_profile(VirtualProfile((selected,), (folder,)), root)
    assert changed and files_in(root) == before
