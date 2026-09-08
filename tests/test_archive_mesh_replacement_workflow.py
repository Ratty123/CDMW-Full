"""Archive replacement entry points with real Qt wiring and owned mesh fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CDMW_GUI_STARTUP_SMOKE", "1")

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QLabel, QMenu,
    QMessageBox, QPlainTextEdit, QRadioButton, QTabWidget,
)

from cdmw.app.events import AppEventBus
from cdmw.core import archive_mesh_import_preview
from cdmw.models import ArchiveEntry, ModPackageInfo
from cdmw.domain.packages.export_policy import ModPackageExportOptions
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.static_mesh_replacer import build_static_replacement_preview_mesh
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser import source_mix_overlay
from cdmw.ui.archive_browser import actions as archive_actions
from cdmw.ui.archive_browser import mesh_patch_flow
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import configure_synthetic_archive_context
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.preview.rust_session import RustPreviewSessionController
from cdmw.services.mesh_rust_contract import RUST_MESH_RENDERER
from tests.test_static_mesh_replacer_preview import _minimal_pac_original, _minimal_two_part_pac_original


APP = QApplication.instance() or QApplication([])
REPLACE_LABEL = "Replace Mesh from File..."


def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "Timed out waiting for the archive workflow"


@pytest.fixture
def archive_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    settings = create_settings(settings_file_path=tmp_path / "settings.cfg")
    window = MainWindow(app_context=AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    ))
    window.settings_file_path = tmp_path / "settings.cfg"
    multipart = getattr(request, "param", False)
    original, _mesh = (_minimal_two_part_pac_original if multipart else _minimal_pac_original)()
    # The shared fixture leaves its 40-byte PAC influence rows empty. Populate
    # valid rigid influences so the real importer can prove donor-weight reuse.
    original = bytearray(original)
    cursor = 0x50
    for section_index in range(5):
        if section_index:
            for vertex_index in range(6 if multipart else 3):
                original[cursor + vertex_index * 40 + 28] = 255
        cursor += struct.unpack_from("<I", original, 0x14 + section_index * 8)[0]
    pamt, paz = tmp_path / "0.pamt", tmp_path / "0.paz"
    pamt.write_bytes(b"owned synthetic archive index")
    paz.write_bytes(original)
    entry = ArchiveEntry("object/model/target.pac", pamt, paz, 0, len(original), len(original), 0, 0)
    configure_synthetic_archive_context(window, entry)
    archive_paths = [pamt, paz]
    if multipart:
        wrappers = "".join(
            f'<SkinnedMeshMaterialWrapper _subMeshName="target{index}">'
            '<Material Name="_resourceMaterial" _materialName="SkinnedMeshCloth_Ver2">'
            '<Vector Name="_parameters"><MaterialParameterTexture StringItemID="_overlayColorTexture" '
            '_name="_overlayColorTexture" Index="0">'
            f'<ResourceReferencePath_ITexture Name="_value" _path="object/texture/target{index}.dds"/>'
            '</MaterialParameterTexture></Vector></Material></SkinnedMeshMaterialWrapper>'
            for index in range(2)
        )
        sidecar = ('<Root><SkinnedMeshProperty><Vector Name="_subMeshResources">' + wrappers
                   + '</Vector></SkinnedMeshProperty></Root>').encode()
        sidecar_paz = tmp_path / "sidecar.paz"
        sidecar_paz.write_bytes(sidecar)
        sidecar_entry = ArchiveEntry(
            "object/modelproperty/target.pac_xml", pamt, sidecar_paz, 0, len(sidecar), len(sidecar), 0, 0,
        )
        window.archive.archive_entries.append(sidecar_entry)
        window.archive.archive_entries_by_normalized_path[sidecar_entry.path.casefold()] = (sidecar_entry,)
        window.archive.archive_entries_by_basename[sidecar_entry.basename.casefold()] = (sidecar_entry,)
        archive_paths.append(sidecar_paz)
        for index in range(2):
            texture_paz = tmp_path / f"target{index}.dds.paz"
            Image.new("RGBA", (8, 8), (128, 128, 128, 255)).save(texture_paz, format="DDS")
            texture_size = texture_paz.stat().st_size
            texture_entry = ArchiveEntry(
                f"object/texture/target{index}.dds", pamt, texture_paz, 0, texture_size, texture_size, 0, 0,
            )
            window.archive.archive_entries.append(texture_entry)
            window.archive.archive_entries_by_normalized_path[texture_entry.path] = (texture_entry,)
            window.archive.archive_entries_by_basename[texture_entry.basename] = (texture_entry,)
            archive_paths.append(texture_paz)
    monkeypatch.setattr(window.archive, "_current_archive_entry", lambda: entry)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in archive_paths}
    try:
        yield window, entry
    finally:
        for dialog in tuple(window._modeless_alignment_dialogs.values()):
            dialog.reject()
        if window.utility_worker is not None:
            window.utility_worker.stop()
        wait_for(lambda: window.worker_thread is None)
        window._finalize_close()
        window.deleteLater()
        APP.processEvents()
        assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


def test_loose_folder_button_scans_on_shell_worker_and_opens_review(
    archive_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, entry = archive_window
    source = tmp_path / "loose" / entry.path
    source.parent.mkdir(parents=True)
    source.write_bytes(b"replacement game-format payload")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(tmp_path / "loose"))
    monkeypatch.setattr(window.archive, "_archive_lookup_indexes_snapshot", lambda: (
        window.archive.archive_entries_by_normalized_path,
        window.archive.archive_entries_by_basename,
    ))
    worker_threads, reviewed, warnings = [], [], []
    real_scan = source_mix_overlay.run_source_mix_scan

    def scan(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        return real_scan(*args, **kwargs)

    def review(dialog):
        assert dialog.windowTitle() == "Loose Mod Overlay Review"
        tree = dialog.findChild(QTabWidget).widget(0)
        candidate = tree.topLevelItem(0).data(0, Qt.UserRole)
        reviewed.append(candidate)
        dialog.reject()
        return QDialog.Rejected

    monkeypatch.setattr(source_mix_overlay, "run_source_mix_scan", scan)
    monkeypatch.setattr(QDialog, "exec", review)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))
    window.archive.archive_import_loose_mod_button.click()
    wait_for(lambda: reviewed or warnings)
    assert warnings == []
    assert reviewed[0].target_archive_entry == entry
    assert reviewed[0].source_path == source
    assert worker_threads and worker_threads[0] != threading.get_ident()
    assert window.worker_thread is None


def test_replacement_import_menu_tracks_target_and_busy_state(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, entry = archive_window
    archive = window.archive
    archive._update_archive_model_action_controls(None)
    action = next(a for a in archive.archive_import_menu_button.menu().actions() if a.text().rstrip(".") == REPLACE_LABEL.rstrip("."))
    calls = []
    monkeypatch.setattr(archive, "_start_archive_mesh_patch", calls.append)
    archive._update_archive_model_action_controls(None)
    assert action.isEnabled()
    action.trigger()
    assert calls == [entry]
    window.worker_thread = object()
    try:
        archive._update_archive_model_action_controls(None)
        assert not action.isEnabled()
    finally:
        window.worker_thread = None
    monkeypatch.setattr(archive, "_current_archive_entry", lambda: None)
    archive._update_archive_model_action_controls(None)
    assert not action.isEnabled()


def test_replacement_context_menu_uses_clicked_target(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, entry = archive_window
    archive = window.archive
    item = SimpleNamespace(isSelected=lambda: True)
    monkeypatch.setattr(archive.archive_tree, "itemAt", lambda _position: item)
    monkeypatch.setattr(archive.archive_tree, "setCurrentItem", lambda _item: None)
    monkeypatch.setattr(archive, "_archive_tree_item_kind", lambda _item: "file")
    monkeypatch.setattr(archive, "_archive_tree_item_value", lambda _item: 0)
    monkeypatch.setattr(archive, "_archive_entry_at_tree_position", lambda _position: entry)
    monkeypatch.setattr(archive, "_schedule_archive_selection_state_update", lambda: None)
    calls = []
    monkeypatch.setattr(archive, "_start_archive_mesh_patch", calls.append)

    class Menu(QMenu):
        def exec(self, *_args):
            action = next(a for a in self.actions() if a.text() == REPLACE_LABEL)
            assert action.isEnabled()
            action.trigger()
            return action

    monkeypatch.setattr(archive_actions, "QMenu", Menu)
    archive._show_archive_tree_context_menu(QPoint())
    assert calls == [entry]


@pytest.mark.parametrize("archive_window,case", [(False, "geometry"), (False, "transformed"), (True, "textured")], indirect=["archive_window"])
def test_obj_import_builds_reparseable_loose_pac_without_opening_original_editor(
    archive_window, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case,
) -> None:
    window, entry = archive_window
    source = tmp_path / "replacement.obj"
    monkeypatch.setattr(RustPreviewSessionController, '_launch_if_needed', lambda self: None)
    source.write_text(
        "o replacement\nv 0 0 0\nv 2 0 0\nv 2 2 0\nv 0 2 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n",
        encoding="utf-8",
    )
    if case == "textured":
        source.write_text(
            "mtllib replacement.mtl\nv 0 0 0\nv 2 0 0\nv 2 2 0\nv 0 2 0\n"
            "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
            "o red\nusemtl red\nf 1/1 2/2 3/3\no blue\nusemtl blue\nf 1/1 3/3 4/4\n",
            encoding="utf-8",
        )
        source.with_suffix(".mtl").write_text(
            "newmtl red\nKd 1 1 1\nmap_Kd red.png\nnewmtl blue\nKd 1 1 1\nmap_Kd blue.png\n",
            encoding="utf-8",
        )
        Image.new("RGB", (8, 8), (220, 20, 20)).save(tmp_path / "red.png")
        Image.new("RGB", (8, 8), (20, 20, 220)).save(tmp_path / "blue.png")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(source), ""))
    opened, warnings, setup_modes = [], [], []
    monkeypatch.setattr(window, "_open_mesh_editor_for_entry", lambda *a, **kw: opened.append((a, kw)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))

    def accept_setup(dialog):
        modes = dialog.findChildren(QRadioButton)
        if not modes:
            warnings.append((dialog.windowTitle(), [widget.toPlainText() for widget in dialog.findChildren(QPlainTextEdit)]))
            dialog.reject()
            return QDialog.Rejected
        selected = next(button for button in modes if button.isChecked())
        setup_modes.append(selected.text())
        assert selected.text() == "Mesh Replacement"
        assert selected.isEnabled()
        material_mode = dialog.findChild(QComboBox, "MeshImportMaterialMode")
        assert material_mode.currentData() is False
        assert material_mode.currentText() == "Keep target materials and textures"
        if case == "textured":
            material_mode.setCurrentIndex(material_mode.findData(True))
        dialog.accept()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_setup)
    window.archive._update_archive_model_action_controls(None)
    window.archive.archive_model_import_mesh_button.click()
    wait_for(lambda: window._modeless_alignment_dialogs or warnings)
    assert warnings == []
    assert opened == []
    assert setup_modes == ["Mesh Replacement"]
    dialog = next(iter(window._modeless_alignment_dialogs.values()))
    wait_for(lambda: bool(getattr(dialog, "_cdmw_builder_construction_complete", False)))
    context = dialog._cdmw_builder_construction_context
    assert context["entry"] == entry
    assert context["scene_import_result"].mesh.total_faces == 2
    assert context["original_mesh"].total_faces == (2 if case == "textured" else 1)
    assert callable(context["continue_build_callback"])
    assert dialog._source_mix_task_controller._owner is window
    assert dialog.parentWidget() is window.archive
    assert opened == []

    controller = context['alignment_d3d11_preview_host'].controller
    wait_for(lambda: bool(controller.desired_package_path))
    assert controller._desired_package.manifest_path.is_file()
    manifest = json.loads(controller._desired_package.manifest_path.read_text(encoding='utf-8'))
    assert manifest['renderer'] == RUST_MESH_RENDERER
    assert manifest['interaction_profile'] == 'static_replacement'

    exported, preflight_results, build_summaries = [], [], []
    real_final_preview = mesh_patch_flow.build_final_package_preview

    def record_final_preview(*args, **kwargs):
        build_summaries.append(args[0].summary_lines)
        result = real_final_preview(*args, **kwargs)
        preflight_results.append(result)
        return result

    monkeypatch.setattr(mesh_patch_flow, "build_final_package_preview", record_final_preview)
    monkeypatch.setattr(window.archive, "_collect_archive_mod_ready_export_target", lambda **_kw: (
        tmp_path / "output", ModPackageInfo(title="Replacement regression"), True, False,
        ModPackageExportOptions(),
    ))
    monkeypatch.setattr(window.archive, "_prompt_archive_mesh_related_file_selection", lambda *_a, **_kw: ())
    monkeypatch.setattr(window.archive, "_show_archive_import_preview", lambda *a, **kw: exported.append((a, kw)))
    monkeypatch.setattr(QMessageBox, "exec", lambda _self: QMessageBox.Ok)
    wait_for(lambda: window.worker_thread is None)
    complete_swap = dialog.findChild(QCheckBox, "MeshAlignmentCompleteExternalSwapCheckbox")
    assert complete_swap.isChecked() == (case == "textured")
    transformed_preview = []
    if case == "transformed":
        context["alignment_mode_combo"].setCurrentIndex(context["alignment_mode_combo"].findData("manual"))
        context["scale_to_length_checkbox"].setChecked(False)
        for axis, value in zip("xyz", (3, 4, 1)):
            context[f"offset_{axis}_spin"].setValue(value)
            context[f"scale_{axis}_spin"].setValue(2)
        context["rotate_z_spin"].setValue(90)
        real_build = archive_mesh_import_preview.build_static_mesh_replacement

        def record_preview(original_data, original, replacement, options):
            transformed_preview.append(build_static_replacement_preview_mesh(original, replacement, options))
            return real_build(original_data, original, replacement, options)

        monkeypatch.setattr(archive_mesh_import_preview, "build_static_mesh_replacement", record_preview)
    build_button = dialog._material_authority_build_button
    status = dialog.findChild(QLabel, "MeshReplacementBuilderStatus")
    assert build_button.isEnabled()
    build_button.click()
    wait_for(lambda: exported or warnings or "failed" in status.text().lower())
    assert warnings == [], str(warnings) + str(build_summaries)
    assert "failed" not in status.text().lower(), status.text()
    wait_for(lambda: "Wrote rebuilt" in status.text())
    assert len(exported) == 1
    result = exported[0][0][1]
    assert result.import_mode == "static_replacement"
    assert result.parsed_mesh.total_faces == 2
    package_root = exported[0][1]["loose_package_root"]
    output_files = list(package_root.rglob("target.pac"))
    assert len(output_files) == 1
    assert output_files[0].read_bytes() == result.rebuilt_data
    rebuilt = parse_pac(output_files[0].read_bytes(), entry.path)
    assert rebuilt.total_faces == 2
    assert len(rebuilt.submeshes) == (2 if case == "textured" else 1)
    for part in rebuilt.submeshes:
        assert len(part.bone_weights) == len(part.vertices)
        assert all(sum(weights) == pytest.approx(1.0) for weights in part.bone_weights)
    if case == "transformed":
        expected = [(3, 4, 1), (3, 8, 1), (-1, 8, 1), (-1, 4, 1)]
        assert len(rebuilt.submeshes[0].vertices) == len(expected)
        assert len(transformed_preview) == 1
        for part in (rebuilt.submeshes[0], transformed_preview[0].submeshes[0]):
            for actual, point in zip(part.vertices, expected):
                assert actual == pytest.approx(point, abs=5e-4)
    if case == "textured":
        assert len(result.source_owned_output_draw_sections) == 2
        sidecars = list(package_root.rglob("*.pac_xml"))
        assert len(sidecars) == 1
        assert "target0" in sidecars[0].read_text() and "target1" in sidecars[0].read_text()
        texture_files = list(package_root.rglob("*.dds"))
        assert len(texture_files) >= 2
        colors = [Image.open(path).convert("RGB").getpixel((4, 4)) for path in texture_files]
        assert any(red > blue + 100 for red, _green, blue in colors)
        assert any(blue > red + 100 for red, _green, blue in colors)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    assert opened == []


def test_cancel_file_picker_preserves_editor_and_starts_no_worker(archive_window, monkeypatch: pytest.MonkeyPatch) -> None:
    window, _entry = archive_window
    opened = []
    monkeypatch.setattr(window, "_open_mesh_editor_for_entry", lambda *a, **kw: opened.append((a, kw)))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: ("", ""))
    window.archive._update_archive_model_action_controls(None)
    window.archive.archive_model_import_mesh_button.click()
    assert opened == []
    assert window.worker_thread is None
    assert not window._modeless_alignment_dialogs
