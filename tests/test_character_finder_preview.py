from __future__ import annotations

from dataclasses import asdict, replace
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import ArchiveLookupResult
from cdmw.domain.archives.catalogue_operations import PrepareEntriesResult
from cdmw.domain.archives.character_catalogue import CharacterCatalogFile, CharacterCatalogComponent
from cdmw.domain.character_finder import CharacterRenderResult, character_preview_detail
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.character_finder import preview_controller as module
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet
from cdmw.workers.character_finder_workers import CharacterFinderRenderWorker, character_render_key, cached_character_render
from tests.test_character_finder_dialog import row, detail
from tests.test_archive_remote_preview_dependencies import _CatalogueService, _dto, _prepared


_APP = None


def wait_for(predicate, timeout=3):
    until = time.monotonic() + timeout
    while not predicate() and time.monotonic() < until:
        QTest.qWait(5)
    assert predicate(), "Qt operation did not complete within the focused test deadline"


class Service(_CatalogueService):
    def get_character_catalog_detail(self, request, **kw):
        self.requests.append((request, kw))
        return f"detail-{len(self.requests)}"


class Preparation(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, service, parent):
        super().__init__(parent)

    def cancel(self): pass
    def start(self, selected, token): self.ready.emit(token, selected)


@pytest.fixture
def controller(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    service = Service()
    monkeypatch.setattr(module, "CharacterPreviewPreparation", Preparation)
    controller = module.CharacterFinderPreviewController(service, fingerprint="fp", cache_root=tmp_path,
        settings=ModelPreviewRenderSettings())
    yield controller, service
    controller.shutdown()
    wait_for(lambda: not controller.busy)
    controller.deleteLater()
    _APP.processEvents()


def test_selected_job_cancels_old_thread_and_rejects_its_late_result(controller, monkeypatch):
    owner, service = controller
    jobs, delivered = [], []
    monkeypatch.setattr(module, "cached_character_render", lambda *_: None)

    class Worker(QObject):
        package_ready = Signal(int, object)
        completed = Signal(int, object)
        failed = Signal(int, str)
        finished = Signal()

        def __init__(self, token, selected, **kw):
            super().__init__()
            self.token, self.selected = token, selected
            self.stopped, self.release, self.exited = threading.Event(), threading.Event(), threading.Event()
            jobs.append(self)

        def stop(self): self.stopped.set()

        def run(self):
            self.release.wait(3)
            result = CharacterRenderResult(self.selected.row.key, "package", "thumbnail", "base_appearance", ())
            self.package_ready.emit(self.token, result)
            self.completed.emit(self.token, result)
            self.exited.set()
            self.finished.emit()

    monkeypatch.setattr(module, "CharacterFinderRenderWorker", Worker)
    owner.package_ready.connect(lambda key, value: delivered.append(key))
    owner.visible([row(3)], session_id="session-a", generation=1)
    owner.select(detail(row(1)), 1)
    wait_for(lambda: len(jobs) == 1)
    owner.select(detail(row(2)), 2)
    assert jobs[0].stopped.is_set()
    QTest.qWait(25)
    assert len(jobs) == 1  # Replacement waits for actual teardown, not just stop().
    jobs[0].release.set()
    wait_for(lambda: len(jobs) == 2)
    assert jobs[0].exited.is_set() and jobs[1].selected.row.key == row(2).key
    assert not delivered
    started = time.monotonic()
    owner.shutdown()
    assert time.monotonic() - started < .2 and owner.busy
    jobs[1].release.set()
    wait_for(lambda: not owner.busy)
    assert not delivered and not service.requests


def test_warm_thumbnail_and_preview_reuse_without_preparation(controller, tmp_path):
    owner, _ = controller
    selected = detail(row(1))
    key = character_render_key(selected, "fp", owner._settings)
    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text("{}")
    root = tmp_path / "character_finder" / "thumbnails"
    root.mkdir(parents=True)
    image = root / (key + ".png")
    image.write_bytes(b"cached fixture image")
    result = CharacterRenderResult(key, str(package), str(image), "base_appearance", ())
    (root / (key + ".json")).write_text(json.dumps(asdict(result)))
    delivered = []
    owner.thumbnail_ready.connect(lambda _, value: delivered.append(value))
    owner._preparation.start = lambda *_: pytest.fail("warm cache unnecessarily prepared archive entries")
    owner.select(selected, 1)
    wait_for(lambda: len(delivered) == 1 and not owner.busy)
    assert delivered[0].cache_hit
    assert key != character_render_key(selected, "refreshed", owner._settings)
    assert key != character_render_key(replace(selected, context_key="other appearance"), "fp", owner._settings)
    (package / "manifest.json").unlink()
    assert cached_character_render(tmp_path, key) is None


def test_extra_context_lookup_cannot_publish_missing_entries_as_complete():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/body.pac")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, "character/body.pabc", ".pabc", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (), total_candidates=0, truncated=False,
        prepared={1: _prepared(model)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 9)
    preparation._model_ready(9, snapshot)
    request = preparation._request
    service.result_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (), 1, True))
    assert len(results) == 1 and not results[0].dependencies_complete
    preparation.start(selected, 10)
    preparation._model_ready(10, snapshot)
    failures = []
    preparation.failed.connect(lambda token, message: failures.append((token, message)))
    service.request_cancelled.emit(preparation._request)
    assert failures[0][0] == 10 and preparation._detail is None


