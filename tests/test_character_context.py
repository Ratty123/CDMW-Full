from __future__ import annotations

import os
import json
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSettings, Signal
from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from cdmw.core.appearance_composite import appearance_model_slot
from cdmw.core.archive import build_archive_entry_basename_index, build_archive_entry_path_index
from cdmw.domain.character_context import (
    CharacterContextAppearance,
    CharacterContextDiscoveryRequest,
    CharacterContextDiscoveryResult,
    CharacterContextOption,
    CharacterContextSelection,
    NativePreviewContextComponent,
    default_character_context_selection,
    merge_character_context_dependency_entries,
    selected_character_context_components,
)
from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings
from cdmw.rendering.native_preview_core import build_native_preview_core_job
from cdmw.services.character_context_service import CharacterContextService
from cdmw.services.mesh_dotnet_reference_composite import _native_reference_batch
from cdmw.ui.character_context_panel import CharacterContextPanel
from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.mesh_editor.character_context import MeshEditorCharacterContextMixin
from cdmw.ui.mesh_editor.tab import MeshEditorTab
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker
import cdmw.workers.character_context_workers as character_context_workers
from cdmw.workers.character_context_workers import (
    CharacterContextPackageRequest,
    _package_cache_key,
    run_character_context_discovery,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _entries(tmp_path: Path, payloads: tuple[tuple[str, bytes | str], ...]) -> tuple[ArchiveEntry, ...]:
    paz_path = tmp_path / "0.paz"
    pamt_path = tmp_path / "0.pamt"
    offset = 0
    result: list[ArchiveEntry] = []
    with paz_path.open("wb") as handle:
        for path, payload in payloads:
            data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
            handle.write(data)
            result.append(
                ArchiveEntry(path, pamt_path, paz_path, offset, len(data), len(data), 0, 0)
            )
            offset += len(data)
    return tuple(result)


def test_appearance_slot_prefers_nested_hair_and_face_components() -> None:
    assert appearance_model_slot("character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0006_02.pac") == "hair"
    assert appearance_model_slot("character/model/1_pc/2_phw/head/head_sub/cd_phw_00_head_sub_00_0004.pac") == "face"
    assert appearance_model_slot("character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0028.pac") == "head"


def test_context_dependencies_merge_once_and_preserve_completeness(tmp_path: Path) -> None:
    source, context, texture = _entries(
        tmp_path,
        (("source.pac", b"PAR "), ("face.pac", b"PAR "), ("face.dds", b"DDS ")),
    )
    component = NativePreviewContextComponent(
        context,
        "face",
        "Face",
        "authored",
        dependency_entries=(texture, source),
        dependencies_complete=True,
    )
    merged, complete = merge_character_context_dependency_entries((source,), True, (component,))
    assert merged == (source, context, texture)
    assert complete


def test_discovery_uses_exact_authored_context_and_filters_alternatives(tmp_path: Path) -> None:
    source_path = "character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0028.pac"
    entries = _entries(
        tmp_path,
        (
            (
                "character/appearance/3_npc/cd_nhw_south_20011.app_xml",
                "<Appearance>"
                '<Head><Prefab Name="cd_phw_00_head_00_0028" HeadScale="1.10" /></Head>'
                '<Face><Prefab Name="cd_phw_00_head_sub_00_0004" /></Face>'
                '<Hair><Prefab Name="cd_phw_00_hair_00_0006_02" /></Hair>'
                '<Nude><Prefab Name="cd_phw_00_nude_20_0001" CharacterScale="0.99" /></Nude>'
                "</Appearance>",
            ),
            (source_path, b"PAR "),
            ("character/model/1_pc/2_phw/head/head_sub/cd_phw_00_head_sub_00_0004.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0006_02.pac", b"PAR "),
            ("character/model/1_pc/2_phw/nude/cd_phw_00_nude_20_0001.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0007.pac", b"PAR "),
            ("character/model/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0007.pac", b"PAR "),
            ("character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pac", b"PAR "),
            ("character/modelproperty/1_pc/2_phw/head/head/cd_phw_00_head_00_0028.pac_xml", '<T Path="head.dds"/>'),
            ("character/modelproperty/1_pc/2_phw/head/head_sub/cd_phw_00_head_sub_00_0004.pac_xml", '<T Path="face.dds"/>'),
            ("character/modelproperty/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0006_02.pac_xml", '<T Path="hair6.dds"/>'),
            ("character/modelproperty/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0007.pac_xml", '<T Path="hair7.dds"/>'),
            ("character/modelproperty/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0007.pac_xml", '<T Path="phm.dds"/>'),
            ("character/modelproperty/1_pc/2_phw/nude/cd_phw_00_nude_20_0001.pac_xml", '<T Path="body20.dds"/>'),
            ("character/modelproperty/1_pc/2_phw/nude/cd_phw_00_nude_00_0001.pac_xml", '<T Path="body0.dds"/>'),
            ("character/texture/head.dds", b"DDS "),
            ("character/texture/face.dds", b"DDS "),
            ("character/texture/hair6.dds", b"DDS "),
            ("character/texture/hair7.dds", b"DDS "),
            ("character/texture/phm.dds", b"DDS "),
            ("character/texture/body20.dds", b"DDS "),
            ("character/texture/body0.dds", b"DDS "),
        ),
    )
    source = entries[1]
    authored_results: list[CharacterContextDiscoveryResult] = []
    result = run_character_context_discovery(
        CharacterContextDiscoveryRequest(
            source,
            entries,
            build_archive_entry_path_index(entries),
            build_archive_entry_basename_index(entries),
            "archive-a",
            7,
        ),
        authored_ready=authored_results.append,
    )

    assert result.request_id == 7
    assert len(authored_results) == 1
    assert authored_results[0].appearances == result.appearances
    assert authored_results[0].compatible_hair == ()
    assert authored_results[0].compatible_body == ()
    assert len(result.appearances) == 1
    authored = result.appearances[0]
    assert {option.slot for option in authored.options} == {"face", "hair", "body"}
    assert [option.entry.basename for option in result.compatible_hair] == ["cd_phw_00_hair_00_0007.pac"]
    assert [option.entry.basename for option in result.compatible_body] == ["cd_phw_00_nude_00_0001.pac"]
    authored_by_slot = {option.slot: option for option in authored.options}
    assert authored_by_slot["face"].scale == pytest.approx(1.0 / 1.10)
    assert authored_by_slot["hair"].scale == pytest.approx(1.0 / 1.10)
    assert authored_by_slot["body"].scale == pytest.approx(0.99 / 1.10)
    selection = default_character_context_selection(result)
    assert selection.hair_option_id == ""
    assert selection.body_option_id == ""
    components = selected_character_context_components(result, selection)
    assert len(components) == 1
    assert components[0].slot == "face"


def test_discovery_publishes_authored_context_before_bounded_compatibility_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, app_entry, hair, sidecar, texture = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            (
                "character/appearance/example.app_xml",
                '<Appearance><Head><Prefab Name="source" /></Head>'
                '<Hair><Prefab Name="hair" /></Hair></Appearance>',
            ),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
            ("character/modelproperty/1_pc/2_phw/head/hair/hair.pac_xml", '<T Path="hair.dds"/>'),
            ("character/texture/hair.dds", b"DDS "),
        ),
    )
    entries = (source, app_entry, hair, sidecar, texture)
    authored_results: list[CharacterContextDiscoveryResult] = []
    skeleton_indexes: list[tuple[str, ...]] = []
    original_compatible_options = character_context_workers._compatible_options

    def observe_compatible_options(*args, **kwargs):
        assert authored_results, "authored context must be published before optional alternatives are checked"
        return original_compatible_options(*args, **kwargs)

    def observe_skeleton_resolution(*_args, archive_entries_by_basename=None, **_kwargs):
        skeleton_indexes.append(tuple((archive_entries_by_basename or {}).keys()))
        return type("SkeletonResolution", (), {})()

    monkeypatch.setattr(character_context_workers, "_compatible_options", observe_compatible_options)
    monkeypatch.setattr(
        character_context_workers,
        "resolve_skeleton_descriptor_for_model",
        observe_skeleton_resolution,
    )

    result = run_character_context_discovery(
        CharacterContextDiscoveryRequest(
            source,
            entries,
            build_archive_entry_path_index(entries),
            build_archive_entry_basename_index(entries),
            "archive",
            3,
        ),
        authored_ready=authored_results.append,
    )

    assert result.appearances
    assert skeleton_indexes
    assert all(
        "prefabdata" in basename
        for skeleton_index in skeleton_indexes
        for basename in skeleton_index
    )


