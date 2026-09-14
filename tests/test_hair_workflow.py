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


def test_hair_button_opens_single_setup(owner, monkeypatch):
    from cdmw.ui.mesh_editor import hair_flow
    calls = []
    monkeypatch.setattr(hair_flow, "start_hair_workflow", lambda *args: calls.append(args))
    bar = hair_flow.build_hair_entry_bar(owner)
    from PySide6.QtWidgets import QPushButton
    button = bar.findChild(QPushButton, "MeshEditorHairMenu")
    assert button.text() == "Hair Tools" and button.menu() is None
    button.click()
    assert calls == [(owner,)]


def test_single_setup_requires_character_and_catalogue_and_rejects_stale_choices(owner, monkeypatch):
    from cdmw.ui.mesh_editor import hair_setup_dialog as setup
    from cdmw.ui.mesh_editor import hair_flow
    from tests.test_hair_registration import XML, STEM
    from cdmw.core import archive_extraction
    tasks = []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    hair_flow.build_hair_entry_bar(owner)
    dialog = setup.HairSetupDialog(owner)
    assert dialog.character.currentData() is None
    assert dialog.preset.currentData() == "empty" and dialog.preset.isHidden()
    assert not dialog.waiting_start.isEnabled()
    assert not owner.archive_catalogue_service.calls
    dialog.character.setCurrentIndex(dialog.character.findData("Oongka"))
    request = owner.archive_catalogue_service.calls[-1][1]
    assert "oongka" in request.key
    context = SimpleNamespace(character="Oongka", dependencies=SimpleNamespace(entry_for_path=lambda path: SimpleNamespace(orig_size=len(XML))))
    dialog._context_ready(context)
    assert len(tasks) == 1
    monkeypatch.setattr(archive_extraction, "read_archive_entry_data", lambda entry: (XML, ""))
    # The real utility callable accepts its logger argument.
    choices = tasks[0]["task"](lambda _: None)
    assert choices[0].prefab_stem == STEM
    dialog.character.setCurrentIndex(dialog.character.findData("Kliff"))
    tasks[0]["on_complete"](choices)
    assert dialog._picker is None
    dialog.reject()
    assert dialog._closed
    owner.archive_catalogue_service.current_session = None
    unavailable = setup.HairSetupDialog(owner, character="Damiane")
    assert not unavailable.waiting_start.isEnabled() and "catalogue" in unavailable.status.text()
    unavailable.reject()


def test_reference_geometry_cache_is_bounded_generation_scoped_and_returns_isolated_snapshots(monkeypatch):
    import threading
    from cdmw.workers import mesh_archive_refit_worker as worker
    calls=[]
    def prepare(args, stop):
        calls.append(args)
        return {**args,"_archive_snapshot":SimpleNamespace(original_data=b"owned",mesh=SimpleNamespace(submeshes=[SimpleNamespace(vertices=[[0,0,0]],faces=[])])),
            "_archive_preview_lease":None,"_archive_neutral_appearance":None,"_archive_appearance_warning":"","_archive_material_reason":""}
    monkeypatch.setattr(worker,"_prepare_hair_geometry_source",prepare)
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


@pytest.mark.parametrize("ending", ["ready", "failure", "cancel", "catalogue_change"])
def test_setup_waits_for_prepared_scene_and_disposes_obsolete_results(owner, ending):
    from PySide6.QtWidgets import QDialog
    from cdmw.ui.mesh_editor.hair_setup_dialog import HairSetupDialog
    tasks, accepted, closed = [], [], []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    dialog = HairSetupDialog(owner, character="Damiane")
    dialog.context = SimpleNamespace(character="Damiane", arguments=lambda: {"character":"Damiane"})
    picker = QDialog(dialog)
    picker._closed = True
    picker.selected_entry = SimpleNamespace(identity="chosen")
    picker.selected_dependencies = object()
    dialog._picker = picker
    dialog.accepted.connect(lambda: accepted.append(True))
    dialog._selected(picker, QDialog.Accepted)
    assert not accepted and len(tasks) == 1
    assert not dialog.mode.isEnabled() and not dialog.character.isEnabled()
    prepared = SimpleNamespace(service=SimpleNamespace(close_edit_session=lambda *args, **kwargs: closed.append(args)),
                               view=SimpleNamespace(session_id="isolated"))
    if ending == "failure":
        tasks[0]["on_error"]("Failed reference")
        assert dialog.retry.isEnabled() and "Failed reference" in dialog.status.text()
        assert not accepted
    else:
        if ending == "cancel": dialog.reject()
        if ending == "catalogue_change": dialog._session_changed(None)
        tasks[0]["on_complete"](prepared)
        assert bool(accepted) == (ending == "ready")
        assert bool(closed) == (ending != "ready")
    dialog.reject()