def test_combined_body_reuses_only_identical_rendered_components():
    body, head = _dto(1, "character/body.pac"), _dto(2, "character/head.pac")
    body_component = CharacterCatalogComponent("body", "body_variant", (1,), (3,), 1.02, {}, "resolved")
    head_component = CharacterCatalogComponent("head", "head_variant", (2,), (4,), .95, {}, "resolved")
    files = tuple(CharacterCatalogFile(i, f"character/{i}.pabc", ".pabc", "dependency", "fixture") for i in range(1, 5))
    first = replace(detail(row(1, embedded_face=True)), models=(body, head),
                    components=(body_component, head_component), files=files, total_file_count=4)
    preview = character_preview_detail(first)
    assert preview.models == (body,) and preview.components == (body_component,)
    assert {f.entry_id for f in preview.files} == {1, 3} and preview.total_file_count == 2
    assert first.models == (body, head)  # UI ownership/details remain complete.
    settings = ModelPreviewRenderSettings()
    key = character_render_key(first, "fp", settings)
    other_owner = replace(first, row=replace(first.row, key="other-owner"), context_key="other-owner",
                          components=(body_component, replace(head_component, name="different_head")))
    assert character_render_key(other_owner, "fp", settings) == key
    assert character_render_key(replace(first, components=(replace(body_component, scale=1.1), head_component)), "fp", settings) != key
    assert character_render_key(replace(first, components=(replace(body_component, name="other_pabc_variant"), head_component)), "fp", settings) != key
    assert character_render_key(replace(first, files=(*files[:2], replace(files[2], path="different/material.dds"), files[3])), "fp", settings) != key
    assert character_preview_detail(replace(first, files=files[:2])).models == (body, head)


