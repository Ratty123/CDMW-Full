from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSettings, QThread
from PySide6.QtWidgets import QApplication, QMessageBox

from cdmw.core.item_icon import (
    ItemIconLibraryRecord,
    load_item_icon_library_index,
    save_item_icon_library_index,
)
from cdmw.models import RunCancelled
from cdmw.ui.item_icons_tab import ItemIconLibraryTab


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 4.0) -> None:
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def _make_tab(root: Path, *, resolver=None) -> ItemIconLibraryTab:
    return ItemIconLibraryTab(
        settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=root,
        get_archive_entries=lambda: (),
        get_texconv_path=lambda: "",
        resolve_target_template_path=resolver or (lambda _entry: root / "template.png"),
    )


def _record(path: Path) -> ItemIconLibraryRecord:
    stat = path.stat()
    with Image.open(path) as image:
        width, height = image.size
    return ItemIconLibraryRecord(
        path=path,
        root_path=path.parent,
        relative_path=path.name,
        file_size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        width=width,
        height=height,
    )


def _install_records(tab: ItemIconLibraryTab, records: list[ItemIconLibraryRecord]) -> None:
    tab.records = list(records)
    tab._records_by_key = {tab._path_key(record.path): record for record in records}
    tab._record_positions_by_key = {
        tab._path_key(record.path): index for index, record in enumerate(records)
    }
    tab._populate_records_tree(select_path=records[0].path if records else None)
    tab._selection_preview_timer.stop()


def _finish_tab(tab: ItemIconLibraryTab) -> None:
    tab.request_shutdown()
    _wait_until(lambda: not tab.iter_shutdown_workers())


def test_index_worker_cleanup_is_ordered_on_ui_thread() -> None:
    app = _app()
    cleanup_on_ui_thread: list[bool] = []

    class TrackingTab(ItemIconLibraryTab):
        def _cleanup_index_worker(self) -> None:
            cleanup_on_ui_thread.append(QThread.currentThread() is app.thread())
            super()._cleanup_index_worker()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        for index in range(20):
            tab_root = root / str(index)
            tab_root.mkdir()
            tab = TrackingTab(
                settings=QSettings(str(tab_root / "settings.ini"), QSettings.Format.IniFormat),
                base_dir=tab_root,
                get_archive_entries=lambda: (),
                get_texconv_path=lambda: "",
                resolve_target_template_path=lambda _entry: tab_root / "template.png",
            )
            generated = tab.mesh_editor_generated_icon_path(
                target_model_path="character/model/target.pac",
                source_model_path="source.obj",
            )
            Image.new("RGBA", (8, 8), (20, 40, 60, 255)).save(generated)
            tab.register_mesh_editor_generated_icon(
                generated,
                target_model_path="character/model/target.pac",
                source_model_path="source.obj",
            )
            _wait_until(lambda: tab._index_thread is None)
            _finish_tab(tab)
            assert not tab._item_icon_thread_lifecycle._pending
            tab.deleteLater()
            app.processEvents()

    assert len(cleanup_on_ui_thread) >= 40
    assert all(cleanup_on_ui_thread)


def test_metadata_save_is_nonblocking_and_updates_one_loaded_record() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "icon.png"
        Image.new("RGBA", (32, 32), (20, 40, 60, 255)).save(source)
        record = _record(source)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            save_item_icon_library_index(tab.index_path, roots=(root,), records=(record,))
            _install_records(tab, [record])
            tab.tags_edit.setText("weapon, draft")
            tab.notes_edit.setPlainText("keep this note")
            tab.favorite_checkbox.setChecked(True)

            from cdmw.workers import item_icon_workers as worker_module

            original_update = worker_module.update_item_icon_library_record_metadata
            started = threading.Event()

            def slow_update(*args, **kwargs):
                started.set()
                time.sleep(0.2)
                return original_update(*args, **kwargs)

            with (
                patch.object(worker_module, "update_item_icon_library_record_metadata", side_effect=slow_update),
                patch.object(worker_module, "scan_item_icon_library") as scan_mock,
            ):
                before = time.perf_counter()
                tab.save_selected_metadata()
                elapsed = time.perf_counter() - before
                assert elapsed < 0.05
                assert started.wait(1.0)
                _wait_until(lambda: tab._index_thread is None)
                scan_mock.assert_not_called()

            stored = load_item_icon_library_index(tab.index_path)["records"]
            row = next(iter(stored.values()))
            assert row["tags"] == ["weapon", "draft"]
            assert row["notes"] == "keep this note"
            assert row["favorite"] is True
            updated = tab._record_for_path(source)
            assert updated is not None and updated.favorite and updated.tags == ("weapon", "draft")
            assert tab.records_tree.currentItem().text(0).startswith("* ")
        finally:
            _finish_tab(tab)


