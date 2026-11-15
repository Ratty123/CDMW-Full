"""Head companions use only declared, unambiguous sources and the head pose."""

import threading
from types import SimpleNamespace

import pytest

from cdmw.core.common import RunCancelled
from cdmw.workers import archive_preview_native as owner
from tests.test_progressive_archive_preview import _entry


@pytest.fixture
def head_worker(monkeypatch):
    head = _entry("character/model/1_pc/head/head/face.pac", ".pac")
    eye = _entry("character/model/1_pc/head/head_sub/eye.pac", ".pac")
    prefab = _entry("character/bin__/prefab/1_pc/head/head/face.prefab", ".prefab")
    descriptor = _entry("character/prefab/1_pc/head/head/face.prefabdata_xml", ".prefabdata_xml")
    worker = owner.ArchivePreviewNativeMixin()
    worker.entry = head
    worker.stop_event = threading.Event()
    worker.native_preview_dependency_entries = (head, eye, prefab, descriptor)
    worker.native_preview_dependency_entries_complete = True
    worker.texture_entries_by_normalized_path = {head.path:(head,), eye.path:(eye,)}
    worker.texture_entries_by_basename = {}
    monkeypatch.setattr("cdmw.core.skeleton_resolver.resolve_skeleton_descriptor_for_model",
        lambda *args, **kwargs: SimpleNamespace(skeleton_descriptor_entry=descriptor,
            descriptor_entry=descriptor, skeleton_variation_entry=object()))
    monkeypatch.setattr(owner, "native_preview_model_property_indices",
                        lambda *args: {head.path:0, eye.path:0})
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda *args, **kwargs: (b"PAC", ""))
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_mesh", lambda *args: SimpleNamespace())
    monkeypatch.setattr(owner, "_native_presentation_geometry_payload", lambda *args: b"immutable posed vertices")
    return worker, eye, descriptor


def test_companion_uses_selected_head_descriptor_and_complete_dependencies(head_worker, monkeypatch):
    worker, eye, descriptor = head_worker
    def apply(entry, mesh, data, **kwargs):
        assert entry is eye and data == b"PAC"
        assert kwargs['authored_descriptor'] is descriptor
        return SimpleNamespace(_cdmw_skeleton_variation_source="authored.pabc"), ("applied",)
    monkeypatch.setattr("cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance", apply)
    components, notes = worker._prepare_native_head_component_geometry()
    assert len(components) == 1
    assert components[0].entry is eye
    assert components[0].appearance_path == worker.entry.path
    assert components[0].dependencies_complete
    assert components[0].presentation_geometry_payload == b"immutable posed vertices"
    assert notes == ("applied",)


def test_unresolved_binding_keeps_its_diagnostic(head_worker, monkeypatch):
    worker, _, _ = head_worker
    monkeypatch.setattr("cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance",
        lambda entry, mesh, data, **kwargs: (mesh, ("unresolved palette",)))
    assert worker._prepare_native_head_component_geometry() == ((), ("unresolved palette",))


def test_ambiguous_companion_or_unrelated_prefab_is_not_used(head_worker, monkeypatch):
    worker, eye, _ = head_worker
    worker.texture_entries_by_normalized_path[eye.path] = (eye, eye)
    assert worker._prepare_native_head_component_geometry() == ((), ())
    worker.texture_entries_by_normalized_path[eye.path] = (eye,)
    monkeypatch.setattr(owner, "native_preview_model_property_indices", lambda *args: {eye.path:0})
    assert worker._prepare_native_head_component_geometry() == ((), ())


def test_cancelled_component_read_is_propagated(head_worker, monkeypatch):
    worker, _, _ = head_worker
    def cancelled(*args, **kwargs):
        raise RunCancelled()
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", cancelled)
    with pytest.raises(RunCancelled):
        worker._prepare_native_head_component_geometry()
