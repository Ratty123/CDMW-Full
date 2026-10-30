"""Explicit face descriptors can legitimately contain no shape deformation."""

from pathlib import Path

import pytest

from cdmw.core import archive_mesh_appearance as appearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import ArchiveEntry


@pytest.mark.parametrize("descriptor_xml", [
    b"<HeadPrefabData/>",
    b'<HeadPrefabData><FacialAnimationIntensityMask FileName="BoneMask_Base.xml"/>'
    b'<SkeletonMorphMask FileName="ARIntensityMask_Base.xml"/></HeadPrefabData>',
])
def test_authored_face_without_shape_references_keeps_source_geometry(monkeypatch, descriptor_xml):
    model = ArchiveEntry("character/model/head.pac", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    descriptor = ArchiveEntry("character/prefab/head.prefabdata_xml", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    unrelated = ArchiveEntry("character/binary/skeletonvariation/other.pabc", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    reads = []

    def read(entry, **_kwargs):
        reads.append(entry.path)
        assert entry is descriptor, "An empty authored face must not borrow another shape"
        return descriptor_xml, False, ""

    monkeypatch.setattr(appearance, "read_archive_entry_data", read)
    mesh = ParsedMesh(format="pac", submeshes=[SubMesh(name="head", vertices=[(1., 2., 3.)])])
    result, notes = appearance.apply_archive_mesh_appearance(
        model, mesh, b"fixture", archive_entries_by_normalized_path={}, archive_entries_by_basename={},
        context_entries=(descriptor, unrelated), authored_descriptor=descriptor)
    assert result is mesh and result.submeshes[0].vertices == [(1., 2., 3.)]
    assert notes == () and reads == [descriptor.path]


@pytest.mark.parametrize(("descriptor_xml", "error"), [
    (b"<HeadPrefabData>", "no element found"),
    (b'<HeadPrefabData><SkeletonName FileName="missing.pab"/></HeadPrefabData>', "unresolved skeletonname"),
    (b'<HeadPrefabData><SkeletonVariationName FileName="missing.pabc"/></HeadPrefabData>', "unresolved skeletonvariationname"),
    (b'<HeadPrefabData><MorphTargetSet FileName="missing.pamt"/></HeadPrefabData>', "Authored appearance descriptor could not be resolved"),
])
def test_invalid_or_missing_authored_shape_still_blocks_preview(monkeypatch, descriptor_xml, error):
    model = ArchiveEntry("character/model/head.pac", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    descriptor = ArchiveEntry("character/prefab/head.prefabdata_xml", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    monkeypatch.setattr(appearance, "read_archive_entry_data", lambda *_args, **_kwargs: (descriptor_xml, False, ""))
    with pytest.raises(ValueError, match=error):
        appearance.apply_archive_mesh_appearance(model, ParsedMesh(format="pac"), b"fixture",
            archive_entries_by_normalized_path={}, archive_entries_by_basename={}, authored_descriptor=descriptor)
