"""Real shared-workspace regressions for issue #22, using owned loose files."""

import os
import sys
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from cdmw.models import MatchedOriginalTexture
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.texture_workflow.job import normalize_texture_mode


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(.002)
    assert predicate()


@pytest.fixture
def workspace(tmp_path, monkeypatch, request):
    app = QApplication.instance() or QApplication([])
    settings = create_settings(settings_file_path=tmp_path / "textures.cfg")
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("ui/textures_mode", "replace")
    settings.setValue("ui/shell_variant", getattr(request, "param", "compact_rail"))
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    callback_errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *error: callback_errors.append("".join(traceback.format_exception(*error))))
    assert window.textures.job.mode == "replace"
    window._activate_tool_key("replace_assistant")
    wait_for(lambda: created_tool_widget(window.replace_assistant_tab) is not None)
    textures = window.textures
    matcher = created_tool_widget(window.replace_assistant_tab)
    import_event = matcher._handle_queue_worker_event
    def assert_gui_delivery(*args):
        assert QThread.currentThread() == app.thread()
        import_event(*args)
    monkeypatch.setattr(matcher, "_handle_queue_worker_event", assert_gui_delivery)
    try:
        yield window, textures, matcher
    finally:
        owners = [matcher]
        editor = created_tool_widget(window.texture_editor_tab)
        if editor is not None:
            owners.append(editor)
        threads = [thread for owner in owners for _name, thread, _worker in owner.iter_shutdown_workers()
                   if thread is not None]
        for owner in owners:
            owner.request_shutdown()
        def stopped():
            for thread in threads:
                try:
                    if thread.isRunning():
                        return False
                except RuntimeError:
                    pass  # Qt has delivered finished and deleted this thread.
            return True
        wait_for(stopped)
        app.processEvents()
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
        assert not callback_errors, "\n".join(callback_errors)


def load_folder(matcher, folder, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_a, **_k: str(folder))
    matcher.add_folder_button.click()
    wait_for(lambda: matcher.import_thread is None)