def test_one_authored_style_expands_all_of_its_model_pieces(tmp_path: Path) -> None:
    source, hair, uptail, app_entry = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair_uptail.pac", b"PAR "),
            ("character/appearance/example.app_xml", b"<Appearance/>"),
        ),
    )
    option = CharacterContextOption(
        "hair-style",
        hair,
        "hair",
        "Authored Hair (2 pieces)",
        "authored",
        "Authored",
        component_entries=(hair, uptail),
    )
    appearance = CharacterContextAppearance("appearance", app_entry, "Example", (option,), 1)
    result = CharacterContextDiscoveryResult(1, source, "archive", (appearance,))
    selection = CharacterContextSelection(appearance_id="appearance", hair_option_id="hair-style")

    components = selected_character_context_components(result, selection)

    assert [component.entry for component in components] == [hair, uptail]


def test_archive_preview_worker_owns_context_before_native_build(tmp_path: Path) -> None:
    source, hair = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
        ),
    )
    component = NativePreviewContextComponent(hair, "hair", "Authored Hair", "authored")

    worker = ArchivePreviewWorker(
        1,
        source,
        None,
        {},
        {},
        None,
        None,
        (),
        preview_context_components=(component,),
    )

    assert worker.preview_context_components == (component,)


def test_character_context_package_cache_key_includes_dependency_fingerprints(tmp_path: Path) -> None:
    source, hair, dependency = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
            ("character/modelproperty/1_pc/2_phw/head/hair/hair.pac_xml", b"<Material/>"),
        ),
    )
    changed_dependency = ArchiveEntry(
        dependency.path,
        dependency.pamt_path,
        dependency.paz_file,
        dependency.offset,
        dependency.comp_size + 1,
        dependency.orig_size + 1,
        dependency.flags,
        dependency.paz_index,
    )

    def request(dep: ArchiveEntry) -> CharacterContextPackageRequest:
        component = NativePreviewContextComponent(
            hair,
            "hair",
            "Authored Hair",
            "authored",
            dependency_entries=(dep,),
            dependencies_complete=True,
        )
        return CharacterContextPackageRequest(
            1,
            source,
            (component,),
            (source,),
            True,
            "archive",
            tmp_path / "cache",
            None,
            ModelPreviewRenderSettings(),
        )

    assert _package_cache_key(request(dependency)) != _package_cache_key(request(changed_dependency))


