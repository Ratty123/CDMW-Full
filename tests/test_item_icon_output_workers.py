from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.core import item_icon as item_icon_core
from cdmw.core.item_icon import ItemIconLibraryRecord, patch_existing_loose_mod_with_item_icon
from cdmw.models import RunCancelled
from cdmw.ui.item_icons_tab import ItemIconLibraryTab


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_until(predicate, *, timeout: float = 4.0) -> None:  # type: ignore[no-untyped-def]
    app = _app()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def _prepared_tab(root: Path) -> tuple[ItemIconLibraryTab, Path, object]:
    source = root / "source.png"
    template = root / "template.png"
    Image.new("RGBA", (32, 24), (20, 80, 140, 255)).save(source)
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(template)
    entry = SimpleNamespace(
        path="ui/texture/icon/itemicon_test.png",
        extension=".png",
        pamt_path=Path("0000/package.pamt"),
    )
    tab = ItemIconLibraryTab(
        settings=QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat),
        base_dir=root,
        get_archive_entries=lambda: (),
        resolve_target_template_path=lambda _entry: template,
    )
    _wait_until(lambda: tab._index_thread is None)
    stat = source.stat()
    record = ItemIconLibraryRecord(
        path=source,
        root_path=root,
        relative_path=source.name,
        file_size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        width=32,
        height=24,
    )
    tab.records = [record]
    tab._records_by_key = {tab._path_key(source): record}
    tab._record_positions_by_key = {tab._path_key(source): 0}
    tab._populate_records_tree(select_path=source)
    tab._selection_preview_timer.stop()
    tab._target_entries = [entry]
    tab._populate_target_combo(select_path=entry.path)
    return tab, source, entry


def _finish_tab(tab: ItemIconLibraryTab) -> None:
    tab.request_shutdown()
    _wait_until(lambda: not tab.iter_shutdown_workers())


def test_export_handler_is_nonblocking_and_latest_request_wins() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first_output = root / "first"
        second_output = root / "second"
        tab, _source, _entry = _prepared_tab(root)
        from cdmw.workers import item_icon_workers as worker_module

        original_build = worker_module.build_item_icon_payload
        first_started = threading.Event()
        call_count = 0

        def cancellable_build(*args, stop_event=None, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_started.set()
                while stop_event is not None and not stop_event.wait(0.005):
                    pass
                raise RunCancelled("cancelled")
            return original_build(*args, stop_event=stop_event, **kwargs)

        try:
            with (
                patch("cdmw.ui.item_icons.tab.QFileDialog.getExistingDirectory", side_effect=(str(first_output), str(second_output))),
                patch("cdmw.ui.item_icons.workers.QMessageBox.information") as information,
                patch.object(worker_module, "build_item_icon_payload", side_effect=cancellable_build),
            ):
                started_at = time.perf_counter()
                tab.export_generated_icon()
                assert time.perf_counter() - started_at < 0.05
                assert first_started.wait(1.0)
                started_at = time.perf_counter()
                tab.export_generated_icon()
                assert time.perf_counter() - started_at < 0.05
                _wait_until(lambda: tab._output_thread is None)

            relative = Path("ui/texture/icon/itemicon_test.png")
            assert not (first_output / relative).exists()
            assert (second_output / relative).is_file()
            assert information.call_count == 1
            assert str(second_output / relative) in information.call_args.args[2]
        finally:
            _finish_tab(tab)


def test_output_shutdown_is_nonblocking_and_leaves_no_partial_file() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        output = root / "output"
        tab, _source, _entry = _prepared_tab(root)
        from cdmw.workers import item_icon_workers as worker_module

        started = threading.Event()

        def cancellable_build(*_args, stop_event=None, **_kwargs):  # type: ignore[no-untyped-def]
            started.set()
            while stop_event is not None and not stop_event.wait(0.005):
                pass
            raise RunCancelled("cancelled")

        with (
            patch("cdmw.ui.item_icons.tab.QFileDialog.getExistingDirectory", return_value=str(output)),
            patch.object(worker_module, "build_item_icon_payload", side_effect=cancellable_build),
        ):
            tab.export_generated_icon()
            assert started.wait(1.0)
            started_at = time.perf_counter()
            tab.request_shutdown()
            assert time.perf_counter() - started_at < 0.05
            _wait_until(lambda: not tab.iter_shutdown_workers())

        assert not (output / "ui/texture/icon/itemicon_test.png").exists()
        assert not tuple(output.rglob("*.tmp")) if output.exists() else True


def test_add_to_loose_mod_handler_is_nonblocking_under_slow_copy() -> None:
    _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        loose_root = root / "ExistingMod"
        existing = loose_root / "character/model/sample.pac"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"mesh")
        tab, _source, _entry = _prepared_tab(root)
        from cdmw.workers import item_icon_workers as worker_module

        original_patch = worker_module.patch_existing_loose_mod_with_item_icon
        started = threading.Event()

        def slow_patch(*args, **kwargs):  # type: ignore[no-untyped-def]
            started.set()
            time.sleep(0.2)
            return original_patch(*args, **kwargs)

        try:
            with (
                patch("cdmw.ui.item_icons.tab.QFileDialog.getExistingDirectory", return_value=str(loose_root)),
                patch("cdmw.ui.item_icons.workers.QMessageBox.information") as information,
                patch.object(worker_module, "patch_existing_loose_mod_with_item_icon", side_effect=slow_patch),
            ):
                started_at = time.perf_counter()
                tab.add_to_existing_loose_mod()
                assert time.perf_counter() - started_at < 0.05
                assert started.wait(1.0)
                _wait_until(lambda: tab._output_thread is None)

            assert (root / "ExistingMod_with_icon/ui/texture/icon/itemicon_test.png").is_file()
            assert information.call_count == 1
        finally:
            _finish_tab(tab)