def test_file_import_copy_is_nonblocking_and_updates_one_record_without_rescan() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        existing = root / "existing.png"
        source = root / "incoming.png"
        Image.new("RGBA", (16, 16), (20, 30, 40, 255)).save(existing)
        Image.new("RGBA", (48, 24), (50, 60, 70, 255)).save(source)
        existing_record = _record(existing)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            save_item_icon_library_index(tab.index_path, roots=(root,), records=(existing_record,))
            _install_records(tab, [existing_record])
            from cdmw.workers import item_icon_workers as worker_module

            original_copy = worker_module._copy_item_icon_source_to_stage
            original_index = worker_module._write_item_icon_index_stage
            copy_started = threading.Event()
            index_started = threading.Event()

            def slow_copy(*args, **kwargs):
                copy_started.set()
                time.sleep(0.15)
                return original_copy(*args, **kwargs)

            def slow_index(*args, **kwargs):
                index_started.set()
                time.sleep(0.15)
                return original_index(*args, **kwargs)

            with (
                patch.object(worker_module, "_copy_item_icon_source_to_stage", side_effect=slow_copy),
                patch.object(worker_module, "_write_item_icon_index_stage", side_effect=slow_index),
                patch.object(worker_module, "scan_item_icon_library") as scan_mock,
            ):
                before = time.perf_counter()
                stored = tab.add_imported_source(source)
                assert time.perf_counter() - before < 0.05
                assert stored is not None
                assert copy_started.wait(1.0)
                assert index_started.wait(1.0)
                _wait_until(lambda: tab._index_thread is None)
                scan_mock.assert_not_called()

            assert stored.is_file()
            assert len(tab.records) == 2
            assert tab._record_for_path(existing) == existing_record
            imported = tab._record_for_path(stored)
            assert imported is not None and (imported.width, imported.height) == (48, 24)
            assert tab.current_source_path() == stored
            assert len(load_item_icon_library_index(tab.index_path)["records"]) == 2
        finally:
            _finish_tab(tab)


def test_generated_registration_index_is_nonblocking_and_changes_only_target_record() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            tab.edited_root.mkdir(parents=True, exist_ok=True)
            generated = tab.edited_root / "generated.png"
            other = tab.edited_root / "other.png"
            Image.new("RGBA", (32, 32), (80, 90, 100, 255)).save(generated)
            Image.new("RGBA", (8, 8), (110, 120, 130, 255)).save(other)
            generated_record = _record(generated)
            other_record = _record(other)
            save_item_icon_library_index(
                tab.index_path,
                roots=(tab.edited_root,),
                records=(generated_record, other_record),
            )
            _install_records(tab, [generated_record, other_record])
            from cdmw.workers import item_icon_workers as worker_module

            original_index = worker_module._write_item_icon_index_stage
            started = threading.Event()

            def slow_index(*args, **kwargs):
                started.set()
                time.sleep(0.2)
                return original_index(*args, **kwargs)

            with (
                patch.object(worker_module, "_write_item_icon_index_stage", side_effect=slow_index),
                patch.object(worker_module, "scan_item_icon_library") as scan_mock,
            ):
                before = time.perf_counter()
                stored = tab.register_mesh_editor_generated_icon(
                    generated,
                    target_model_path="character/model/target.pac",
                    source_model_path="source.obj",
                )
                assert time.perf_counter() - before < 0.05
                assert stored == generated
                assert started.wait(1.0)
                _wait_until(lambda: tab._index_thread is None)
                scan_mock.assert_not_called()

            updated = tab._record_for_path(generated)
            assert updated is not None and "mesh-editor" in updated.tags
            assert tab._record_for_path(other) == other_record
            assert len(tab.records) == 2
        finally:
            _finish_tab(tab)