def test_native_job_serializes_bounded_preview_context_components(tmp_path: Path) -> None:
    source, hair = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
        ),
    )
    component = NativePreviewContextComponent(
        hair,
        "hair",
        "Authored Hair",
        "authored",
        1.0,
        "character/appearance/example.app_xml",
        (hair,),
        True,
    )
    job = build_native_preview_core_job(
        source,
        cache_root=tmp_path / "cache",
        output_root=tmp_path / "package",
        preview_context_components=(component, component),
        preview_context_presentation_paths=(tmp_path / "context-presentation.bin",),
    )

    assert len(job["preview_context_components"]) == 1
    row = job["preview_context_components"][0]
    assert row["entry"]["path"] == hair.path
    assert row["slot"] == "hair"
    assert row["authority"] == "authored"
    assert row["appearance_path"].endswith("example.app_xml")
    assert row["context_presentation_geometry_path"].endswith("context-presentation.bin")
    assert "presentation_geometry_path" not in row
    assert job["presentation_geometry_path"] == ""


class _PanelService(QObject):
    discovery_started = Signal(str, object)
    discovery_progress = Signal(str, int, int, str)
    discovery_ready = Signal(str, object)
    discovery_failed = Signal(str, str)
    selection_changed = Signal(str, object, object)
    package_started = Signal(str)
    package_ready = Signal(str, str, float)
    package_failed = Signal(str, str)

    def __init__(self, result: CharacterContextDiscoveryResult) -> None:
        super().__init__()
        self.result = result
        self.current = default_character_context_selection(result)
        self.requests = 0
        self.cancelled = 0

    def source_key(self, _entry: ArchiveEntry) -> str:
        return self.result.source_key

    def cached_result(self, _entry: ArchiveEntry) -> CharacterContextDiscoveryResult:
        return self.result

    def selection(self, _entry: ArchiveEntry):
        return self.current

    def request_discovery(self, _entry: ArchiveEntry) -> bool:
        self.requests += 1
        return True

    def cancel_pending_discovery(self, _entry: ArchiveEntry) -> None:
        self.cancelled += 1

    def set_selection(self, _entry: ArchiveEntry, selection) -> bool:
        self.current = selection
        return True

    def select_appearance(self, _entry: ArchiveEntry, _appearance_id: str) -> bool:
        return True

    def use_authored_hair_and_body(self, _entry: ArchiveEntry) -> bool:
        return True

    def reset_selection(self, _entry: ArchiveEntry) -> bool:
        return True

    def clear_selection(self, _entry: ArchiveEntry) -> bool:
        return True


