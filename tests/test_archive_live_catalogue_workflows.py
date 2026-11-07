"""Archive Browser workflows that must work from the live catalogue alone.

The standalone catalogue shows results without filling the legacy ``archive_entries``
list or its path indexes. Every case here keeps those legacy collections empty, the
state that GitHub issues 26 to 29 were reported from.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveLookupKind,
    ArchiveLookupResult,
)
from cdmw.domain.archives.character_catalogue import CharacterCatalogScopeResult
from cdmw.domain.archives.filters import archive_entry_identity_key
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, AssetFamilyGraph
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
from cdmw.ui.archive_browser import source_mix_overlay
from cdmw.ui.archive_browser.asset_catalog_scope import ArchiveAssetCatalogScopeMixin
from cdmw.ui.archive_browser.asset_family_dialog import ArchiveAssetFamilyDialogMixin
from cdmw.ui.archive_browser.asset_family_panel import ArchiveAssetFamilyPanelMixin
from cdmw.ui.archive_browser.character_dependency_export import (
    ArchiveCharacterDependencyExportMixin,
)
from cdmw.ui.archive_browser.character_dependency_live import (
    ANIMATION_SCOPE_WARNING,
    CHARACTER_KEY_MISSING_TEXT,
    character_catalogue_asset_key,
    plan_character_dependencies_round,
)
from cdmw.ui.archive_browser.mesh_dds_preview import ArchiveMeshDdsPreviewMixin
from cdmw.ui.archive_browser.mesh_direct_patch import ArchiveMeshDirectPatchMixin
from cdmw.ui.archive_browser.mesh_swap_support import ArchiveMeshSwapSupportMixin
from cdmw.ui.archive_browser.remote_entry_lookup import (
    LiveCatalogueState,
    compatibility_entries,
    entry_indexes,
    live_catalogue_state,
    lookup_requests,
)
from cdmw.ui.archive_browser.source_mix_overlay import ArchiveSourceMixOverlayMixin
from cdmw.ui.archive_browser.virtual_path_lookup import ArchiveVirtualPathLookupMixin
from cdmw.ui.archive_browser.workflow_dependencies import (
    ArchiveWorkflowDependenciesUnavailable,
)
from cdmw.ui.texture_workflow.editor_bridge import TextureWorkflowEditorBridgeMixin
from cdmw.workers.source_mix_workers import (
    SourceMixIndexSnapshot,
    SourceMixScanRequest,
    SourceMixTargetResolveRequest,
    run_source_mix_scan,
    run_source_mix_target_resolution,
)

SESSION = "session-live"


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _dto(entry_id: int, path: str, *, pamt: str = "C:/Game/0009/0.pamt", offset: int | None = None,
         active: bool = False) -> ArchiveEntryDto:
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    archive_offset = entry_id * 100 if offset is None else offset
    return ArchiveEntryDto(
        session_id=SESSION,
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(path.casefold(), pamt, 0, archive_offset),
        path=path,
        source_pamt=pamt,
        paz_file=pamt.replace(".pamt", ".paz"),
        paz_index=0,
        offset=archive_offset,
        stored_size=64,
        original_size=64,
        flags=0,
        extension=extension,
        package=pamt.replace("\\", "/").split("/")[-2],
        role=ArchiveEntryRole.MODEL,
        category="ModelMeshPhysics",
        is_previewable=True,
        is_active_override=active,
    )


class _LookupService(QObject):
    """Answers resolve_entries from a fixed catalogue, one batch per request."""

    batch_ready = Signal(str, str, object)
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)

    def __init__(self, catalogue: list[ArchiveEntryDto]) -> None:
        super().__init__()
        self.catalogue = list(catalogue)
        self.requests: list[object] = []
        self.scope_requests: list[object] = []
        self.scope_reply: object = None
        self.character_catalog_available = True
        self.compatibility_entry = ArchiveCatalogueService.compatibility_entry

    def _matches(self, request) -> list[ArchiveEntryDto]:
        if request.kind is ArchiveLookupKind.ENTRY_IDS:
            wanted = set(request.entry_ids)
            return [dto for dto in self.catalogue if dto.entry_id in wanted]
        values = {value.casefold() for value in request.values}
        if request.kind is ArchiveLookupKind.EXACT_PATHS:
            return [dto for dto in self.catalogue if dto.path.casefold().strip("/") in values]
        if request.kind is ArchiveLookupKind.BASENAMES:
            return [dto for dto in self.catalogue if dto.path.rsplit("/", 1)[-1].casefold() in values]
        return []

    def resolve_entries(self, request, *, ui_generation: int) -> str:
        self.requests.append(request)
        request_id = f"lookup-{len(self.requests)}"
        matches = self._matches(request)
        payload = ArchiveLookupResult(SESSION, tuple(matches), len(matches), False)

        def deliver() -> None:
            self.batch_ready.emit(request_id, "resolve_entries", payload)
            self.result_ready.emit(request_id, "resolve_entries", ArchiveLookupResult(SESSION, (), len(matches), False))

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, deliver)
        return request_id

    def scope_character_catalog(self, request, *, ui_generation: int) -> str:
        self.scope_requests.append(request)
        request_id = f"scope-{len(self.scope_requests)}"
        reply = self.scope_reply

        def deliver() -> None:
            if isinstance(reply, str):
                self.request_failed.emit(request_id, SimpleNamespace(message=reply))
            else:
                self.result_ready.emit(request_id, "scope_character_catalog", reply)

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, deliver)
        return request_id

    def cancel(self, _request_id: str) -> bool:
        return True


def _drain() -> None:
    app = _app()
    for _ in range(20):
        app.processEvents()


class _Bridge:
    def __init__(self, current: ArchiveEntryDto | None = None) -> None:
        self.current_session = SimpleNamespace(session_id=SESSION)
        self.displays_v2 = True
        self.controller = SimpleNamespace(generation=3)
        self.scopes: list[tuple[tuple[int, ...], str]] = []
        self._current = current
        self.model = SimpleNamespace(entry_for_index=lambda _index: self._current)

    def apply_entry_id_scope(self, entry_ids, *, label: str, preferred_prefab_stems=()) -> bool:
        self.scopes.append((tuple(entry_ids), label))
        return True


class _Shell:
    archive_browser_tab = object()

    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.logs: list[str] = []

    def set_status_message(self, message: str, error: bool = False) -> None:
        self.messages.append((str(message), bool(error)))

    def append_archive_log(self, message: str, verbose: bool = False) -> None:
        self.logs.append(str(message))

    append_log = append_archive_log

    def _activate_tool_widget(self, _widget) -> None:
        return None

    def _run_utility_task(self, *, task, on_complete, **_kwargs) -> None:
        on_complete(task(lambda _message: None, None))


class _LiveOwner(QObject):
    def __init__(self, catalogue: list[ArchiveEntryDto], current: ArchiveEntryDto | None = None) -> None:
        super().__init__()
        _app()
        self.archive = self
        self.textures = self
        self.shell = _Shell()
        self.archive_entries: list[ArchiveEntry] = []
        self.archive_entries_by_normalized_path: dict = {}
        self.archive_entries_by_basename: dict = {}
        self.archive_catalogue_service = _LookupService(catalogue)
        self.archive_remote_bridge = _Bridge(current)
        self.archive_remote_query_pending = False


# ------------------------------------------------------------------ catalogue state


def test_state_distinguishes_ready_loading_and_missing_catalogue() -> None:
    owner = _LiveOwner([])
    assert live_catalogue_state(owner) == LiveCatalogueState.READY
    owner.archive_remote_bridge.current_session = None
    owner.archive_remote_query_pending = True
    assert live_catalogue_state(owner) == LiveCatalogueState.LOADING
    owner.archive_remote_query_pending = False
    assert live_catalogue_state(owner) == LiveCatalogueState.UNAVAILABLE


def test_lookup_requests_stay_inside_the_worker_bound() -> None:
    requests = lookup_requests(SESSION, ArchiveLookupKind.EXACT_PATHS, (f"a/{n}.pac" for n in range(600)))
    assert [len(request.values) for request in requests] == [256, 256, 88]
    assert all(request.limit == 4096 for request in requests)


# ------------------------------------------------------------------ issue 26: loose import


def _loose_folder(root: Path) -> Path:
    folder = root / "mod"
    (folder / "character" / "model").mkdir(parents=True)
    (folder / "character" / "model" / "phm_00_nude_00_0001.pac").write_bytes(b"PAC edited")
    (folder / "flat_only.pac").write_bytes(b"PAC flattened")
    (folder / "twice.pac").write_bytes(b"PAC ambiguous")
    (folder / "phm_00_nude_00_0001.fbx").write_bytes(b"FBX scene")
    return folder


def _catalogue_for_loose() -> list[ArchiveEntryDto]:
    return [
        _dto(1, "character/model/phm_00_nude_00_0001.pac"),
        _dto(2, "character/other/flat_only.pac"),
        _dto(3, "character/a/twice.pac"),
        _dto(4, "character/b/twice.pac"),
    ]


def test_loose_scan_matches_targets_from_live_lookups(tmp_path: Path) -> None:
    owner = _LiveOwner(_catalogue_for_loose())
    folder = _loose_folder(tmp_path)
    scanned = run_source_mix_scan(SourceMixScanRequest(source_path=folder, source_kind="loose"))
    paths, basenames = source_mix_overlay._live_lookup_values(scanned.candidates)
    service = owner.archive_catalogue_service
    found = []
    for request in (
        *lookup_requests(SESSION, ArchiveLookupKind.EXACT_PATHS, paths),
        *lookup_requests(SESSION, ArchiveLookupKind.BASENAMES, basenames),
    ):
        found.extend(service._matches(request))
    path_index, basename_index = entry_indexes(compatibility_entries(owner, found))
    resolved = run_source_mix_target_resolution(
        SourceMixTargetResolveRequest(folder, scanned.candidates, SourceMixIndexSnapshot.capture(path_index, basename_index))
    ).candidates
    by_name = {Path(candidate.display_path).name: candidate for candidate in resolved}
    exact = by_name["phm_00_nude_00_0001.pac"]
    assert (exact.match_status, exact.default_action) == ("exact", "replace")
    assert exact.target_archive_entry.path == "character/model/phm_00_nude_00_0001.pac"
    assert by_name["flat_only.pac"].match_status == "basename"
    assert by_name["twice.pac"].target_archive_entry is None, "an ambiguous filename is never guessed"
    assert by_name["phm_00_nude_00_0001.fbx"].target_archive_entry is None, "FBX is not converted to a PAC target"


def test_loose_import_route_resolves_targets_with_empty_legacy_indexes(tmp_path: Path) -> None:
    class _Owner(ArchiveSourceMixOverlayMixin, _LiveOwner):
        pass

    owner = _Owner(_catalogue_for_loose())
    folder = _loose_folder(tmp_path)
    scanned = run_source_mix_scan(SourceMixScanRequest(source_path=folder, source_kind="loose"))
    reviewed = []

    class _Controller:
        def start(self, request, operation, *, on_complete, on_error, **_kwargs):
            on_complete(operation(request))
            return True

    with patch.object(source_mix_overlay, "source_mix_task_controller_for_guard", lambda *a, **k: _Controller()), \
            patch.object(_Owner, "_open_archive_loose_mod_overlay_dialog", lambda self, **kwargs: reviewed.append(kwargs)):
        owner._resolve_loose_mod_targets_from_live_catalogue(scanned, str(folder))
        _drain()
    assert reviewed, "the review dialog opens once targets are matched"
    candidates = reviewed[0]["_scan_result"].candidates
    targets = {Path(c.display_path).name: c.target_archive_entry for c in candidates}
    assert targets["phm_00_nude_00_0001.pac"] is not None
    assert {request.kind for request in owner.archive_catalogue_service.requests} == {
        ArchiveLookupKind.EXACT_PATHS,
        ArchiveLookupKind.BASENAMES,
    }


class _CappedLookupService(_LookupService):
    """Cuts each answer at ``cap`` entries, lowest ids first, like the worker's request limit."""

    def __init__(self, catalogue: list[ArchiveEntryDto], cap: int) -> None:
        super().__init__(catalogue)
        self.cap = int(cap)

    def resolve_entries(self, request, *, ui_generation: int) -> str:
        self.requests.append(request)
        request_id = f"lookup-{len(self.requests)}"
        matches = sorted(self._matches(request), key=lambda dto: dto.entry_id)
        payload = ArchiveLookupResult(SESSION, tuple(matches[: self.cap]), len(matches), len(matches) > self.cap)

        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self.result_ready.emit(request_id, "resolve_entries", payload))
        return request_id