def write_source(path, content=b"external DDS payload"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.mark.parametrize("workspace", ["legacy", "compact_rail"], indirect=True)
def test_replace_navigation_and_recursive_import_never_open_editor(workspace, tmp_path, monkeypatch):
    window, textures, matcher = workspace
    folder = tmp_path / "flat"
    first = write_source(folder / "coat.DDS")
    second = write_source(folder / "nested" / "coat.dds")
    png = write_source(folder / "color.PNG")
    write_source(folder / "ignored.txt")
    with patch("cdmw.services.texture_editor_service.TextureEditorService.create_document_from_source",
               side_effect=AssertionError("replacement import must not decode")):
        load_folder(matcher, folder, monkeypatch)
        assert {item.source_path for item in matcher.items} == {first.resolve(), second.resolve(), png.resolve()}
        matcher.queue_tree.setCurrentItem(matcher.queue_tree.topLevelItem(1))
        textures.show_texture_review(operation="replacement")
        assert textures.job.mode == "replace"
        assert textures.texture_pages.currentWidget() is window.replace_assistant_tab
        assert window.settings.value("ui/textures_mode") == "replace"
        assert created_tool_widget(window.texture_editor_tab) is None
        assert not textures.job.sessions
        assert not textures._pending_texture_sources
        matcher.import_external_sources([first, folder])
        wait_for(lambda: matcher.import_thread is None)
        assert len(matcher.items) == 3
        assert len(textures.job.assets) == 3
    assert normalize_texture_mode("replace") == "replace"
    assert normalize_texture_mode("bad saved value") == "edit"


def test_reload_replaces_batch_and_bulk_removal_uses_rows_not_export_checks(workspace, tmp_path, monkeypatch):
    window, textures, matcher = workspace
    folder = tmp_path / "textures"
    first = write_source(folder / "first.dds", b"before")
    obsolete = write_source(folder / "obsolete.dds")
    load_folder(matcher, folder, monkeypatch)
    old_keys = set(textures.job.assets)
    matcher.package_title_edit.setText("My recolor")
    prior_output = tmp_path / "existing-output"
    prior_output.mkdir()
    matcher.last_built_output_root = prior_output
    first.write_bytes(b"after")
    obsolete.unlink()
    write_source(folder / "new.dds")
    matcher.reload_folder_button.click()
    wait_for(lambda: matcher.import_thread is None)
    assert {item.source_path.name for item in matcher.items} == {"first.dds", "new.dds"}
    assert old_keys.isdisjoint(textures.job.assets)
    assert next(item for item in matcher.items if item.source_path == first).source_path.read_bytes() == b"after"
    assert matcher.package_title_edit.text() == "My recolor"
    assert matcher.last_built_output_root == prior_output

    rows = [matcher.queue_tree.topLevelItem(index) for index in range(2)]
    rows[0].setCheckState(0, Qt.Unchecked)
    assert len(textures.job.selected) == 1
    for row in rows:
        row.setSelected(True)
    matcher.remove_selected_button.click()
    assert not matcher.items and not textures.job.assets and not textures.job.selected
    assert first.exists() and prior_output.exists()
    matcher.reload_folder_button.click()
    wait_for(lambda: matcher.import_thread is None)
    matcher.clear_all_button.click()
    assert not textures.job.assets and not textures._pending_texture_sources
    assert not textures._replacement_asset_keys
    assert created_tool_widget(window.texture_editor_tab) is None


@pytest.mark.parametrize("close_during_import", [False, True])
def test_empty_failed_and_cancelled_scans_preserve_batch_and_reject_late_results(workspace, tmp_path, monkeypatch, close_during_import):
    _window, textures, matcher = workspace
    folder = tmp_path / "original"
    write_source(folder / "keep.dds")
    load_folder(matcher, folder, monkeypatch)
    old_keys = set(textures.job.assets)
    empty = tmp_path / "empty"
    empty.mkdir()
    load_folder(matcher, empty, monkeypatch)
    assert set(textures.job.assets) == old_keys
    assert matcher.last_import_folder == folder

    from cdmw.ui.replace_assistant import workers
    build_items = workers.build_replace_assistant_items
    with monkeypatch.context() as scoped:
        scoped.setattr(workers, "build_replace_assistant_items", lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("scan denied")))
        load_folder(matcher, empty, scoped)
    assert set(textures.job.assets) == old_keys
    assert "scan denied" in matcher.status_label.text()

    release = threading.Event()
    entered = threading.Event()
    ticks = []
    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return build_items(*args, **kwargs)
    monkeypatch.setattr(workers, "build_replace_assistant_items", paused)
    timer = QTimer()
    timer.setInterval(1)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    try:
        matcher._add_sources([empty], replace_queue=True, folder=empty)
        wait_for(lambda: entered.is_set() and len(ticks) >= 3)
        assert textures.job.busy and matcher.cancel_import_button.isEnabled()
        if close_during_import:
            started = time.monotonic()
            matcher.request_shutdown()
            assert time.monotonic() - started < .5
        else:
            matcher.cancel_import_button.click()
        # Simulate a success already queued before cancellation was requested.
        matcher.import_worker.completed.emit({"items": build_items([folder], perform_matching=False)})
        QApplication.processEvents()
        assert set(textures.job.assets) == old_keys
    finally:
        release.set()
        timer.stop()
        wait_for(lambda: matcher.import_thread is None)
    assert not textures.job.busy
    if not close_during_import:
        matcher.clear_all_button.click()
        assert not textures.job.assets


def test_build_uses_latest_raw_sources_and_excludes_unchecked_unmatched_files(workspace, tmp_path, monkeypatch):
    window, textures, matcher = workspace
    folder = tmp_path / "edited"
    first = write_source(folder / "coat.dds", b"first edit")
    write_source(folder / "unmatched.dds")
    original = write_source(tmp_path / "original.dds", b"original")
    load_folder(matcher, folder, monkeypatch)
    item = next(item for item in matcher.items if item.source_path == first)
    item.matched_original = MatchedOriginalTexture(
        package_root="0000", archive_relative_path="character/coat.dds",
        loose_relative_path=Path("0000/character/coat.dds"), original_dds_path=original,
        match_reason="manual original",
    )
    item.status = "matched"
    textures.synchronize_replacement_matches(matcher)
    textures.job.set_selected([textures.replacement_item_key(item)])
    observed = []
    monkeypatch.setattr(matcher, "_launch_build_worker", lambda options, items, **_k:
                        observed.append([(i.source_path, i.source_path.read_bytes(), i.matched_original.archive_relative_path) for i in items]))
    matcher.start_build()
    assert observed == [[(first, b"first edit", "character/coat.dds")]]
    textures.finish_texture_operation()
    first.write_bytes(b"second edit")
    matcher.start_build()
    assert observed[-1] == [(first, b"second edit", "character/coat.dds")]
    textures.finish_texture_operation()
    assert created_tool_widget(window.texture_editor_tab) is None


