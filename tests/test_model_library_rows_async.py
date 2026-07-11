from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication

from cdmw.models import RunCancelled
from cdmw.services.settings_service import create_settings
from cdmw.ui.model_library.tab import ModelLibraryTab
from cdmw.workers.model_library_delete import (
    ModelLibraryDeleteRequest,
    delete_model_library_targets,
)
from cdmw.workers.model_library_rows import (
    ModelLibraryDeleteTarget,
    ModelLibraryRowsRequest,
    freeze_model_library_rows,
    prepare_model_library_rows,
)


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _close_tab(app: QApplication, tab: ModelLibraryTab) -> None:
    tab.request_shutdown()
    assert _wait_for(app, lambda: tab._task_thread is None)
    tab.close()
    tab.deleteLater()
    QCoreApplication.sendPostedEvents(tab, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_prepared_rows_are_frozen_and_include_worker_owned_status_and_delete_target() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        downloads = root / "downloads"
        asset = downloads / "Example-uid"
        asset.mkdir(parents=True)
        (asset / "model_metadata.json").write_text(json.dumps({"uid": "uid", "name": "Example"}), encoding="utf-8")
        scene = asset / "scene.glb"
        scene.write_bytes(b"glb")
        rows = freeze_model_library_rows(
            [
                {
                    "kind": "local",
                    "name": "scene",
                    "path": str(scene),
                    "root": str(downloads),
                    "extension": ".glb",
                    "size": 3,
                    "import_supported": True,
                    "texture_status": "None found",
                }
            ]
        )

        result = prepare_model_library_rows(
            ModelLibraryRowsRequest(7, "local", rows, str(downloads), normalize_local=True)
        )

        assert result.request_id == 7
        assert isinstance(result.all_rows, tuple) and result.visible_indices == (0,)
        prepared = result.all_rows[0]
        assert prepared.columns[1:5] == ("Example", "Downloaded", "Ready", "None found")
        assert prepared.local_delete_target is not None
        assert prepared.local_delete_target.path == str(asset)
        assert prepared.no_texture_delete_target == prepared.local_delete_target


def test_mirror_download_probe_and_hide_filter_are_worker_prepared() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        downloads = Path(temp_dir) / "downloads"
        asset = downloads / "Example-uid"
        asset.mkdir(parents=True)
        (asset / "model_metadata.json").write_text(json.dumps({"uid": "uid"}), encoding="utf-8")
        rows = freeze_model_library_rows([{"kind": "mirror", "uid": "uid", "name": "Example"}])

        result = prepare_model_library_rows(
            ModelLibraryRowsRequest(3, "mirror", rows, str(downloads), hide_downloaded=True)
        )

        assert result.hidden_downloaded_count == 1 and result.visible_indices == ()
        assert result.all_rows[0].columns[3] == "Downloaded"
        assert result.all_rows[0].payload.to_dict()["asset_dir"] == str(asset)


def test_slow_scan_dispatch_keeps_qt_heartbeat_alive() -> None:
    app = _app()
    started = threading.Event()
    release = threading.Event()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab.local_roots = [str(root)]
        app.processEvents()
        heartbeat = [0]
        timer = QTimer(tab)
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setInterval(5)

        def record_heartbeat() -> None:
            heartbeat[0] += 1

        timer.timeout.connect(record_heartbeat)
        timer.start()

        def slow_scan(_roots: object, **_kwargs: object) -> tuple[object, ...]:
            started.set()
            release.wait(2.0)
            return ()

        try:
            with mock.patch("cdmw.ui.model_library.actions.scan_local_model_files", side_effect=slow_scan):
                before = time.perf_counter()
                tab.scan_local_roots()
                assert (time.perf_counter() - before) * 1000.0 < 50.0
                assert started.wait(1.0)
                probe_loop = QEventLoop()
                QTimer.singleShot(120, probe_loop.quit)
                probe_started = time.perf_counter()
                probe_loop.exec()
                probe_elapsed_ms = (time.perf_counter() - probe_started) * 1000.0
                assert heartbeat[0] >= 5, (heartbeat[0], probe_elapsed_ms)
        finally:
            release.set()
            if tab._task_thread is not None:
                assert _wait_for(app, lambda: tab._task_thread is None)
            timer.stop()
            _close_tab(app, tab)


def test_latest_row_request_wins_when_first_preparation_finishes_late() -> None:
    app = _app()
    started = threading.Event()
    release = threading.Event()
    call_count = 0
    real_prepare = prepare_model_library_rows
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab._set_active_results_view("local", persist=False)

        def delayed(request: ModelLibraryRowsRequest, *, stop_event: threading.Event) -> object:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                started.set()
                release.wait(2.0)
                return real_prepare(request)
            return real_prepare(request, stop_event=stop_event)

        with mock.patch("cdmw.ui.model_library.controller.prepare_model_library_rows", side_effect=delayed):
            tab._populate_results([{"kind": "local", "name": "First", "path": "first.obj", "extension": ".obj"}])
            assert started.wait(1.0)
            tab._populate_results([{"kind": "local", "name": "Second", "path": "second.obj", "extension": ".obj"}])
            release.set()
            assert _wait_for(
                app,
                lambda: tab._task_thread is None
                and not tab._populating_results
                and tab.results_tree.topLevelItemCount() == 1
                and tab.results_tree.topLevelItem(0).text(1) == "Second",
            )
        assert call_count == 2
        _close_tab(app, tab)


def test_cached_refilter_reuses_worker_frozen_source_snapshot() -> None:
    app = _app()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab._set_active_results_view("local", persist=False)
        tab._populate_results([{"kind": "local", "name": "Cached", "path": "cached.obj", "extension": ".obj"}])
        assert _wait_for(app, lambda: tab._task_thread is None and not tab._populating_results)

        with mock.patch(
            "cdmw.ui.model_library.controller.freeze_model_library_rows",
            side_effect=AssertionError("cached refilter must not freeze rows on the UI thread"),
        ):
            before = time.perf_counter()
            tab._populate_results(tab.local_models)
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert _wait_for(app, lambda: tab._task_thread is None and not tab._populating_results)
        _close_tab(app, tab)


def test_delete_worker_revalidates_owned_folder_and_removes_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        downloads = root / "downloads"
        asset = downloads / "Example-uid"
        asset.mkdir(parents=True)
        (asset / "model_metadata.json").write_text("{}", encoding="utf-8")
        (asset / "nested").mkdir()
        (asset / "nested" / "file.bin").write_bytes(b"payload")
        prepared = prepare_model_library_rows(
            ModelLibraryRowsRequest(
                1,
                "local",
                freeze_model_library_rows(
                    [{"kind": "local", "name": "Example", "path": str(asset / "nested" / "file.bin"), "root": str(downloads), "asset_dir": str(asset)}]
                ),
                str(downloads),
            )
        ).all_rows[0]
        assert prepared.local_delete_target is not None

        result = delete_model_library_targets(
            ModelLibraryDeleteRequest(4, (prepared.local_delete_target,))
        )

        assert result.request_id == 4 and result.errors == ()
        assert result.deleted_paths == (str(asset),)
        assert not asset.exists()


def test_delete_worker_rejects_outside_root_and_honors_pre_cancel() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        approved = root / "approved"
        approved.mkdir()
        outside = root / "outside.obj"
        outside.write_text("o outside", encoding="utf-8")
        forged = ModelLibraryDeleteTarget(
            path=str(outside),
            label="local model file",
            target_kind="local_file",
            allowed_root=str(approved),
            identity=os.path.normcase(os.path.abspath(str(outside))).casefold(),
        )

        rejected = delete_model_library_targets(ModelLibraryDeleteRequest(1, (forged,)))

        assert rejected.deleted_paths == () and rejected.errors
        assert outside.is_file()
        stop_event = threading.Event()
        stop_event.set()
        try:
            delete_model_library_targets(ModelLibraryDeleteRequest(2, (forged,)), stop_event=stop_event)
        except RunCancelled:
            pass
        else:
            raise AssertionError("pre-cancelled delete must not inspect or mutate targets")
        assert outside.is_file()


def test_delete_dispatch_and_shutdown_are_fast_and_cancel_before_mutation() -> None:
    app = _app()
    started = threading.Event()
    cancelled = threading.Event()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        downloads = root / "downloads"
        asset = downloads / "Example-uid"
        asset.mkdir(parents=True)
        (asset / "model_metadata.json").write_text("{}", encoding="utf-8")
        scene = asset / "scene.obj"
        scene.write_text("o scene", encoding="utf-8")
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab._set_active_results_view("local", persist=False)
        tab._populate_results(
            [{"kind": "local", "name": "Example", "path": str(scene), "root": str(downloads), "asset_dir": str(asset), "extension": ".obj", "import_supported": True}]
        )
        assert _wait_for(app, lambda: tab._task_thread is None and not tab._populating_results)
        target = tab._local_delete_target_for_payload(tab.local_models[0])
        assert target is not None

        def slow_delete(_request: object, *, stop_event: threading.Event) -> object:
            started.set()
            if stop_event.wait(2.0):
                cancelled.set()
                raise RunCancelled("cancelled")
            raise AssertionError("test delete should be cancelled")

        with mock.patch("cdmw.ui.model_library.commands.delete_model_library_targets", side_effect=slow_delete):
            before = time.perf_counter()
            tab._delete_local_targets_from_disk([target], item_label="local item")
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert started.wait(1.0)
            before = time.perf_counter()
            tab.request_shutdown()
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert cancelled.wait(1.0)
            assert _wait_for(app, lambda: tab._task_thread is None)
        assert asset.is_dir()
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_model_library_row_and_delete_ui_owners_contain_no_slow_completion_io() -> None:
    actions = Path("cdmw/ui/model_library/actions.py").read_text(encoding="utf-8")
    local_rows = Path("cdmw/ui/model_library/local_rows.py").read_text(encoding="utf-8")
    controller = Path("cdmw/ui/model_library/controller.py").read_text(encoding="utf-8")
    commands = Path("cdmw/ui/model_library/commands.py").read_text(encoding="utf-8")
    workers = Path("cdmw/workers/model_library_rows.py").read_text(encoding="utf-8")

    scan_complete = actions[actions.index("        def complete(result: object) -> None:"):actions.index("        self._run_task", actions.index("        def complete(result: object) -> None:"))]
    assert "_normalize_local_model_rows" not in scan_complete
    assert "read_text" not in local_rows and ".stat(" not in local_rows
    assert not any(token in controller for token in (".is_file(", ".is_dir(", ".stat(", ".resolve(", ".read_text("))
    delete_start = commands.index("    def _delete_local_targets_from_disk")
    delete_body = commands[delete_start:commands.index("    def import_selected_model", delete_start)]
    assert "shutil.rmtree" not in delete_body and ".unlink(" not in delete_body
    assert "from cdmw.ui" not in workers
    assert "prepare_model_library_rows" in actions and "prepare_model_library_rows" in controller