def test_panel_shows_face_default_and_keeps_hair_body_optional(tmp_path: Path) -> None:
    _app()
    source, face, hair, body, app_entry = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/head_sub/face.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/hair/hair.pac", b"PAR "),
            ("character/model/1_pc/2_phw/nude/body.pac", b"PAR "),
            ("character/appearance/example.app_xml", b"<Appearance/>")
        ),
    )
    options = (
        CharacterContextOption("face", face, "face", "Eyes, Brows", "authored", "Authored", face_contents=("Eyes", "Brows")),
        CharacterContextOption("hair", hair, "hair", "Authored Hair", "authored", "Authored"),
        CharacterContextOption("body", body, "body", "Authored Body", "authored", "Authored"),
    )
    appearance = CharacterContextAppearance("appearance", app_entry, "Example", options, 3)
    result = CharacterContextDiscoveryResult(1, source, "archive", (appearance,))
    service = _PanelService(result)
    panel = CharacterContextPanel(service, surface_label="Test")
    panel.set_source_entry(source)
    panel.activate()

    assert service.requests == 1
    assert panel.face_tree.topLevelItemCount() == 1
    assert panel.face_tree.topLevelItem(0).checkState(0).name == "Checked"
    assert panel.hair_tree.currentItem().text(0) == "None"
    assert panel.body_tree.currentItem().text(0) == "None"
    panel.close_button.click()
    assert service.cancelled == 1
    panel.deleteLater()