def _resolve_loose_with_service(tmp_path: Path, service: _LookupService) -> dict:
    class _Owner(ArchiveSourceMixOverlayMixin, _LiveOwner):
        pass

    owner = _Owner([])
    owner.archive_catalogue_service = service
    folder = tmp_path / "mod"
    (folder / "character" / "model").mkdir(parents=True)
    (folder / "character" / "model" / "phm_00_nude_00_0001.pac").write_bytes(b"PAC edited")
    (folder / "flat_only.pac").write_bytes(b"PAC flattened")
    (folder / "solo.pac").write_bytes(b"PAC name with two archive copies")
    scanned = run_source_mix_scan(SourceMixScanRequest(source_path=folder, source_kind="loose"))
    reviewed = []

    class _Controller:
        def start(self, request, operation, *, on_complete, on_error, **_kwargs):
            on_complete(operation(request))
            return True

    with patch.object(source_mix_overlay, "source_mix_task_controller_for_guard", lambda *a, **k: _Controller()), \
            patch.object(_Owner, "_open_archive_loose_mod_overlay_dialog", lambda self, **kwargs: reviewed.append(kwargs)):
        owner._resolve_loose_mod_targets_from_live_catalogue(scanned, str(folder))
        _drain()
    assert reviewed, "the review dialog opens once targets are matched"
    return {
        Path(candidate.display_path).name: candidate
        for candidate in reviewed[0]["_scan_result"].candidates
    } | {"__owner__": owner}