def test_same_generated_style_uses_preset_message_and_no_archive_reopen(owner, monkeypatch):
    from PySide6.QtWidgets import QDialog, QComboBox
    from cdmw.ui.mesh_editor import hair_setup_dialog, hair_flow
    sent, opened = [], []
    target = SimpleNamespace(path="character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0008_01_player.pac", identity="hair")
    state = SimpleNamespace(payload={"template":{"character":"Damiane"}, "groups":[{"mode":"generated"}], "converted":False})
    owner.standalone_rust_authoring_session = SimpleNamespace(shadow_service=SimpleNamespace(_session=lambda _: SimpleNamespace(hair_state=state)), shadow_session_id="current")
    owner._current_target_entry = lambda: target
    owner.shell = SimpleNamespace(_activate_tool_widget=lambda _: None, _prepare_mesh_editor_archive_launch=lambda *args, **kwargs: opened.append(args))
    owner._rust_host_message = lambda event, **kwargs: {"event":event, **kwargs}
    owner._send_rust_message = lambda message: sent.append(message) or True
    hair_flow.build_hair_entry_bar(owner)
    class Setup(QDialog):
        def __init__(self, owner, **kwargs):
            super().__init__(owner)
            self._closed = False
            self.selected_entry, self.prepared_result = target, None
            self.context = SimpleNamespace(character="Damiane")
            self.mode, self.preset = QComboBox(), QComboBox()
            self.mode.addItem("Create", "generated")
            self.preset.addItem("Long", "long")
    monkeypatch.setattr(hair_setup_dialog, "HairSetupDialog", Setup)
    dialog = hair_flow.start_hair_workflow(owner)
    dialog.accept()
    assert not opened and sent == [{"event":"hair_preset", "request_id":0, "extra":{"preset":"long"}}]


def test_context_rejects_stale_preparation_failures_and_reports_catalogue_change(owner):
    resolver=context_module.HairContextPreparation(owner.archive_catalogue_service)
    errors=[];resolver.failed.connect(errors.append)
    resolver.start();old=resolver._token;resolver.start()
    resolver._preparation.failed.emit(old,"stale")
    assert errors==[]
    owner.archive_catalogue_service.session_published.emit(owner.archive_catalogue_service.current_session)
    assert len(errors)==1 and "changed" in errors[0]


