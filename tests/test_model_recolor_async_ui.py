from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from cdmw.core.recolor_variants import analyze_recolor_variant_package
from cdmw.models import RunCancelled
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from cdmw.services.settings_service import create_settings
from cdmw.ui.model_library.tab import ModelLibraryTab
from cdmw.ui.recolor_variants_tab import RecolorVariantsTab
from cdmw.ui.shell.model_library_bridge import ModelLibraryShellBridgeMixin
from cdmw.workers.model_library_workers import (
    ModelLibraryImportPathRequest,
    ModelLibraryImportPathResult,
    resolve_model_library_import_path,
)
from tests.test_recolor_variants import _write_mod


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _close_worker_tab(app: QApplication, tab: object) -> None:
    tab.request_shutdown()
    _wait_for(app, lambda: tab.worker_thread is None if hasattr(tab, "worker_thread") else tab._task_thread is None)
    tab.close()
    tab.deleteLater()
    app.processEvents()


def test_model_zip_resolution_dispatch_is_fast_and_stale_selection_is_rejected() -> None:
    app = _app()
    started = threading.Event()
    release = threading.Event()
    emitted: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab._set_active_results_view("local", persist=False)
        first = {"kind": "local", "name": "First", "path": str(root / "first.zip"), "extension": ".zip"}
        second = {"kind": "local", "name": "Second", "path": str(root / "second.zip"), "extension": ".zip"}
        tab._populate_results([first, second])
        while tab._populating_results:
            app.processEvents()
        tab.preview_mesh_requested.connect(lambda path, _payload: emitted.append(str(path)))

        def slow_resolution(_request: object, *, stop_event: threading.Event) -> ModelLibraryImportPathResult:
            started.set()
            release.wait(2.0)
            if stop_event.is_set():
                raise RunCancelled("cancelled")
            return ModelLibraryImportPathResult(root / "resolved.gltf")

        with mock.patch("cdmw.ui.model_library.tab.resolve_model_library_import_path", side_effect=slow_resolution):
            before = time.perf_counter()
            tab.preview_selected_model()
            elapsed_ms = (time.perf_counter() - before) * 1000.0
            assert elapsed_ms < 50.0
            assert started.wait(1.0)
            tab.results_tree.setCurrentItem(tab.results_tree.topLevelItem(1))
            release.set()
            assert _wait_for(app, lambda: tab._task_thread is None)

        assert emitted == []
        _close_worker_tab(app, tab)


def test_model_import_resolver_discovers_downloaded_mirror_asset() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        asset_dir = root / "Example-safe_uid"
        scene = asset_dir / "gltf" / "scene.gltf"
        scene.parent.mkdir(parents=True)
        scene.write_text("{}", encoding="utf-8")

        result = resolve_model_library_import_path(
            ModelLibraryImportPathRequest(
                kind="mirror",
                uid="safe_uid",
                download_root=str(root),
            )
        )

        assert result.asset_dir == asset_dir
        assert result.import_path == scene