def test_heads_share_complete_shape_and_material_inputs_but_keep_variants_distinct():
    head = _dto(1, "character/head.pac")
    component = CharacterCatalogComponent("head", "head_variant", (1,), (2,), .97, {"Name": "head_variant"}, "resolved")
    shape = CharacterCatalogFile(2, "character/head_variant.prefabdata_xml", ".prefabdata_xml", "dependency", "fixture")
    custom = CharacterCatalogFile(3, "character/custom.paccd", ".paccd", "dependency", "fixture")
    owner = CharacterCatalogFile(4, "character/first.app_xml", ".app_xml", "direct", "fixture")
    first = replace(detail(row(1, role="head")), models=(head,), components=(component,),
        files=(shape, custom, owner), total_file_count=3, appearance_path=owner.path)
    second = replace(first, row=replace(first.row, key="other-owner", label="Other owner"), context_key="other-owner",
        appearance_path="character/second.app_xml", files=(shape, custom, replace(owner, entry_id=5, path="character/second.app_xml")))
    settings = ModelPreviewRenderSettings()
    key = character_render_key(first, "fp", settings)
    assert character_render_key(second, "fp", settings) == key
    assert character_preview_detail(first).files == (shape, custom)
    assert first.files == (shape, custom, owner)
    variants = (
        replace(second, components=(replace(component, scale=1.0),)),
        replace(second, components=(replace(component, name="other_shape"),)),
        replace(second, components=(replace(component, attributes={"Name": "head_variant", "Color": "2"}),)),
        replace(second, files=(replace(shape, path="character/other.pabc"), custom)),
        replace(second, files=(shape, replace(custom, entry_id=6, path="character/other.paccd"))),
        replace(second, total_file_count=300),
    )
    assert all(character_render_key(variant, "fp", settings) != key for variant in variants)
    declared_app = replace(first, components=(replace(component, context_entry_ids=(2, 4)),))
    assert owner in character_preview_detail(declared_app).files


def test_extra_context_consumes_streamed_lookup_and_prepared_batches():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/head.pac")
    extra = _dto(2, "character/head.pabc")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, extra.path, ".pabc", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (), total_candidates=0, truncated=False,
        prepared={1: _prepared(model)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 9)
    preparation._model_ready(9, snapshot)
    request = preparation._request
    service.batch_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (extra,), 1, False))
    service.result_ready.emit(request, "resolve_entries", ArchiveLookupResult("session-a", (), 1, False))
    assert not results
    request = preparation._request
    service.batch_ready.emit(request, "prepare_entry", PrepareEntriesResult("session-a", (_prepared(extra),), 1, 1, 40))
    service.result_ready.emit(request, "prepare_entry", PrepareEntriesResult("session-a", (), 1, 1, 40))
    assert len(results) == 1 and results[0].dependencies_complete
    assert {entry.path for entry in results[0].entries} == {model.path, extra.path}
    assert str(results[0].entries_by_id[2].prepared_path).replace("\\", "/") == "C:/cache/2.pabc"


def test_prepared_model_dependencies_keep_ids_for_authored_descriptor_selection():
    service = Service()
    preparation = CharacterPreviewPreparation(service)
    model = _dto(1, "character/body.pac")
    descriptor = _dto(2, "character/body_variant.prefabdata_xml")
    selected = replace(detail(row(1)), models=(model,), files=(
        CharacterCatalogFile(2, descriptor.path, ".prefabdata_xml", "dependency", "fixture"),), total_file_count=1)
    snapshot = ArchivePreviewDependencySet.from_dtos(model, (descriptor,), total_candidates=1,
        truncated=False, prepared={1: _prepared(model), 2: _prepared(descriptor)})
    preparation._provider.request = lambda *_a, **_kw: True
    results = []
    preparation.ready.connect(lambda _token, value: results.append(value))
    preparation.start(selected, 1)
    preparation._model_ready(1, snapshot)
    assert len(results) == 1 and results[0].entries_by_id[2].path == descriptor.path
    assert not service.requests  # Already prepared; no repeated lookup/extraction.


def test_incomplete_character_dependencies_cannot_trigger_an_archive_wide_native_scan(tmp_path):
    worker = CharacterFinderRenderWorker(1, SimpleNamespace(dependencies_complete=False),
        cache_root=tmp_path, fingerprint="fp", settings=ModelPreviewRenderSettings())
    with pytest.raises(ValueError, match="dependencies are incomplete"):
        worker._build_package("fixture")
    assert not list(tmp_path.iterdir())


def test_cancel_after_capture_preserves_existing_metadata(tmp_path):
    selected = detail(row(1))
    worker = CharacterFinderRenderWorker(1, SimpleNamespace(detail=selected), cache_root=tmp_path,
        fingerprint="fp", settings=ModelPreviewRenderSettings())
    worker._build_package = lambda _: (SimpleNamespace(package_dir=tmp_path / "package"), "base_appearance", ())
    target = tmp_path / "image.png"
    metadata = target.with_suffix(".json")
    metadata.write_text("old usable metadata")
    def capture(*_):
        worker.stop()
        return target
    worker._capture = capture
    delivered = []
    worker.completed.connect(lambda *_: delivered.append(True))
    worker.run()
    assert not delivered and metadata.read_text() == "old usable metadata"
    assert not list(tmp_path.rglob("*.tmp"))


