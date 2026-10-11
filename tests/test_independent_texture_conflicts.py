"""Existing raw inputs cannot erase typed texture requirements."""
import pytest

from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services.independent_item_compatibility import scan_independent_conflicts
from cdmw.services.independent_item_install import prepare_install
from cdmw.services.independent_item_package import package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_independent_item_compatibility import mount_mod
from tests.test_independent_item_regressions import files_in
from tests.test_independent_texture_composition import backups, visible_texture
from tests.test_independent_texture_packages import TEXTURE_PATH, dds_payload, texture_game, texture_package


@pytest.mark.parametrize('virtual', [False, True])
@pytest.mark.parametrize('mounted', [False, True])
@pytest.mark.parametrize('equal', [False, True])
def test_raw_texture_writer_respects_typed_final_bytes(tmp_path, virtual, mounted, equal):
    root, snapshot = texture_game(tmp_path)
    registry_before = (root / 'meta/0.pathc').read_bytes()
    foreign_bytes = dds_payload(fill=1)
    required = foreign_bytes if equal else snapshot.payload(TEXTURE_PATH)
    package = texture_package(snapshot, {TEXTURE_PATH: required}, title='Required texture owner')
    package_path = tmp_path / 'required.cditem'
    package_path.write_bytes(package_bytes(package))
    folder = tmp_path / 'foreign-texture'
    if mounted:
        mount_mod(root, folder, {TEXTURE_PATH: foreign_bytes}, name='foreign-texture')
        folders = ()
    else:
        target = folder / 'files' / TEXTURE_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(foreign_bytes)
        folders = (folder,)
    before = files_in(root)

    def prepare():
        if virtual:
            return prepare_profile(VirtualProfile((package_path,), folders), root)
        return prepare_install([package_path], root, folders=folders)

    if not equal:
        with pytest.raises(ValueError) as error:
            prepare()
        message = str(error.value)
        assert package.title in message
        assert 'foreign-texture' in message
        assert TEXTURE_PATH in message
        assert 'different final bytes' in message
        assert files_in(root) == before
        return

    prepared = prepare()
    if virtual:
        publish_profile(prepared)
    else:
        backups(tmp_path / 'backups').apply(prepared.preparation)
    assert visible_texture(root, virtual=virtual) == foreign_bytes
    assert (root / 'meta/0.pathc').read_bytes() == registry_before
    if not virtual:
        assert scan_independent_conflicts(root).compatible