def test_delete_unlink_is_nonblocking_and_removes_only_selected_record() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "delete.png"
        keep = root / "keep.png"
        Image.new("RGBA", (16, 16), (140, 20, 20, 255)).save(source)
        Image.new("RGBA", (16, 16), (20, 140, 20, 255)).save(keep)
        source_record = _record(source)
        keep_record = _record(keep)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            save_item_icon_library_index(tab.index_path, roots=(root,), records=(source_record, keep_record))
            _install_records(tab, [source_record, keep_record])
            from cdmw.workers import item_icon_workers as worker_module

            original_unlink = worker_module._unlink_item_icon_backup
            started = threading.Event()

            def slow_unlink(path: Path) -> None:
                started.set()
                time.sleep(0.2)
                original_unlink(path)

            with (
                patch("cdmw.ui.item_icons.tab.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes),
                patch.object(worker_module, "_unlink_item_icon_backup", side_effect=slow_unlink),
                patch.object(worker_module, "scan_item_icon_library") as scan_mock,
            ):
                before = time.perf_counter()
                tab.delete_selected_source()
                assert time.perf_counter() - before < 0.05
                assert started.wait(1.0)
                _wait_until(lambda: tab._index_thread is None)
                scan_mock.assert_not_called()

            assert not source.exists()
            assert keep.is_file()
            assert tab._record_for_path(source) is None
            assert tab._record_for_path(keep) == keep_record
            assert len(load_item_icon_library_index(tab.index_path)["records"]) == 1
            assert not tuple(root.glob(".*.delete"))
        finally:
            _finish_tab(tab)


def test_latest_generated_registration_wins_for_the_same_library_path() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            tab.edited_root.mkdir(parents=True, exist_ok=True)
            generated = tab.edited_root / "generated.png"
            Image.new("RGBA", (24, 24), (40, 50, 60, 255)).save(generated)
            record = _record(generated)
            save_item_icon_library_index(tab.index_path, roots=(tab.edited_root,), records=(record,))
            _install_records(tab, [record])
            from cdmw.workers import item_icon_workers as worker_module

            original_index = worker_module._write_item_icon_index_stage
            first_started = threading.Event()
            call_count = 0

            def cancellable_index(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    first_started.set()
                    stop_event = kwargs.get("stop_event")
                    while stop_event is not None and not stop_event.wait(0.005):
                        pass
                    raise RunCancelled("cancelled")
                return original_index(*args, **kwargs)

            with patch.object(worker_module, "_write_item_icon_index_stage", side_effect=cancellable_index):
                tab.register_mesh_editor_generated_icon(
                    generated,
                    target_model_path="character/model/first.pac",
                    source_model_path="source.obj",
                )
                assert first_started.wait(1.0)
                before = time.perf_counter()
                tab.register_mesh_editor_generated_icon(
                    generated,
                    target_model_path="character/model/second.pac",
                    source_model_path="source.obj",
                )
                assert time.perf_counter() - before < 0.05
                _wait_until(lambda: tab._index_thread is None)

            updated = tab._record_for_path(generated)
            assert updated is not None
            assert "target:second" in updated.tags
            assert "target:first" not in updated.tags
            assert call_count == 2
        finally:
            _finish_tab(tab)


def test_shutdown_cancels_import_and_preserves_index_without_temp_leaks() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        existing = root / "existing.png"
        source = root / "incoming.png"
        Image.new("RGBA", (12, 12), (10, 20, 30, 255)).save(existing)
        Image.new("RGBA", (64, 64), (70, 80, 90, 255)).save(source)
        record = _record(existing)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            save_item_icon_library_index(tab.index_path, roots=(root,), records=(record,))
            _install_records(tab, [record])
            index_before = tab.index_path.read_bytes()
            from cdmw.workers import item_icon_workers as worker_module

            started = threading.Event()

            def cancellable_copy(_source, _staged, stop_event):
                started.set()
                while not stop_event.wait(0.005):
                    pass
                raise RunCancelled("cancelled")

            with patch.object(worker_module, "_copy_item_icon_source_to_stage", side_effect=cancellable_copy):
                stored = tab.add_imported_source(source)
                assert stored is not None
                assert started.wait(1.0)
                before = time.perf_counter()
                tab.request_shutdown()
                assert time.perf_counter() - before < 0.05
                _wait_until(lambda: not tab.iter_shutdown_workers())

            assert not stored.exists()
            assert tab.index_path.read_bytes() == index_before
            assert not tuple(tab.index_path.parent.glob(".cdmw_item_icon_store_*"))
            assert not tuple(tab.edited_root.glob(".*.tmp"))
        finally:
            _finish_tab(tab)


def test_library_mutation_handlers_delegate_disk_and_index_work() -> None:
    tab_source = Path("cdmw/ui/item_icons/tab.py").read_text(encoding="utf-8")
    worker_source = Path("cdmw/workers/item_icon_workers.py").read_text(encoding="utf-8")
    delete_start = tab_source.index("    def delete_selected_source")
    delete_end = tab_source.index("    def _show_records_context_menu", delete_start)
    register_start = tab_source.index("    def register_mesh_editor_generated_icon")
    register_end = tab_source.index("    def choose_source_dialog", register_start)

    assert ".unlink(" not in tab_source[delete_start:delete_end]
    assert "self.scan_library(" not in tab_source[delete_start:delete_end]
    assert "shutil.copy" not in tab_source
    assert "update_item_icon_library_record_metadata(" not in tab_source[register_start:register_end]
    assert "self.scan_library(" not in tab_source[register_start:register_end]
    assert tab_source.count("self._queue_item_icon_library_mutation(") == 3
    assert "class ItemIconLibraryMutationWorker" in worker_source
    assert "atomic_publish_files(publications)" in worker_source
    assert "self._latest_mutation_request_ids.get(key) != request_id" in Path(
        "cdmw/ui/item_icons/workers.py"
    ).read_text(encoding="utf-8")


def test_latest_source_preview_wins_without_blocking_selection_handler() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first = root / "first.png"
        second = root / "second.png"
        Image.new("RGBA", (24, 24), (220, 10, 10, 255)).save(first)
        Image.new("RGBA", (24, 24), (10, 220, 10, 255)).save(second)
        tab = _make_tab(root)
        try:
            _wait_until(lambda: tab._index_thread is None)
            _install_records(tab, [_record(first), _record(second)])

            from cdmw.workers import item_icon_workers as worker_module

            def delayed_preview(source_path: Path, **_kwargs) -> Path:
                if Path(source_path) == first:
                    time.sleep(0.2)
                return Path(source_path)

            with patch.object(worker_module, "build_item_icon_source_preview_png", side_effect=delayed_preview):
                before = time.perf_counter()
                tab.update_source_preview()
                assert time.perf_counter() - before < 0.05
                tab.select_source_path(second)
                tab._selection_preview_timer.stop()
                before = time.perf_counter()
                tab.update_source_preview()
                assert time.perf_counter() - before < 0.05
                _wait_until(lambda: tab._source_preview_thread is None)

            image = tab.source_preview_label._source_image
            assert image is not None and not image.isNull()
            color = image.pixelColor(image.width() // 2, image.height() // 2)
            assert color.green() > color.red()
            assert tab._source_preview_request_id >= 2
        finally:
            _finish_tab(tab)


def test_final_preview_resolves_and_processes_off_ui_thread() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.png"
        template = root / "template.png"
        Image.new("RGBA", (96, 48), (0, 0, 0, 255)).save(source)
        Image.new("RGBA", (64, 64), (0, 0, 0, 0)).save(template)
        ui_thread_id = threading.get_ident()
        resolver_thread_ids: list[int] = []

        def slow_resolver(_entry: object) -> Path:
            resolver_thread_ids.append(threading.get_ident())
            time.sleep(0.2)
            return template

        tab = _make_tab(root, resolver=slow_resolver)
        try:
            _wait_until(lambda: tab._index_thread is None)
            _install_records(tab, [_record(source)])
            entry = SimpleNamespace(path="ui/item/itemicon_target.png", extension=".png")
            tab._target_entries = [entry]
            tab._populate_target_combo(select_path=entry.path)

            before = time.perf_counter()
            tab.update_final_preview()
            elapsed = time.perf_counter() - before

            assert elapsed < 0.05
            _wait_until(lambda: tab._final_preview_thread is None)
            assert resolver_thread_ids and resolver_thread_ids[0] != ui_thread_id
            assert tab.final_preview_label._source_image is not None
            assert "target 64x64" in tab.target_meta_label.text()
        finally:
            _finish_tab(tab)


def test_shutdown_cancels_active_scan_without_waiting_on_ui_thread() -> None:
    _app()
    started = threading.Event()

    def cancellable_scan(*_args, stop_event=None, **_kwargs):
        started.set()
        while stop_event is not None and not stop_event.is_set():
            time.sleep(0.005)
        raise RunCancelled("cancelled")

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        from cdmw.workers import item_icon_workers as worker_module

        with patch.object(worker_module, "scan_item_icon_library", side_effect=cancellable_scan):
            tab = _make_tab(root)
            assert started.wait(1.0)
            preview_temp = Path(tab._temp_preview_dir.name)
            before = time.perf_counter()
            tab.request_shutdown()
            assert time.perf_counter() - before < 0.05
            _wait_until(lambda: tab._index_thread is None)
            assert not tab.iter_shutdown_workers()
            assert not preview_temp.exists()