def test_archive_browser_keeps_character_context_disabled_for_heads(tmp_path: Path) -> None:
    _app()
    source = _entries(
        tmp_path,
        (("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),),
    )[0]

    class Harness(ArchivePreviewD3D11PartsMixin):
        character_context_service = None

    harness = Harness()
    harness.archive_character_context_panel = QFrame()
    harness.archive_character_context_button = QPushButton()
    harness.archive_character_context_button.setCheckable(True)
    harness.archive_character_context_panel.show()
    harness.archive_character_context_button.show()

    harness._sync_archive_character_context_source(source)

    assert harness.archive_character_context_button.isHidden()
    assert not harness.archive_character_context_button.isEnabled()
    assert harness.archive_character_context_panel.isHidden()


def test_shipped_preview_paths_do_not_start_character_context_workers() -> None:
    root = Path(__file__).resolve().parents[1]
    shipped_preview_sources = (
        root / "cdmw" / "ui" / "archive_browser" / "workers.py",
        root / "cdmw" / "workers" / "archive_preview_native.py",
        root / "cdmw" / "ui" / "mesh_editor" / "tab.py",
        root / "cdmw" / "ui" / "shell" / "tool_tabs.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in shipped_preview_sources)

    assert "CharacterContextService(" not in source
    assert "character_context_workers" not in source
    assert "_archive_character_context_preview_dependencies" not in source


def test_mesh_editor_keeps_character_context_disabled_for_heads(tmp_path: Path) -> None:
    _app()
    source, face, app_entry = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/model/1_pc/2_phw/head/head_sub/face.pac", b"PAR "),
            ("character/appearance/example.app_xml", b"<Appearance/>"),
        ),
    )
    option = CharacterContextOption("face", face, "face", "Face Set", "authored", "Authored")
    appearance = CharacterContextAppearance("appearance", app_entry, "Example", (option,), 1)
    result = CharacterContextDiscoveryResult(1, source, "archive", (appearance,))
    service = _PanelService(result)
    tab = MeshEditorTab(
        settings=QSettings(str(tmp_path / "mesh-editor.ini"), QSettings.Format.IniFormat),
        character_context_service=service,
    )

    tab._set_mesh_editor_character_context_source(source)
    assert tab.character_context_service is None
    assert tab.character_context_toolbar.isHidden()
    assert tab.character_context_toggle_button.isHidden()
    assert not tab.character_context_toggle_button.isEnabled()
    tab.character_context_toggle_button.setChecked(True)
    assert tab.character_context_panel.isHidden()
    assert service.requests == 0

    tab.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_mesh_editor_hides_old_context_until_atomic_resident_swap(tmp_path: Path) -> None:
    class Host:
        def __init__(self) -> None:
            self.hidden: list[tuple[int, ...]] = []

        def set_hidden_source_submeshes(self, indices) -> bool:
            self.hidden.append(tuple(int(index) for index in indices))
            return True

    class Harness(MeshEditorCharacterContextMixin):
        pass

    package = tmp_path / "package"
    package.mkdir()
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "batches": [
                    {"editor_identity": {"source_submesh_index": 0, "context_component": False}},
                    {"editor_identity": {"source_submesh_index": 2, "context_component": True}},
                    {"editor_identity": {"source_submesh_index": 3, "context_component": True}},
                ]
            }
        ),
        encoding="utf-8",
    )
    harness = Harness()
    harness.standalone_native_host_frame = Host()
    harness.character_context_loaded_source_indices = (2, 3)
    harness.character_context_next_source_indices = ()
    harness.character_context_visibility_restore_pending = False
    harness.character_context_resident_swap_pending = False

    assert harness._mesh_character_context_source_indices(str(package)) == (2, 3)
    harness._hide_mesh_character_context_until_rebuild()
    assert harness.standalone_native_host_frame.hidden == [(2, 3)]
    harness.character_context_next_source_indices = (4, 5)
    harness.character_context_resident_swap_pending = True
    harness._handle_mesh_character_context_resident_package_applied()

    assert harness.standalone_native_host_frame.hidden == [(2, 3), ()]
    assert harness.character_context_loaded_source_indices == (4, 5)
    assert harness.character_context_visibility_restore_pending is False


def test_native_context_batches_remain_reference_only_by_contract() -> None:
    protocol = Path("native/cdmw_preview_core/src/owners/protocol_json.cpp").read_text(encoding="utf-8")
    report = Path("native/cdmw_preview_core/src/owners/preview_report.cpp").read_text(encoding="utf-8")
    writer = Path("native/cdmw_preview_core/src/owners/package_writer_json.cpp").read_text(encoding="utf-8")
    reference = Path("cdmw/services/mesh_dotnet_reference_composite.py").read_text(encoding="utf-8")

    assert '"preview_context_components"' in protocol
    assert "mesh.source_prefab_component = true;" in report
    assert "mesh.source_context_component = true;" in report
    assert "context_presentation_component_count" in report
    assert "context_component" in writer
    assert "bool(identity.get(\"prefab_component\", False))" in reference


def test_context_identity_is_reference_only_even_without_prefab_compatibility_flag() -> None:
    assert _native_reference_batch(
        {
            "editor_identity": {
                "source_component_index": 0,
                "prefab_component": False,
                "context_component": True,
            }
        }
    )
    assert not _native_reference_batch(
        {
            "editor_identity": {
                "source_component_index": 0,
                "prefab_component": False,
                "context_component": False,
            }
        }
    )