def test_picker_selection_owns_preparation_and_can_retry_failure(owner):
    dialog = picker_module.HairReferencePickerDialog(owner, "hair", styles=((0, "first"), (1, "second")))
    QApplication.processEvents()
    first, second = row(1), row(2)
    dialog._details = {item.key: replace(detail(item), models=(SimpleNamespace(entry_id=i),))
                       for i, item in enumerate((first, second))}
    dialog._add(first)
    dialog._add(second)
    dialog.grid.setCurrentRow(0)
    dialog.choose.click()
    first_token = dialog._prepare.started[-1][1]
    dialog.grid.setCurrentRow(1)
    dialog.choose.click()
    second_token = dialog._prepare.started[-1][1]
    before = dialog.status.text()
    dialog._prepare.failed.emit(first_token, "Obsolete failure")
    assert dialog.status.text() == before
    dialog._prepare.failed.emit(second_token, "Try again")
    assert dialog.status.text() == "Try again" and dialog.choose.isEnabled()
    dialog.choose.click()
    retry_token = dialog._prepare.started[-1][1]
    assert len({first_token, second_token, retry_token}) == 3
    dialog._prepare.failed.emit(second_token, "Late retry failure")
    assert dialog.status.text() == "Preparing character materials…"
    dialog._preview.failed.emit(first.key, "Unselected thumbnail failure")
    assert dialog.status.text() == "Preparing character materials…"
    target = SimpleNamespace(path="hair.pac", basename="hair.pac")
    inputs = SimpleNamespace(detail=dialog._details[second.key], dependencies_complete=True,
                             entries=(target,), entries_by_id={1: target})
    dialog._prepare.ready.emit(second_token, inputs)
    assert dialog.selected_entry is None and not dialog._closed
    dialog._prepare.ready.emit(retry_token, inputs)
    assert dialog.selected_entry is target and dialog._closed


def test_unsupported_registered_style_is_disabled_and_next_verified_base_selected(owner):
    from PySide6.QtCore import Qt
    dialog = picker_module.HairReferencePickerDialog(owner, "hair", styles=((0, "first"), (1, "second")), audit_hair=True)
    QApplication.processEvents()
    first, second = row(1), row(2)
    dialog._details = {item.key: replace(detail(item), models=(SimpleNamespace(entry_id=i),))
                       for i, item in enumerate((first, second))}
    dialog._add(first)
    dialog._add(second)
    dialog.grid.setCurrentRow(0)
    dialog._audit_active = first.key
    dialog._audit_done(dialog._generation, None, "This registered hairstyle uses multiple PAC meshes.")
    assert not dialog.grid.item(0).flags() & Qt.ItemIsEnabled
    assert "multiple PAC" in dialog.grid.item(0).toolTip() and not dialog.choose.isEnabled()
    inputs = SimpleNamespace(detail=dialog._details[second.key])
    dialog._audit_active = second.key
    dialog._audit_done(dialog._generation, inputs, "")
    assert dialog._key() == second.key and dialog.choose.isEnabled()
    assert dialog.selected_entry is None  # Choices are checked without starting the editor.
    dialog.reject()


def test_create_checks_one_base_at_a_time_and_waits_for_start_without_thumbnails(owner):
    dialog = picker_module.HairReferencePickerDialog(owner, "hair",
        styles=((0, "first"), (1, "second"), (2, "third")), audit_hair=True, base_only=True)
    ready = []
    dialog.base_ready.connect(lambda: ready.append(True))
    QApplication.processEvents()
    service = owner.archive_catalogue_service
    assert len(service.calls) == 1
    for index, supported in [(0, False), (1, True)]:
        token = service.calls[-1][0]
        item = row(index + 1)
        value = replace(detail(item), models=(SimpleNamespace(entry_id=index),))
        service.result_ready.emit(token, "get_character_catalog_detail", value)
        target = SimpleNamespace(path=f"hair{index}.pac", basename=f"hair{index}.pac")
        inputs = SimpleNamespace(detail=dialog._details[item.key], dependencies_complete=True,
            entries=(target,), entries_by_id={index:target})
        dialog._audit_done(dialog._generation, inputs if supported else None, "" if supported else "Unsupported multi-PAC style")
    assert len(service.calls) == 2 and ready == [True]
    assert dialog._preview.selected == [] and dialog._preview.visible_rows == []
    assert dialog.choose.isEnabled() and dialog.selected_entry is None
    dialog._choose()
    assert dialog.selected_entry is target and dialog._closed