def _two_copy_catalogue() -> list[ArchiveEntryDto]:
    return [
        _dto(1, "character/model/phm_00_nude_00_0001.pac"),
        _dto(2, "character/other/flat_only.pac"),
        _dto(6, "character/a/solo.pac"),
        _dto(7, "character/b/solo.pac"),
    ]


def test_a_cut_answer_never_makes_one_copy_look_unique(tmp_path: Path) -> None:
    # Cap 3 keeps ids 1, 2 and 6 of the combined filename answer: one solo.pac survives.
    service = _CappedLookupService(_two_copy_catalogue(), cap=3)
    by_name = _resolve_loose_with_service(tmp_path, service)
    by_name.pop("__owner__")
    retried = [request for request in service.requests if request.kind is ArchiveLookupKind.BASENAMES and len(request.values) == 1]
    assert {request.values[0] for request in retried} >= {"flat_only.pac", "solo.pac"}
    solo = by_name["solo.pac"]
    assert solo.target_archive_entry is None, "asked alone, solo.pac has two archive copies"
    assert "multiple archive targets" in solo.confidence
    assert by_name["flat_only.pac"].match_status == "basename"
    assert by_name["phm_00_nude_00_0001.pac"].match_status == "exact"


def test_a_filename_still_cut_when_asked_alone_matches_only_by_path(tmp_path: Path) -> None:
    service = _CappedLookupService(_two_copy_catalogue(), cap=1)
    by_name = _resolve_loose_with_service(tmp_path, service)
    owner = by_name.pop("__owner__")
    assert by_name["phm_00_nude_00_0001.pac"].match_status == "exact"
    assert by_name["flat_only.pac"].match_status == "basename", "a filename whose own answer is complete still matches"
    solo = by_name["solo.pac"]
    assert solo.target_archive_entry is None, "the one surviving copy of a cut answer is never treated as unique"
    assert solo.default_action == "skip"
    assert any("instead of being guessed" in line for line in owner.shell.logs)