@pytest.mark.parametrize("unavailable", [False, True])
def test_finder_passes_authored_shape_to_primary_and_attached_meshes(tmp_path, monkeypatch, unavailable):
    import copy
    import struct
    from cdmw.domain.character_finder import CharacterPreviewInputs
    from tests.test_release_inspired_improvements import _entry
    from tests.test_pabc_neutral_bind_frames import _fixture

    body = _entry("character/model/body_base.pac")
    attached = _entry("character/model/underwear.pac")
    variant = _entry("character/prefab/body_variant.prefabdata_xml")
    base = _entry("character/prefab/body_base.prefabdata_xml")
    component = CharacterCatalogComponent("body", "body_variant", (1, 2), (3, 4), 1.02, {}, "resolved")
    selected = replace(detail(row(1, embedded_face=True)), models=(_dto(1, body.path), _dto(2, attached.path)),
        components=(component,))
    inputs = CharacterPreviewInputs(selected, {1: body, 2: attached, 3: variant, 4: base},
        (body, attached, variant, base), True)
    worker = CharacterFinderRenderWorker(1, inputs, cache_root=tmp_path, fingerprint="fp", settings=ModelPreviewRenderSettings())
    _rig, raw = _fixture()
    changed = copy.deepcopy(raw)
    changed.submeshes[0].vertices[0] = (.2, 1.7, .03)
    changed._cdmw_skeleton_variation_source = "character/variant.pabc"
    calls = []

    def appearance(entry, parsed, data, **kwargs):
        assert kwargs["authored_descriptor"] == variant
        if unavailable:
            raise ValueError("The declared skeleton variation is unavailable")
        return changed, ("Applied authored variant",)

    def native(entry, **kwargs):
        calls.append((entry, kwargs))
        return SimpleNamespace(succeeded=True, package_path=str(tmp_path / "native"))

    monkeypatch.setattr("cdmw.core.archive.read_archive_entry_data", lambda *a, **kw: (b"owned PAC", False, ""))
    monkeypatch.setattr("cdmw.modding.mesh_parser.parse_mesh", lambda *a, **kw: raw)
    monkeypatch.setattr("cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance", appearance)
    monkeypatch.setattr("cdmw.workers.archive_preview_native.native_preview_model_property_indices", lambda *a: ())
    monkeypatch.setattr("cdmw.rendering.native_preview_core.run_native_preview_core_preview_job", native)
    monkeypatch.setattr("cdmw.services.preview_material_status.native_preview_missing_texture_reason", lambda *a: None)
    monkeypatch.setattr("cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package", lambda *a, **kw: "package")
    if unavailable:
        with pytest.raises(ValueError, match="declared skeleton variation"):
            worker._build_package("fixture")
        assert not calls  # No raw-geometry retry advertised as the true appearance.
        return
    package, status, notes = worker._build_package("fixture")
    assert package == "package" and status == "base_appearance" and "Applied authored variant" in notes
    assert len(calls) == 1 and calls[0][0] == body
    kwargs = calls[0][1]
    primary = struct.unpack_from("<6f", kwargs["presentation_geometry_payload"], 24)[:3]
    assert primary == pytest.approx(tuple(v * 1.02 for v in changed.submeshes[0].vertices[0]))
    context = kwargs["preview_context_components"]
    assert len(context) == 1 and context[0].entry == attached and context[0].scale == 1.02
    assert context[0].presentation_geometry_source == changed._cdmw_skeleton_variation_source
    assert struct.unpack_from("<6f", context[0].presentation_geometry_payload, 24)[:3] == pytest.approx(changed.submeshes[0].vertices[0])