def test_auto_match_runs_on_file_only_batch_without_editor(workspace, tmp_path, monkeypatch):
    window, textures, matcher = workspace
    folder = tmp_path / "edited"
    write_source(folder / "coat.dds")
    write_source(folder / "unmatched.dds")
    originals = tmp_path / "originals"
    write_source(originals / "0000" / "character" / "coat.dds")
    monkeypatch.setattr(matcher, "get_original_root", lambda: str(originals))
    load_folder(matcher, folder, monkeypatch)
    callback_threads = []
    complete = matcher._handle_auto_match_complete
    def record_delivery(*args):
        callback_threads.append(QThread.currentThread())
        complete(*args)
    monkeypatch.setattr(matcher, "_handle_auto_match_complete", record_delivery)
    with patch("cdmw.services.texture_editor_service.TextureEditorService.create_document_from_source",
               side_effect=AssertionError("matching must not decode")):
        matcher.auto_match_button.click()
        wait_for(lambda: matcher.match_thread is None and not matcher._catalogue_request_busy())
    matched = next(item for item in matcher.items if item.source_path.name == "coat.dds")
    missing = next(item for item in matcher.items if item.source_path.name == "unmatched.dds")
    assert matched.matched_original.archive_relative_path == "character/coat.dds"
    assert missing.status == "unresolved" and missing.matched_original is None
    assert textures.job.assets[textures.replacement_item_key(matched)].replacement_item is matched
    assert callback_threads == [QApplication.instance().thread()]
    assert created_tool_widget(window.texture_editor_tab) is None


def test_edit_is_explicit_and_clear_closes_sessions_once(workspace, tmp_path, monkeypatch):
    from PIL import Image
    window, textures, matcher = workspace
    folder = tmp_path / "pngs"
    folder.mkdir()
    for index in range(3):
        Image.new("RGBA", (4, 4), (80, index, 20, 255)).save(folder / f"{index}.png")
    load_folder(matcher, folder, monkeypatch)
    assert not textures.job.sessions
    matcher.open_in_editor_button.click()
    wait_for(lambda: len(textures.job.sessions) == 1 and not textures.job.busy
             and not created_tool_widget(window.texture_editor_tab)._busy())
    assert textures.job.mode == "edit"
    textures.open_texture_sources([folder / "1.png", folder / "2.png"])
    editor = created_tool_widget(window.texture_editor_tab)
    wait_for(lambda: len(textures.job.sessions) == 3 and not editor._busy())
    sessions = tuple(textures.job.sessions)
    editor.layer_visible_checkbox.click()
    assert not editor.document.layers[0].visible
    textures._synchronize_texture_job()
    edited_key = textures.job.active_asset_key
    textures.set_texture_mode("replace")
    wait_for(lambda: not textures.job.busy and not editor._busy())
    assert tuple(textures.job.sessions) == sessions
    edited = textures.job.assets[edited_key].replacement_item
    with Image.open(edited.source_path) as output:
        assert output.convert("RGBA").getextrema()[3] == (0, 0)
    assert textures.replacement_item_key(matcher._current_item()) == edited_key
    matcher.open_in_editor_button.click()
    assert editor._sessions[editor._active_session_index] is sessions[-1]
    assert len(textures.job.sessions) == 3 and len(textures.job.assets) == 3
    textures.set_texture_mode("replace")
    wait_for(lambda: not textures.job.busy and not editor._busy())
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.No)
    matcher.clear_all_button.click()
    assert len(textures.job.sessions) == 3
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: QMessageBox.Yes)
    with patch.object(editor, "_load_session_index", wraps=editor._load_session_index) as load:
        matcher.clear_all_button.click()
        assert load.call_count == 1
    assert not textures.job.sessions and editor.document is None
    assert not textures.job.assets and not matcher.items
    assert all((folder / f"{index}.png").exists() for index in range(3))


