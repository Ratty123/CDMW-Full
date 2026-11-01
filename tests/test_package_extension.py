"""Packages are written as .cdmw; .cditem packages from before the rename stay readable."""
from pathlib import Path

import pytest

from cdmw.constants import PACKAGE_EXTENSION, PACKAGE_EXTENSIONS
from cdmw.core.mod_compatibility import (
    LEGACY_SEMANTIC_EXPORT_FILE, SEMANTIC_EXPORT_FILE, read_semantic_export, semantic_export_path,
    semantic_export_wrapper)
from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_package as owner
from tests.test_independent_item_streaming import package  # noqa: F401 (fixture)
from tests.test_semantic_export_contract import original_export  # noqa: F401 (fixture)
from tests.test_virtual_loader import packages


def test_packages_are_written_as_cdmw_and_legacy_names_stay_writable(package, tmp_path):
    assert PACKAGE_EXTENSION == '.cdmw' and PACKAGE_EXTENSIONS == ('.cdmw', '.cditem')
    folder = tmp_path / 'written'
    for name in ('new.cdmw', 'old.cditem', 'UPPER.CDMW'):
        owner.write_package(package, folder / name)
        assert owner.read_package(folder / name) == package
    with pytest.raises(IndependentItemError, match=r'\.cdmw extension'):
        owner.write_package(package, folder / 'wrong.zip')
    assert not (folder / 'wrong.zip').exists()


def test_updating_a_legacy_package_keeps_its_name(package, tmp_path):
    folder = tmp_path / 'shared'
    legacy = folder / 'shared.cditem'
    owner.write_package(package, legacy)
    owner.write_package(package, legacy, expected_digest=package.digest)
    assert [path.name for path in folder.iterdir()] == ['shared.cditem']


def test_new_semantic_exports_use_the_cdmw_name():
    assert SEMANTIC_EXPORT_FILE == 'cdmw-semantic.cdmw'
    assert LEGACY_SEMANTIC_EXPORT_FILE == 'cdmw-semantic.cditem'


@pytest.mark.parametrize('name', [SEMANTIC_EXPORT_FILE, LEGACY_SEMANTIC_EXPORT_FILE])
def test_semantic_export_folders_are_read_under_either_name(original_export, tmp_path, name):
    folder = tmp_path / 'export'
    folder.mkdir()
    (folder / name).write_bytes(original_export)
    assert semantic_export_path(folder) == folder / name
    assert semantic_export_wrapper(folder) == folder / name
    assert read_semantic_export(folder) is not None


def test_a_folder_holding_both_wrapper_names_refuses(original_export, tmp_path):
    for name in (SEMANTIC_EXPORT_FILE, LEGACY_SEMANTIC_EXPORT_FILE):
        (tmp_path / name).write_bytes(original_export)
    with pytest.raises(ValueError, match='single opaque'):
        semantic_export_path(tmp_path)


@pytest.mark.parametrize('suffix', ['.cdmw', '.cditem', '.CDMW'])
def test_a_renamed_semantic_export_file_is_still_recognised(original_export, tmp_path, suffix):
    selected = tmp_path / f'shared{suffix}'
    selected.write_bytes(original_export)
    assert read_semantic_export(selected) is not None
    other = tmp_path / 'shared.zip'
    other.write_bytes(original_export)
    assert semantic_export_path(other) is None


def test_an_empty_folder_names_the_current_wrapper(tmp_path):
    assert semantic_export_wrapper(tmp_path) == tmp_path / SEMANTIC_EXPORT_FILE


def test_virtual_profiles_mix_cdmw_and_legacy_packages(tmp_path, monkeypatch):
    from cdmw.services import virtual_loader_process
    from cdmw.services.virtual_loader_state import load_profile, publish_profile
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    root, paths = packages(tmp_path)
    renamed = paths[0].rename(paths[0].with_suffix('.cdmw'))
    selection = (renamed, paths[1])
    publish_profile(virtual_loader_process.prepare_profile_in_subprocess(VirtualProfile(selection), root))
    profile = load_profile(root)
    assert profile['packages'] == [str(path) for path in selection]
    assert len(profile['items']) == 2
    # CDMW's own retained copies keep the name the runtime validates.
    retained = sorted(Path(root, '.cdmw/virtual-loader/generations').glob('*/packages/*'))
    assert len(retained) == 2 and all(path.suffix == '.cditem' for path in retained)