def test_create_dialog_loads_scene_only_after_start_and_mode_change_invalidates_base(owner):
    from cdmw.ui.mesh_editor.hair_setup_dialog import HairSetupDialog
    tasks = []
    owner._run_utility_task_when_idle = lambda **kwargs: tasks.append(kwargs)
    dialog = HairSetupDialog(owner, character="Damiane")
    context = SimpleNamespace(character="Damiane", dependencies=SimpleNamespace(entry_for_path=lambda _: object()))
    dialog._context_ready(context)
    tasks.pop()["on_complete"]([SimpleNamespace(index=0, prefab_stem="first")])
    picker = dialog._picker
    assert picker.isHidden() and dialog.preset.currentData() == "empty"
    started = []
    picker._choose = lambda: started.append(True)
    picker.base_ready.emit()
    assert not started and dialog.waiting_start.isEnabled()
    dialog.waiting_start.click()
    assert started == [True]
    dialog.mode.setCurrentIndex(dialog.mode.findData("existing"))
    picker.base_ready.emit()
    assert dialog._picker is None and not dialog.waiting_start.isEnabled()
    dialog.reject()


def test_clean_context_keeps_eyes_and_excludes_shader_dependent_facial_layers(owner):
    service = owner.archive_catalogue_service
    resolver = context_module.HairContextPreparation(service)
    resolver.start()
    prefix = "character/model/1_pc/2_phw/"
    models = [SimpleNamespace(entry_id=i, extension=".pac", path=prefix + path)
        for i,path in enumerate(("head/head/cd_phw_00_head_00_0111.pac", "nude/cd_phw_00_nude_00_0001_damian.pac", "head/head_sub/eyeleft.pac",
            "head/head_sub/eyeright.pac", "head/head_sub/eyelash.pac", "head/head_sub/eyebrow.pac",
            "head/head_sub/eyecover.pac", "head/head_sub/tooth.pac"))]
    value = replace(detail(row()), models=tuple(models))
    service.result_ready.emit(service.calls[-1][0], "get_character_catalog_detail", value)
    assert resolver._preparation.started[-1][0].models == tuple(models[:4])