def test_import_cancellation_reaches_traversal_and_item_construction(tmp_path, monkeypatch):
    from cdmw.core import replace_assistant as core
    from cdmw.models import RunCancelled
    folder = tmp_path / "folder"
    write_source(folder / "first.dds")
    stop = threading.Event()
    def walk(*_args, **_kwargs):
        yield str(folder), [], ["first.dds"]
        stop.set()
        yield str(folder), [], ["late.dds"]
        pytest.fail("cancelled traversal continued")
    monkeypatch.setattr(core.os, "walk", walk)
    with pytest.raises(RunCancelled):
        core.collect_replace_assistant_imports([folder], stop_event=stop)
    stop.clear()
    monkeypatch.setattr(core, "collect_replace_assistant_imports",
                        lambda *_a, **_k: [folder / f"{index}.dds" for index in range(300)])
    def progress(current, _total, _detail):
        if current == 100:
            stop.set()
    with pytest.raises(RunCancelled):
        core.build_replace_assistant_items([folder], perform_matching=False, stop_event=stop, on_progress=progress)


def test_real_native_folder_match_package_and_external_rebuild(workspace, tmp_path, monkeypatch):
    """Exercise the reported flat-folder workflow through the real build worker."""
    import hashlib
    import zipfile
    from PIL import Image
    from cdmw.core.texture_native import (
        decode_dds_preview_with_directxtex, encode_dds_with_directxtex,
        find_directxtex_texture_binary,
    )
    from cdmw.core.texture_pipeline.inspection import parse_dds

    if find_directxtex_texture_binary() is None:
        pytest.skip("This integration check requires the existing DirectXTex texture helper.")
    window, textures, matcher = workspace
    folder = tmp_path / "external-edits"
    folder.mkdir()
    originals = tmp_path / "originals"
    formats = {"coat": "BC7_UNORM", "boots": "BC3_UNORM", "hat": "BC1_UNORM", "belt": "BC3_UNORM"}
    seed = tmp_path / "seed.png"
    Image.new("RGBA", (8, 8), (70, 70, 70, 255)).save(seed)
    for name, dds_format in formats.items():
        target = originals / "0009" / "character" / "textures" / f"{name}.dds"
        target.parent.mkdir(parents=True, exist_ok=True)
        assert encode_dds_with_directxtex(seed, target, dds_format=dds_format)
    Image.new("RGBA", (8, 8), (210, 25, 20, 255)).save(folder / "coat.png")
    Image.new("RGBA", (8, 8), (20, 190, 40, 255)).save(seed)
    assert encode_dds_with_directxtex(seed, folder / "boots.dds", dds_format=formats["boots"])
    Image.new("RGBA", (8, 8), (170, 100, 20, 255)).save(folder / "hat.png")
    monkeypatch.setattr(matcher, "get_original_root", lambda: str(originals))
    matcher.package_output_root_edit.setText(str(tmp_path / "packages"))
    matcher.package_title_edit.setText("Folder regression")
    matcher.overwrite_package_checkbox.setChecked(True)
    matcher.package_zip_checkbox.setChecked(True)
    matcher._set_combo_by_value(matcher.build_mode_combo, "rebuild_only")
    for profile, checkbox in matcher.package_profile_checkboxes.items():
        checkbox.setChecked(profile in {"dmm", "jmm"})
    reviews = []
    monkeypatch.setattr(matcher, "_open_review_dialog", lambda items: reviews.append(tuple(items)))
    wrong_threads = []
    set_status = matcher.status_label.setText
    def record_status(text):
        if QThread.currentThread() != QApplication.instance().thread():
            wrong_threads.append(text)
        else:
            set_status(text)
    monkeypatch.setattr(matcher.status_label, "setText", record_status)
    def fingerprints(root):
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*") if p.is_file()}
    original_hashes = fingerprints(originals)
    def match_and_build(expected_names, red_coat):
        source_hashes = fingerprints(folder)
        matcher.auto_match_button.click()
        wait_for(lambda: matcher.match_thread is None and not matcher._catalogue_request_busy())
        assert all(item.status == "matched" for item in matcher.items)
        assert {item.matched_original.archive_relative_path for item in matcher.items} == {
            f"character/textures/{name}.dds" for name in expected_names
        }
        matcher.build_package_button.click()
        wait_for(lambda: matcher.build_thread is None and not textures.job.busy, timeout=45)
        QApplication.processEvents()
        assert matcher.last_built_output_root is not None, matcher.log_view.toPlainText()
        assert len(reviews) > 0
        assert set(p.stem for p in matcher.last_built_output_root.rglob("*.dds")) == expected_names
        for output in (tmp_path / "packages").rglob("*.dds"):
            info = parse_dds(output)
            assert (info.width, info.height, info.dds_format) == (8, 8, formats[output.stem])
            # Keep verification images distinct across builds, as production preview caches do.
            preview = tmp_path / "decoded" / str(len(reviews)) / output.parent.parent.parent.name / f"{output.stem}.png"
            preview.parent.mkdir(parents=True, exist_ok=True)
            assert decode_dds_preview_with_directxtex(output, preview, max_dimension=8)
            with Image.open(preview) as image:
                pixel = image.convert("RGB").getpixel((0, 0))
                if output.stem == "coat":
                    assert pixel[0 if red_coat else 2] > 170 and pixel[2 if red_coat else 0] < 60, pixel
                elif output.stem == "boots":
                    assert pixel[1 if red_coat else 2] > 150 and pixel[0] < 60, pixel
        archives = list((tmp_path / "packages").glob("*.zip"))
        assert len(archives) == 2
        for path in archives:
            with zipfile.ZipFile(path) as archive:
                names = [name for name in archive.namelist() if name.endswith(".dds")]
                assert {Path(name).stem for name in names} == expected_names
                assert all(archive.read(name).startswith(b"DDS ") for name in names)
        assert fingerprints(folder) == source_hashes
        assert fingerprints(originals) == original_hashes
        assert created_tool_widget(window.texture_editor_tab) is None
        assert not textures.job.sessions
    with patch("cdmw.services.texture_editor_service.TextureEditorService.create_document_from_source",
               side_effect=AssertionError("bulk replacement must not create editor documents")):
        load_folder(matcher, folder, monkeypatch)
        match_and_build({"coat", "boots", "hat"}, red_coat=True)
        Image.new("RGBA", (8, 8), (20, 25, 210, 255)).save(folder / "coat.png")
        Image.new("RGBA", (8, 8), (20, 35, 195, 255)).save(seed)
        assert encode_dds_with_directxtex(seed, folder / "boots.dds", dds_format=formats["boots"])
        (folder / "hat.png").unlink()
        Image.new("RGBA", (8, 8), (100, 80, 40, 255)).save(folder / "belt.png")
        matcher.reload_folder_button.click()
        wait_for(lambda: matcher.import_thread is None)
        match_and_build({"coat", "boots", "belt"}, red_coat=False)
        previous_packages = fingerprints(tmp_path / "packages")
        (folder / "boots.dds").write_bytes(b"damaged external DDS")
        matcher.build_package_button.click()
        wait_for(lambda: matcher.build_thread is None and not textures.job.busy, timeout=45)
        assert "not written" in matcher.status_label.text()
        assert fingerprints(tmp_path / "packages") == previous_packages
        assert fingerprints(originals) == original_hashes
        assert created_tool_widget(window.texture_editor_tab) is None
    assert len(reviews) == 2
    assert not wrong_threads, f"Build updated status widgets outside the GUI thread: {wrong_threads}"