def test_model_resolution_close_is_nonblocking_and_cancels_worker() -> None:
    app = _app()
    started = threading.Event()
    cancelled = threading.Event()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = ModelLibraryTab(settings=settings, base_dir=root)
        tab._set_active_results_view("local", persist=False)
        payload = {"kind": "local", "name": "Slow", "path": str(root / "slow.zip"), "extension": ".zip"}
        tab._populate_results([payload])
        while tab._populating_results:
            app.processEvents()

        def cancellable(_request: object, *, stop_event: threading.Event) -> object:
            started.set()
            if stop_event.wait(2.0):
                cancelled.set()
                raise RunCancelled("cancelled")
            return ModelLibraryImportPathResult(None)

        with mock.patch("cdmw.ui.model_library.tab.resolve_model_library_import_path", side_effect=cancellable):
            tab.import_selected_model()
            assert started.wait(1.0)
            before = time.perf_counter()
            tab.request_shutdown()
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert cancelled.wait(1.0)
            assert _wait_for(app, lambda: tab._task_thread is None)
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_recolor_analysis_and_image_preview_run_off_ui_thread() -> None:
    app = _app()
    main_thread = threading.get_ident()
    worker_threads: list[int] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = _write_mod(root)
        analysis = analyze_recolor_variant_package(source)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = RecolorVariantsTab(settings=settings, base_dir=root, get_texconv_path=lambda: "")
        tab.source_path_edit.setText(str(source))

        def slow_analysis(_source: Path, *, stop_event: threading.Event) -> object:
            worker_threads.append(threading.get_ident())
            time.sleep(0.15)
            return analysis

        with mock.patch("cdmw.ui.recolor_variants_tab.analyze_recolor_variant_package", side_effect=slow_analysis):
            before = time.perf_counter()
            tab.analyze_source()
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert _wait_for(app, lambda: tab.analysis is not None and tab.worker_thread is None)

        target = next(item for item in analysis.targets if item.editable and item.target_kind == "texture_slot")
        before_png = root / "before.png"
        after_png = root / "after.png"
        Image.new("RGBA", (16, 16), (40, 80, 120, 255)).save(before_png)
        Image.new("RGBA", (16, 16), (120, 80, 40, 255)).save(after_png)

        def slow_preview(*_args: object, **_kwargs: object) -> object:
            from cdmw.core.recolor_variants import RecolorVariantPreviewImage

            worker_threads.append(threading.get_ident())
            time.sleep(0.15)
            return RecolorVariantPreviewImage(target.target_id, root / "source.dds", before_png, after_png)

        with mock.patch("cdmw.ui.recolor_variants_tab.preview_recolor_variant_target_image", side_effect=slow_preview):
            before = time.perf_counter()
            tab.refresh_selected_preview()
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            assert _wait_for(
                app,
                lambda: tab.current_preview_image is not None and tab.worker_thread is None,
            ), (
                tab._worker_kind,
                tab._operation_request_id,
                tab.worker_thread is not None,
                tab.current_preview_image,
                tab._selected_target(),
                worker_threads,
            )

        assert worker_threads and all(thread_id != main_thread for thread_id in worker_threads)
        _close_worker_tab(app, tab)


def test_recolor_stale_analysis_and_close_do_not_publish_or_block() -> None:
    app = _app()
    started = threading.Event()
    release = threading.Event()
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = _write_mod(root)
        analysis = analyze_recolor_variant_package(source)
        settings = create_settings(settings_file_path=root / "settings.ini")
        tab = RecolorVariantsTab(settings=settings, base_dir=root, get_texconv_path=lambda: "")
        tab.source_path_edit.setText(str(source))

        def slow_analysis(_source: Path, *, stop_event: threading.Event) -> object:
            started.set()
            release.wait(2.0)
            return analysis

        with mock.patch("cdmw.ui.recolor_variants_tab.analyze_recolor_variant_package", side_effect=slow_analysis):
            tab.analyze_source()
            assert started.wait(1.0)
            tab.source_path_edit.setText(str(root / "new-source"))
            before = time.perf_counter()
            tab.request_shutdown()
            assert (time.perf_counter() - before) * 1000.0 < 50.0
            release.set()
            assert _wait_for(app, lambda: tab.worker_thread is None)

        assert tab.analysis is None
        tab.close()
        tab.deleteLater()
        app.processEvents()


def test_shell_model_import_handler_defers_file_io_and_scene_import() -> None:
    captured: dict[str, object] = {}
    entry = object()

    class Owner:
        _import_local_model_to_current_archive = ModelLibraryShellBridgeMixin._import_local_model_to_current_archive

        def _current_archive_mesh_entry(self) -> object:
            return entry

        def _background_task_active(self) -> bool:
            return False

        @staticmethod
        def _archive_entry_identity_key(value: object) -> int:
            return id(value)

        def set_status_message(self, *_args: object, **_kwargs: object) -> None:
            pass

        def _run_utility_task(self, **kwargs: object) -> None:
            captured.update(kwargs)

    owner = Owner()
    before = time.perf_counter()
    owner._import_local_model_to_current_archive("slow-scene.gltf", {"name": "Slow Scene"})
    elapsed_ms = (time.perf_counter() - before) * 1000.0

    assert elapsed_ms < 50.0
    assert captured["task_accepts_cancel"] is True
    assert callable(captured["task"])


def test_scene_import_honors_pre_cancelled_request() -> None:
    stop_event = threading.Event()
    stop_event.set()
    try:
        import_scene_mesh_with_report(Path("unused.gltf"), stop_event=stop_event)
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled scene import must not touch the source file")
