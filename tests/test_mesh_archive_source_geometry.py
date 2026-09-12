from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.core import archive_mesh_appearance as appearance
from cdmw.core.skeleton_resolver import SkeletonDescriptorResolution
from cdmw.domain.cancellation import RunCancelled
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveSessionLoadWorker
from tests.test_mesh_preserved_skin_influences import _eight_influence_pac
from tests.test_release_inspired_improvements import _entry


def test_rigid_attachment_does_not_require_unrelated_character_skeleton(monkeypatch):
    entry = _entry("character/model/1_pc/1_phm/armor/bag.pac")
    pabc = _entry("character/variation/body.pabc")
    mesh = SimpleNamespace(format="pac", submeshes=[SimpleNamespace(
        bone_indices=[(0,)], bone_weights=[(1.,)],
    )])
    monkeypatch.setattr(appearance, "_related_appearance_entries", lambda *a, **k: (pabc,))
    monkeypatch.setattr(appearance, "resolve_skeleton_descriptor_for_model", lambda *a, **k: SkeletonDescriptorResolution())
    monkeypatch.setattr(appearance, "read_archive_entry_data", lambda *a, **k: (b"PABC", False, ""))
    monkeypatch.setattr(appearance, "resolve_skeleton_for_model", lambda *a, **k: (None, SimpleNamespace(blocking_errors=("unresolved",))))
    monkeypatch.setattr(appearance, "apply_skeleton_variation_to_mesh", lambda *a, **k: pytest.fail("unresolved rigid geometry needs no character deformation"))
    returned, notes = appearance.apply_archive_mesh_appearance(
        entry, mesh, b"rigid source", archive_entries_by_normalized_path={}, archive_entries_by_basename={},
    )
    assert returned is mesh and "Rigid attachment" in notes[0]


def test_single_weighted_slot_with_resolved_palette_still_applies_appearance(monkeypatch):
    entry = _entry("character/model/armor.pac")
    pabc = _entry("character/variation/body.pabc")
    mesh = SimpleNamespace(format="pac", submeshes=[SimpleNamespace(bone_indices=[(0,)], bone_weights=[(1.,)])])
    deformed = SimpleNamespace(format="pac")
    monkeypatch.setattr(appearance, "_related_appearance_entries", lambda *a, **k: (pabc,))
    monkeypatch.setattr(appearance, "resolve_skeleton_descriptor_for_model", lambda *a, **k: SkeletonDescriptorResolution())
    monkeypatch.setattr(appearance, "read_archive_entry_data", lambda *a, **k: (b"PABC", False, ""))
    monkeypatch.setattr(appearance, "parse_pabc_skeleton_variation", lambda *a, **k: SimpleNamespace(matched_record_count=1, record_count=1))
    monkeypatch.setattr(appearance, "apply_skeleton_variation_to_mesh", lambda *a, **k: deformed)
    returned, notes = appearance.apply_archive_mesh_appearance(
        entry, mesh, b"skinned", skeleton=object(), bone_palette=(0,),
        archive_entries_by_normalized_path={}, archive_entries_by_basename={},
    )
    assert returned is deformed and "Applied character skeleton variation" in notes[0]


@pytest.mark.parametrize("failure", ["palette", "no_variation", "broken", "cancel"])
def test_archive_loader_preserves_geometry_only_for_unresolved_palette(tmp_path, monkeypatch, failure):
    app = QApplication.instance() or QApplication([])
    source = _eight_influence_pac()
    entry = _entry("character/model/armor.pac", data=source)
    worker = MeshArchiveSessionLoadWorker(1, entry, archive_entries_by_basename={entry.basename: (entry,)})
    loaded, errors = [], []
    worker.loaded.connect(lambda _, result: loaded.append(result))
    worker.error.connect(lambda _, message: errors.append(message))
    monkeypatch.setattr("cdmw.workers.mesh_editor_aux_workers.read_archive_entry_data", lambda *a, **k: (source, False, ""))

    def unavailable(*args, **kwargs):
        if failure == "no_variation":
            return args[1], ()
        if failure == "cancel":
            worker.stop()
            raise RunCancelled("cancelled")
        raise (appearance.UnresolvedPacBonePaletteError if failure == "palette" else ValueError)("unresolved transform")

    monkeypatch.setattr(appearance, "apply_archive_mesh_appearance", unavailable)
    worker.run()
    if failure not in {"palette", "no_variation"}:
        assert not loaded
        assert bool(errors) == (failure == "broken")
        return
    assert not errors and len(loaded) == 1
    result = loaded[0]
    try:
        assert "Loaded source geometry" in result.appearance_warning
        assert result.source_skeleton is None
        sid = result.view.session_id
        assert result.service._session(sid).neutral_appearance is None
        assert result.service._session(sid).skeleton_resolution_reason
        snapshot = result.service.capture_export_snapshot(sid)
        snapshot.mesh.submeshes[0].vertices[0] = (.1, 0., 0.)
        rebuilt, report = result.service.rebuild_result_from_snapshot(snapshot)
        assert report.validation_status == "passed" and rebuilt.data != source
        from cdmw.modding.mesh_parser import parse_pac
        assert parse_pac(rebuilt.data).submeshes[0].bone_weights == parse_pac(source).submeshes[0].bone_weights
    finally:
        result.service.close_edit_session(result.view.session_id, force_without_saving=True)
        app.processEvents()