def test_loose_mod_patch_cancellation_removes_staging_and_final_output(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    source_root = tmp_path / "ExistingMod"
    payload = source_root / "character/model/sample.pac"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"mesh")
    stop_event = threading.Event()
    original_copy = item_icon_core.shutil.copy2

    def cancelling_copy(source, destination, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_copy(source, destination, *args, **kwargs)
        stop_event.set()
        return result

    monkeypatch.setattr(item_icon_core.shutil, "copy2", cancelling_copy)
    with pytest.raises(RunCancelled):
        patch_existing_loose_mod_with_item_icon(
            source_root,
            target_path="ui/texture/icon/itemicon_test.dds",
            payload_data=b"DDS icon",
            stop_event=stop_event,
        )

    assert not (tmp_path / "ExistingMod_with_icon").exists()
    assert not (tmp_path / "ExistingMod_with_icon.zip").exists()
    assert not tuple(tmp_path.glob(".ExistingMod_with_icon.*.tmp"))


def test_loose_mod_patch_rolls_back_directory_if_zip_publication_fails(tmp_path: Path) -> None:
    source_root = tmp_path / "ZippedMod"
    payload = source_root / "character/model/sample.pac"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"mesh")
    (source_root / "manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    with zipfile.ZipFile(source_root / "old.zip", "w") as archive:
        archive.writestr("old.txt", "old")

    with patch.object(item_icon_core, "atomic_publish_files", side_effect=OSError("publish failed")):
        with pytest.raises(OSError, match="publish failed"):
            patch_existing_loose_mod_with_item_icon(
                source_root,
                target_path="ui/texture/icon/itemicon_test.dds",
                payload_data=b"DDS icon",
            )

    assert not (tmp_path / "ZippedMod_with_icon").exists()
    assert not (tmp_path / "ZippedMod_with_icon.zip").exists()
    assert not tuple(tmp_path.glob(".ZippedMod_with_icon.*.tmp"))


def test_item_icon_output_handlers_delegate_all_build_and_write_work() -> None:
    tab_source = Path("cdmw/ui/item_icons/tab.py").read_text(encoding="utf-8")
    worker_source = Path("cdmw/workers/item_icon_workers.py").read_text(encoding="utf-8")
    output_start = tab_source.index("    def export_generated_icon")
    output_end = tab_source.index("    def open_selected_in_texture_editor", output_start)
    output_handlers = tab_source[output_start:output_end]

    assert "build_item_icon_payload(" not in output_handlers
    assert "patch_existing_loose_mod_with_item_icon(" not in output_handlers
    assert ".write_bytes(" not in output_handlers
    assert output_handlers.count("self._queue_item_icon_output(") == 2
    assert "class ItemIconOutputWorker" in worker_source
    assert "atomic_write_bytes(request.destination" in worker_source
    assert "request_id != self._output_request_id" in Path("cdmw/ui/item_icons/workers.py").read_text(encoding="utf-8")
