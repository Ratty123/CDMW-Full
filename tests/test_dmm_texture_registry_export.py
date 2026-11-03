"""DMM archive packages retain textures while other formats retain their registry."""
import pytest

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.mod_compatibility import compatibility_from_payloads, read_compatibility
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.services.archive_overlay_package_service import export_archive_overlay_package
from tests.test_new_item_service import _fake_dds


@pytest.mark.parametrize("for_dmm", (False, True))
@pytest.mark.parametrize("supplied_compatibility", (False, True))
def test_archive_export_registry_policy_preserves_texture_bytes(tmp_path, for_dmm, supplied_compatibility):
    root = tmp_path / "mod"
    (root / "meta").mkdir(parents=True)
    (root / "meta/0.pathc").write_bytes(b"previous export registry")
    path, dds = "character/texture/authored.dds", _fake_dds(4, 4)
    registry = b"updated texture registry"
    compatibility = compatibility_from_payloads(
        {path: dds, "meta/0.pathc": registry}, {path: None, "meta/0.pathc": b"stock registry"})
    result = export_archive_overlay_package((), (ArchiveAddRequest(tmp_path / "0.pamt", path, dds, 0),),
        package_root=root, metadata_files=(("meta/0.pathc", registry),), for_dmm=for_dmm,
        compatibility=compatibility if supplied_compatibility else None)
    entries = parse_archive_pamt(root / "0036/0.pamt")
    assert len(entries) == 1 and entries[0].path == path
    assert read_archive_entry_data(entries[0])[0] == dds
    assert (root / "meta/0.pathc").exists() is (not for_dmm)
    assert ("meta/0.pathc" in result.metadata_files) is (not for_dmm)
    evidence = read_compatibility(root)
    assert ("meta/0.pathc" in {row["path"] for row in evidence.files}) is (not for_dmm)
    if for_dmm:
        assert "meta/0.pathc" not in evidence.originals
    else:
        assert (root / "meta/0.pathc").read_bytes() == registry
