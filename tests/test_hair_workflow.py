"""Real Qt construction and resident request lifecycle for the Hair workflow."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.character_catalogue import CharacterCatalogSearchResult
from cdmw.ui.mesh_editor import hair_context_preparation as context_module
from cdmw.ui.mesh_editor import hair_reference_picker as picker_module
from tests.test_character_finder_dialog import Service, Preview, Host, row, detail

_APP = None


class Preparation(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)

    def __init__(self, _service, parent=None):
        super().__init__(parent)
        self.started = []
        self.cancelled = 0

    def start(self, value, token): self.started.append((value, token))
    def cancel(self): self.cancelled += 1


@pytest.fixture
def owner(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(context_module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(picker_module, "CharacterPreviewPreparation", Preparation)
    monkeypatch.setattr(picker_module, "CharacterFinderPreviewController", Preview)
    monkeypatch.setattr(picker_module, "RustPreviewHostFrame", Host)
    window = QWidget()
    window.archive = window
    window.archive_catalogue_service = Service()
    window.archive_catalogue_service.current_session = ArchiveSessionHandle("session-a", "C:/game", "fp", 10, 3, True)
    window._native_preview_package_cache_root = lambda: tmp_path
    window._current_model_preview_render_settings = lambda: None
    yield window
    for picker in list(getattr(window, "_hair_reference_dialogs", ())):
        picker.reject()
        picker._release()
    window.deleteLater()
    _APP.processEvents()


@pytest.mark.parametrize("role", ["head", "body"])
def test_reference_picker_requests_eligibility_before_pagination_and_defends_selection(owner, role):
    dialog = picker_module.HairReferencePickerDialog(owner, role)
    QApplication.processEvents()
    service = owner.archive_catalogue_service
    token, request, _ = service.calls[-1]
    assert request.selection_purpose == "hair_" + role
    assert request.body_family == "2_phw" and request.role is None
    path = ("character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac" if role == "head"
            else "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac")
    good = row(1, role=role if role == "head" else "whole_character", path=path, body_family="2_phw")
    bad = [replace(good, key="armor", path="character/model/1_pc/2_phw/armor/cd_phw_00_ub.pac"),
           replace(good, key="other-family", body_family="1_phm"), replace(good, key="ambiguous", model_count=2)]
    service.result_ready.emit(token, "search_character_catalog", CharacterCatalogSearchResult("session-a", 100, 0, 72, (good, *bad), (), ()))
    assert dialog.grid.count() == 1
    assert dialog._rows == {good.key: good}
    dialog._page(1)
    assert service.calls[-1][1].page_start == 72
    dialog.search.setText("matching")
    dialog._timer.stop()
    dialog._search()
    assert service.calls[-1][1].page_start == 0
    dialog.reject()
    service.result_ready.emit(token, "search_character_catalog", CharacterCatalogSearchResult("session-a", 1, 0, 72, (good,), (), ()))
    assert dialog._closed


def test_automatic_context_selects_matching_roles_cancels_stale_work_and_reuses_generation(owner):
    service = owner.archive_catalogue_service
    resolver = context_module.HairContextPreparation(service)
    emitted, errors = [], []
    resolver.ready.connect(emitted.append)
    resolver.failed.connect(errors.append)
    resolver.start()
    old_request = service.calls[-1][0]
    resolver.start()
    request = service.calls[-1][0]
    assert old_request in service.cancelled
    head = SimpleNamespace(entry_id=1, extension=".pac", path="character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac", basename="head.pac")
    body = SimpleNamespace(entry_id=2, extension=".pac", path="character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001_damian.pac", basename="body.pac")
    fuzz = SimpleNamespace(entry_id=3, extension=".pac", path="character/model/1_pc/2_phw/nude/cd_phw_00_fuzz.pac", basename="fuzz.pac")
    value = replace(detail(row()), models=(head, body, fuzz), appearance_path=context_module.DAMIANE_APPEARANCE)
    service.result_ready.emit(old_request, "get_character_catalog_detail", value)
    assert not resolver._preparation.started
    service.result_ready.emit(request, "get_character_catalog_detail", value)
    prepared, token = resolver._preparation.started[-1]
    assert prepared.models == (head, body)
    inputs = SimpleNamespace(detail=value, dependencies_complete=True, entries=(head, body), entries_by_id={1: head, 2: body})
    resolver._preparation.ready.emit(token, inputs)
    assert not errors and emitted[-1].head is head and emitted[-1].body is body
    count = len(service.calls)
    resolver.start()
    assert len(service.calls) == count and emitted[-1] is emitted[0]
    service.session_published.emit(service.current_session)
    resolver.start()
    assert len(service.calls) == count + 1


def test_hair_menu_exposes_presets_and_registered_style_entry(owner, monkeypatch):
    from cdmw.ui.mesh_editor import hair_flow
    calls = []
    monkeypatch.setattr(hair_flow, "start_hair_workflow", lambda *args: calls.append(args))
    bar = hair_flow.build_hair_entry_bar(owner)
    from PySide6.QtWidgets import QToolButton
    button = bar.findChild(QToolButton, "MeshEditorHairMenu")
    create, edit = button.menu().actions()
    assert [a.text() for a in create.menu().actions()] == ["Cropped", "Bob", "Long", "Ponytail", "Empty"]
    create.menu().actions()[1].trigger()
    edit.trigger()
    assert calls == [(owner, "generated", "bob"), (owner, "existing")]


def test_reference_geometry_cache_is_bounded_generation_scoped_and_returns_isolated_snapshots(monkeypatch):
    import threading
    from cdmw.workers import mesh_archive_refit_worker as worker
    calls=[]
    def prepare(args, stop):
        calls.append(args)
        return {**args,"_archive_snapshot":SimpleNamespace(original_data=b"owned",mesh=SimpleNamespace(submeshes=[SimpleNamespace(vertices=[[0,0,0]],faces=[])])),
            "_archive_preview_lease":None,"_archive_neutral_appearance":None,"_archive_appearance_warning":"","_archive_material_reason":""}
    monkeypatch.setattr(worker,"prepare_archive_refit_source",prepare)
    monkeypatch.setattr(worker,"_hair_references",worker.OrderedDict())
    args={"_archive_entry":SimpleNamespace(identity="head"),"_hair_context_identity":("session","generation1")}
    first=worker.prepare_hair_reference_source(args,threading.Event())
    first["_archive_snapshot"].mesh.submeshes[0].vertices[0][0]=99
    second=worker.prepare_hair_reference_source(args,threading.Event())
    assert len(calls)==1 and second["_archive_snapshot"].mesh.submeshes[0].vertices==[[0,0,0]]
    for index in range(6):worker.prepare_hair_reference_source({**args,"_archive_entry":SimpleNamespace(identity=str(index))},threading.Event())
    assert len(worker._hair_references)==4
    worker.prepare_hair_reference_source({**args,"_hair_context_identity":("session","generation2")},threading.Event())
    assert len(worker._hair_references)==1
    stop=threading.Event();stop.set()
    with pytest.raises(RuntimeError):worker.prepare_hair_reference_source(args,stop)


def test_context_rejects_stale_preparation_failures_and_reports_catalogue_change(owner):
    resolver=context_module.HairContextPreparation(owner.archive_catalogue_service)
    errors=[];resolver.failed.connect(errors.append)
    resolver.start();old=resolver._token;resolver.start()
    resolver._preparation.failed.emit(old,"stale")
    assert errors==[]
    owner.archive_catalogue_service.session_published.emit(owner.archive_catalogue_service.current_session)
    assert len(errors)==1 and "changed" in errors[0]