def test_500_file_import_match_and_bulk_remove_keep_editor_unloaded(workspace, tmp_path, monkeypatch):
    from PIL import Image
    window, textures, matcher = workspace
    seed = tmp_path / "seed.dds"
    Image.new("RGBA", (4, 4), (100, 90, 80, 255)).save(seed)
    payload = seed.read_bytes()
    folder, originals = tmp_path / "flat", tmp_path / "originals"
    for index in range(500):
        write_source(folder / f"texture_{index:04}.dds", payload)
        write_source(originals / "0009" / "character" / f"texture_{index:04}.dds", payload)
    monkeypatch.setattr(matcher, "get_original_root", lambda: str(originals))
    ticks = [time.monotonic()]
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.monotonic()))
    timer.start()
    try:
        with patch("cdmw.services.texture_editor_service.TextureEditorService.create_document_from_source",
                   side_effect=AssertionError("bulk queues must not open editor documents")):
            load_folder(matcher, folder, monkeypatch)
            imported_at = time.monotonic()
            assert len(ticks) > 1
            before_match = len(ticks)
            matcher.auto_match_button.click()
            wait_for(lambda: matcher.match_thread is None and not matcher._catalogue_request_busy())
            matched_at = time.monotonic()
            assert len(ticks) > before_match
            assert len(matcher.items) == len(textures.job.assets) == 500
            assert all(item.status == "matched" for item in matcher.items)
            matcher.queue_tree.selectAll()
            matcher.remove_selected_button.click()
            assert not matcher.items and not textures.job.assets
            assert not textures.job.sessions and created_tool_widget(window.texture_editor_tab) is None
    finally:
        timer.stop()
    print(f"500 files: import={imported_at - ticks[0]:.3f}s, match={matched_at - imported_at:.3f}s, "
          f"largest observed GUI heartbeat gap={max(b - a for a, b in zip(ticks, ticks[1:])):.3f}s")