def test_shared_service_discovers_once_reuses_session_cache_and_shuts_down(tmp_path: Path) -> None:
    source, app_entry, hair = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0028.pac", b"PAR "),
            (
                "character/appearance/example.app_xml",
                '<Appearance><Head><Prefab Name="cd_phw_00_head_00_0028" /></Head>'
                '<Hair><Prefab Name="cd_phw_00_hair_00_0006" /></Hair></Appearance>',
            ),
            ("character/model/1_pc/2_phw/head/hair/cd_phw_00_hair_00_0006.pac", b"PAR "),
        ),
    )
    entries = (source, app_entry, hair)
    path_index = build_archive_entry_path_index(entries)
    basename_index = build_archive_entry_basename_index(entries)
    service = CharacterContextService(
        entries_provider=lambda: entries,
        path_index_provider=lambda: path_index,
        basename_index_provider=lambda: basename_index,
        archive_fingerprint_provider=lambda: "archive-session",
    )
    ready: list[CharacterContextDiscoveryResult] = []
    selections: list[object] = []
    service.discovery_ready.connect(lambda _key, result: ready.append(result))
    service.selection_changed.connect(lambda _key, _selection, components: selections.append(components))

    assert service.request_discovery(source)
    assert ready == []
    source_key = service.source_key(source)
    assert _wait_for(lambda: source_key in service._complete_source_keys)
    assert len(ready) == 2
    assert ready[0].appearances[0].options[0].slot == "hair"
    assert ready[1].appearances == ready[0].appearances
    assert len(selections) == 1
    assert service.request_discovery(source)
    assert _wait_for(lambda: len(ready) == 3)
    assert ready[2] is ready[1]
    service.request_shutdown()
    assert _wait_for(lambda: service.iter_shutdown_workers() == ())
    destroyed: list[object] = []
    service.destroyed.connect(lambda: destroyed.append(True))
    service.deleteLater()
    assert _wait_for(lambda: bool(destroyed))


def test_shared_service_close_during_discovery_rejects_late_result(tmp_path: Path) -> None:
    payloads: list[tuple[str, bytes | str]] = [
        ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR ")
    ]
    payloads.extend(
        (
            f"character/appearance/context_{index:04d}.app_xml",
            f'<Appearance><Head><Prefab Name="other_{index:04d}" /></Head></Appearance>',
        )
        for index in range(300)
    )
    entries = _entries(tmp_path, tuple(payloads))
    source = entries[0]
    service = CharacterContextService(
        entries_provider=lambda: entries,
        archive_fingerprint_provider=lambda: "archive-session",
    )
    ready: list[object] = []
    service.discovery_ready.connect(lambda _key, result: ready.append(result))

    assert service.request_discovery(source)
    service.request_shutdown()
    assert _wait_for(lambda: service.iter_shutdown_workers() == ())
    assert ready == []
    destroyed: list[object] = []
    service.destroyed.connect(lambda: destroyed.append(True))
    service.deleteLater()
    assert _wait_for(lambda: bool(destroyed))


def test_shared_service_rejects_stale_packages_and_cancels_every_owned_worker(tmp_path: Path) -> None:
    source, app_entry = _entries(
        tmp_path,
        (
            ("character/model/1_pc/2_phw/head/head/source.pac", b"PAR "),
            ("character/appearance/example.app_xml", b"<Appearance/>"),
        ),
    )
    appearance = CharacterContextAppearance("appearance", app_entry, "Example", (), 0)
    result = CharacterContextDiscoveryResult(1, source, "archive", (appearance,))
    service = CharacterContextService(archive_fingerprint_provider=lambda: "archive")
    source_key = service.source_key(source)
    service._cache[source_key] = result
    service._package_request_id = 4
    ready: list[tuple[str, str]] = []
    service.package_ready.connect(lambda key, path, _elapsed: ready.append((key, path)))

    service._handle_package_ready(source_key, 3, "stale", 1.0)
    service._handle_package_ready(source_key, 4, "latest", 1.0)

    assert ready == [(source_key, "latest")]

    class Worker:
        def __init__(self) -> None:
            self.stopped = 0

        def stop(self) -> None:
            self.stopped += 1

    first = Worker()
    second = Worker()
    service._package_operations = {object(): first, object(): second}  # type: ignore[assignment]
    service._cancel_package()
    assert first.stopped == 1
    assert second.stopped == 1
    service._package_operations = {}
    service.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