def test_reference_geometry_loader_preserves_authored_transform_without_material_or_editor_work(monkeypatch, tmp_path):
    import threading
    from cdmw.models import ArchiveEntry
    from cdmw.workers import mesh_archive_refit_worker as worker
    from cdmw.services import archive_read_service
    from cdmw.modding import mesh_parser, skeleton_parser
    from cdmw.core import skeleton_resolver, archive_mesh_appearance
    entry = ArchiveEntry("head.pac", tmp_path/"0.pamt", tmp_path/"0.paz", 0, 4, 4, 0, 0)
    skeleton_entry = replace(entry, path="head.pab")
    descriptor = SimpleNamespace(identity="mounted-pabc")
    dependencies = SimpleNamespace(entry_matching=lambda _: entry, entries=(), entries_by_normalized_path={}, entries_by_basename={})
    mesh, skeleton, transform = object(), object(), object()
    calls = []
    monkeypatch.setattr(archive_read_service, "read_archive_entry_data", lambda entry, **_: (b"data", "", ""))
    monkeypatch.setattr(mesh_parser, "parse_mesh", lambda *args: mesh)
    monkeypatch.setattr(skeleton_resolver, "resolve_skeleton_for_model", lambda *args, **kwargs: (skeleton_entry, None))
    monkeypatch.setattr(skeleton_parser, "parse_pab", lambda *args: skeleton)
    def appearance(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(_cdmw_neutral_appearance=transform), ()
    monkeypatch.setattr(archive_mesh_appearance, "apply_archive_mesh_appearance", appearance)
    def forbidden(*args, **kwargs): raise AssertionError("Fitting geometry must not open an editor or decode DDS")
    monkeypatch.setattr(worker, "MeshArchiveSessionLoadWorker", forbidden)
    monkeypatch.setattr(worker, "MeshArchiveMaterialContextWorker", forbidden)
    args = {"_archive_entry":entry, "_archive_dependencies":dependencies, "_hair_authored_descriptors":{"head.pac":descriptor}}
    prepared = worker.prepare_hair_reference_source(args, threading.Event())
    assert prepared["_archive_snapshot"].mesh is mesh
    assert prepared["_archive_neutral_appearance"] is transform
    assert calls[0]["authored_descriptor"] is descriptor and calls[0]["skeleton"] is skeleton
    args["_hair_authored_descriptors"]["head.pac"] = None
    prepared = worker.prepare_hair_reference_source(args, threading.Event())
    assert prepared["_archive_neutral_appearance"] is None and len(calls) == 1


@pytest.mark.parametrize("ending", ["replace", "cancel", "resume", "invalid"])
def test_queued_prepared_hair_scene_has_one_owner_and_releases_obsolete_result(tmp_path, ending, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin
    from cdmw.ui.mesh_editor import tab_session_runtime
    monkeypatch.setattr(tab_session_runtime, "_tab", SimpleNamespace(ArchiveEntry=ArchiveEntry))
    disposed, opened = [], []
    class Queue(MeshEditorSessionMixin):
        _discard_archive_session_result = staticmethod(disposed.append)
        def open_archive_session(self, entry, **kwargs): opened.append(kwargs["prepared_result"])
    queue = Queue()
    entry = ArchiveEntry("hair.pac", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 4, 4, 0, 0)
    prepared, replacement = object(), object()
    kwargs = dict(resume_manifest_path=None, material_preview_model=None, material_companion_entry=None,
        material_package_path=None, material_package_lease=None, material_context_verified_for_rust=False,
        material_source_identity=None, archive_dependencies=None)
    queue._queue_archive_session_open(entry, prepared_result=prepared, **kwargs)
    if ending == "replace":
        queue._queue_archive_session_open(entry, prepared_result=replacement, **kwargs)
        assert disposed == [prepared]
        queue._resume_queued_archive_session_open()
        assert opened == [replacement]
    elif ending == "cancel":
        queue._discard_queued_archive_session_open()
        queue._discard_queued_archive_session_open()
        assert disposed == [prepared] and not opened
    else:
        if ending == "invalid": queue.archive_session_open_pending["entry"] = None
        queue._resume_queued_archive_session_open()
        assert disposed == ([prepared] if ending == "invalid" else [])
        assert opened == ([] if ending == "invalid" else [prepared])
    assert queue.archive_session_open_pending is None


@pytest.mark.parametrize("failure", ["cancel_after_load", "cancel_after_copy", "copy_failure", "cancel_cached_copy"])
def test_reference_cache_cancellation_releases_unpublished_assets(monkeypatch, failure):
    import threading
    from cdmw.workers import mesh_archive_refit_worker as worker

    stop = threading.Event()
    released = []
    lease = SimpleNamespace(lease=SimpleNamespace(release=lambda: released.append(True)))
    def prepare(args, _stop):
        if failure == "cancel_after_load": stop.set()
        return {**args, "_archive_snapshot": SimpleNamespace(original_data=b"owned", mesh=SimpleNamespace(submeshes=[])),
                "_archive_preview_lease": lease, "_archive_neutral_appearance": None,
                "_archive_appearance_warning": "", "_archive_material_reason": ""}
    monkeypatch.setattr(worker, "_prepare_hair_geometry_source", prepare)
    monkeypatch.setattr(worker, "_hair_references", worker.OrderedDict())
    args = {"_archive_entry": SimpleNamespace(identity="head"), "_hair_context_identity": ("session", "generation")}
    if failure == "cancel_cached_copy":
        worker.prepare_hair_reference_source(args, stop)
    original = worker.copy.deepcopy
    def interrupted(value, *args, **kwargs):
        if failure == "copy_failure": raise ValueError("Copy failed")
        if failure in {"cancel_after_copy", "cancel_cached_copy"}: stop.set()
        return original(value, *args, **kwargs)
    monkeypatch.setattr(worker.copy, "deepcopy", interrupted)
    with pytest.raises((RuntimeError, ValueError)):
        worker.prepare_hair_reference_source(args, stop)
    assert released == ([] if failure == "cancel_cached_copy" else [True])
    assert len(worker._hair_references) == (1 if failure == "cancel_cached_copy" else 0)