def test_complete_filename_answers_need_no_second_lookup(tmp_path: Path) -> None:
    catalogue = [
        _dto(1, "character/model/phm_00_nude_00_0001.pac"),
        _dto(2, "character/other/flat_only.pac"),
        _dto(6, "character/a/solo.pac"),
    ]
    service = _CappedLookupService(catalogue, cap=4096)
    by_name = _resolve_loose_with_service(tmp_path, service)
    by_name.pop("__owner__")
    assert len(service.requests) == 2
    assert by_name["solo.pac"].match_status == "basename"


def test_review_explains_where_fbx_and_other_models_go(tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel, QWidget

    _app()

    class _WidgetOwner(ArchiveSourceMixOverlayMixin, QWidget):
        pass

    owner = _WidgetOwner()
    owner.shell = _Shell()
    folder = _loose_folder(tmp_path)
    scanned = run_source_mix_scan(SourceMixScanRequest(source_path=folder, source_kind="loose"))
    hints = []

    def _capture(dialog) -> int:
        label = dialog.findChild(QLabel, "layout_cdmw_ui_archive_browser_source_mix_overlay_scene_model_hint")
        hints.append(label.text() if label is not None else None)
        return 0

    with patch.object(source_mix_overlay.QDialog, "exec", _capture):
        owner._open_archive_loose_mod_overlay_dialog(_scan_result=scanned, _selected_dir=str(folder))
        (folder / "phm_00_nude_00_0001.fbx").unlink()
        without_fbx = run_source_mix_scan(SourceMixScanRequest(source_path=folder, source_kind="loose"))
        owner._open_archive_loose_mod_overlay_dialog(_scan_result=without_fbx, _selected_dir=str(folder))
    assert hints[0] is not None and "Import Replacement" in hints[0]
    assert hints[1] is None, "the hint appears only when the folder holds such a model"


def test_loose_import_reports_loading_and_unloaded_catalogue_separately() -> None:
    owner = _LiveOwner([])
    assert source_mix_overlay._source_mix_index_snapshot(owner) == source_mix_overlay.LIVE_CATALOGUE_TARGETS
    owner.archive_remote_bridge.current_session = None
    shown = []
    with patch.object(source_mix_overlay.QMessageBox, "information", lambda _parent, _title, text: shown.append(text)):
        owner.archive_remote_query_pending = True
        assert source_mix_overlay._source_mix_index_snapshot(owner) is None
        owner.archive_remote_query_pending = False
        assert source_mix_overlay._source_mix_index_snapshot(owner) is None
    assert "still loading" in shown[0]
    assert "not loaded yet" in shown[1]


# ------------------------------------------------------------------ issue 26: Show Target In Archive


class _RevealOwner(ArchiveVirtualPathLookupMixin, TextureWorkflowEditorBridgeMixin, _LiveOwner):
    pass


def test_show_target_reveals_the_exact_identity_through_the_live_catalogue() -> None:
    catalogue = [
        _dto(10, "character/model/body.pac", pamt="C:/Game/0009/0.pamt", offset=400),
        _dto(11, "character/model/body.pac", pamt="C:/Game/0036/0.pamt", offset=900, active=True),
    ]
    owner = _RevealOwner(catalogue)
    target = ArchiveCatalogueService.compatibility_entry(catalogue[0])
    owner._show_archive_browser_from_texture_editor(target.path, target)
    _drain()
    assert owner.archive_remote_bridge.scopes == [((10,), "body.pac (target)")], (
        "the copy the editor opened, not the active override with the same path"
    )
    assert not any("not loaded" in message for message, _error in owner.shell.messages)


def test_show_target_waits_for_a_loading_catalogue() -> None:
    owner = _RevealOwner([])
    owner.archive_remote_bridge.current_session = None
    owner.archive_remote_query_pending = True
    shown = []
    from cdmw.ui.texture_workflow import editor_bridge

    with patch.object(editor_bridge.QMessageBox, "information", lambda _parent, _title, text: shown.append(text)):
        owner._show_archive_browser_from_texture_editor("character/model/body.pac")
    assert shown and "still loading" in shown[0]
    assert owner.archive_remote_bridge.scopes == []


# ------------------------------------------------------------------ issue 28: scopes


class _ScopeOwner(ArchiveAssetCatalogScopeMixin, _LiveOwner):
    def __init__(self, catalogue, current=None) -> None:
        super().__init__(catalogue, current)
        self.archive_tree = SimpleNamespace(currentIndex=lambda: None)
        self.archive_package_filter_hint_label = SimpleNamespace(text="", setText=lambda text: setattr(self, "hint", text))
        self.archive_filtered_entries = ["unchanged"]


def test_show_only_this_file_scopes_the_live_catalogue() -> None:
    current = _dto(21, "character/model/armor.pac")
    owner = _ScopeOwner([current, _dto(22, "character/model/other.pac")], current)
    entry = ArchiveCatalogueService.compatibility_entry(current)
    assert owner._apply_archive_direct_scope(
        [entry], scope_label="armor.pac only", placeholder_text="", hint_text="Single-file scope active.",
        progress_text="", log_text="scoped",
    )
    assert owner.archive_remote_bridge.scopes == [((21,), "armor.pac only")]
    assert owner.archive_filtered_entries == ["unchanged"], "the legacy list is not the live view"
    assert owner.hint.startswith("Single-file scope active.")


def test_family_scope_matches_full_identity_and_reports_missing_members() -> None:
    catalogue = [
        _dto(31, "character/model/armor.pac"),
        _dto(32, "character/texture/armor.dds"),
        _dto(33, "character/texture/armor.dds", pamt="C:/Game/0036/0.pamt", offset=77),
    ]
    owner = _ScopeOwner(catalogue)
    members = [
        ArchiveCatalogueService.compatibility_entry(catalogue[0]),
        ArchiveCatalogueService.compatibility_entry(catalogue[2]),
        ArchiveEntry("character/texture/gone.dds", Path("C:/Game/0009/0.pamt"), Path("C:/Game/0009/0.paz"), 5, 1, 1, 0, 0),
    ]
    owner._apply_archive_direct_scope(
        members, scope_label="Asset family for armor.pac", placeholder_text="", hint_text="Family.",
        progress_text="", log_text="family",
    )
    _drain()
    assert owner.archive_remote_bridge.scopes == [((31, 33), "Asset family for armor.pac")], (
        "the overlapping path from the other package is not included"
    )
    assert "1 file(s) could not be matched" in owner.hint


def test_scope_that_matches_nothing_does_not_claim_a_scope() -> None:
    owner = _ScopeOwner([])
    missing = ArchiveEntry("character/model/none.pac", Path("C:/Game/0009/0.pamt"), Path("C:/Game/0009/0.paz"), 1, 1, 1, 0, 0)
    owner._apply_archive_direct_scope(
        [missing], scope_label="none", placeholder_text="", hint_text="", progress_text="", log_text="",
    )
    _drain()
    assert owner.archive_remote_bridge.scopes == []
    assert owner.shell.messages[-1][1] is True


# ------------------------------------------------------------------ issue 27: character export


def _payload_entries(root: Path, payloads: list[tuple[str, bytes]]) -> list[ArchiveEntry]:
    package = root / "0009"
    package.mkdir(parents=True, exist_ok=True)
    paz = package / "0.paz"
    entries, offset = [], 0
    with paz.open("wb") as handle:
        for path, data in payloads:
            handle.write(data)
            entries.append(ArchiveEntry(path, package / "0.pamt", paz, offset, len(data), len(data), 0, 0))
            offset += len(data)
    (package / "0.pamt").write_bytes(b"")
    return entries


def test_planner_rounds_record_what_the_bounded_set_is_missing(tmp_path: Path) -> None:
    body, app, custom = _payload_entries(tmp_path, [
        ("character/model/body_a.pac", b"PAC"),
        ("character/appearance/hero.app_xml", b'<App><Body Name="body_a.pac" CustomizationFile="hero_custom.xml"/></App>'),
        ("character/customization/hero_custom.xml", b"<Custom/>"),
    ])
    first = plan_character_dependencies_round(body, (body, app))
    assert not first.plan.blocking_errors
    assert "hero_custom.xml" in first.missing_basenames
    second = plan_character_dependencies_round(body, (body, app, custom))
    assert any(entry.path == custom.path for entry in second.plan.entries)


class _CharacterOwner(ArchiveCharacterDependencyExportMixin, _LiveOwner):
    def __init__(self, catalogue) -> None:
        super().__init__(catalogue)
        self.exports: list[tuple[object, dict]] = []

    def _run_character_dependency_package_export(self, entry, plan, **kwargs) -> None:
        self.exports.append((plan, kwargs))


def test_character_export_runs_from_the_live_catalogue(tmp_path: Path) -> None:
    body, app, custom = _payload_entries(tmp_path, [
        ("character/model/body_a.pac", b"PAC"),
        ("character/appearance/hero.app_xml", b'<App><Body Name="body_a.pac" CustomizationFile="hero_custom.xml"/></App>'),
        ("character/customization/hero_custom.xml", b"<Custom/>"),
    ])
    dtos = []
    for entry_id, entry in enumerate((body, app, custom), start=1):
        dto = _dto(entry_id, entry.path, pamt=str(entry.pamt_path).replace("\\", "/"), offset=entry.offset)
        dtos.append(ArchiveEntryDto(**{**{slot: getattr(dto, slot) for slot in dto.__slots__},
                                       "paz_file": str(entry.paz_file), "stored_size": entry.comp_size,
                                       "original_size": entry.orig_size}))
    owner = _CharacterOwner(dtos)
    owner.archive_catalogue_service.scope_reply = CharacterCatalogScopeResult(SESSION, (1, 2), 1, 2, False)
    selected = ArchiveCatalogueService.compatibility_entry(dtos[0])
    owner._export_character_dependency_package_for_entry(selected)
    _drain()
    service = owner.archive_catalogue_service
    assert service.scope_requests[0].key == character_catalogue_asset_key(body.path)
    assert owner.exports, owner.shell.messages
    plan, indexes = owner.exports[0]
    assert {entry.path for entry in plan.entries} >= {body.path, app.path, custom.path}, (
        "the descriptor's customization file was looked up after the first pass missed it"
    )
    assert ANIMATION_SCOPE_WARNING in plan.warnings
    assert "character/customization/hero_custom.xml" in indexes["path_index"]


def test_character_export_explains_an_unmatched_armor_model() -> None:
    owner = _CharacterOwner([_dto(1, "character/model/cd_phw_00_ub_00_0211.pac")])
    owner.archive_catalogue_service.scope_reply = f"{CHARACTER_KEY_MISSING_TEXT}. Refresh the finder."
    shown = []
    from cdmw.ui.archive_browser import character_dependency_export as module

    with patch.object(module.QMessageBox, "information", lambda _p, _t, text: shown.append(text)), \
            patch.object(module.QMessageBox, "warning", lambda _p, _t, text: shown.append("WARN " + text)):
        owner._export_character_dependency_package_for_entry(
            ArchiveCatalogueService.compatibility_entry(owner.archive_catalogue_service.catalogue[0])
        )
        _drain()
    assert shown and shown[0].startswith("No matching appearance descriptor was found")
    assert "Load Archive Browser data first" not in shown[0]
    assert not owner.exports


def test_character_export_without_any_catalogue_says_so() -> None:
    owner = _CharacterOwner([])
    owner.archive_remote_bridge.current_session = None
    shown = []
    from cdmw.ui.archive_browser import character_dependency_export as module

    with patch.object(module.QMessageBox, "warning", lambda _p, _t, text: shown.append(text)):
        owner._export_character_dependency_package_for_entry(
            ArchiveEntry("a.pac", Path("C:/0.pamt"), Path("C:/0.paz"), 0, 1, 1, 0, 0)
        )
    assert "not loaded yet" in shown[0]


# ------------------------------------------------------------------ issue 29: stale references


class _FamilyOwner(
    ArchiveAssetFamilyPanelMixin,
    ArchiveAssetFamilyDialogMixin,
    ArchiveMeshDdsPreviewMixin,
    ArchiveMeshDirectPatchMixin,
    ArchiveMeshSwapSupportMixin,
):
    def __init__(self, current: ArchiveEntry) -> None:
        _app()
        self.archive = self
        self.shell = _Shell()
        self.current = current
        self.archive_asset_family_cache = OrderedDict()
        self.current_archive_model_texture_references = []
        self.current_archive_asset_family_graph = None
        self.current_archive_references_source_identity = None
        self.previewed: list[ArchiveEntry] = []

    def _current_archive_entry(self):
        return self.current

    def _render_archive_preview(self, entry) -> None:
        self.previewed.append(entry)


def _entry(path: str, offset: int) -> ArchiveEntry:
    return ArchiveEntry(path, Path("C:/Game/0009/0.pamt"), Path("C:/Game/0009/0.paz"), offset, 1, 1, 0, 0)


def test_right_clicked_model_never_reuses_the_previewed_models_family() -> None:
    model_a, model_b = _entry("character/model/a.pac", 1), _entry("character/model/b.pac", 2)
    owner = _FamilyOwner(model_b)  # A was previewed, then B was right-clicked
    owner.current_archive_model_texture_references = [ArchiveModelTextureReference(reference_name="a_texture.dds")]
    owner.current_archive_asset_family_graph = AssetFamilyGraph(root_path=model_a.path, summary="A")
    owner.current_archive_references_source_identity = archive_entry_identity_key(model_a)

    def unavailable(_owner, _entry, **_options):
        raise ArchiveWorkflowDependenciesUnavailable("The archive worker is still preparing the selected file.")

    from cdmw.ui.archive_browser import asset_family_dialog

    with patch.object(asset_family_dialog, "archive_workflow_dependency_context", unavailable):
        assert owner._archive_asset_family_graph_or_prepare(model_b, "Asset Family") is None
        assert owner._archive_related_references_for_entry(model_b) is None
        assert owner._current_archive_related_references_for_entry(model_b) == ()
        assert owner._prompt_archive_mesh_related_file_selection(
            model_b, title="Export", intro_text="", confirm_button_text="Export",
        ) is None
    assert owner.previewed == [model_b], "B's own dependencies are requested instead"
    assert "Preparing b.pac" in owner.shell.messages[0][0]


def test_references_built_for_the_right_clicked_model_are_used() -> None:
    model_b = _entry("character/model/b.pac", 2)
    owner = _FamilyOwner(model_b)
    references = [ArchiveModelTextureReference(reference_name="b_texture.dds")]
    owner.current_archive_model_texture_references = references
    owner.current_archive_asset_family_graph = AssetFamilyGraph(root_path=model_b.path, summary="B")
    owner.current_archive_references_source_identity = archive_entry_identity_key(model_b)
    graph, _cached = owner._archive_asset_family_graph_for_entry(model_b)
    assert graph.summary == "B"
    assert owner._current_archive_related_references_for_entry(model_b) == tuple(references)


def _prepared_set(owner_entry: ArchiveEntry, *members: ArchiveEntry, root: Path):
    from dataclasses import replace

    from cdmw.ui.archive_browser.remote_preview_dependencies import ArchivePreviewDependencySet

    prepared = []
    for member in (owner_entry, *members):
        path = root / f"{member.offset}_{Path(member.path).name}"
        path.write_bytes(b"\0" * 8)
        prepared.append(replace(member, prepared_path=path))
    return ArchivePreviewDependencySet(
        "session-a", owner_entry.offset, tuple(prepared),
        {entry.path.casefold(): (entry,) for entry in prepared},
        {Path(entry.path).name.casefold(): (entry,) for entry in prepared}, len(prepared), False,
    )


def test_asset_family_never_builds_from_another_models_prepared_set(tmp_path) -> None:
    # A prepared set lists every file its model's preview needed, so a right-clicked
    # model can appear in the previewed model's set. Its family was built from that
    # borrowed set, and a graph built that way was then served from the cache.
    model_a, model_b = _entry("character/model/a.pac", 1), _entry("character/model/b.pac", 2)
    owner = _FamilyOwner(model_b)
    borrowed = _prepared_set(model_a, model_b, root=tmp_path)
    owner.archive_remote_bridge = SimpleNamespace(displays_v2=True, prepared_dependencies_for=lambda _entry: borrowed)
    owner._archive_asset_family_graph_for_entry(model_b)  # an internal caller may still borrow it
    assert owner._archive_asset_family_graph_or_prepare(model_b, "Asset Family") is None
    assert owner.previewed == [model_b]
    assert owner.shell.messages[-1][0].startswith("Preparing b.pac and its related files.")
    own = _prepared_set(model_b, root=tmp_path)
    owner.archive_remote_bridge.prepared_dependencies_for = lambda _entry: own
    graph, _references = owner._archive_asset_family_graph_or_prepare(model_b, "Asset Family")
    assert graph.root_path == model_b.path