def test_shared_build_preserves_remote_identity_and_ignores_unchecked_stale_original(workspace, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from cdmw.core.texture_native import encode_dds_with_directxtex, find_directxtex_texture_binary
    from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryRef, ArchiveSessionHandle
    from cdmw.domain.archives.catalogue_operations import PrepareEntryResult

    if find_directxtex_texture_binary() is None:
        pytest.skip("This integration check requires the existing DirectXTex texture helper.")
    window, textures, matcher = workspace
    folder = tmp_path / "flat"
    folder.mkdir()
    for name in ("selected", "unchecked"):
        Image.new("RGBA", (8, 8), (50, 100, 150, 255)).save(folder / f"{name}.png")
    original = tmp_path / "prepared-original.dds"
    assert encode_dds_with_directxtex(folder / "selected.png", original, dds_format="BC3_UNORM")
    load_folder(matcher, folder, monkeypatch)
    requests = []
    def prepare_entry(request, **_kwargs):
        requests.append(request)
        return "owned-prepare"
    monkeypatch.setattr(matcher, "archive_catalogue_service",
                        SimpleNamespace(prepare_entry=prepare_entry, cancel=lambda _request: True))
    session = ArchiveSessionHandle("owned-session", str(tmp_path), "current-fingerprint", 2, 1, False)
    matcher.set_archive_catalogue_session(session)
    for index, item in enumerate(matcher.items, start=23):
        selected = item.source_path.stem == "selected"
        item.matched_original = MatchedOriginalTexture(
            package_root="0009", archive_relative_path=f"character/{item.source_path.stem}.dds",
            loose_relative_path=Path(f"0009/character/{item.source_path.stem}.dds"),
            archive_session_id=session.session_id, archive_entry_id=index,
            archive_fingerprint=session.fingerprint if selected else "stale-fingerprint",
        )
        item.status = "matched"
    selected = next(item for item in matcher.items if item.source_path.stem == "selected")
    selected_key = textures.replacement_item_key(selected)
    selected_id = selected.matched_original.archive_entry_id
    textures.synchronize_replacement_matches(matcher)
    textures.job.set_selected([selected_key])
    matcher.package_output_root_edit.setText(str(tmp_path / "package"))
    matcher.package_title_edit.setText("Remote selection")
    matcher._set_combo_by_value(matcher.build_mode_combo, "rebuild_only")
    monkeypatch.setattr(matcher, "_open_review_dialog", lambda _items: None)
    matcher.build_package_button.click()
    assert [request.entry_id for request in requests] == [selected_id]
    assert requests[0].session_id == session.session_id
    assert textures.job.busy
    identity = ArchiveDurableIdentity("character/selected.dds", str(tmp_path / "0009/0.pamt"), 0, 0)
    matcher._handle_catalogue_result("owned-prepare", "prepare_entry", PrepareEntryResult(
        ArchiveEntryRef(session.session_id, selected_id, identity, identity.normalized_path),
        str(original), original.stat().st_size, "owned-fixture", "Raw",
    ))
    wait_for(lambda: matcher.build_thread is None and not textures.job.busy, timeout=45)
    assert matcher.last_built_output_root is not None, matcher.log_view.toPlainText()
    assert {path.stem for path in (tmp_path / "package").rglob("*.dds")} == {"selected"}
    assert textures.job.assets[selected_key].replacement_item.matched_original.archive_entry_id == selected_id
    assert created_tool_widget(window.texture_editor_tab) is None
